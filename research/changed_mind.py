"""Changed-mind pilot (owner-approved pilot only; evaluation not approved).

Session 1a: a scripted customer agrees one exact exchange variant X and defers. Session 1b, a
separate conversation with no memory given to the actor: the customer says they changed their
mind, describes Y by its options (never naming X), agrees Y by item ID and defers. Session 2: "go
ahead with the exchange we agreed last time"; the customer never restates X or Y except in R.

Arms: Hn (1a then 1b transcripts, labelled with their order, under the neutral header), M (Mem0)
and Ho (Honcho), each ingesting 1a then 1b for the same customer, and R (Y restated with its ID;
harness control). Success = Y executed under the existing oracle; an exchange to X is a stale
commitment. Reuses the commitment-pilot harness (scripted customer, oracle, ledger, providers);
a second infrastructure failure marks that session failed and the run continues.
Dry run by default; live calls need --approved-requests 240.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

from research import commitment_pilot as cp

STAGE = "cm-pilot-v1"
DIRECTORY = cp.RUNS / STAGE
NAMESPACE = "AE-CHANGED-MIND-PILOT-v1"
SEED = int(hashlib.sha256(NAMESPACE.encode()).hexdigest()[:8], 16)
EVAL_SEED = 529098645  # commitment-eval-v1 families are avoided (names and IDs)
ARMS = ("Hn", "M", "Ho", "R")
CFG = cp.PROVIDER_STAGES[STAGE]
BUDGET = cp.BUDGETS[cp.STAGE_BUDGET[STAGE]]
SOURCES = ("changed_mind.py", "commitment_pilot.py", "memory_gateway.py", "provider_ingest.py",
           "memory_retrievers.py", "copilot_shim.py")  # fmt: skip
HOH_STAGE = "cm-hoh-v1"  # dev check of Honcho at its highest level; reuses the pilot's ingestion
HOH_DIRECTORY = cp.RUNS / HOH_STAGE
HOH_CFG = cp.PROVIDER_STAGES[HOH_STAGE]
HOH_BUDGET = cp.BUDGETS[cp.STAGE_BUDGET[HOH_STAGE]]
HOH_LEVEL = cp.RETRIEVERS["Hoh"][1]
LEVEL_RULE = ("Honcho 5c7d24b ReasoningLevel = minimal, low, medium, high, max (src/config.py; "
              "schemas/api.py default low). Rule: the highest level the server accepts with the configured "
              "shim model, chosen before any call; 'max' validated offline in the API container "
              "(openai transport, claude-haiku-5.5 via the shim, MAX_TOOL_ITERATIONS 10).")  # fmt: skip
EVAL_STAGE, EVAL_TAG = "cm-eval-v1", "changed-mind-eval-v1"
EVAL_DIRECTORY = cp.RUNS / EVAL_STAGE
EVAL_CFG = cp.PROVIDER_STAGES[EVAL_STAGE]
EVAL_BUDGET = cp.BUDGETS[cp.STAGE_BUDGET[EVAL_STAGE]]
EVAL_ARMS = ("N", "Hn", "M", "Ho", "Hoh")
EVAL_SOURCES = (*SOURCES, "changed_mind_analysis.py")
# A fresh name pool: the shared one has too few unused combinations after C, D and E families.
EVAL_FIRST = ("Imogen", "Jasper", "Kiran", "Linnea", "Marlo", "Nadia", "Orrin", "Petra")
EVAL_LAST = (
    "Iverson",
    "Jessup",
    "Kingsley",
    "Lockhart",
    "Merriweather",
    "Norcross",
    "Oakley",
    "Pendleton",
)
ASKS_EARLIER = re.compile(r"\b(?:previous|earlier|originally|before|last time|which item)\b")


def build(base: dict[str, Any], pool: list[str]) -> list[dict[str, Any]]:
    """Four D families: Y (target) at positions 0-3 once each; X two places after Y."""
    avoid = cp.build_eval_families(base, EVAL_SEED, pool)
    families = cp.build_eval_families(base, SEED, pool, count=4, prefix="D", width=1,
                                      namespace=NAMESPACE, avoid=avoid)  # fmt: skip
    for f in families:
        alternatives = f["alternatives"]
        f["stale_id"] = alternatives[(f["target_position"] + 2) % len(alternatives)]["item_id"]
    return families


def build_eval(base: dict[str, Any], pool: list[str], seed: int) -> list[dict[str, Any]]:
    """32 F families from the tag-derived seed, disjoint from the C, D and E families."""
    avoid = cp.build_eval_families(base, EVAL_SEED, pool) + build(base, pool)
    families = cp.build_eval_families(base, seed, pool, count=32, prefix="F", width=2,
                                      namespace=f"AE-CHANGED-MIND-EVAL-v1-{seed}", avoid=avoid,
                                      names=[(a, b) for a in EVAL_FIRST for b in EVAL_LAST])  # fmt: skip
    for f in families:
        alternatives = f["alternatives"]
        f["stale_id"] = alternatives[(f["target_position"] + 2) % len(alternatives)]["item_id"]
    return families


def prepare(seed: int | None = None) -> dict[str, Any]:
    """Families (pilot D1-D4, or the 32 evaluation families for a seed), isolated DB, validated Y
    references and X (stale) exchanges; zero inference."""
    setup = cp.prepare(
        builder=build if seed is None else (lambda base, pool: build_eval(base, pool, seed))
    )
    for f in setup["families"].values():
        if len({f["stale_id"], f["target_id"], f["rejected_id"]}) != 3:
            raise cp.FatalStop(f"{f['family']}: X, Y and the rejected variant must differ.")
        stale = {**cp.reference_action(f)["arguments"], "new_item_ids": [f["stale_id"]]}
        env = setup["constructor"]()
        before = env.get_db_hash()
        env.make_tool_call("exchange_delivered_order_items", requestor="assistant", **stale)
        if env.get_db_hash() == before:
            raise cp.FatalStop(f"{f['family']}: the stale exchange does not change the DB.")
    setup["customer"] = ChangedMindCustomer
    return setup


class ChangedMindCustomer(cp.ScriptedCustomer):
    """Session 1a agrees X; session 1b changes to Y; session 2 is the commitment-pilot customer
    with target Y (target-blind consent outside R, so X, Y and others get the same reply)."""

    def __init__(self, family: dict[str, Any], session: int, arm: str = "N") -> None:
        self.phase = arm if session == 1 else "2"
        view = {**family, "target_id": family["stale_id"]} if self.phase == "S1a" else family
        super().__init__(view, session, arm if session == 2 else "N")

    def reply(self, agent_text: str) -> str:
        if self.phase != "S1b":
            return super().reply(agent_text)
        f, self.turns = self.family, self.turns + 1
        wanted = cp._option(f, f["target_id"])
        if self.turns == 1:
            return (f"Hi, I'm {f['first']} {f['last']} ({f['email']}). About the exchange for the "
                    f"{f['product']} from order {f['order_id']} that we discussed before: I've changed my "
                    f"mind. I'd now like the {wanted} instead. Can you find it and confirm its exact item ID?")  # fmt: skip
        if self.turns > 6:
            return self._end("I'll come back another time.")
        named = cp.identified(f, agent_text)
        if named == {f["target_id"]}:
            self.agreed = True
            return self._end(f"Yes, that's the one: the {wanted}. Let's agree on that instead, but "
                             "please don't make the exchange today; I'll confirm it next time.")  # fmt: skip
        if named == {f["stale_id"]}:
            return f"No, I changed my mind; I want the {wanted} now."
        if named and f["target_id"] not in named:
            return f"No, not that one. I want the {wanted}."
        if ASKS_EARLIER.search(agent_text.casefold()):
            return f"It's the one we agreed last time, but I now want the {wanted}. What is its exact item ID?"
        return f"To be clear, I want the {wanted}. What is its exact item ID?"


def plan(setup: dict[str, Any], note: str | None) -> dict[str, Any]:
    names = sorted(setup["families"])
    first = [{"session": 1, "family": f, "arm": a} for f in names for a in ("S1a", "S1b")]
    second = [{"session": 2, "family": f, "arm": a} for f in names for a in ARMS]
    random.Random(SEED).shuffle(second)
    sources = {
        n: hashlib.sha256((Path(cp.__file__).parent / n).read_bytes()).hexdigest() for n in SOURCES
    }
    return {"stage": STAGE, "namespace": NAMESPACE, "seed": SEED, "manifest_sha256": setup["manifest_sha256"],
            "template_pool": setup["pool"], "request_cap": BUDGET["cap"], "credit_stop": BUDGET["credit_stop"],
            "call_max": cp.CALL_MAX, "episode_cap": CFG["episode_cap"], "shim_caps": CFG["shim_caps"],
            "session_requests": cp.SESSION_REQUESTS, "session_tools": cp.SESSION_TOOLS,
            "mem0": {"scope": f"user_id {CFG['prefix']}<family>, run_id per session", "search": "library default"},
            "honcho": {"workspace": CFG["workspace"], "reasoning_level": "server default"},
            "header": cp.NEUTRAL_HEADER, "memory_max_chars": cp.HISTORY_MAX,
            "infra_rule": "second infrastructure failure: that session failed (infra); the run continues",
            "note": note, "sources": sources, "jobs": first + second}  # fmt: skip


def hoh_plan(setup: dict[str, Any], note: str | None) -> dict[str, Any]:
    jobs = [{"session": 2, "family": f, "arm": "Hoh"} for f in sorted(setup["families"])]
    sources = {
        n: hashlib.sha256((Path(cp.__file__).parent / n).read_bytes()).hexdigest() for n in SOURCES
    }
    return {"stage": HOH_STAGE, "manifest_sha256": setup["manifest_sha256"], "request_cap": HOH_BUDGET["cap"],
            "credit_stop": HOH_BUDGET["credit_stop"], "call_max": cp.CALL_MAX, "episode_cap": HOH_CFG["episode_cap"],
            "shim_caps": HOH_CFG["shim_caps"], "honcho": {"workspace": HOH_CFG["workspace"], "reasoning_level": HOH_LEVEL,
            "ingestion": "none (reuses cm-pilot-v1)"}, "level_rule": LEVEL_RULE, "header": cp.NEUTRAL_HEADER,
            "memory_max_chars": cp.HISTORY_MAX, "note": note, "sources": sources, "jobs": jobs}  # fmt: skip


def hoh_retrieve(setup: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Retrieval only (no ingestion): Honcho dialectic at HOH_LEVEL for each family, with the
    shim requests and credits each dialectic call used."""
    from research import provider_ingest

    status = provider_ingest.post("/status", {"provider": "mem0"}, url=cp.GATEWAY)
    problems = cp.shim_problems(directory, HOH_CFG["shim_caps"])
    if (
        status["honcho_workspace"] != HOH_CFG["workspace"]
        or status["honcho_reasoning_level"] is not None
    ):
        problems.append("gateway Honcho workspace or default level is not the changed-mind setting")
    problems += cp.pilot_ledger(
        cp.journal_rows(directory), HOH_BUDGET["cap"], HOH_BUDGET["credit_stop"]
    )["reasons"]
    if problems:
        return {"refused": problems}
    queue = provider_ingest.post("/status", {"provider": "honcho"}, url=cp.GATEWAY)["queue"]
    (directory / "honcho-queue.json").write_text(json.dumps(queue) + "\n", encoding="utf-8")
    journal = directory / "shims" / "honcho.calls.jsonl"
    cost: dict[str, dict[str, float]] = {}

    def spent() -> dict[str, Any]:
        return cp.pilot_ledger(cp.journal_rows(journal.parent), 10**6, 10**6)

    def search(provider: str, scope: str, query: str, level: str | None = None) -> list[str]:
        before = spent()
        body = {"provider": provider, "scope": scope, "query": query, "reasoning_level": level}
        try:
            return provider_ingest.post("/search", body, url=cp.GATEWAY, timeout=900)["results"]
        finally:
            after = spent()
            cost[scope] = {"shim_requests": after["started"] - before["started"],
                           "shim_credits": round(after["recorded_credits"] - before["recorded_credits"], 4)}  # fmt: skip

    records = cp.retrieve_memories(
        setup, directory, search, HOH_CFG["prefix"], sorted(setup["families"]), ("Hoh",)
    )
    for name in setup["families"]:
        path = directory / "memory" / f"{name}-Hoh.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["scope"] in cost and "shim_requests" not in record:
            record.update(cost[record["scope"]])
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {"refused": cp.shim_problems(directory, HOH_CFG["shim_caps"]), "honcho_queue": queue,
            "retrievals": [{**cp.memory_meta(r), **cost.get(r["scope"], {})} for r in records]}  # fmt: skip


