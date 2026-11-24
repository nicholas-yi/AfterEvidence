"""Honcho Stage 3 (approved 2026-11-17): dreaming, application-written facts, a memory tool.

The dated changed-mind task with the customer who never restates (Study 7's Hod setting). Arms, in
priority order (reverse order is the pre-declared cut order if the budget does not fit):
- Hod: the Honcho dialectic over backdated messages (baseline), plain workspace.
- Hdr: after ingestion, one dream per customer (schedule_dream, then two empty queue polls), then
  the dialectic; its own workspace.
- Ht: no memory block; the actor may call recall_customer_memory (its question goes verbatim to the
  dialectic over the plain workspace) at most MEMORY_TOOL_CAP times per session.
- Hw: the application writes structured facts into Honcho as its own conclusions: a frozen
  summarizer prompt reads only the dated transcripts (after 1a, then after 1b, replacing its earlier
  facts); then the dialectic; its own workspace. The app writes the facts, not Honcho.
- Fd: control for Hw. The same final summarizer facts go straight to the actor under the neutral
  header, with no Honcho in between.
Stage 3 was deferred until after the Plastic Labs call: the evaluation tag requires the owner's call
notes (CALL_NOTES); the dev check needs them too unless the owner allows it before (flag).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from research import changed_mind as cm
from research import commitment_pilot as cp
from research import honcho_features as hf

DEV_STAGE, EVAL_STAGE, TAG = "hf3-dev-v1", "hf3-eval-v1", "honcho-stage3-eval-v1"
DEV_DIRECTORY, EVAL_DIRECTORY = cp.RUNS / DEV_STAGE, cp.RUNS / EVAL_STAGE
ARMS = ("Hod", "Hdr", "Ht", "Hw", "Fd")  # priority order
MEMORY_TOOL_CAP = 2
# Customer-scope prefixes per arm; plain workspace = the stage's default workspace.
PREFIXES = {"Hod": "cmp-h3d-", "Ht": "cmp-h3d-", "Hdr": "cmp-h3r-", "Hw": "cmp-h3w-"}
APP_SHIM = "app"
APP_URL = os.environ.get("AFTEREVIDENCE_APP_SHIM", "http://127.0.0.1:8815/v1/chat/completions")
TOKEN_FILE = Path(cp.__file__).resolve().parent / "providers" / "shim-token.txt"  # git-ignored
# Recorded from the Plastic Labs call notes before any tag (design review, 2026-11-17).
CALL_NOTES: str | None = (
    "2026-11-17: the Plastic Labs call did not cover models or configuration, so no "
    "recommendation is recorded and none is adopted. Stage 3 keeps its pre-specified design: server "
    "default level, claude-haiku-5.5 substituted for every provider LLM. A Plastic Labs-recommended "
    "model remains untested (an unaddressed limitation)."
)
SUMMARIZER_PROMPT = (
    "You keep a customer-account record for a retail support application. Below are the dated "
    "transcripts of this customer's conversations so far, oldest first. Write the facts the "
    "application should store about the customer's open requests and agreements: 1 to 5 short, "
    'self-contained facts, one per line, each starting with "- ". Include dates, order IDs and '
    "exact item IDs as stated in the transcripts. If an agreement was changed, state which "
    "agreement is current and which one it replaced."
)
SOURCES = (*hf.SOURCES, "honcho_stage3.py", "honcho_stage3_analysis.py")
# Credits per request for the caps: the dev check's measured episode rate (higher than Study 6's),
# Study 6's Honcho rate (higher than measured) and the episode rate for the app summarizer.
RATES = {"episodes": 0.1253, "honcho": 0.087, APP_SHIM: 0.122}
L_FIRST = ("Leander", "Marisol", "Nevin", "Oriana", "Pascal", "Rosalie", "Soren", "Tamsin")
L_LAST = (
    "Langford",
    "Merriman",
    "Nettleton",
    "Overbury",
    "Penhallow",
    "Radcliffe",
    "Stanhope",
    "Tolliver",
)
M2_SEED = 2964917046  # second-model-eval-v1 P families are avoided


def workspaces(stage: str) -> dict[str, str]:
    base = cp.PROVIDER_STAGES[stage]["workspace"]
    return {PREFIXES["Hdr"]: f"{base}-dream", PREFIXES["Hw"]: f"{base}-facts"}


def summarizer_input(source: Path, family: str, today: dt.date, upto: str) -> str:
    """Only the dated transcripts (no labels, manifest or oracle fields)."""
    a, b = cm._first_sessions(source, family)
    parts = [f"{cm.session_label(today, 'a')}\n{cp.transcript(a['messages'])}"]
    if upto == "b":
        parts.append(f"{cm.session_label(today, 'b')}\n{cp.transcript(b['messages'])}")
    return "\n\n".join(parts)


def parse_facts(text: str) -> list[str]:
    facts = [
        line.strip()[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")
    ]
    return [f[:400] for f in facts if f][:5]


def summarize(transcripts: str, token: str, model: str = "claude-haiku-5.5") -> list[str]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SUMMARIZER_PROMPT},
            {"role": "user", "content": transcripts},
        ],
    }
    request = urllib.request.Request(
        APP_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        reply = json.loads(response.read())
    return parse_facts(reply["choices"][0]["message"]["content"] or "")


def _token() -> str:
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def memory_tool(directory: Path, stage: str) -> Any:
    """The Ht tool: the dialectic over the plain workspace; a reached shim cap stops the run."""
    caps = cp.PROVIDER_STAGES[stage]["shim_caps"]

    def recall(family: str, question: str) -> str:
        problems = cp.shim_problems(directory, caps)
        if problems:
            raise cp.FatalStop(f"Shim problem during the memory tool: {problems}")
        body = {
            "provider": "honcho",
            "scope": cp.provider_scope(family, PREFIXES["Ht"]),
            "query": question or "What is known about this customer?",
            "mode": "ask",
        }
        return "\n".join(hf._post("/search", body)["results"])

    return recall


def history(directory_unused: Path | None = None) -> Any:
    def load(directory: Path, job: dict[str, Any]) -> tuple[str | None, dict | None]:
        if job["arm"] in cp.NO_MEMORY_ARMS:
            return None, None
        return cp._session_two_history(directory, job)

    return load


def _record(
    family: dict[str, Any],
    provider: str,
    mode: str,
    query: str,
    scope: str,
    results: list[str] | None,
    error: str | None,
) -> dict[str, Any]:
    from research.memory_retrievers import pack

    text, ids = pack(
        [(f"{provider}-{n}", t) for n, t in enumerate(results or [], 1)], cp.HISTORY_MAX
    )
    return {
        "text": text if not error else "",
        "ids": ids if not error else [],
        "raw_count": len(results or []),
        "error": error,
        "provider": provider,
        "mode": mode,
        "reasoning_level": None,
        "query": query,
        "scope": scope,
        "chars": 0 if error else len(text),
        **cp.target_mentions(family, "" if error else text),
    }


def providers(
    setup: dict[str, Any],
    directory: Path,
    source: Path,
    today: dt.date,
    stage: str,
    token: str | None = None,
    summarizer: Any = None,
) -> dict[str, Any]:
    from research import provider_ingest

    cfg, budget = cp.PROVIDER_STAGES[stage], cp.BUDGETS[cp.STAGE_BUDGET[stage]]
    status = hf._post("/status", {"provider": "honcho"})
    problems = cp.shim_problems(directory, cfg["shim_caps"])
    if (
        status["honcho_workspace"] != cfg["workspace"]
        or status.get("honcho_workspace_by_prefix") != workspaces(stage)
        or status["honcho_reasoning_level"] is not None
    ):
        problems.append("gateway Honcho workspaces or level are not this stage's setting")
    problems += cp.pilot_ledger(cp.journal_rows(directory), budget["cap"], budget["credit_stop"])[
        "reasons"
    ]
    if problems:
        return {"refused": problems}
    summarizer = summarizer or (lambda text: summarize(text, token or _token()))
    ledger, errors, dreams = directory / "ingest.jsonl", [], {}
    (directory / "facts").mkdir(parents=True, exist_ok=True)
    (directory / "memory").mkdir(parents=True, exist_ok=True)
    inputs = {p: cm.dated_inputs(source, today, p) for p in sorted(set(PREFIXES.values()))}
    families = sorted(inputs[PREFIXES["Hod"]])

    def ingest(prefix: str, family: str, episodes: list[dict[str, Any]]) -> None:
        rows = provider_ingest.ingest_provider(
            "honcho", cp.provider_scope(family, prefix), episodes, ledger, cp.GATEWAY
        )
        caps = cp.shim_problems(directory, cfg["shim_caps"])
        if caps:
            raise cp.FatalStop(f"Shim cap: {caps}")
        errors.extend(f"ingestion failed: {prefix}{family}" for r in rows if r["status"] != "ok")

    try:
        for family in families:
            for prefix in (PREFIXES["Hod"], PREFIXES["Hdr"]):
                ingest(prefix, family, inputs[prefix][family]["episodes_honcho"])
            path, scope = (
                directory / "facts" / f"{family}.json",
                cp.provider_scope(family, PREFIXES["Hw"]),
            )
            record = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"steps": []}
            )
            episodes = inputs[PREFIXES["Hw"]][family]["episodes_honcho"]
            for order, episode in zip("ab", episodes):
                if any(s["after"] == order for s in record["steps"]):
                    continue
                ingest(PREFIXES["Hw"], family, [episode])
                previous = record["steps"][-1]["created"] if record["steps"] else []
                try:
                    facts, error = summarizer(summarizer_input(source, family, today, order)), None
                except Exception as failure:  # recorded; Hw and Fd then have fewer facts
                    facts, error = [], f"{type(failure).__name__}: {failure}"[:300]
                written = (
                    hf._post(
                        "/honcho/facts",
                        {
                            "provider": "honcho",
                            "scope": scope,
                            "facts": facts,
                            "session": episode["id"],
                            "delete": previous,
                        },
                    )["result"]
                    if facts
                    else {"created": previous, "deleted": []}
                )
                record["steps"].append({"after": order, "facts": facts, "error": error, **written})
                path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            dream_path = directory / "facts" / f"{family}-dream.json"
            if not dream_path.exists():
                result = hf._post(
                    "/honcho/dream", {"scope": cp.provider_scope(family, PREFIXES["Hdr"])}
                )["result"]
                dream_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            dreams[family] = json.loads(dream_path.read_text(encoding="utf-8"))
    except cp.FatalStop as stop:
        return {"refused": [str(stop)]}
    queues = {
        p: hf._post("/status", {"provider": "honcho", "scope": f"customer:{p}"})["queue"]
        for p in sorted(set(PREFIXES.values()))
    }
    (directory / "honcho-queue.json").write_text(json.dumps(queues) + "\n", encoding="utf-8")
    for family in families:
        f = setup["families"][family]
        query = cp.first_message(f, "Hod")
        for arm in ("Hod", "Hdr", "Hw"):
            path = directory / "memory" / f"{family}-{arm}.json"
            if path.exists():
                continue
            scope = cp.provider_scope(family, PREFIXES[arm])
            try:
                results, error = (
                    list(
                        hf._post("/search", {"provider": "honcho", "scope": scope, "query": query})[
                            "results"
                        ]
                    ),
                    None,
                )
            except Exception as failure:  # recorded; the session runs without memory
                results, error = [], f"{type(failure).__name__}: {failure}"[:300]
            path.write_text(
                json.dumps(
                    _record(f, "honcho", "dialectic", query, scope, results, error), indent=2
                )
                + "\n",
                encoding="utf-8",
            )
        steps = json.loads((directory / "facts" / f"{family}.json").read_text(encoding="utf-8"))[
            "steps"
        ]
        final = steps[-1]["facts"] if steps else []
        error = None if final else "no summarizer facts"
        (directory / "memory" / f"{family}-Fd.json").write_text(
            json.dumps(
                _record(
                    f,
                    "app",
                    "facts-direct",
                    "",
                    "",
                    ["\n".join(f"- {x}" for x in final)] if final else [],
                    error,
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "refused": cp.shim_problems(directory, cfg["shim_caps"]),
        "ingestion_errors": errors,
        "honcho_queues": queues,
        "dreams": dreams,
    }


def plan(
    setup: dict[str, Any],
    note: str | None,
    today: dt.date,
    source: Path,
    stage: str,
    arms: tuple[str, ...],
    seed: int,
    extra: dict[str, Any],
) -> dict[str, Any]:
    common = hf._common(setup, today, stage)
    for key in ("arms", "restating_rule", "retrievals", "shared", "prefix", "honcho"):
        common.pop(key, None)
    cfg, cap = cp.PROVIDER_STAGES[stage], cp.BUDGETS[cp.STAGE_BUDGET[stage]]
    limits = {"episodes": cfg["episode_cap"], **cfg["shim_caps"]}
    rates = RATES
    common["budget"] = {
        "caps": limits,
        "hard_cap": cap["cap"],
        "credit_stop": cap["credit_stop"],
        "rates": rates,
        "conservative_at_caps": round(sum(limits[k] * rates[k] for k in limits), 1),
    }
    return {
        **common,
        "call_notes": CALL_NOTES,
        "arms_priority": arms,
        "arms": {
            "Hod": "Honcho dialectic (baseline)",
            "Hdr": "one dream per customer, then the dialectic",
            "Ht": f"memory tool only (dialectic, verbatim question), <= {MEMORY_TOOL_CAP} calls",
            "Hw": "app-written facts as Honcho conclusions, then the dialectic",
            "Fd": "the same facts directly, no Honcho (control for Hw)",
        },
        "prefixes": PREFIXES,
        "honcho": {
            "workspace": cp.PROVIDER_STAGES[stage]["workspace"],
            "workspaces_by_prefix": workspaces(stage),
            "reasoning_level": "server default",
        },
        "summarizer_prompt": SUMMARIZER_PROMPT,
        "summarizer_input": "dated transcripts only (1a; then 1a and 1b)",
        "memory_tool_cap": MEMORY_TOOL_CAP,
        "note": note,
        **extra,
        "jobs": hf.schedule(list(setup["families"]), arms, seed),
    }


def dev_summary(
    directory: Path, setup: dict[str, Any], outcome: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Per family x arm (booleans and counts only), integration gates, ledger, measured costs."""
    families = sorted(setup["families"])
    records = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (directory / "memory").glob("*.json")
    }
    rows = []
    for r in cp.final_reports(directory):
        f = setup["families"][r["family"]]
        text = records.get(f"{r['family']}-{r['arm']}", {}).get("text") or ""
        calls = r.get("memory_tool_calls") or []
        stale = cm.stale_attempts(f, r.get("messages") or [])
        rows.append(
            {
                "family": r["family"],
                "arm": r["arm"],
                "status": r.get("status"),
                "success": bool(r.get("success")),
                "stale_commitment": stale,
                "declined": r.get("mutations") == 0,
                "memory_has_Y": f["target_id"] in text,
                "memory_has_X": f["stale_id"] in text,
                "tool_calls": len(calls),
                "tool_errors": sum(bool(c["error"]) and c["error"] != "cap" for c in calls),
                "tool_has_Y": any(f["target_id"] in c["answer"] for c in calls),
                "requests": r.get("requests_started"),
                "leakage": bool(r.get("leakage")),
            }
        )
    facts = {}
    for family in families:
        path = directory / "facts" / f"{family}.json"
        steps = json.loads(path.read_text(encoding="utf-8"))["steps"] if path.exists() else []
        facts[family] = {
            "steps": len(steps),
            "final_facts": len(steps[-1]["facts"]) if steps else 0,
            "errors": [s["error"] for s in steps if s["error"]],
        }
    dreams = {}
    for family in families:
        path = directory / "facts" / f"{family}-dream.json"
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        dreams[family] = d.get("dream_runs_after", 0) > d.get("dream_runs_before", 0)
    ok = {
        arm: sum(not records.get(f"{f}-{arm}", {"error": "missing"}).get("error") for f in families)
        for arm in ("Hod", "Hdr", "Hw", "Fd")
    }
    ht = [r for r in rows if r["arm"] == "Ht"]
    gates = {
        **{f"{arm}_memory_3of4": ok[arm] >= 3 for arm in ok},
        "facts_written_3of4": sum(v["steps"] == 2 and v["final_facts"] > 0 for v in facts.values())
        >= 3,
        "dream_triggered_3of4": sum(dreams.values()) >= 3,
        "memory_tool_exercised_without_error": sum(r["tool_calls"] for r in ht) > 0
        and not any(r["tool_errors"] for r in ht),
        "zero_leakage": not any(r["leakage"] for r in rows),
        "no_harness_defect": len(rows) == len(families) * len(ARMS)
        and not (outcome or {}).get("refused"),
    }
    rows_all = cp.journal_rows(directory)
    budget = cp.BUDGETS[cp.STAGE_BUDGET[DEV_STAGE]]
    groups = {
        "total": rows_all,
        "episodes": [r for r in rows_all if Path(r["_journal"]).parent.name != "shims"],
        **{
            lb: [r for r in rows_all if Path(r["_journal"]).name == f"{lb}.calls.jsonl"]
            for lb in cp.PROVIDER_STAGES[DEV_STAGE]["shim_caps"]
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
    per_arm = {
        arm: round(
            sum(r["requests"] or 0 for r in rows if r["arm"] == arm) / max(1, len(families)), 2
        )
        for arm in ARMS
    }
    return {
        "rows": sorted(rows, key=lambda r: (r["family"], ARMS.index(r["arm"]))),
        "memory_ok": ok,
        "facts": facts,
        "dreams_triggered": dreams,
        "gates": gates,
        "verdict": "PASS" if all(gates.values()) else "FAIL",
        "ledger": ledger,
        "episode_requests_per_family": per_arm,
    }


def setup_for(stage: str, directory: Path, seed: int | None = None) -> dict[str, Any]:
    setup = hf.prepare(seed) if seed is None else prepare_eval(seed)
    setup["memory_tool"], setup["memory_tool_arms"], setup["memory_tool_cap"] = (
        memory_tool(directory, stage),
        ("Ht",),
        MEMORY_TOOL_CAP,
    )
    return setup


def build_eval(base: dict[str, Any], pool: list[str], seed: int) -> list[dict[str, Any]]:
    """32 L families from the tag-derived seed, disjoint from the C-G, K and P families."""
    from research import second_model as m2

    avoid = (
        cp.build_eval_families(base, cm.EVAL_SEED, pool)
        + cm.build(base, pool)
        + cm.build_eval(base, pool, cm.CM_EVAL_SEED)
        + cm.build_dated_eval(base, pool, hf.DE_SEED)
        + hf.build_eval(base, pool, m2.HF_SEED)
        + m2.build_eval(base, pool, M2_SEED)
    )
    families = cp.build_eval_families(
        base,
        seed,
        pool,
        count=32,
        prefix="L",
        width=2,
        namespace=f"AE-HONCHO-STAGE3-EVAL-v1-{seed}",
        avoid=avoid,
        names=[(a, b) for a in L_FIRST for b in L_LAST],
    )
    for f in families:
        alternatives = f["alternatives"]
        f["stale_id"] = alternatives[(f["target_position"] + 2) % len(alternatives)]["item_id"]
    return families


def prepare_eval(seed: int) -> dict[str, Any]:
    return hf._validate(cp.prepare(builder=lambda base, pool: build_eval(base, pool, seed)))


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


def eval_plan(
    setup: dict[str, Any], note: str | None, tag: dict[str, Any], today: Any
) -> dict[str, Any]:
    names = sorted(setup["families"])
    dev = DEV_DIRECTORY / "summary.json"
    sources = {
        n: hashlib.sha256((Path(cp.__file__).parent / n).read_bytes()).hexdigest() for n in SOURCES
    }
    public = plan(
        setup,
        note,
        today,
        EVAL_DIRECTORY,
        EVAL_STAGE,
        ARMS,
        tag["seed"],
        {
            "tag": tag["tag"],
            "tag_commit": tag["commit"],
            "seed": tag["seed"],
            "seed_rule": "int(first 8 hex of SHA-256(tag commit SHA))",
            "template_pool": setup["pool"],
            "namespace": f"AE-HONCHO-STAGE3-EVAL-v1-{tag['seed']}",
            "sources": sources,
            "dev_check": hashlib.sha256(dev.read_bytes()).hexdigest() if dev.exists() else None,
            "exclusion": "no explicit 1a or 1b agreement: excluded from every arm, reported, not replaced",
            "analysis": "research/honcho_stage3_analysis.py: only arms complete for every included family",
        },
    )
    first = [{"session": 1, "family": f, "arm": a} for f in names for a in ("S1a", "S1b")]
    return {**public, "jobs": first + public["jobs"]}


def eval_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    tag, directory = tag_state(), EVAL_DIRECTORY
    if tag is None:
        if args.approved_requests is None:
            print(
                f"Dry run: tag {TAG} not found; the tag needs CALL_NOTES and evaluation caps first."
            )
            return 0
        parser.error(f"The evaluation needs the annotated protocol tag {TAG}.")
    if tag["changed"]:
        parser.error(f"Frozen sources differ from {TAG}: {tag['changed']} (a deviation; not run).")
    if not CALL_NOTES:
        parser.error(
            "The Stage 3 evaluation needs the owner's Plastic Labs call notes (CALL_NOTES)."
        )
    setup = setup_for(EVAL_STAGE, directory, tag["seed"])
    today = hf._today(directory)
    setup["today"] = cm.today_sentence(today)
    if args.summarize:
        from research.honcho_stage3_analysis import analyse, rows_from_runs

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
    hf._live(parser, args, EVAL_STAGE)
    dev = DEV_DIRECTORY / "summary.json"
    if not dev.exists() or json.loads(dev.read_text(encoding="utf-8"))["verdict"] != "PASS":
        parser.error("The evaluation starts only after the dev check passed.")
    hf._plan_file(directory, public, parser)
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
        jobs, history_fn = cm.select(public["jobs"], "session1", []), None
    else:
        jobs, history_fn = cm.select(public["jobs"], "sessions", included), history()
        missing = [
            cp.job_id(j)
            for j in jobs
            if j["arm"] in cp.RETRIEVERS
            and not (directory / "memory" / f"{j['family']}-{j['arm']}.json").exists()
        ]
        problems = cp.shim_problems(directory, cp.PROVIDER_STAGES[EVAL_STAGE]["shim_caps"])
        if missing or problems:
            parser.error(f"Sessions need every memory record and clean shims: {missing} {problems}")
    outcome = asyncio.run(
        cp.live_run(
            directory,
            args.model,
            EVAL_STAGE,
            jobs,
            setup,
            history_fn=history_fn,
            infra_continue=True,
            exclude_uncommitted=True,
        )
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


def dev_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    directory, source = DEV_DIRECTORY, cp.RUNS / hf.SOURCE_STAGE
    setup = setup_for(DEV_STAGE, directory)
    today = hf._today(directory)
    setup["today"] = cm.today_sentence(today)
    if args.summarize:
        print(json.dumps(dev_summary(directory, setup), indent=2, default=str))
        return 0
    notes = CALL_NOTES or (
        "not yet recorded (the owner allowed the dev check before the call notes)"
        if args.dev_before_call_notes
        else None
    )
    inputs = {
        f: {
            x: hashlib.sha256(cp.transcript(r["messages"]).encode()).hexdigest()
            for x, r in zip(("1a", "1b"), cm._first_sessions(source, f))
        }
        for f in sorted(setup["families"])
    }
    public = plan(
        setup,
        args.note,
        today,
        source,
        DEV_STAGE,
        ARMS,
        hf.DEV_SEED,
        {
            "source_stage": hf.SOURCE_STAGE,
            "inputs": inputs,
            "call_notes": notes,
            "dev_before_call_notes": bool(args.dev_before_call_notes),
        },
    )
    if args.approved_requests is None:
        print(json.dumps({**public, "jobs": len(public["jobs"])}, indent=2))
        return 0
    if CALL_NOTES is None and not args.dev_before_call_notes:
        parser.error(
            "Stage 3 waits for the owner's call notes (or --dev-before-call-notes if the owner allows)."
        )
    hf._live(parser, args, DEV_STAGE)
    hf._plan_file(directory, public, parser)
    if args.phase == "providers":
        result = providers(setup, directory, source, today, DEV_STAGE)
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    missing = [
        cp.job_id(j)
        for j in public["jobs"]
        if j["arm"] in cp.RETRIEVERS
        and not (directory / "memory" / f"{j['family']}-{j['arm']}.json").exists()
    ]
    problems = cp.shim_problems(directory, cp.PROVIDER_STAGES[DEV_STAGE]["shim_caps"])
    if missing or problems:
        parser.error(f"Sessions need every memory record and clean shims: {missing} {problems}")
    outcome = asyncio.run(
        cp.live_run(
            directory,
            args.model,
            DEV_STAGE,
            public["jobs"],
            setup,
            history_fn=history(),
            infra_continue=True,
            exclude_uncommitted=True,
        )
    )
    summary = dev_summary(directory, setup, outcome)
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Honcho Stage 3: dreaming, app-written facts, memory tool."
    )
    parser.add_argument("--stage", choices=["dev", "eval"], default="dev")
    parser.add_argument("--phase", choices=["session1", "providers", "sessions"])
    parser.add_argument("--approved-requests", type=int)
    parser.add_argument("--note", help="Provenance note recorded in the plan (required to run).")
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument(
        "--dev-before-call-notes",
        action="store_true",
        help="Only if the owner allows the dev check before the call notes are recorded.",
    )
    args = parser.parse_args()
    if args.stage == "dev" and args.phase == "session1":
        parser.error(
            "The dev check reuses frozen session-1 dialogues; use --phase providers|sessions."
        )
    return eval_main(parser, args) if args.stage == "eval" else dev_main(parser, args)


if __name__ == "__main__":
    raise SystemExit(main())
