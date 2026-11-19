"""Episode runner for the proposed stale-memory diagnostic (approval pending; not run).

Runs one staleness stage serially through the existing Copilot harness: `CopilotBackend`
journals, the flat `WireCommand` action contract with one counted re-ask per episode, and
`study_runner`'s skip-existing semantics. The default invocation is a dry run that prints the
plan and one rendered episode and makes no model calls. Stage A needs `--approved-requests 144`;
Stage B also needs an existing v2 protocol tag. Before every episode the runner re-reads every
journal in the stage directory and refuses to start on any stop reason.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Protocol, TextIO

from pydantic import BaseModel

from research.copilot_backend import PilotRequestLimit
from research.staleness import (
    ACTOR_INSTRUCTIONS,
    DEV_REQUEST_CAP,
    EVAL_REQUEST_CAP,
    PAID_CONDITIONS,
    REGIMES,
    REQUESTS_PER_EPISODE,
    TOOLS,
    AccountEnv,
    Family,
    dev_families,
    eval_families,
    feasibility,
    ledger_stops,
    render_memory,
    scenario,
)
from research.tau_copilot import WireCommand, protocol_commit

SHUFFLE_SEED = 20261113
V2_TAG_PREFIX = "staleness-v2"
STAGES = {
    "a": {"cap": DEV_REQUEST_CAP, "credit_stop": 36.0, "replicates": 1},
    "b": {"cap": EVAL_REQUEST_CAP, "credit_stop": 825.0, "replicates": 2},
}
TOOL_NAMES = {tool["name"] for tool in TOOLS}
ROOT = Path(__file__).resolve().parent / "runs" / "staleness"
ACTION_FORMAT = (
    "Each turn return exactly one JSON action: "
    '{"kind":"tool","value":"lookup_account|submit_target|abstain","arguments_json":"JSON-encoded '
    'argument object"}. lookup_account takes {}; submit_target takes {"value": "..."}; abstain takes '
    '{"reason": "..."}.'
)


class Backend(Protocol):
    calls: int

    def write(self, event: str, **fields: object) -> None: ...

    async def complete(
        self,
        system: str,
        prompt: str,
        response_schema: type[BaseModel] | dict[str, Any] | None = None,
    ) -> str: ...


def stage_plan(stage: str, tag: str | None = None) -> dict[str, Any]:
    """Shuffled job list. Stage B families exist only for an explicit, existing v2 tag."""
    if stage == "a":
        families, commit = dev_families(), None
    elif stage == "b":
        if not tag or not tag.startswith(V2_TAG_PREFIX):
            raise ValueError(f"Stage B needs an explicit existing {V2_TAG_PREFIX}* protocol tag.")
        commit = protocol_commit(tag)
        families = eval_families(commit)
    else:
        raise ValueError(f"unknown stage {stage!r}")
    settings = STAGES[stage]
    jobs = [
        {"family": f.family_id, "regime": r, "condition": c, "replicate": n}
        for f in families
        for r in REGIMES
        for c in PAID_CONDITIONS
        for n in range(1, int(settings["replicates"]) + 1)
    ]
    random.Random(SHUFFLE_SEED).shuffle(jobs)
    sources = {
        name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in ("staleness.py", "staleness_runner.py")
    }
    return {
        "stage": stage,
        "shuffle_seed": SHUFFLE_SEED,
        "tag": tag,
        "tag_commit": commit,
        "request_cap": settings["cap"],
        "credit_stop": settings["credit_stop"],
        "requests_per_episode": REQUESTS_PER_EPISODE,
        "sources": sources,
        "jobs": jobs,
        "_families": {f.family_id: f for f in families},
    }


def job_id(job: dict[str, Any]) -> str:
    return f"{job['family']}-{job['regime']}-{job['condition']}-r{job['replicate']}"


def episode_system(visible: dict[str, Any], condition: str) -> str:
    memory = render_memory(visible, condition)
    return f"{ACTOR_INSTRUCTIONS}\n{ACTION_FORMAT}" + (f"\n\n{memory}" if memory else "")


def episode_prompt(visible: dict[str, Any], history: list[dict[str, Any]]) -> str:
    return json.dumps({"customer_request": visible["request"], "tools": TOOLS, "history": history})


def _action(text: str) -> tuple[str, dict[str, Any]]:
    value = WireCommand.model_validate_json(text).native(TOOL_NAMES)
    if value["kind"] != "tool":
        raise ValueError("Only tool actions are available in this task.")
    name, arguments = value["name"], value["arguments"]
    expected = {"lookup_account": set(), "submit_target": {"value"}, "abstain": {"reason"}}[name]
    if set(arguments) != expected or not all(isinstance(v, str) for v in arguments.values()):
        raise ValueError(f"{name} takes exactly {sorted(expected)} as strings.")
    return name, arguments


async def run_episode(
    backend: Backend, family: Family, regime: str, condition: str
) -> dict[str, Any]:
    """One episode; malformed output gets one counted re-ask per episode and is never repaired."""
    case = scenario(family, regime)
    visible = case["visible"]
    env, history, reasks = AccountEnv(case), [], 0
    system = episode_system(visible, condition)
    status, error = "completed", None
    try:
        while env.terminal is None:
            prompt = episode_prompt(visible, history)
            text = await backend.complete(system, prompt, WireCommand)
            try:
                name, arguments = _action(text)
            except ValueError as rejected:
                if reasks:
                    raise
                reasks += 1
                backend.write("actor-reask", error=str(rejected)[:300], rejected=text)
                note = f"\n\nYour previous action was rejected: {str(rejected)[:300]} Return one valid action."
                name, arguments = _action(
                    await backend.complete(system + note, prompt, WireCommand)
                )
            history.append(
                {"action": name, "arguments": arguments, "result": env.call(name, arguments)}
            )
    except PilotRequestLimit as stop:
        status, error = "budget-capped", str(stop)
    except (ValueError, RuntimeError, TimeoutError, OSError) as failure:
        status, error = "failed", f"{type(failure).__name__}: {failure}"[:500]
    result = env.outcome()
    return {
        "family": family.family_id,
        "regime": regime,
        "condition": condition,
        "status": status,
        "outcome": result["outcome"],
        "looked_up_before_submit": result["looked_up_before_submit"],
        "terminal": env.terminal,
        "submitted": env.submitted,
        "reasks": reasks,
        "requests_started": backend.calls,
        "memory_chars": len(render_memory(visible, condition)),
        "error": error,
        "history": history,
    }


def journal_rows(directory: Path) -> list[dict[str, Any]]:
    rows = []
    for journal in sorted(directory.rglob("*.calls.jsonl")):
        rows += [
            json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line
        ]
    return rows


def start_refusals(directory: Path, cap: int, credit_stop: float) -> list[str]:
    rows = journal_rows(directory)
    reasons = ledger_stops(rows, cap, credit_stop)
    started = sum(r.get("event") == "copilot-request-started" for r in rows)
    if started + REQUESTS_PER_EPISODE > cap:
        reasons.append(
            f"next episode could exceed the cap: {started} + {REQUESTS_PER_EPISODE} > {cap}"
        )
    return reasons


async def run_stage(
    plan: dict[str, Any], directory: Path, make_backend: Any, credit_stop: float | None = None
) -> dict[str, Any]:
    """Serial episodes; existing outputs are skipped, never retried; stops before any unsafe start."""
    directory.mkdir(parents=True, exist_ok=True)
    stop_at = min(plan["credit_stop"], credit_stop or plan["credit_stop"])
    results: list[dict[str, Any]] = []
    for job in plan["jobs"]:
        output = directory / f"{job_id(job)}.json"
        journal_path = output.with_suffix(".calls.jsonl")
        if output.exists() or journal_path.exists():
            results.append({**job, "status": "skipped-existing"})
            continue
        refusals = start_refusals(directory, plan["request_cap"], stop_at)
        if refusals:
            return {"refused": refusals, "results": results}
        with journal_path.open("x", encoding="utf-8", newline="\n") as journal:
            backend = make_backend(journal)
            backend.write("staleness-episode-started", **job, stage=plan["stage"])
            report = await run_episode(
                backend, plan["_families"][job["family"]], job["regime"], job["condition"]
            )
        report.update(stage=plan["stage"], replicate=job["replicate"], tag=plan["tag"])
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        results.append(
            {k: report[k] for k in ("family", "regime", "condition", "status", "outcome")}
        )
    return {"refused": [], "results": results}


def summarize(directory: Path) -> dict[str, Any]:
    reports = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
        if p.name not in {"plan.json", "summary.json"}
    ]
    rows = [
        {k: r[k] for k in ("family", "regime", "condition", "outcome", "looked_up_before_submit")}
        for r in reports
    ]
    outcomes = Counter(f"{r['condition']}/{r['regime']}/{r['outcome']}" for r in rows)
    lookups = {
        c: sum(bool(r["looked_up_before_submit"]) for r in rows if r["condition"] == c)
        for c in PAID_CONDITIONS
    }
    return {
        "episodes": len(rows),
        "statuses": dict(Counter(r["status"] for r in reports)),
        "outcomes": dict(sorted(outcomes.items())),
        "looked_up_before_submit": lookups,
        "reasks": sum(r["reasks"] for r in reports),
        "requests_started": sum(r["requests_started"] for r in reports),
        "floor_check": feasibility(rows),
    }


async def live_run(
    plan: dict[str, Any], directory: Path, model: str, credit_stop: float | None
) -> dict:
    from research.copilot_backend import CopilotBackend, isolated_client, quota_snapshot

    client = isolated_client()
    try:
        await client.start()
        selected = next((m for m in await client.list_models() if m.id == model), None)
        if selected is None or (selected.policy is not None and selected.policy.state != "enabled"):
            raise ValueError("Model is not enabled for this Copilot account.")
        quota = (await quota_snapshot(client)).quota_snapshots.get("premium_interactions")
        if quota is None or quota.remaining_percentage < 1:
            raise RuntimeError("Quota unavailable or below 1%; no inference permitted.")

        def make_backend(journal: TextIO) -> CopilotBackend:
            return CopilotBackend(
                client, model, directory / "isolated-copilot", journal, REQUESTS_PER_EPISODE
            )

        return await run_stage(plan, directory, make_backend, credit_stop)
    finally:
        await client.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Staleness diagnostic runner; dry run by default.")
    parser.add_argument("--stage", choices=sorted(STAGES), default="a")
    parser.add_argument(
        "--approved-requests", type=int, help="Owner-approved stage cap; enables model calls."
    )
    parser.add_argument("--tag", help=f"Existing {V2_TAG_PREFIX}* protocol tag (Stage B only).")
    parser.add_argument(
        "--credit-stop", type=float, help="Optional lower credit stop for this stage."
    )
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--summarize", action="store_true", help="Summarize existing reports only.")
    args = parser.parse_args()
    directory = ROOT / f"stage-{args.stage}"
    if args.summarize:
        print(json.dumps(summarize(directory), indent=2))
        return 0
    plan = stage_plan(args.stage, args.tag)
    public = {k: v for k, v in plan.items() if not k.startswith("_")}
    if args.approved_requests is None:
        job = plan["jobs"][0]
        visible = scenario(plan["_families"][job["family"]], job["regime"])["visible"]
        print(
            json.dumps(
                {**public, "jobs": len(plan["jobs"]), "first_jobs": plan["jobs"][:5]}, indent=2
            )
        )
        print(f"\n--- dry run, no model calls: {job_id(job)} ---")
        print(episode_system(visible, job["condition"]))
        print(episode_prompt(visible, []))
        return 0
    if args.approved_requests != plan["request_cap"]:
        parser.error(f"--approved-requests must equal the stage cap {plan['request_cap']}.")
    if args.credit_stop is not None and args.credit_stop > plan["credit_stop"]:
        parser.error("--credit-stop may only lower the stage credit stop.")
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text(encoding="utf-8")) != public:
        parser.error("The stage plan or frozen sources changed since this stage started.")
    plan_path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    outcome = asyncio.run(live_run(plan, directory, args.model, args.credit_stop))
    summary = summarize(directory)
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"refused": outcome["refused"], **summary}, indent=2))
    return 1 if outcome["refused"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