def hoh_summary(directory: Path, setup: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for r in cp.final_reports(directory):
        f = setup["families"][r["family"]]
        record = json.loads(
            (directory / "memory" / f"{r['family']}-Hoh.json").read_text(encoding="utf-8")
        )
        text = record.get("text") or ""
        stale = stale_attempts(f, r.get("messages") or [])
        rows.append({"family": r["family"], "arm": r["arm"], "status": r.get("status"), "success": r.get("success"),
                     "stale_commitment": stale, "declined": r.get("mutations") == 0,
                     "wrong_variant_other": int(r.get("wrong_variant_attempts") or 0) - stale,
                     "unauthorized": r.get("unauthorized_attempts"), "proposals_before_consent": r.get("proposals_before_consent"),
                     "requests": r.get("requests_started"), "attempt": r.get("attempt"), "leakage": bool(r.get("leakage")),
                     "memory_error": bool(record.get("error")), "memory_chars": record.get("chars"),
                     "memory_has_Y": f["target_id"] in text, "memory_has_X": f["stale_id"] in text,
                     "shim_requests": record.get("shim_requests"), "shim_credits": record.get("shim_credits")})  # fmt: skip
    rows_all = cp.journal_rows(directory)
    ledger = {k: {x: y for x, y in cp.pilot_ledger(v, HOH_BUDGET["cap"], HOH_BUDGET["credit_stop"]).items() if x != "reasons"}
              for k, v in {"total": rows_all, "honcho": [r for r in rows_all if Path(r["_journal"]).parent.name == "shims"],
                           "episodes": [r for r in rows_all if Path(r["_journal"]).parent.name != "shims"]}.items()}  # fmt: skip
    gates = {"retrievals_4of4": sum(not r["memory_error"] for r in rows) == 4 and len(rows) == 4,
             "zero_leakage": not any(r["leakage"] for r in rows)}  # fmt: skip
    return {"level": HOH_LEVEL, "rows": rows, "gates": gates, "verdict": "PASS" if all(gates.values()) else "FAIL",
            "ledger": ledger}  # fmt: skip


def committed(directory: Path) -> list[str]:
    """Families whose 1a and 1b both reached an explicit agreement with an unchanged DB."""
    by: dict[str, set[str]] = {}
    for r in cp.final_reports(directory):
        if r.get("session") == 1 and r.get("commitment"):
            by.setdefault(r["family"], set()).add(r["arm"])
    return sorted(f for f, arms in by.items() if arms == {"S1a", "S1b"})


def _first_sessions(directory: Path, family: str) -> tuple[dict[str, Any], dict[str, Any]]:
    reports = {r["arm"]: r for r in cp.final_reports(directory)
               if r.get("family") == family and r.get("session") == 1}  # fmt: skip
    a, b = reports.get("S1a"), reports.get("S1b")
    if not (a and a.get("commitment") and b and b.get("commitment")):
        raise cp.FatalStop(f"{family}: missing session-1a or 1b agreement.")
    return a, b


def labelled_history(directory: Path, family: str) -> str:
    a, b = _first_sessions(directory, family)
    return (f"Earlier session (1 of 2):\n{cp.transcript(a['messages'])}\n\n"
            f"Most recent session (2 of 2):\n{cp.transcript(b['messages'])}")  # fmt: skip


def history(directory: Path, job: dict[str, Any]) -> tuple[str | None, dict | None]:
    if job["arm"] == "Hn":
        return labelled_history(directory, job["family"]), None
    if job["arm"] in cp.RETRIEVERS:
        return cp._session_two_history(directory, job)
    return None, None


def provider_inputs(directory: Path, prefix: str = CFG["prefix"]) -> dict[str, dict[str, Any]]:
    """Both sessions per committed family, in order (1a then 1b), as separate episodes."""
    inputs = {}
    for family in committed(directory):
        a, b = _first_sessions(directory, family)
        inputs[family] = {"episodes": [{"id": f"{prefix}{family}-s1{x}", "lines": cp.dialogue(r["messages"])}
                                       for x, r in (("a", a), ("b", b))]}  # fmt: skip
    return inputs


def select(jobs: list[dict[str, Any]], phase: str, included: list[str]) -> list[dict[str, Any]]:
    if phase == "session1":
        return [j for j in jobs if j["session"] == 1]
    return [j for j in jobs if j["session"] == 2 and j["family"] in included]


def stale_attempts(family: dict[str, Any], messages: list[dict[str, Any]]) -> int:
    return sum(c["name"] == "exchange_delivered_order_items"
               and c["arguments"].get("new_item_ids") == [family["stale_id"]]
               for m in messages if m.get("role") == "assistant" for c in (m.get("tool_calls") or []))  # fmt: skip


def summarize(directory: Path, setup: dict[str, Any]) -> dict[str, Any]:
    """Per family x arm table (booleans only for memory), integration gates, ledger."""
    from research.provider_ingest import done

    reports = cp.final_reports(directory)
    attempts: dict[str, int] = {}
    for p in directory.glob("D*-s*-a*.json"):
        key = cp.ATTEMPT.match(p.name)
        if key:
            data = json.loads(p.read_text(encoding="utf-8"))
            attempts[key.group(1)] = attempts.get(key.group(1), 0) + int(
                data.get("requests_started") or 0
            )
    rows = []
    for r in reports:
        family = setup["families"][r["family"]]
        row = {k: r.get(k) for k in ("family", "session", "arm", "status", "success", "commitment",
                                       "attempt", "proposals_before_consent", "unauthorized_attempts")}  # fmt: skip
        row["requests"] = attempts.get(cp.job_id(r), r.get("requests_started"))
        row["infra_failed"] = bool(r.get("infra_failure"))
        if r["session"] == 2:
            stale = stale_attempts(family, r.get("messages") or [])
            row.update(stale_commitment=stale, declined=r.get("mutations") == 0,
                       wrong_variant_other=int(r.get("wrong_variant_attempts") or 0) - stale,
                       leakage=bool(r.get("leakage")))  # fmt: skip
            path = directory / "memory" / f"{r['family']}-{r['arm']}.json"
            if r["arm"] in cp.PROVIDER_ARMS and path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                text = record.get("text") or ""
                row.update(memory_error=bool(record.get("error")), memory_has_Y=family["target_id"] in text,
                           memory_has_X=family["stale_id"] in text)  # fmt: skip
        rows.append(row)
    second = [r for r in rows if r["session"] == 2]
    ingested = done(directory / "ingest.jsonl")
    retrieval = {p: sum(r["arm"] == a and r.get("memory_error") is False for r in second)
                 for a, p in cp.PROVIDER_ARMS.items()}  # fmt: skip
    ingest_ok = {p: sum(all((p, cp.provider_scope(f, CFG["prefix"]), f"{CFG['prefix']}{f}-s1{x}") in ingested
                            for x in "ab") for f in setup["families"]) for p in cp.PROVIDER_ARMS.values()}  # fmt: skip
    queue_path = directory / "honcho-queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else None
    first = {a: sum(r["arm"] == a and bool(r["commitment"]) for r in rows) for a in ("S1a", "S1b")}
    gates = {"1a_agreement_4of4": first["S1a"] == 4, "1b_agreement_4of4": first["S1b"] == 4,
             "R_4of4": sum(r["arm"] == "R" and bool(r["success"]) for r in second) == 4,
             **{f"{p}_ingested_retrieved_3of4": ingest_ok[p] >= 3 and retrieval[p] >= 3 for p in ingest_ok},
             "honcho_queue_drained": bool(queue) and not (queue["pending"] or queue["in_progress"]),
             "zero_leakage": not any(r.get("leakage") for r in second)}  # fmt: skip
    arms = {a: {"successes": sum(r["arm"] == a and bool(r["success"]) for r in second),
                "n": sum(r["arm"] == a for r in second),
                "stale_commitment": sum(r["stale_commitment"] > 0 for r in second if r["arm"] == a)}
            for a in ARMS}  # fmt: skip
    rows_all = cp.journal_rows(directory)
    groups = {label: [r for r in rows_all if Path(r["_journal"]).name == f"{label}.calls.jsonl"]
              for label in CFG["shim_caps"]}  # fmt: skip
    groups["episodes"] = [r for r in rows_all if Path(r["_journal"]).parent.name != "shims"]
    ledger = {k: {x: y for x, y in cp.pilot_ledger(v, BUDGET["cap"], BUDGET["credit_stop"]).items() if x != "reasons"}
              for k, v in {"total": rows_all, **groups}.items()}  # fmt: skip
    return {"rows": sorted(rows, key=lambda r: (r["family"], r["session"], str(r["arm"]))), "arms": arms,
            "ingested_families": ingest_ok, "retrievals_ok": retrieval, "honcho_queue": queue, "gates": gates,
            "verdict": "PASS" if all(gates.values()) else "FAIL", "ledger": ledger}  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description="Changed-mind pilot; dry run by default.")
    parser.add_argument("--stage", choices=["pilot", "hoh", "eval"], default="eval")
    parser.add_argument("--phase", choices=["session1", "providers", "sessions"])
    parser.add_argument("--approved-requests", type=int)
    parser.add_argument("--note", help="Provenance note recorded in the plan (required to run).")
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.stage == "eval":
        return eval_main(parser, args)
    setup = prepare()
    if args.stage == "hoh":
        return hoh_main(parser, args, setup)
    if args.summarize:
        print(json.dumps(summarize(DIRECTORY, setup), indent=2, default=str))
        return 0
    public = plan(setup, args.note)
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
    if args.approved_requests != BUDGET["cap"] or not args.note or not args.phase:
        parser.error(f"Live runs need --phase, --note and --approved-requests {BUDGET['cap']}.")
    plan_path = DIRECTORY / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding="utf-8")) != public:
            parser.error("The plan or frozen sources changed since the pilot started.")
    elif any(DIRECTORY.glob("*.calls.jsonl")):
        parser.error("Run directory has journals but no plan; use a fresh directory.")
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    if not plan_path.exists():
        plan_path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    included = committed(DIRECTORY)
    if args.phase == "providers":
        result = cp.provider_phase(setup, DIRECTORY, provider_inputs(DIRECTORY), STAGE)
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    jobs = select(public["jobs"], args.phase, included)
    if args.phase == "sessions":
        missing = [cp.job_id(j) for j in jobs if j["arm"] in cp.PROVIDER_ARMS
                   and not (DIRECTORY / "memory" / f"{j['family']}-{j['arm']}.json").exists()]  # fmt: skip
        if missing or cp.shim_problems(DIRECTORY, CFG["shim_caps"]):
            parser.error(f"Sessions need every retrieval and clean shims: {missing}")
    outcome = asyncio.run(cp.live_run(DIRECTORY, args.model, STAGE, jobs, setup, history_fn=history,
                                      infra_continue=True, exclude_uncommitted=True))  # fmt: skip
    summary = summarize(DIRECTORY, setup)
    (DIRECTORY / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({"refused": outcome["refused"], "infra_events": outcome["infra_events"],
                      **{k: v for k, v in summary.items() if k != "rows"}}, indent=2, default=str))  # fmt: skip
    return 1 if outcome["refused"] else 0


