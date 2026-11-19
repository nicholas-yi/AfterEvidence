"""Honcho features (owner decision "staged_auto", 2026-11-16): Stage 1 dev check, Stage 2 evaluation.

The dated changed-mind task: 1a at T-3 days, 1b at T-1 day, and every arm's session-2 prompt says
"Today is <T>". Arms:
- Hod (Ho): the Honcho dialectic over backdated messages at the server default level (Study 6).
- Hs (Ho-search): Honcho workspace message search over both peers' messages in the customer's own
  two sessions; the query is the customer's first session-2 message (as for every retrieval);
  hits keep Honcho's order and are rendered with their stored time and speaker.
- A restating customer, the same script except that when the agent asks which item without
  proposing one, it names Y with its item ID: Nr (no memory), Hnr (dated transcripts), Hodr (the
  Hod retrieval, identical text) and Mir (Mem0 with in-band dates, as Study 6's Mi). Proposals
  still get the target-blind consent, so a proposed X is executed.
Stage 1 reuses the frozen cm-pilot-v1 D1-D4 dialogues (as the dated dev check) for Hs, Nr, Hnr,
Hodr and Mir. Stage 2 generates 32 K families after tag honcho-features-eval-v1 and runs arms in
priority order (Hs, Hod, Nr, Hodr, Mir, Hnr), each for every family before the next starts.
Dry run by default; live calls need --approved-requests at the stage's cap.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import random
import re
import subprocess
from pathlib import Path
from typing import Any

from research import changed_mind as cm
from research import commitment_pilot as cp

DEV_STAGE, EVAL_STAGE, TAG = "hf-dev-v1", "hf-eval-v1", "honcho-features-eval-v1"
DEV_DIRECTORY, EVAL_DIRECTORY = cp.RUNS / DEV_STAGE, cp.RUNS / EVAL_STAGE
# Stage 1b: the restating arms rerun with the structural rule, reusing Stage 1's retrievals.
DEV2_STAGE = "hf-dev-v2"
DEV2_DIRECTORY = cp.RUNS / DEV2_STAGE
SOURCE_STAGE = cm.STAGE  # frozen D1-D4 dialogues, as the dated dev check used
DEV_SEED = int(hashlib.sha256(b"AE-HONCHO-FEATURES-DEV-v1").hexdigest()[:8], 16)
DEV_ARMS = ("Hs", "Nr", "Hnr", "Hodr", "Mir")
RESTATING_DEV_ARMS = ("Nr", "Hnr", "Hodr", "Mir")
EVAL_ARMS = ("Hs", "Hod", "Nr", "Hodr", "Mir", "Hnr")  # run priority order
# Retrieval arms: (provider, mode). Hodr reuses Hod's record so only the customer differs.
RETRIEVALS = {
    "Hod": ("honcho", "dialectic"),
    "Hs": ("honcho", "messages"),
    "Mir": ("mem0", "search"),
}
SHARED = {"Hodr": "Hod"}
OWNER = (
    'Owner decision "staged_auto" (ask_user, relayed by Lead, 2026-11-16 ~11:30 ET): Stage 1 '
    "<= 350 requests / 40 credits; Stage 2 starts only if every Stage 1 gate passes, <= 3,000 "
    "requests / 400 credits; Stage 3 (dream, conclusions, memory tool) deferred."
)
SOURCES = (*cm.SOURCES, "honcho_features.py", "honcho_features_analysis.py")
# Measured Study 6 rates (credits per request) for the caps; replaced by Stage 1 rates if higher.
RATES = {"episode": 0.122, "mem0": 0.098, "honcho": 0.087}
ASK_ITEM = (
    "We already agreed on it last time. Please go ahead with that one "
    "and tell me the exact item ID you will use."
)
# Structural restating rule (Lead, 2026-11-16 12:42 ET): after the opening, an agent text naming
# exactly one alternative item ID gets the base target-blind consent; naming zero or several gets
# Y's options and ID, whatever the wording, at most RESTATE_MAX times per session.
RESTATE_MAX = 2
# Independent, deliberately broad audit of the restating customer (not the detector it uses).
WHICH_AUDIT = re.compile(r"\b(?:which|choose|pick|select)\b")
K_FIRST = ("Alaric", "Bettina", "Corwin", "Dagny", "Emrys", "Freya", "Gareth", "Hollis")
K_LAST = (
    "Ashdown",
    "Blackwood",
    "Carrow",
    "Davenport",
    "Ellery",
    "Fairweather",
    "Greenhalgh",
    "Hartigan",
)
DE_SEED = 1103969526  # changed-mind-dated-eval-v1 G families are avoided (names and IDs)


class RestatingCustomer(cm.ChangedMindCustomer):
    """Changed-mind customer; in restating arms it names Y (with its ID) only when asked which item."""

    def __init__(self, family: dict[str, Any], session: int, arm: str = "N") -> None:
        super().__init__(family, session, arm)
        self.restated = 0

    def reply(self, agent_text: str) -> str:
        text = super().reply(agent_text)
        # The base script returns ASK_ITEM exactly when the agent named zero or several items,
        # outside the opening, consent, payment and turn-limit branches.
        if (
            self.phase == "2"
            and self.arm in cp.RESTATING_ARMS
            and text == ASK_ITEM
            and self.restated < RESTATE_MAX
        ):
            self.restated += 1
            f = self.family
            return f"{cp.RESTATEMENT}the {cp._option(f, f['target_id'])}, item {f['target_id']}."
        return text


def restated(report: dict[str, Any]) -> int:
    return sum(
        m.get("role") == "user" and (m.get("content") or "").startswith(cp.RESTATEMENT)
        for m in report.get("messages") or []
    )


def unanswered(report: dict[str, Any]) -> int:
    """Restating arms: agent turns that ask which item but got the non-restating reply while the
    customer still had restatements left."""
    if report.get("arm") not in cp.RESTATING_ARMS:
        return 0
    messages, count, used = report.get("messages") or [], 0, 0
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and WHICH_AUDIT.search((m.get("content") or "").casefold()):
            reply = next(
                (x.get("content") for x in messages[i + 1 :] if x.get("role") == "user"), None
            )
            count += reply == ASK_ITEM and used < RESTATE_MAX
        if m.get("role") == "user" and (m.get("content") or "").startswith(cp.RESTATEMENT):
            used += 1
    return count


def _validate(setup: dict[str, Any]) -> dict[str, Any]:
    for f in setup["families"].values():
        if len({f["stale_id"], f["target_id"], f["rejected_id"]}) != 3:
            raise cp.FatalStop(f"{f['family']}: X, Y and the rejected variant must differ.")
        stale = {**cp.reference_action(f)["arguments"], "new_item_ids": [f["stale_id"]]}
        env = setup["constructor"]()
        before = env.get_db_hash()
        env.make_tool_call("exchange_delivered_order_items", requestor="assistant", **stale)
        if env.get_db_hash() == before:
            raise cp.FatalStop(f"{f['family']}: the stale exchange does not change the DB.")
    setup["customer"] = RestatingCustomer
    return setup


def build_eval(base: dict[str, Any], pool: list[str], seed: int) -> list[dict[str, Any]]:
    """32 K families from the tag-derived seed, disjoint from the C, D, E, F and G families."""
    avoid = (
        cp.build_eval_families(base, cm.EVAL_SEED, pool)
        + cm.build(base, pool)
        + cm.build_eval(base, pool, cm.CM_EVAL_SEED)
        + cm.build_dated_eval(base, pool, DE_SEED)
    )
    families = cp.build_eval_families(
        base,
        seed,
        pool,
        count=32,
        prefix="K",
        width=2,
        namespace=f"AE-HONCHO-FEATURES-EVAL-v1-{seed}",
        avoid=avoid,
        names=[(a, b) for a in K_FIRST for b in K_LAST],
    )
    for f in families:
        alternatives = f["alternatives"]
        f["stale_id"] = alternatives[(f["target_position"] + 2) % len(alternatives)]["item_id"]
    return families


def prepare(seed: int | None = None) -> dict[str, Any]:
    if seed is None:
        return _validate(cp.prepare(builder=cm.build))
    return _validate(cp.prepare(builder=lambda base, pool: build_eval(base, pool, seed)))


def history(today: dt.date, source: Path) -> Any:
    """Hn and Hnr: dated transcripts; Nr: nothing; retrieval arms: their recorded memory."""

    def load(directory: Path, job: dict[str, Any]) -> tuple[str | None, dict | None]:
        if job["arm"] in ("Hn", "Hnr"):
            return cm.dated_history_text(source, job["family"], today), None
        if job["arm"] in cp.NO_MEMORY_ARMS:
            return None, None
        return cp._session_two_history(directory, job)

    return load


def _post(path: str, body: dict[str, Any], timeout: int = 900) -> dict[str, Any]:
    from research import provider_ingest

    return provider_ingest.post(path, body, url=cp.GATEWAY, timeout=timeout)


def retrieve(
    setup: dict[str, Any], directory: Path, families: list[str], prefix: str
) -> list[dict[str, Any]]:
    """One retrieval per (family, retrieval arm), never repeated; an error means no memory."""
    from research.memory_retrievers import pack

    (directory / "memory").mkdir(parents=True, exist_ok=True)
    records = []
    for name in sorted(families):
        family, scope = setup["families"][name], cp.provider_scope(name, prefix)
        query = cp.first_message(family, "Hod")  # the same opening in every arm
        for arm, (provider, mode) in RETRIEVALS.items():
            path = directory / "memory" / f"{name}-{arm}.json"
            if not path.exists():
                body = {
                    "provider": provider,
                    "scope": scope,
                    "query": query,
                    **({"mode": mode} if mode == "messages" else {}),
                }
                try:
                    results = list(_post("/search", body)["results"])
                    text, ids = pack(
                        [(f"{provider}-{n}", t) for n, t in enumerate(results, 1)], cp.HISTORY_MAX
                    )
                    record = {"text": text, "ids": ids, "raw_count": len(results), "error": None}
                except Exception as error:  # recorded; the session runs without memory
                    record = {
                        "text": "",
                        "ids": [],
                        "raw_count": 0,
                        "error": f"{type(error).__name__}: {error}"[:300],
                    }
                record.update(
                    provider=provider,
                    mode=mode,
                    reasoning_level=None,
                    query=query,
                    scope=scope,
                    chars=len(record["text"]),
                    **cp.target_mentions(family, record["text"]),
                )
                path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            records.append(json.loads(path.read_text(encoding="utf-8")))
        for arm, base in SHARED.items():
            path = directory / "memory" / f"{name}-{arm}.json"
            if not path.exists():
                record = json.loads(
                    (directory / "memory" / f"{name}-{base}.json").read_text(encoding="utf-8")
                )
                path.write_text(
                    json.dumps({**record, "shared_from": base}, indent=2) + "\n", encoding="utf-8"
                )
    return records


def providers(
    setup: dict[str, Any], directory: Path, source: Path, today: dt.date, stage: str
) -> dict[str, Any]:
    from research import provider_ingest

    cfg, budget = cp.PROVIDER_STAGES[stage], cp.BUDGETS[cp.STAGE_BUDGET[stage]]
    status = _post("/status", {"provider": "mem0"})
    problems = cp.shim_problems(directory, cfg["shim_caps"])
    if Path(status["state"]) != (directory / "mem0").resolve():
        problems.append("gateway Mem0 state is not this stage's fresh directory")
    if (
        status["honcho_workspace"] != cfg["workspace"]
        or status.get("honcho_workspace_by_prefix")
        or status["honcho_reasoning_level"] is not None
    ):
        problems.append("gateway Honcho workspace or level is not this stage's setting")
    problems += cp.pilot_ledger(cp.journal_rows(directory), budget["cap"], budget["credit_stop"])[
        "reasons"
    ]
    if problems:
        return {"refused": problems}
    inputs = cm.dated_inputs(source, today, cfg["prefix"])
    ledger, errors = directory / "ingest.jsonl", []
    for family in sorted(inputs):
        for provider, key in (("mem0", "episodes_mem0"), ("honcho", "episodes_honcho")):
            scope = cp.provider_scope(family, cfg["prefix"])
            rows = provider_ingest.ingest_provider(
                provider, scope, inputs[family][key], ledger, cp.GATEWAY
            )
            caps = cp.shim_problems(directory, cfg["shim_caps"])
            if caps:
                return {"refused": caps}
            errors += [
                f"ingestion failed: {provider} {family}" for r in rows if r["status"] != "ok"
            ]
    queue = _post("/status", {"provider": "honcho"})["queue"]
    (directory / "honcho-queue.json").write_text(json.dumps(queue) + "\n", encoding="utf-8")
    records = retrieve(setup, directory, sorted(inputs), cfg["prefix"])
    return {
        "refused": cp.shim_problems(directory, cfg["shim_caps"]),
        "ingestion_errors": errors,
        "honcho_queue": queue,
        "retrievals": [cp.memory_meta(r) for r in records],
    }


def schedule(families: list[str], arms: tuple[str, ...], seed: int) -> list[dict[str, Any]]:
    """Arm blocks in priority order; each block runs every family (seeded order) before the next."""
    rng, jobs = random.Random(seed), []
    for arm in arms:
        order = sorted(families)
        rng.shuffle(order)
        jobs += [{"session": 2, "family": f, "arm": arm} for f in order]
    return jobs


def caps(stage: str) -> dict[str, Any]:
    cfg, budget = cp.PROVIDER_STAGES[stage], cp.BUDGETS[cp.STAGE_BUDGET[stage]]
    limits = {"episodes": cfg["episode_cap"], **cfg["shim_caps"]}
    at_caps = (
        limits["episodes"] * RATES["episode"]
        + limits.get("mem0", 0) * RATES["mem0"]
        + limits.get("honcho", 0) * RATES["honcho"]
    )
    return {
        "caps": limits,
        "hard_cap": budget["cap"],
        "credit_stop": budget["credit_stop"],
        "rates": RATES,
        "conservative_at_caps": round(at_caps, 1),
    }


def _common(setup: dict[str, Any], today: dt.date, stage: str) -> dict[str, Any]:
    cfg = cp.PROVIDER_STAGES[stage]
    sources = {
        n: hashlib.sha256((Path(cp.__file__).parent / n).read_bytes()).hexdigest() for n in SOURCES
    }
    return {
        "stage": stage,
        "owner": OWNER,
        "today_utc": today.isoformat(),
        "today_sentence": cm.today_sentence(today),
        "sessions": {
            o: {
                "start_utc": cm.session_start(today, o).isoformat(),
                "label": cm.session_label(today, o),
            }
            for o in cm.DATED_SESSIONS
        },
        "message_gap_seconds": cm.MESSAGE_GAP_SECONDS,
        "arms": {
            "Hod": "Honcho dialectic, backdated, server default level (Ho)",
            "Hs": "Honcho message search over the customer's own sessions (Ho-search); Honcho's order",
            "Nr": "restating customer, no memory",
            "Hnr": "restating customer, dated transcripts",
            "Hodr": "restating customer, the Hod retrieval (identical text)",
            "Mir": "restating customer, Mem0 with in-band dates (Study 6 Mi)",
        },
        "restating_rule": {
            "restatement_prefix": cp.RESTATEMENT,
            "replaces": ASK_ITEM,
            "max_per_session": RESTATE_MAX,
            "trigger": "after the opening, an agent text naming zero or several alternative item "
            "IDs (exactly one gets the target-blind consent)",
            "content": "Y's options and item ID; never X",
        },
        "retrieval_query": "the customer's first session-2 message",
        "retrievals": RETRIEVALS,
        "shared": SHARED,
        "prefix": cfg["prefix"],
        "honcho": {"workspace": cfg["workspace"], "reasoning_level": "server default"},
        "budget": caps(stage),
        "call_max": cp.CALL_MAX,
        "session_requests": cp.SESSION_REQUESTS,
        "session_tools": cp.SESSION_TOOLS,
        "header": cp.NEUTRAL_HEADER,
        "memory_max_chars": cp.HISTORY_MAX,
        "infra_rule": "second infrastructure failure: that session failed (infra); the run continues",
        "manifest_sha256": setup["manifest_sha256"],
        "sources": sources,
    }


def dev_plan(
    setup: dict[str, Any], note: str | None, today: dt.date, source: Path
) -> dict[str, Any]:
    inputs = {}
    for f in sorted(setup["families"]):
        a, b = cm._first_sessions(source, f)
        inputs[f] = {
            x: hashlib.sha256(cp.transcript(r["messages"]).encode()).hexdigest()
            for x, r in (("1a", a), ("1b", b))
        }
    return {
        **_common(setup, today, DEV_STAGE),
        "source_stage": SOURCE_STAGE,
        "inputs": inputs,
        "gates": "retrieval OK >= 3/4 per provider arm (Hs, Hod for Hodr, Mir); zero leakage (Y only in "
        "the restatement, after the agent asks); no harness defect. Outcomes descriptive.",
        "note": note,
        "jobs": schedule(list(setup["families"]), DEV_ARMS, DEV_SEED),
    }


def reuse_retrievals(directory: Path) -> dict[str, str]:
    """Copy Stage 1's Hod, Hodr and Mir records (no new ingestion); returns their hashes."""
    (directory / "memory").mkdir(parents=True, exist_ok=True)
    copied = {}
    for path in sorted((DEV_DIRECTORY / "memory").glob("*.json")):
        if path.stem.rsplit("-", 1)[1] in ("Hod", "Hodr", "Mir"):
            target = directory / "memory" / path.name
            if not target.exists():
                target.write_bytes(path.read_bytes())
            copied[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return copied


def dev2_plan(
    setup: dict[str, Any], note: str | None, today: dt.date, source: Path
) -> dict[str, Any]:
    first = dev_plan(setup, note, today, source)
    reused = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((DEV_DIRECTORY / "memory").glob("*.json"))
        if p.stem.rsplit("-", 1)[1] in ("Hod", "Hodr", "Mir")
    }
    return {
        **first,
        **{k: v for k, v in _common(setup, today, DEV2_STAGE).items() if k in ("stage", "budget")},
        "rerun_of": "hf-dev-v1 restating arms (invalid: keyword trigger missed imperative which-item requests)",
        "reused_retrievals": reused,
        "jobs": schedule(list(setup["families"]), RESTATING_DEV_ARMS, DEV_SEED),
    }


