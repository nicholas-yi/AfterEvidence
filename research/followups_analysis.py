"""Pre-specified analyses of Studies 10 (write it down; tag write-it-down-eval-v1), 11 (third
model; tag third-model-eval-v1) and 12 (memory poisoning; tag poisoned-memory-eval-v1).

Standard library only, so CI can recompute the published tables from the public CSVs. Unit: family;
a family without both session-1 agreements is excluded from every arm. Only arms complete for every
included family are analysed; others are reported as not run. Exact family-paired McNemar, Holm
within each family of tests:
- Study 10 primary (two): Mw vs Mi (does writing the facts into Mem0 help it?) and Tn vs Hn (does
  memory the agent must ask for work as well as memory given up front?) on success. Secondary
  (two): Mw vs Fd on success (what Mem0's storage and search of the facts loses) and Mw vs Mi on
  executing the superseded item X.
- Study 11 primary (three): Mi, Hod and Fd each vs Hn on success; secondary: the same pairs on X.
- Study 12 (memory poisoning; tag poisoned-memory-eval-v1) primary (three): Mi, Hod and Fd each vs
  Hn on executing the planted item Z (the "stale" field); secondary: the same pairs on success.
Descriptive: declines, memory-tool sessions, memory Y/X booleans, requests and credits. Comparisons
with other studies are descriptive only (different families).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research import honcho_features_analysis as hfa
from research.changed_mind_analysis import _flag, _num
from research.memory_analysis import wilson

FIELDS: tuple[str, ...] = (*hfa.FIELDS, "tool_calls")
STUDIES: dict[str, dict[str, Any]] = {
    "wd": {
        "arms": ("Mi", "Mw", "Hn", "Tn", "Fd"),
        "memory_arms": ("Mi", "Mw", "Fd"),
        "blocks": {
            "primary_success": (("Mw", "Mi", "success"), ("Tn", "Hn", "success")),
            "secondary": (("Mw", "Fd", "success"), ("Mw", "Mi", "stale")),
        },
    },
    "pz": {
        "arms": ("Hn", "Mi", "Hod", "Fd"),
        "memory_arms": ("Mi", "Hod", "Fd"),
        "blocks": {
            "primary_harm": (("Mi", "Hn", "stale"), ("Hod", "Hn", "stale"), ("Fd", "Hn", "stale")),
            "secondary_success": (
                ("Mi", "Hn", "success"),
                ("Hod", "Hn", "success"),
                ("Fd", "Hn", "success"),
            ),
        },
    },
    "m3": {
        "arms": ("Hn", "Mi", "Hod", "Fd"),
        "memory_arms": ("Mi", "Hod", "Fd"),
        "blocks": {
            "primary_success": (
                ("Mi", "Hn", "success"),
                ("Hod", "Hn", "success"),
                ("Fd", "Hn", "success"),
            ),
            "secondary_stale": (
                ("Mi", "Hn", "stale"),
                ("Hod", "Hn", "stale"),
                ("Fd", "Hn", "stale"),
            ),
        },
    },
}


def rows_from_runs(study: str, directory: Path) -> list[dict[str, Any]]:
    from research.commitment_pilot import final_reports

    rows = hfa.rows_from_runs(directory, STUDIES[study]["memory_arms"])
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


def analyse(study: str, rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    spec = STUDIES[study]
    arms_order, memory_arms = spec["arms"], spec["memory_arms"]
    first = [r for r in rows if str(r["session"]) == "1"]
    agreed: dict[str, set[str]] = {}
    for r in first:
        if _flag(r.get("commitment")):
            agreed.setdefault(r["family"], set()).add(r["arm"])
    families = sorted({r["family"] for r in first})
    included = sorted(f for f in families if agreed.get(f) == {"S1a", "S1b"})
    second = [r for r in rows if str(r["session"]) == "2" and r["family"] in included]
    complete = {
        a for a in arms_order if {r["family"] for r in second if r["arm"] == a} == set(included)
    }
    tables: dict[str, dict[str, dict[str, bool]]] = {"success": {}, "stale": {}}
    for r in second:
        tables["success"].setdefault(r["family"], {})[r["arm"]] = _flag(r.get("success"))
        tables["stale"].setdefault(r["family"], {})[r["arm"]] = _num(r.get("stale_commitment")) > 0
    arms: dict[str, Any] = {}
    for arm in arms_order:
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
            if arm in memory_arms
            else None,
            "memory_has_X": sum(_flag(r.get("memory_has_X")) for r in cell)
            if arm in memory_arms
            else None,
        }
    blocks = {name: hfa._block(pairs, tables, complete) for name, pairs in spec["blocks"].items()}
    return {
        "study": study,
        "planned_families": planned_families,
        "session1_families": len(families),
        "included": len(included),
        "excluded": sorted(set(families) - set(included)),
        "complete_arms": [a for a in arms_order if a in complete],
        "not_run_arms": [a for a in arms_order if a not in complete],
        "arms": arms,
        **blocks,
        "leakage_sessions": sum(_flag(r.get("leakage")) for r in rows),
        "requests_total": int(sum(_num(r.get("requests")) for r in rows)),
        "credits_total": round(sum(_num(r.get("credits")) for r in rows), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-specified analyses of Studies 10, 11 and 12.")
    parser.add_argument("--study", choices=sorted(STUDIES), required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root", type=Path, help="Private run directory (research/runs/commitment/<stage>)."
    )
    source.add_argument("--csv", type=Path, help="Public per-session CSV.")
    parser.add_argument("--write-csv", type=Path, help="Write the public CSV (with --root).")
    args = parser.parse_args()
    rows = rows_from_runs(args.study, args.root) if args.root else hfa.read_csv(args.csv)
    if args.write_csv:
        write_csv(rows, args.write_csv)
    print(json.dumps(analyse(args.study, rows), indent=2))


if __name__ == "__main__":
    main()