def hoh_main(
    parser: argparse.ArgumentParser, args: argparse.Namespace, setup: dict[str, Any]
) -> int:
    if args.summarize:
        print(json.dumps(hoh_summary(HOH_DIRECTORY, setup), indent=2, default=str))
        return 0
    public = hoh_plan(setup, args.note)
    if args.approved_requests is None:
        print(json.dumps({**public, "jobs": len(public["jobs"])}, indent=2))
        return 0
    if (
        args.approved_requests != HOH_BUDGET["cap"]
        or not args.note
        or args.phase not in ("providers", "sessions")
    ):
        parser.error(
            f"Live runs need --phase providers|sessions, --note and --approved-requests {HOH_BUDGET['cap']}."
        )
    plan_path = HOH_DIRECTORY / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding="utf-8")) != public:
            parser.error("The plan or frozen sources changed since the check started.")
    else:
        HOH_DIRECTORY.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    if args.phase == "providers":
        result = hoh_retrieve(setup, HOH_DIRECTORY)
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    missing = [
        f for f in setup["families"] if not (HOH_DIRECTORY / "memory" / f"{f}-Hoh.json").exists()
    ]
    if missing or cp.shim_problems(HOH_DIRECTORY, HOH_CFG["shim_caps"]):
        parser.error(f"Sessions need every retrieval and a clean shim: {missing}")
    outcome = asyncio.run(cp.live_run(HOH_DIRECTORY, args.model, HOH_STAGE, public["jobs"], setup,
                                      history_fn=history, infra_continue=True, exclude_uncommitted=True))  # fmt: skip
    summary = hoh_summary(HOH_DIRECTORY, setup)
    (HOH_DIRECTORY / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({"refused": outcome["refused"], "infra_events": outcome["infra_events"],
                      **{k: v for k, v in summary.items() if k != "rows"}}, indent=2, default=str))  # fmt: skip
    return 1 if outcome["refused"] else 0