def eval_plan(
    setup: dict[str, Any], note: str | None, tag: dict[str, Any], today: dt.date
) -> dict[str, Any]:
    names = sorted(setup["families"])
    first = [{"session": 1, "family": f, "arm": a} for f in names for a in ("S1a", "S1b")]
    return {
        **_common(setup, today, EVAL_STAGE),
        "tag": tag["tag"],
        "tag_commit": tag["commit"],
        "seed": tag["seed"],
        "seed_rule": "int(first 8 hex of SHA-256(tag commit SHA))",
        "namespace": f"AE-HONCHO-FEATURES-EVAL-v1-{tag['seed']}",
        "template_pool": setup["pool"],
        "arm_priority": EVAL_ARMS,
        "dev_check": tag.get("dev_check"),
        "exclusion": "no explicit 1a or 1b agreement: excluded from every arm, reported, not replaced",
        "analysis": "research/honcho_features_analysis.py: only arms complete for every included family; "
        "the rest are reported as not run",
        "deadline": "publish by 2026-11-17 11:00 ET; anything incomplete then is published as partial",
        "note": note,
        "jobs": first + schedule(names, EVAL_ARMS, tag["seed"]),
    }


def tag_state(tag: str = TAG) -> dict[str, Any] | None:
    root = Path(cp.__file__).resolve().parent.parent

    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout

    try:
        commit = git("rev-parse", f"{tag}^{{commit}}").decode().strip()
    except subprocess.CalledProcessError:
        return None
    changed = [
        n
        for n in SOURCES
        if git("show", f"{commit}:research/{n}") != (Path(cp.__file__).parent / n).read_bytes()
    ]
    return {"tag": tag, "commit": commit, "seed": cp.eval_seed(commit), "changed": changed}


