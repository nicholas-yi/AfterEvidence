"""Second-model replication (owner, 2026-11-17: "just use cheap stuff"): the dated changed-mind task
with gpt-6-luna, an OpenAI model at Claude Haiku 5.5's per-token price, as the actor and as every
provider's substituted LLM (the shims serve --model whatever model name a provider requests).

Customer who never restates. Arms, in priority order: Hn (dated transcripts), Mi (Mem0 with in-band
dates), Hod (Honcho dialectic, backdated), Hs (Honcho message search). Ingestion and retrieval reuse
the Honcho features machinery (Mi is that stage's Mem0 in-band record). Dev check on the frozen
cm-pilot-v1 D1-D4 dialogues (Haiku's session 1), then 32 P families with session 1 also run by the
second model, after tag second-model-eval-v1. Primary (Holm across three): Mi, Hod and Hs each vs Hn
on success; secondary: executing the superseded X, the same pairs. Cross-model comparisons with
Studies 6-7 are descriptive only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from research import changed_mind as cm
from research import commitment_pilot as cp
from research import honcho_features as hf

MODEL = "gpt-6-luna"
DEV_STAGE, EVAL_STAGE, TAG = "m2-dev-v1", "m2-eval-v1", "second-model-eval-v1"
DEV_DIRECTORY, EVAL_DIRECTORY = cp.RUNS / DEV_STAGE, cp.RUNS / EVAL_STAGE
ARMS = ("Hn", "Mi", "Hod", "Hs")
SOURCES = (*hf.SOURCES, "second_model.py", "second_model_analysis.py")
P_FIRST = ("Ines", "Jorah", "Kestrel", "Lior", "Mireille", "Niall", "Odessa", "Perrin")
P_LAST = (
    "Islington",
    "Jardine",
    "Kettering",
    "Lindqvist",
    "Marchbanks",
    "Northcott",
    "Ormsby",
    "Pemberton",
)
HF_SEED = 4066264165  # honcho-features-eval-v1 K families are avoided


def mem0_record(directory: Path, families: list[str]) -> None:
    """Mi is the same Mem0 in-band retrieval the features stage stores as Mir."""
    for family in families:
        source, target = (
            directory / "memory" / f"{family}-Mir.json",
            directory / "memory" / f"{family}-Mi.json",
        )
        if source.exists() and not target.exists():
            record = json.loads(source.read_text(encoding="utf-8"))
            target.write_text(
                json.dumps({**record, "shared_from": "Mir"}, indent=2) + "\n", encoding="utf-8"
            )


def build_eval(base: dict[str, Any], pool: list[str], seed: int) -> list[dict[str, Any]]:
    avoid = (
        cp.build_eval_families(base, cm.EVAL_SEED, pool)
        + cm.build(base, pool)
        + cm.build_eval(base, pool, cm.CM_EVAL_SEED)
        + cm.build_dated_eval(base, pool, hf.DE_SEED)
        + hf.build_eval(base, pool, HF_SEED)
    )
    families = cp.build_eval_families(
        base,
        seed,
        pool,
        count=32,
        prefix="P",
        width=2,
        namespace=f"AE-SECOND-MODEL-EVAL-v1-{seed}",
        avoid=avoid,
        names=[(a, b) for a in P_FIRST for b in P_LAST],
    )
    for f in families:
        alternatives = f["alternatives"]
        f["stale_id"] = alternatives[(f["target_position"] + 2) % len(alternatives)]["item_id"]
    return families


def prepare(seed: int | None = None) -> dict[str, Any]:
    if seed is None:
        return hf.prepare()
    return hf._validate(cp.prepare(builder=lambda base, pool: build_eval(base, pool, seed)))


def plan(
    setup: dict[str, Any],
    note: str | None,
    today: Any,
    stage: str,
    seed: int,
    extra: dict[str, Any],
    first: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    common = hf._common(setup, today, stage)
    for key in ("arms", "restating_rule", "shared"):
        common.pop(key, None)
    return {
        **common,
        "model": MODEL,
        "provider_llm": f"{MODEL} (shims started with --model {MODEL})",
        "arms": {
            "Hn": "dated transcripts",
            "Mi": "Mem0 with in-band dates",
            "Hod": "Honcho dialectic, backdated",
            "Hs": "Honcho message search",
        },
        "arms_priority": ARMS,
        "note": note,
        **extra,
        "jobs": (first or []) + hf.schedule(list(setup["families"]), ARMS, seed),
    }


def summary(
    directory: Path, setup: dict[str, Any], outcome: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Dev gates (integration): memory OK >= 3/4 for Mi, Hod, Hs; zero leakage; no harness defect."""
    families = sorted(setup["families"])
    records = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (directory / "memory").glob("*.json")
    }
    rows = []
    for r in cp.final_reports(directory):
        if r.get("session") != 2:
            continue
        f = setup["families"][r["family"]]
        text = records.get(f"{r['family']}-{r['arm']}", {}).get("text") or ""
        rows.append(
            {
                "family": r["family"],
                "arm": r["arm"],
                "status": r.get("status"),
                "success": bool(r.get("success")),
                "stale_commitment": cm.stale_attempts(f, r.get("messages") or []),
                "declined": r.get("mutations") == 0,
                "reasks": r.get("reasks"),
                "memory_has_Y": f["target_id"] in text,
                "memory_has_X": f["stale_id"] in text,
                "requests": r.get("requests_started"),
                "leakage": bool(r.get("leakage")),
            }
        )
    ok = {
        arm: sum(not records.get(f"{f}-{arm}", {"error": "missing"}).get("error") for f in families)
        for arm in ("Mi", "Hod", "Hs")
    }
    gates = {
        **{f"{arm}_memory_3of4": n >= 3 for arm, n in ok.items()},
        "zero_leakage": not any(r["leakage"] for r in rows),
        "no_harness_defect": len(rows) == len(families) * len(ARMS)
        and not (outcome or {}).get("refused"),
    }
    budget = cp.BUDGETS[cp.STAGE_BUDGET[DEV_STAGE]]
    rows_all = cp.journal_rows(directory)
    ledger = {
        k: {
            x: y
            for x, y in cp.pilot_ledger(v, budget["cap"], budget["credit_stop"]).items()
            if x != "reasons"
        }
        for k, v in {
            "total": rows_all,
            "episodes": [r for r in rows_all if Path(r["_journal"]).parent.name != "shims"],
        }.items()
    }
    return {
        "rows": sorted(rows, key=lambda r: (r["family"], ARMS.index(r["arm"]))),
        "memory_ok": ok,
        "gates": gates,
        "verdict": "PASS" if all(gates.values()) else "FAIL",
        "ledger": ledger,
    }