def eval_tag_state(tag: str = EVAL_TAG) -> dict[str, Any] | None:
    """The protocol tag's commit, the derived seed, and frozen sources changed since the tag."""
    import subprocess

    root = Path(cp.__file__).resolve().parent.parent

    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout

    try:
        commit = git("rev-parse", f"{tag}^{{commit}}").decode().strip()
    except subprocess.CalledProcessError:
        return None
    changed = [n for n in EVAL_SOURCES
               if git("show", f"{commit}:research/{n}") != (Path(cp.__file__).parent / n).read_bytes()]  # fmt: skip
    return {"tag": tag, "commit": commit, "seed": cp.eval_seed(commit), "changed": changed}


def eval_plan(setup: dict[str, Any], note: str | None, tag: dict[str, Any]) -> dict[str, Any]:
    names = sorted(setup["families"])
    first = [{"session": 1, "family": f, "arm": a} for f in names for a in ("S1a", "S1b")]
    second = [{"session": 2, "family": f, "arm": a} for f in names for a in EVAL_ARMS]
    random.Random(tag["seed"]).shuffle(second)
    sources = {
        n: hashlib.sha256((Path(cp.__file__).parent / n).read_bytes()).hexdigest()
        for n in EVAL_SOURCES
    }
    return {"stage": EVAL_STAGE, "tag": tag["tag"], "tag_commit": tag["commit"], "seed": tag["seed"],
            "seed_rule": "int(first 8 hex of SHA-256(tag commit SHA))", "namespace": f"AE-CHANGED-MIND-EVAL-v1-{tag['seed']}",
            "manifest_sha256": setup["manifest_sha256"], "template_pool": setup["pool"],
            "request_cap": EVAL_BUDGET["cap"], "credit_stop": EVAL_BUDGET["credit_stop"], "call_max": cp.CALL_MAX,
            "episode_cap": EVAL_CFG["episode_cap"], "shim_caps": EVAL_CFG["shim_caps"],
            "session_requests": cp.SESSION_REQUESTS, "session_tools": cp.SESSION_TOOLS,
            "mem0": {"scope": f"user_id {EVAL_CFG['prefix']}<family>, run_id per session", "search": "library default"},
            "honcho": {"workspace": EVAL_CFG["workspace"], "Ho": "server default (low)", "Hoh": HOH_LEVEL},
            "header": cp.NEUTRAL_HEADER, "memory_max_chars": cp.HISTORY_MAX,
            "exclusion": "no explicit 1a or 1b agreement: excluded from every arm, reported, not replaced",
            "infra_rule": "second infrastructure failure: that session failed (infra); the run continues",
            "analysis": "research/changed_mind_analysis.py", "note": note, "sources": sources,
            "jobs": first + second}  # fmt: skip