def dev_summary(
    directory: Path,
    setup: dict[str, Any],
    outcome: dict[str, Any] | None = None,
    stage: str = DEV_STAGE,
    arms: tuple[str, ...] = DEV_ARMS,
) -> dict[str, Any]:
    """Per family x arm (booleans and counts only), integration gates and ledger."""
    rows, records = [], {}
    for path in sorted((directory / "memory").glob("*.json")):
        records[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    for r in cp.final_reports(directory):
        f = setup["families"][r["family"]]
        record = records.get(f"{r['family']}-{r['arm']}", {})
        text = record.get("text") or ""
        stale = cm.stale_attempts(f, r.get("messages") or [])
        rows.append(
            {
                "family": r["family"],
                "arm": r["arm"],
                "status": r.get("status"),
                "success": bool(r.get("success")),
                "stale_commitment": stale,
                "declined": r.get("mutations") == 0,
                "wrong_variant_other": int(r.get("wrong_variant_attempts") or 0) - stale,
                "restated": restated(r),
                "unanswered_which": unanswered(r),
                "memory_error": bool(record.get("error")),
                "memory_has_Y": f["target_id"] in text,
                "memory_has_X": f["stale_id"] in text,
                "proposals_before_consent": r.get("proposals_before_consent"),
                "requests": r.get("requests_started"),
                "attempt": r.get("attempt"),
                "leakage": bool(r.get("leakage")),
            }
        )
    needed = [a for a in RETRIEVALS if a in {SHARED.get(x, x) for x in arms}]
    retrieved = {
        arm: sum(
            not records.get(f"{f}-{arm}", {"error": "missing"}).get("error")
            for f in setup["families"]
        )
        for arm in needed
    }
    expected = len(setup["families"]) * len(arms)
    gates = {
        **{f"{arm}_retrieval_3of4": retrieved[arm] >= 3 for arm in needed},
        "zero_leakage": not any(r["leakage"] for r in rows),
        "restating_customer_answered_every_which": not any(r["unanswered_which"] for r in rows),
        "no_harness_defect": len(rows) == expected and not (outcome or {}).get("refused"),
    }
    rows_all = cp.journal_rows(directory)
    budget = cp.BUDGETS[cp.STAGE_BUDGET[stage]]
    groups = {
        "total": rows_all,
        "episodes": [r for r in rows_all if Path(r["_journal"]).parent.name != "shims"],
        **{
            lb: [r for r in rows_all if Path(r["_journal"]).name == f"{lb}.calls.jsonl"]
            for lb in cp.PROVIDER_STAGES[stage]["shim_caps"]
        },
    }
    ledger = {
        k: {
            x: y
            for x, y in cp.pilot_ledger(v, budget["cap"], budget["credit_stop"]).items()
            if x != "reasons"
        }
        for k, v in groups.items()
    }
    return {
        "rows": sorted(rows, key=lambda r: (r["family"], arms.index(r["arm"]))),
        "retrievals_ok": retrieved,
        "gates": gates,
        "verdict": "PASS" if all(gates.values()) else "FAIL",
        "ledger": ledger,
    }


def _live(parser: argparse.ArgumentParser, args: argparse.Namespace, stage: str) -> None:
    cap = cp.BUDGETS[cp.STAGE_BUDGET[stage]]["cap"]
    if args.approved_requests != cap or not args.note or not args.phase:
        parser.error(f"Live runs need --phase, --note and --approved-requests {cap}.")


def _plan_file(directory: Path, public: dict[str, Any], parser: argparse.ArgumentParser) -> None:
    path = directory / "plan.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != json.loads(
            json.dumps(public)
        ):  # JSON lists vs tuples
            parser.error("The plan or frozen sources changed since the run started.")
        return
    if any(directory.glob("*.calls.jsonl")):
        parser.error("Run directory has journals but no plan; use a fresh directory.")
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")