def dev_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    directory, source = DEV_DIRECTORY, cp.RUNS / hf.SOURCE_STAGE
    setup = prepare()
    today = hf._today(directory)
    setup["today"] = cm.today_sentence(today)
    if args.summarize:
        print(json.dumps(summary(directory, setup), indent=2, default=str))
        return 0
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
        DEV_STAGE,
        hf.DEV_SEED,
        {"source_stage": hf.SOURCE_STAGE, "inputs": inputs},
    )
    if args.approved_requests is None:
        print(json.dumps({**public, "jobs": len(public["jobs"])}, indent=2))
        return 0
    hf._live(parser, args, DEV_STAGE)
    hf._plan_file(directory, public, parser)
    if args.phase == "providers":
        result = hf.providers(setup, directory, source, today, DEV_STAGE)
        mem0_record(directory, sorted(setup["families"]))
        print(json.dumps(result, indent=2))
        return 1 if result["refused"] else 0
    outcome = hf._sessions(args, parser, directory, DEV_STAGE, public["jobs"], setup, source)
    result = summary(directory, setup, outcome)
    (directory / "summary.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "refused": outcome["refused"],
                "infra_events": outcome["infra_events"],
                **{k: v for k, v in result.items() if k != "rows"},
            },
            indent=2,
            default=str,
        )
    )
    return 1 if outcome["refused"] else 0


def tag_state(tag: str = TAG) -> dict[str, Any] | None:
    import subprocess

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
    first = [{"session": 1, "family": f, "arm": a} for f in names for a in ("S1a", "S1b")]
    dev = DEV_DIRECTORY / "summary.json"
    sources = {
        n: hashlib.sha256((Path(cp.__file__).parent / n).read_bytes()).hexdigest() for n in SOURCES
    }
    return plan(
        setup,
        note,
        today,
        EVAL_STAGE,
        tag["seed"],
        {
            "tag": tag["tag"],
            "tag_commit": tag["commit"],
            "seed": tag["seed"],
            "seed_rule": "int(first 8 hex of SHA-256(tag commit SHA))",
            "template_pool": setup["pool"],
            "namespace": f"AE-SECOND-MODEL-EVAL-v1-{tag['seed']}",
            "sources": sources,
            "dev_check": hashlib.sha256(dev.read_bytes()).hexdigest() if dev.exists() else None,
            "exclusion": "no explicit 1a or 1b agreement: excluded from every arm, reported, not replaced",
            "analysis": "research/second_model_analysis.py: only arms complete for every included family",
        },
        first,
    )


def eval_main(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    tag, directory = tag_state(), EVAL_DIRECTORY
    if tag is None:
        if args.approved_requests is None:
            print(f"Dry run: tag {TAG} not found; evaluation families are generated only after it.")
            print(json.dumps(hf.caps(EVAL_STAGE), indent=2))
            return 0
        parser.error(f"The evaluation needs the annotated protocol tag {TAG}.")
    if tag["changed"]:
        parser.error(f"Frozen sources differ from {TAG}: {tag['changed']} (a deviation; not run).")
    setup = prepare(tag["seed"])
    today = hf._today(directory)
    setup["today"] = cm.today_sentence(today)
    if args.summarize:
        from research.second_model_analysis import analyse, rows_from_runs

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
        result = hf.providers(setup, directory, directory, today, EVAL_STAGE)
        mem0_record(directory, included)
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
        outcome = hf._sessions(
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
        description="Second-model replication of the dated changed-mind task."
    )
    parser.add_argument("--stage", choices=["dev", "eval"], default="dev")
    parser.add_argument("--phase", choices=["session1", "providers", "sessions"])
    parser.add_argument("--approved-requests", type=int)
    parser.add_argument("--note", help="Provenance note recorded in the plan (required to run).")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.model != MODEL:
        parser.error(f"This stage runs {MODEL} only.")
    if args.stage == "dev" and args.phase == "session1":
        parser.error(
            "The dev check reuses frozen session-1 dialogues; use --phase providers|sessions."
        )
    return eval_main(parser, args) if args.stage == "eval" else dev_main(parser, args)


if __name__ == "__main__":
    raise SystemExit(main())
