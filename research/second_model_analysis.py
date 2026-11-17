"""Pre-specified analysis of the second-model replication (tag second-model-eval-v1; gpt-6-luna).

Standard library only, so CI can recompute the published table from the public CSV. Unit: family;
exclusion as before. Only arms complete for every included family are analysed; others are not run.
Exact family-paired McNemar:
- Primary (Holm across three): Mi, Hod and Hs each vs Hn on success.
- Secondary (Holm across three): the same pairs on executing the superseded item X.
Comparisons with the Claude Haiku 5.5 studies are descriptive only (different families).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research import honcho_features_analysis as hfa
from research.changed_mind_analysis import _flag, _num
from research.memory_analysis import wilson

ARMS = ("Hn", "Mi", "Hod", "Hs")
MEMORY_ARMS = ("Mi", "Hod", "Hs")
PRIMARY = (("Mi", "Hn", "success"), ("Hod", "Hn", "success"), ("Hs", "Hn", "success"))
SECONDARY = (("Mi", "Hn", "stale"), ("Hod", "Hn", "stale"), ("Hs", "Hn", "stale"))
FIELDS = hfa.FIELDS


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    return hfa.rows_from_runs(directory, MEMORY_ARMS)


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
        arms[arm] = {"successes": k, "n": n, "wilson95": wilson(k, n),
                     "stale": sum(_num(r.get("stale_commitment")) > 0 for r in cell),
                     "declined": sum(_flag(r.get("declined")) for r in cell),
                     "infra_failed": sum(_flag(r.get("infra_failed")) for r in cell),
                     "requests_per_session": round(sum(_num(r.get("requests")) for r in cell) / n, 2),
                     "credits_per_session": round(sum(_num(r.get("credits")) for r in cell) / n, 3),
                     "memory_has_Y": sum(_flag(r.get("memory_has_Y")) for r in cell) if arm in MEMORY_ARMS else None,
                     "memory_has_X": sum(_flag(r.get("memory_has_X")) for r in cell) if arm in MEMORY_ARMS else None}  # fmt: skip
    return {"planned_families": planned_families, "session1_families": len(families), "included": len(included),
            "excluded": sorted(set(families) - set(included)), "complete_arms": [a for a in ARMS if a in complete],
            "not_run_arms": [a for a in ARMS if a not in complete], "arms": arms,
            "primary_success": hfa._block(PRIMARY, tables, complete),
            "secondary_stale": hfa._block(SECONDARY, tables, complete),
            "leakage_sessions": sum(_flag(r.get("leakage")) for r in rows),
            "requests_total": int(sum(_num(r.get("requests")) for r in rows)),
            "credits_total": round(sum(_num(r.get("credits")) for r in rows), 2)}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-specified second-model replication analysis.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root", type=Path, help="Private run directory (research/runs/commitment/m2-eval-v1)."
    )
    source.add_argument("--csv", type=Path, help="Public per-session CSV.")
    parser.add_argument("--write-csv", type=Path, help="Write the public CSV (with --root).")
    args = parser.parse_args()
    rows = rows_from_runs(args.root) if args.root else hfa.read_csv(args.csv)
    if args.write_csv:
        hfa.write_csv(rows, args.write_csv)
    print(json.dumps(analyse(rows), indent=2))


if __name__ == "__main__":
    main()