def _today(directory: Path) -> dt.date:
    """T: the UTC date when the plan is first written; fixed if the run crosses midnight."""
    path = directory / "plan.json"
    if path.exists():
        return dt.date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["today_utc"])
    return dt.datetime.now(dt.timezone.utc).date()


def shim_problems(directory: Path, stage: str) -> list[str]:
    """cp.shim_problems treats empty caps as the v5 defaults; Stage 1b has no shims at all."""
    caps = cp.PROVIDER_STAGES[stage]["shim_caps"]
    if not caps:
        found = sorted(p.name for p in (directory / "shims").glob("*.calls.jsonl"))
        return [f"unexpected shim journals {found}"] if found else []
    return cp.shim_problems(directory, caps)


def _sessions(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    directory: Path,
    stage: str,
    jobs: list[dict[str, Any]],
    setup: dict[str, Any],
    source: Path,
) -> dict[str, Any]:
    missing = [
        cp.job_id(j)
        for j in jobs
        if j["arm"] in cp.RETRIEVERS
        and not (directory / "memory" / f"{j['family']}-{j['arm']}.json").exists()
    ]
    if missing or shim_problems(directory, stage):
        parser.error(f"Sessions need every retrieval and clean shims: {missing}")
    today = _today(directory)
    return asyncio.run(
        cp.live_run(
            directory,
            args.model,
            stage,
            jobs,
            setup,
            history_fn=history(today, source),
            infra_continue=True,
            exclude_uncommitted=True,
        )
    )


