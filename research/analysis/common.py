"""What every Studies 4-20 analysis shares: public rows from private runs, the cohort of included
families, paired outcome tables, Holm blocks, CSV input and output, and the command line.

Standard library only, so CI can recompute every published table from the public CSVs. Unit:
family; a family without every session-1 agreement is excluded from every arm (reported, not
replaced); only arms with a session-2 row for every included family are analysed, the others are
reported as not run.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research.analysis.stats import holm, mcnemar_exact, wilson

Row = dict[str, Any]
Tables = dict[str, dict[str, dict[str, bool]]]
TWO_SESSIONS = ("S1a", "S1b")


def flag(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


def num(value: Any) -> float:
    return float(value) if str(value).strip() not in ("", "None") else 0.0


def read_csv(path: Path) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(rows: list[Row], path: Path, fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: row.get(k, "") for k in fields} for row in rows)


# Private runs to public rows (needs the harness; never imported by the CSV checks).


def attempts(directory: Path, report: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Attempts and the ledger over all of a session's journals."""
    from research.harness.commitment_pilot import job_id, pilot_ledger

    journals = sorted(directory.glob(f"{job_id(report)}-a*.calls.jsonl"))
    lines = [
        {**json.loads(x), "_journal": str(p)}
        for p in journals
        for x in p.read_text(encoding="utf-8").splitlines()
        if x
    ]
    return len(journals), pilot_ledger(lines, 10**9, 10**9)


def report_rows(
    directory: Path, sessions: Iterable[str] = TWO_SESSIONS
) -> Iterator[tuple[dict[str, Any], dict[str, dict[str, Any]], Row]]:
    """(final report, families by name, its public base row) for every session of a run."""
    from research.harness.commitment_pilot import final_reports

    families = {
        f["family"]: f
        for f in json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    }
    reports = final_reports(directory)
    agreed: dict[str, set[str]] = {}
    for r in reports:
        if r.get("session") == 1 and r.get("commitment"):
            agreed.setdefault(r["family"], set()).add(r["arm"])
    included = {f for f, arms in agreed.items() if arms == set(sessions)}
    for r in reports:
        count, ledger = attempts(directory, r)
        row: Row = {
            "family": r["family"],
            "session": r["session"],
            "arm": r["arm"],
            "included": r["family"] in included,
            "status": r.get("status"),
            "attempts": count,
            "infra_failed": bool(r.get("infra_failure")),
            "requests": ledger["started"],
            "credits": round(ledger["recorded_credits"], 4),
        }
        if r["session"] == 1:
            row["commitment"] = bool(r.get("commitment"))
        yield r, families, row


def stale_exchanges(report: dict[str, Any], family: dict[str, Any]) -> int:
    """Exchanges to exactly the superseded item X."""
    return sum(
        c["name"] == "exchange_delivered_order_items"
        and c["arguments"].get("new_item_ids") == [family["stale_id"]]
        for m in report.get("messages") or []
        if m.get("role") == "assistant"
        for c in (m.get("tool_calls") or [])
    )


def session_two(report: dict[str, Any], stale: int) -> Row:
    """The outcome columns every changed-mind session-2 row has."""
    return {
        "success": bool(report.get("success")),
        "stale_commitment": stale,
        "declined": report.get("mutations") == 0,
        "wrong_variant_other": int(report.get("wrong_variant_attempts") or 0) - stale,
        "unauthorized_attempts": report.get("unauthorized_attempts"),
        "proposals_before_consent": report.get("proposals_before_consent"),
        "leakage": bool(report.get("leakage")),
    }


def memory_record(directory: Path, report: dict[str, Any]) -> dict[str, Any] | None:
    path = directory / "memory" / f"{report['family']}-{report['arm']}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def memory_columns(record: dict[str, Any], family: dict[str, Any]) -> Row:
    text = record.get("text") or ""
    return {
        "memory_chars": record.get("chars"),
        "memory_error": bool(record.get("error")),
        "memory_has_Y": family["target_id"] in text,
        "memory_has_X": family["stale_id"] in text,
    }


