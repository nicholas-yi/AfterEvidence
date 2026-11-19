"""Pre-specified analysis of the Honcho Stage 3 evaluation (tag honcho-stage3-eval-v1).

Standard library only, so CI can recompute the published table from the public CSV. Unit: family;
exclusion as before; only arms complete for every included family are analysed. Exact
family-paired McNemar:
- Primary (Holm across three): Hdr, Ht and Hw each vs Hod on success.
- Secondary A (Holm across two): Hw vs Fd (what Honcho's storage and retrieval of the app's facts
  adds or loses) and Fd vs Hod (what structured facts add), on success.
- Secondary B (Holm across three): the primary pairs on executing the superseded item X.
Descriptive: memory-tool calls, declines, memory Y/X booleans, requests and credits.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research import honcho_features_analysis as hfa
from research.changed_mind_analysis import _flag, _num
from research.memory_analysis import wilson

ARMS = ("Hod", "Hdr", "Ht", "Hw", "Fd")
MEMORY_ARMS = ("Hod", "Hdr", "Hw", "Fd")
PRIMARY = (("Hdr", "Hod", "success"), ("Ht", "Hod", "success"), ("Hw", "Hod", "success"))
SECONDARY_A = (("Hw", "Fd", "success"), ("Fd", "Hod", "success"))
SECONDARY_B = (("Hdr", "Hod", "stale"), ("Ht", "Hod", "stale"), ("Hw", "Hod", "stale"))
FIELDS: tuple[str, ...] = (*hfa.FIELDS, "tool_calls")


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    from research.commitment_pilot import final_reports

    rows = hfa.rows_from_runs(directory, MEMORY_ARMS)
    calls = {
        (r["family"], r["arm"]): len(r.get("memory_tool_calls") or [])
        for r in final_reports(directory)
        if r.get("session") == 2
    }
    for row in rows:
        if str(row["session"]) == "2":
            row["tool_calls"] = calls.get((row["family"], row["arm"]), 0)
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in FIELDS} for row in rows)


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    first = [r for r in rows if str(r["session"]) == "1"]
    agreed: dict[str, set[str]] = {}
    for r in first:
        if _flag(r.get("commitment")):
            agreed.setdefault(r["family"], set()).add(r["arm"])
    families = sorted({r["family"] for r in first})
    included = sorted(f for f in families if agreed.get(f) == {"S1a", "S1b"})
    second = [r for r in rows if str(r["session"]) == "2" and r["family"] in included]
    complete = {a for a in ARMS if {r["family"] for r in second if r["arm"] == a} == set(included)}
    tables: dict[str, dict[str, dict[str, bool]]] = {"success": {}, "stale": {}}
    for r in second:
        tables["success"].setdefault(r["family"], {})[r["arm"]] = _flag(r.get("success"))
        tables["stale"].setdefault(r["family"], {})[r["arm"]] = _num(r.get("stale_commitment")) > 0
    arms: dict[str, Any] = {}
    for arm in ARMS:
        cell = [r for r in second if r["arm"] == arm]
        if arm not in complete:
            arms[arm] = {
                "status": "not run" if not cell else f"incomplete ({len(cell)} of {len(included)})"
            }
            continue
        n, k = len(cell), sum(_flag(r.get("success")) for r in cell)
        arms[arm] = {
            "successes": k,
            "n": n,
            "wilson95": wilson(k, n),
            "stale": sum(_num(r.get("stale_commitment")) > 0 for r in cell),
            "declined": sum(_flag(r.get("declined")) for r in cell),
            "infra_failed": sum(_flag(r.get("infra_failed")) for r in cell),
            "tool_sessions": sum(_num(r.get("tool_calls")) > 0 for r in cell),
            "requests_per_session": round(sum(_num(r.get("requests")) for r in cell) / n, 2),
            "credits_per_session": round(sum(_num(r.get("credits")) for r in cell) / n, 3),
            "memory_has_Y": sum(_flag(r.get("memory_has_Y")) for r in cell)
            if arm in MEMORY_ARMS
            else None,
            "memory_has_X": sum(_flag(r.get("memory_has_X")) for r in cell)
            if arm in MEMORY_ARMS
            else None,
        }
    return {
        "planned_families": planned_families,
        "session1_families": len(families),
        "included": len(included),
        "excluded": sorted(set(families) - set(included)),
        "complete_arms": [a for a in ARMS if a in complete],
        "not_run_arms": [a for a in ARMS if a not in complete],
        "arms": arms,
        "primary_success": hfa._block(PRIMARY, tables, complete),
        "secondary_facts": hfa._block(SECONDARY_A, tables, complete),
        "secondary_stale": hfa._block(SECONDARY_B, tables, complete),
        "leakage_sessions": sum(_flag(r.get("leakage")) for r in rows),
        "requests_total": int(sum(_num(r.get("requests")) for r in rows)),
        "credits_total": round(sum(_num(r.get("credits")) for r in rows), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-specified Honcho Stage 3 evaluation analysis."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root", type=Path, help="Private run directory (research/runs/commitment/hf3-eval-v1)."
    )
    source.add_argument("--csv", type=Path, help="Public per-session CSV.")
    parser.add_argument("--write-csv", type=Path, help="Write the public CSV (with --root).")
    args = parser.parse_args()
    rows = rows_from_runs(args.root) if args.root else hfa.read_csv(args.csv)
    if args.write_csv:
        write_csv(rows, args.write_csv)
    print(json.dumps(analyse(rows), indent=2))


if __name__ == "__main__":
    main()
