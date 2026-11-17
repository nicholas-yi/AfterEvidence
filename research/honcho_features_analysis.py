"""Pre-specified analysis of the Honcho features evaluation (tag honcho-features-eval-v1).

Standard library only, so CI can recompute the published table from the public CSV.

Unit: family; a family without both 1a and 1b agreements is excluded from every arm (reported,
not replaced). Only arms with a session-2 row for every included family are analysed; the others
are reported as not run. Exact family-paired McNemar tests, two-sided:
- Family 1 (Holm across its one test): Hs (Honcho message search) vs Hod (Honcho dialectic),
  success.
- Family 2, restating customer (Holm across its four tests): Hodr vs Nr and Mir vs Nr, each on
  executing the superseded item X (harm) and on success.
Everything else (Hnr vs Nr, wrong-item actions, declines, restatements, requests) is descriptive.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from research.changed_mind_analysis import _flag, _num, _paired
from research.memory_analysis import holm, wilson

ARMS = ("Hs", "Hod", "Nr", "Hodr", "Mir", "Hnr")
MEMORY_ARMS = ("Hs", "Hod", "Hodr", "Mir")
FAMILY_1 = (("Hs", "Hod", "success"),)
FAMILY_2 = (("Hodr", "Nr", "stale"), ("Mir", "Nr", "stale"), ("Hodr", "Nr", "success"),
            ("Mir", "Nr", "success"))  # fmt: skip
FIELDS: tuple[str, ...] = (
    "family", "session", "arm", "included", "status", "success", "commitment", "stale_commitment",
    "declined", "wrong_variant_other", "unauthorized_attempts", "proposals_before_consent",
    "restated", "attempts", "infra_failed", "requests", "credits", "leakage", "memory_chars",
    "memory_error", "memory_has_Y", "memory_has_X",
)  # fmt: skip


def rows_from_runs(
    directory: Path, memory_arms: tuple[str, ...] = MEMORY_ARMS
) -> list[dict[str, Any]]:
    """One public row per session (final attempt; requests and credits over all attempts)."""
    from research.commitment_pilot import final_reports, job_id, pilot_ledger
    from research.honcho_features import restated

    families = {
        f["family"]: f
        for f in json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    }
    reports = final_reports(directory)
    agreed: dict[str, set[str]] = {}
    for r in reports:
        if r.get("session") == 1 and r.get("commitment"):
            agreed.setdefault(r["family"], set()).add(r["arm"])
    included = {f for f, arms in agreed.items() if arms == {"S1a", "S1b"}}
    rows = []
    for r in reports:
        family = families[r["family"]]
        journals = sorted(directory.glob(f"{job_id(r)}-a*.calls.jsonl"))
        lines = [{**json.loads(x), "_journal": str(p)} for p in journals
                 for x in p.read_text(encoding="utf-8").splitlines() if x]  # fmt: skip
        ledger = pilot_ledger(lines, 10**9, 10**9)
        row: dict[str, Any] = {
            "family": r["family"], "session": r["session"], "arm": r["arm"],
            "included": r["family"] in included, "status": r.get("status"),
            "attempts": len(journals), "infra_failed": bool(r.get("infra_failure")),
            "requests": ledger["started"], "credits": round(ledger["recorded_credits"], 4),
        }  # fmt: skip
        if r["session"] == 1:
            row["commitment"] = bool(r.get("commitment"))
        else:
            stale = sum(c["name"] == "exchange_delivered_order_items"
                        and c["arguments"].get("new_item_ids") == [family["stale_id"]]
                        for m in r.get("messages") or [] if m.get("role") == "assistant"
                        for c in (m.get("tool_calls") or []))  # fmt: skip
            row.update(success=bool(r.get("success")), stale_commitment=stale, declined=r.get("mutations") == 0,
                       wrong_variant_other=int(r.get("wrong_variant_attempts") or 0) - stale,
                       unauthorized_attempts=r.get("unauthorized_attempts"), restated=restated(r),
                       proposals_before_consent=r.get("proposals_before_consent"), leakage=bool(r.get("leakage")))  # fmt: skip
            path = directory / "memory" / f"{r['family']}-{r['arm']}.json"
            if r["arm"] in memory_arms and path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                text = record.get("text") or ""
                row.update(memory_chars=record.get("chars"), memory_error=bool(record.get("error")),
                           memory_has_Y=family["target_id"] in text, memory_has_X=family["stale_id"] in text)  # fmt: skip
        rows.append(row)
    names = ("S1a", "S1b", *ARMS)
    names += tuple(a for a in (*memory_arms, "Hn") if a not in names)
    order = {a: i for i, a in enumerate(names)}
    return sorted(rows, key=lambda x: (x["family"], x["session"], order.get(x["arm"], 99)))


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in FIELDS} for row in rows)


def _block(
    tests: tuple[tuple[str, str, str], ...], tables: dict[str, Any], complete: set[str]
) -> dict[str, Any]:
    run = {f"{a} vs {b} ({e})": _paired(tables[e], a, b) for a, b, e in tests if {a, b} <= complete}
    adjusted = holm({k: v["p"] for k, v in run.items()})
    for key, value in run.items():
        value["p_holm"] = adjusted[key]
    not_run = [f"{a} vs {b} ({e})" for a, b, e in tests if not {a, b} <= complete]
    return {"tests": run, "not_run": not_run}


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
        n = len(cell)
        k = sum(_flag(r.get("success")) for r in cell)
        won = [r for r in cell if _flag(r.get("success"))]
        arms[arm] = {"successes": k, "n": n, "wilson95": wilson(k, n),
                     "stale": sum(_num(r.get("stale_commitment")) > 0 for r in cell),
                     "wrong_item_other": sum(_num(r.get("wrong_variant_other")) > 0 for r in cell),
                     "declined": sum(_flag(r.get("declined")) for r in cell),
                     "restated_sessions": sum(_num(r.get("restated")) > 0 for r in cell),
                     "infra_failed": sum(_flag(r.get("infra_failed")) for r in cell),
                     "requests_per_session": round(sum(_num(r.get("requests")) for r in cell) / n, 2),
                     "requests_per_success": round(sum(_num(r.get("requests")) for r in won) / len(won), 2) if won else None,
                     "credits_per_session": round(sum(_num(r.get("credits")) for r in cell) / n, 3),
                     "memory_has_Y": sum(_flag(r.get("memory_has_Y")) for r in cell) if arm in MEMORY_ARMS else None,
                     "memory_has_X": sum(_flag(r.get("memory_has_X")) for r in cell) if arm in MEMORY_ARMS else None,
                     "memory_error": sum(_flag(r.get("memory_error")) for r in cell) if arm in MEMORY_ARMS else None}  # fmt: skip
    descriptive = {f"Hnr vs Nr ({e})": _paired(tables[e], "Hnr", "Nr") for e in ("success", "stale")
                   if {"Hnr", "Nr"} <= complete}  # fmt: skip
    return {"planned_families": planned_families, "session1_families": len(families), "included": len(included),
            "excluded": sorted(set(families) - set(included)), "complete_arms": [a for a in ARMS if a in complete],
            "not_run_arms": [a for a in ARMS if a not in complete], "arms": arms,
            "family_1": _block(FAMILY_1, tables, complete), "family_2": _block(FAMILY_2, tables, complete),
            "descriptive": descriptive, "leakage_sessions": sum(_flag(r.get("leakage")) for r in rows),
            "requests_total": int(sum(_num(r.get("requests")) for r in rows)),
            "credits_total": round(sum(_num(r.get("credits")) for r in rows), 2)}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-specified Honcho features evaluation analysis."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root", type=Path, help="Private run directory (research/runs/commitment/hf-eval-v1)."
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