def dev_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    rerun = args.stage == "dev2"
    stage, arms = (DEV2_STAGE, RESTATING_DEV_ARMS) if rerun else (DEV_STAGE, DEV_ARMS)
    setup, source = prepare(), cp.RUNS / SOURCE_STAGE
    directory = DEV2_DIRECTORY if rerun else DEV_DIRECTORY
    today = _today(DEV_DIRECTORY)  # Stage 1b keeps Stage 1's T
    setup["today"] = cm.today_sentence(today)
    if args.summarize:
        print(json.dumps(dev_summary(directory, setup, None, stage, arms), indent=2, default=str))
        return 0
    public = (dev2_plan if rerun else dev_plan)(setup, args.note, today, source)
    if args.approved_requests is None:
        print(json.dumps({**public, "jobs": len(public["jobs"])}, indent=2))
        return 0
    _live(parser, args, stage)
    _plan_file(directory, public, parser)
    if rerun:
        if args.phase != "sessions":
            parser.error("Stage 1b reuses Stage 1's retrievals; use --phase sessions.")
        if reuse_retrievals(directory) != public["reused_retrievals"]:
            parser.error("Stage 1 retrieval records changed since the Stage 1b plan.")
    elif args.phase == "providers":
        result = providers(setup, directory, source, today, DEV_STAGE)
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    outcome = _sessions(args, parser, directory, stage, public["jobs"], setup, source)
    summary = dev_summary(directory, setup, outcome, stage, arms)
    (directory / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "refused": outcome["refused"],
                "infra_events": outcome["infra_events"],
                **{k: v for k, v in summary.items() if k != "rows"},
            },
            indent=2,
            default=str,
        )
    )
    return 1 if outcome["refused"] else 0