def with_tool_calls(directory: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add each session-2 row's memory-tool call count."""
    from research.harness.commitment_pilot import final_reports

    calls = {
        (r["family"], r["arm"]): len(r.get("memory_tool_calls") or [])
        for r in final_reports(directory)
        if r.get("session") == 2
    }
    for row in rows:
        if str(row["session"]) == "2":
            row["tool_calls"] = calls.get((row["family"], row["arm"]), 0)
    return rows


def ordered(rows: list[Row], arms: Iterable[str]) -> list[Row]:
    order = {a: i for i, a in enumerate(arms)}
    return sorted(rows, key=lambda x: (x["family"], x["session"], order.get(x["arm"], 99)))


# Public rows to the pre-specified tables.


@dataclass(frozen=True)
class Cohort:
    families: list[str]
    included: list[str]
    second: list[Row]
    complete: set[str]

    @property
    def excluded(self) -> list[str]:
        return sorted(set(self.families) - set(self.included))

    def cell(self, arm: str) -> list[Row]:
        return [r for r in self.second if r["arm"] == arm]


def cohort(rows: list[Row], arms: Iterable[str], sessions: Iterable[str] = TWO_SESSIONS) -> Cohort:
    first = [r for r in rows if str(r["session"]) == "1"]
    agreed: dict[str, set[str]] = {}
    for r in first:
        if flag(r.get("commitment")):
            agreed.setdefault(r["family"], set()).add(r["arm"])
    families = sorted({r["family"] for r in first})
    included = sorted(f for f in families if agreed.get(f) == set(sessions))
    second = [r for r in rows if str(r["session"]) == "2" and r["family"] in included]
    complete = {a for a in arms if {r["family"] for r in second if r["arm"] == a} == set(included)}
    return Cohort(families, included, second, complete)


def outcome_tables(second: list[Row], counted: Iterable[str] = ()) -> Tables:
    """Per outcome, family -> arm -> bool: success, stale (executed X), and each counted column."""
    tables: Tables = {"success": {}, "stale": {}, **{k: {} for k in counted}}
    for r in second:
        tables["success"].setdefault(r["family"], {})[r["arm"]] = flag(r.get("success"))
        tables["stale"].setdefault(r["family"], {})[r["arm"]] = num(r.get("stale_commitment")) > 0
        for key in counted:
            tables[key].setdefault(r["family"], {})[r["arm"]] = num(r.get(key)) > 0
    return tables


def paired(
    by: dict[str, dict[str, bool]],
    arm: str,
    reference: str,
    names: tuple[str, str] = ("arm_only", "reference_only"),
    digits: int = 6,
) -> dict[str, Any]:
    """Family-paired exact McNemar of `arm` against `reference`."""
    pairs = [f for f, arms in by.items() if arm in arms and reference in arms]
    wins = sum(by[f][arm] and not by[f][reference] for f in pairs)
    losses = sum(by[f][reference] and not by[f][arm] for f in pairs)
    return {
        "arm": arm,
        "reference": reference,
        "pairs": len(pairs),
        names[0]: wins,
        names[1]: losses,
        "p": round(mcnemar_exact(wins, losses), digits),
    }


def with_holm(tests: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    adjusted = holm({k: v["p"] for k, v in tests.items()})
    for key, value in tests.items():
        value["p_holm"] = adjusted[key]
    return tests


def block(
    tests: Iterable[tuple[str, str, str]], tables: Tables, complete: set[str]
) -> dict[str, Any]:
    """One Holm family of (arm, reference, outcome) tests; tests on an arm not run are listed."""
    tests = tuple(tests)
    run = {f"{a} vs {b} ({e})": paired(tables[e], a, b) for a, b, e in tests if {a, b} <= complete}
    not_run = [f"{a} vs {b} ({e})" for a, b, e in tests if not {a, b} <= complete]
    return {"tests": with_holm(run), "not_run": not_run}


def not_run(cell: list[Row], included: int) -> dict[str, str]:
    return {"status": "not run" if not cell else f"incomplete ({len(cell)} of {included})"}


def count(cell: list[Row], column: str) -> int:
    return sum(flag(r.get(column)) for r in cell)


def positive(cell: list[Row], column: str) -> int:
    return sum(num(r.get(column)) > 0 for r in cell)


def mean(cell: list[Row], column: str, digits: int) -> float:
    return round(sum(num(r.get(column)) for r in cell) / len(cell), digits)


def exchange_arms(
    group: Cohort, arms: tuple[str, ...], memory_arms: tuple[str, ...], tools: bool = False
) -> dict[str, Any]:
    """Per arm: success with its Wilson interval, X executed, declines, cost and what the memory
    block contained (Studies 8 to 12)."""
    table: dict[str, Any] = {}
    for arm in arms:
        cell = group.cell(arm)
        if arm not in group.complete:
            table[arm] = not_run(cell, len(group.included))
            continue
        n, k, memory = len(cell), count(cell, "success"), arm in memory_arms
        table[arm] = {
            "successes": k,
            "n": n,
            "wilson95": wilson(k, n),
            "stale": positive(cell, "stale_commitment"),
            "declined": count(cell, "declined"),
            "infra_failed": count(cell, "infra_failed"),
            **({"tool_sessions": positive(cell, "tool_calls")} if tools else {}),
            "requests_per_session": mean(cell, "requests", 2),
            "credits_per_session": mean(cell, "credits", 3),
            "memory_has_Y": count(cell, "memory_has_Y") if memory else None,
            "memory_has_X": count(cell, "memory_has_X") if memory else None,
        }
    return table


def arm_summary(cohort_: Cohort, arms: tuple[str, ...], planned_families: int) -> dict[str, Any]:
    return {
        "planned_families": planned_families,
        "session1_families": len(cohort_.families),
        "included": len(cohort_.included),
        "excluded": cohort_.excluded,
        "complete_arms": [a for a in arms if a in cohort_.complete],
        "not_run_arms": [a for a in arms if a not in cohort_.complete],
    }


def totals(rows: list[Row]) -> dict[str, Any]:
    return {
        "leakage_sessions": sum(flag(r.get("leakage")) for r in rows),
        "requests_total": int(sum(num(r.get("requests")) for r in rows)),
        "credits_total": round(sum(num(r.get("credits")) for r in rows), 2),
    }


def main(
    description: str,
    rows_from_runs: Callable[..., list[Row]],
    analyse: Callable[..., dict[str, Any]],
    fields: tuple[str, ...],
    studies: Iterable[str] = (),
    run: str = "<stage>",
) -> None:
    """`--csv` recomputes the table from a public CSV; `--root` from a private run directory,
    optionally writing its public CSV."""
    parser = argparse.ArgumentParser(description=description)
    if studies:
        parser.add_argument("--study", choices=sorted(studies), required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root", type=Path, help=f"Private run directory (research/runs/commitment/{run})."
    )
    source.add_argument("--csv", type=Path, help="Public per-session CSV.")
    parser.add_argument("--write-csv", type=Path, help="Write the public CSV (with --root).")
    args = parser.parse_args()
    study = (args.study,) if studies else ()
    rows = rows_from_runs(*study, args.root) if args.root else read_csv(args.csv)
    if args.write_csv:
        write_csv(rows, args.write_csv, fields)
    print(json.dumps(analyse(*study, rows), indent=2))
