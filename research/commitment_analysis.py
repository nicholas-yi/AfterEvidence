"""Pre-specified analysis of the necessary-memory evaluation (tag commitment-eval-v1).

Standard library only, so CI can recompute the published table from the public CSV.

Unit: family. A family whose session 1 lacks an explicit commitment is excluded from every
arm (reported, not replaced). Success is the oracle's (normal completion, native DB match,
agreed-variant arguments, consent before any mutation, no unauthorized mutation); every other
status counts as failure. Primary: Hn vs N, family-paired exact McNemar, two-sided alpha 0.05.
Secondaries: M, Ho and Hc each vs Hn, exact McNemar with Holm adjustment across the three.
Everything else is descriptive.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from research.memory_analysis import holm, mcnemar_exact, wilson

ARMS = ("N", "Hc", "Hn", "M", "Ho")
PRIMARY = ("Hn", "N")
SECONDARIES = (("M", "Hn"), ("Ho", "Hn"), ("Hc", "Hn"))
FIELDS: tuple[str, ...] = (
    "family", "session", "arm", "included", "status", "success", "commitment", "attempts",
    "infra_failures", "requests", "credits", "lookups", "proposals_before_consent",
    "wrong_variant_attempts", "unauthorized_attempts", "confirmation_first", "leakage",
    "memory_chars", "memory_error", "memory_has_target_id", "memory_has_target_options",
)  # fmt: skip


def _flag(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


def _num(value: Any) -> float:
    return float(value) if str(value).strip() not in ("", "None") else 0.0


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    """One public row per session from the private run directory (final attempt; requests and
    credits summed over all attempts). No transcripts, names, or memory text."""
    from research.commitment_pilot import final_reports, job_id, pilot_ledger

    reports = final_reports(directory)
    included = {r["family"] for r in reports if r.get("session") == 1 and r.get("commitment")}
    rows = []
    for r in reports:
        stem = job_id(r)
        journals = sorted(directory.glob(f"{stem}-a*.calls.jsonl"))
        lines = [{**json.loads(x), "_journal": str(p)} for p in journals
                 for x in p.read_text(encoding="utf-8").splitlines() if x]  # fmt: skip
        ledger = pilot_ledger(lines, 10**9, 10**9)
        memory = r.get("memory") or {}
        two = r["session"] == 2
        rows.append({
            "family": r["family"], "session": r["session"], "arm": r["arm"],
            "included": r["family"] in included, "status": r.get("status"),
            "success": bool(r.get("success")) if two else "", "commitment": "" if two else bool(r.get("commitment")),
            "attempts": len(journals), "infra_failures": max(0, len(journals) - 1),
            "requests": ledger["started"], "credits": round(ledger["recorded_credits"], 4),
            "lookups": r.get("lookups"), "proposals_before_consent": r.get("proposals_before_consent", ""),
            "wrong_variant_attempts": r.get("wrong_variant_attempts", ""),
            "unauthorized_attempts": r.get("unauthorized_attempts", ""),
            "confirmation_first": r.get("confirmation_first", ""), "leakage": bool(r.get("leakage")),
            "memory_chars": memory.get("chars", ""), "memory_error": bool(memory.get("error")) if memory else "",
            "memory_has_target_id": memory.get("has_target_id", ""),
            "memory_has_target_options": memory.get("has_target_options", ""),
        })  # fmt: skip
    return sorted(
        rows,
        key=lambda x: (x["family"], x["session"], ARMS.index(x["arm"]) if x["arm"] in ARMS else -1),
    )


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in FIELDS} for row in rows)


def _paired(by: dict[str, dict[str, bool]], arm: str, reference: str) -> dict[str, Any]:
    pairs = [f for f, arms in by.items() if arm in arms and reference in arms]
    wins = sum(by[f][arm] and not by[f][reference] for f in pairs)
    losses = sum(by[f][reference] and not by[f][arm] for f in pairs)
    return {"arm": arm, "reference": reference, "pairs": len(pairs), "wins": wins, "losses": losses,
            "p": round(mcnemar_exact(wins, losses), 4)}  # fmt: skip


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    first = [r for r in rows if str(r["session"]) == "1"]
    included = sorted(r["family"] for r in first if _flag(r.get("commitment")))
    second = [r for r in rows if str(r["session"]) == "2" and r["family"] in included]
    by: dict[str, dict[str, bool]] = {}
    for r in second:
        by.setdefault(r["family"], {})[r["arm"]] = _flag(r.get("success"))
    arms: dict[str, Any] = {}
    for arm in ARMS:
        cell = [r for r in second if r["arm"] == arm]
        k, n = sum(_flag(r.get("success")) for r in cell), len(cell)
        arms[arm] = {"successes": k, "n": n, "wilson95": wilson(k, n),
                     "credits_per_session": round(sum(_num(r.get("credits")) for r in cell) / n, 3) if n else None,
                     "requests_per_session": round(sum(_num(r.get("requests")) for r in cell) / n, 2) if n else None,
                     "lookups_mean": round(sum(_num(r.get("lookups")) for r in cell) / n, 2) if n else None,
                     "proposals_before_consent_mean": round(
                         sum(_num(r.get("proposals_before_consent")) for r in cell) / n, 2) if n else None,
                     "wrong_variant": int(sum(_num(r.get("wrong_variant_attempts")) for r in cell)),
                     "unauthorized": int(sum(_num(r.get("unauthorized_attempts")) for r in cell))}  # fmt: skip
    primary = _paired(by, *PRIMARY)
    secondaries = {f"{a} vs {b}": _paired(by, a, b) for a, b in SECONDARIES}
    adjusted = holm({k: v["p"] for k, v in secondaries.items()})
    for key, value in secondaries.items():
        value["p_holm"] = adjusted[key]
    memory: dict[str, Any] = {}
    for arm in ("M", "Ho"):
        cell = [r for r in second if r["arm"] == arm]
        lacking = [
            r
            for r in cell
            if not _flag(r.get("memory_error")) and not _flag(r.get("memory_has_target_id"))
        ]
        memory[arm] = {"retrieval_errors": sum(_flag(r.get("memory_error")) for r in cell),
                       "has_target_id": sum(_flag(r.get("memory_has_target_id")) for r in cell),
                       "has_target_options": sum(_flag(r.get("memory_has_target_options")) for r in cell),
                       "lacking_id_recovered": [sum(_flag(r.get("success")) for r in lacking), len(lacking)]}  # fmt: skip
    complete = len(second) == len(included) * len(ARMS) and len(first) == planned_families
    return {"planned_families": planned_families, "session1_run": len(first), "included": len(included),
            "excluded": sorted(r["family"] for r in first if not _flag(r.get("commitment"))),
            "complete": complete, "arms": arms,
            "primary": {**primary, "alpha": 0.05, "significant": primary["p"] < 0.05},
            "secondaries": secondaries, "provider_memory": memory,
            "leakage_sessions": sum(_flag(r.get("leakage")) for r in rows),
            "credits_total": round(sum(_num(r.get("credits")) for r in rows), 2),
            "requests_total": int(sum(_num(r.get("requests")) for r in rows))}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-specified necessary-memory evaluation analysis."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root", type=Path, help="Private run directory (research/runs/commitment/eval-v1)."
    )
    source.add_argument("--csv", type=Path, help="Public per-session CSV.")
    parser.add_argument("--write-csv", type=Path, help="Write the public CSV (with --root).")
    args = parser.parse_args()
    rows = rows_from_runs(args.root) if args.root else read_csv(args.csv)
    if args.write_csv:
        write_csv(rows, args.write_csv)
    print(json.dumps(analyse(rows), indent=2))


if __name__ == "__main__":
    main()