def stage_one_passed() -> bool:
    """Stage 1's non-restating gates (Hs and retrievals) plus Stage 1b's gates, all passed."""
    first, rerun = DEV_DIRECTORY / "summary-audited.json", DEV2_DIRECTORY / "summary.json"
    if not (first.exists() and rerun.exists()):
        return False
    gates = json.loads(first.read_text(encoding="utf-8"))["gates"]
    superseded = {"restating_customer_answered_every_which"}  # rerun in Stage 1b
    return (
        all(v for k, v in gates.items() if k not in superseded)
        and json.loads(rerun.read_text(encoding="utf-8"))["verdict"] == "PASS"
    )


def eval_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    tag, directory = tag_state(), EVAL_DIRECTORY
    if tag is None:
        if args.approved_requests is None:
            print(f"Dry run: tag {TAG} not found; evaluation families are generated only after it.")
            print(json.dumps(caps(EVAL_STAGE), indent=2))
            return 0
        parser.error(f"The evaluation needs the annotated protocol tag {TAG}.")
    if tag["changed"]:
        parser.error(f"Frozen sources differ from {TAG}: {tag['changed']} (a deviation; not run).")
    checks = [DEV_DIRECTORY / "summary-audited.json", DEV2_DIRECTORY / "summary.json"]
    tag["dev_check"] = {
        p.parent.name + "/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in checks
        if p.exists()
    }
    setup = prepare(tag["seed"])
    today = _today(directory)
    setup["today"] = cm.today_sentence(today)
    if args.summarize:
        from research.honcho_features_analysis import analyse, rows_from_runs

        print(json.dumps(analyse(rows_from_runs(directory)), indent=2))
        return 0
    public = eval_plan(setup, args.note, tag, today)
    if args.approved_requests is None:
        print(
            json.dumps(
                {
                    **public,
                    "jobs": len(public["jobs"]),
                    "references_validated": len(setup["tasks"]),
                },
                indent=2,
            )
        )
        return 0
    _live(parser, args, EVAL_STAGE)
    if not stage_one_passed():
        parser.error("Stage 2 starts only after every Stage 1 gate passed.")
    _plan_file(directory, public, parser)
    if args.phase in ("providers", "sessions"):
        done = {
            (r["family"], r["arm"]) for r in cp.final_reports(directory) if r.get("session") == 1
        }
        if done != {(f, a) for f in setup["families"] for a in ("S1a", "S1b")}:
            parser.error("Session 1 is incomplete.")
    included = cm.committed(directory)
    if args.phase == "providers":
        excluded = sorted(set(setup["families"]) - set(included))
        (directory / "exclusions.json").write_text(
            json.dumps({"included": included, "excluded": excluded}, indent=2) + "\n",
            encoding="utf-8",
        )
        result = providers(setup, directory, directory, today, EVAL_STAGE)
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    if args.phase == "session1":
        outcome = asyncio.run(
            cp.live_run(
                directory,
                args.model,
                EVAL_STAGE,
                cm.select(public["jobs"], "session1", []),
                setup,
                infra_continue=True,
                exclude_uncommitted=True,
            )
        )
    else:
        outcome = _sessions(
            args,
            parser,
            directory,
            EVAL_STAGE,
            cm.select(public["jobs"], "sessions", included),
            setup,
            directory,
        )
    print(
        json.dumps(
            {
                "refused": outcome["refused"],
                "infra_events": outcome["infra_events"],
                "sessions_run": len(outcome["results"]),
            },
            indent=2,
        )
    )
    return 1 if outcome["refused"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Honcho features: Stage 1 dev check and Stage 2 evaluation."
    )
    parser.add_argument("--stage", choices=["dev", "dev2", "eval"], default="dev")
    parser.add_argument("--phase", choices=["session1", "providers", "sessions"])
    parser.add_argument("--approved-requests", type=int)
    parser.add_argument("--note", help="Provenance note recorded in the plan (required to run).")
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.stage in ("dev", "dev2") and args.phase == "session1":
        parser.error(
            "The dev check reuses frozen session-1 dialogues; use --phase providers|sessions."
        )
    return eval_main(parser, args) if args.stage == "eval" else dev_main(parser, args)


if __name__ == "__main__":
    raise SystemExit(main())