def eval_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    tag = eval_tag_state()
    if tag is None:
        if args.approved_requests is None:
            print(
                f"Dry run: tag {EVAL_TAG} not found; evaluation families are generated only after it."
            )
            return 0
        parser.error(f"The evaluation needs the annotated protocol tag {EVAL_TAG}.")
    if tag["changed"]:
        parser.error(
            f"Frozen sources differ from {EVAL_TAG}: {tag['changed']} (a deviation; not run)."
        )
    setup = prepare(tag["seed"])
    if args.summarize:
        from research.changed_mind_analysis import analyse, rows_from_runs

        print(json.dumps(analyse(rows_from_runs(EVAL_DIRECTORY)), indent=2))
        return 0
    public = eval_plan(setup, args.note, tag)
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
    if args.approved_requests != EVAL_BUDGET["cap"] or not args.note or not args.phase:
        parser.error(
            f"Live runs need --phase, --note and --approved-requests {EVAL_BUDGET['cap']}."
        )
    plan_path = EVAL_DIRECTORY / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding="utf-8")) != public:
            parser.error("The plan or frozen sources changed since the run started.")
    elif any(EVAL_DIRECTORY.glob("*.calls.jsonl")):
        parser.error("Run directory has journals but no plan; use a fresh directory.")
    else:
        EVAL_DIRECTORY.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    if args.phase in ("providers", "sessions"):
        done = {r["family"] for r in cp.final_reports(EVAL_DIRECTORY) if r.get("session") == 1}
        if done != set(setup["families"]):
            parser.error(f"Session 1 is incomplete: {sorted(set(setup['families']) - done)}")
    included = committed(EVAL_DIRECTORY)
    if args.phase == "providers":
        excluded = sorted(set(setup["families"]) - set(included))
        (EVAL_DIRECTORY / "exclusions.json").write_text(
            json.dumps({"included": included, "excluded": excluded}, indent=2) + "\n",
            encoding="utf-8",
        )
        result = cp.provider_phase(setup, EVAL_DIRECTORY, provider_inputs(EVAL_DIRECTORY, EVAL_CFG["prefix"]),
                                   EVAL_STAGE, ("M", "Ho", "Hoh"))  # fmt: skip
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    jobs = select(public["jobs"], args.phase, included)
    if args.phase == "sessions":
        missing = [cp.job_id(j) for j in jobs if j["arm"] in cp.RETRIEVERS
                   and not (EVAL_DIRECTORY / "memory" / f"{j['family']}-{j['arm']}.json").exists()]  # fmt: skip
        if missing or cp.shim_problems(EVAL_DIRECTORY, EVAL_CFG["shim_caps"]):
            parser.error(f"Sessions need every retrieval and clean shims: {missing}")
    outcome = asyncio.run(cp.live_run(EVAL_DIRECTORY, args.model, EVAL_STAGE, jobs, setup, history_fn=history,
                                      infra_continue=True, exclude_uncommitted=True))  # fmt: skip
    print(json.dumps({"refused": outcome["refused"], "infra_events": outcome["infra_events"],
                      "sessions_run": len(outcome["results"])}, indent=2))  # fmt: skip
    return 1 if outcome["refused"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
