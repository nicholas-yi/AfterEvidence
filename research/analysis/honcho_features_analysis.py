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

from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis.common import count, mean, paired, positive
from research.analysis.stats import wilson

ARMS = ("Hs", "Hod", "Nr", "Hodr", "Mir", "Hnr")
MEMORY_ARMS = ("Hs", "Hod", "Hodr", "Mir")
FAMILY_1 = (("Hs", "Hod", "success"),)
FAMILY_2 = (
    ("Hodr", "Nr", "stale"),
    ("Mir", "Nr", "stale"),
    ("Hodr", "Nr", "success"),
    ("Mir", "Nr", "success"),
)
FIELDS: tuple[str, ...] = (
    "family",
    "session",
    "arm",
    "included",
    "status",
    "success",
    "commitment",
    "stale_commitment",
    "declined",
    "wrong_variant_other",
    "unauthorized_attempts",
    "proposals_before_consent",
    "restated",
    "attempts",
    "infra_failed",
    "requests",
    "credits",
    "leakage",
    "memory_chars",
    "memory_error",
    "memory_has_Y",
    "memory_has_X",
)


def rows_from_runs(
    directory: Path, memory_arms: tuple[str, ...] = MEMORY_ARMS
) -> list[dict[str, Any]]:
    """One public row per session (final attempt; requests and credits over all attempts)."""
    from research.studies.honcho_features import restated

    rows = []
    for r, families, row in c.report_rows(directory):
        if r["session"] == 2:
            family = families[r["family"]]
            row.update(c.session_two(r, c.stale_exchanges(r, family)), restated=restated(r))
            record = c.memory_record(directory, r) if r["arm"] in memory_arms else None
            if record is not None:
                row.update(c.memory_columns(record, family))
        rows.append(row)
    names = ("S1a", "S1b", *ARMS)
    names += tuple(a for a in (*memory_arms, "Hn") if a not in names)
    return c.ordered(rows, names)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    group = c.cohort(rows, ARMS)
    tables = c.outcome_tables(group.second)
    arms: dict[str, Any] = {}
    for arm in ARMS:
        cell = group.cell(arm)
        if arm not in group.complete:
            arms[arm] = c.not_run(cell, len(group.included))
            continue
        n, k = len(cell), count(cell, "success")
        won = [r for r in cell if c.flag(r.get("success"))]
        memory = arm in MEMORY_ARMS
        arms[arm] = {
            "successes": k,
            "n": n,
            "wilson95": wilson(k, n),
            "stale": positive(cell, "stale_commitment"),
            "wrong_item_other": positive(cell, "wrong_variant_other"),
            "declined": count(cell, "declined"),
            "restated_sessions": positive(cell, "restated"),
            "infra_failed": count(cell, "infra_failed"),
            "requests_per_session": mean(cell, "requests", 2),
            "requests_per_success": mean(won, "requests", 2) if won else None,
            "credits_per_session": mean(cell, "credits", 3),
            "memory_has_Y": count(cell, "memory_has_Y") if memory else None,
            "memory_has_X": count(cell, "memory_has_X") if memory else None,
            "memory_error": count(cell, "memory_error") if memory else None,
        }
    descriptive = {
        f"Hnr vs Nr ({e})": paired(tables[e], "Hnr", "Nr")
        for e in ("success", "stale")
        if {"Hnr", "Nr"} <= group.complete
    }
    return {
        **c.arm_summary(group, ARMS, planned_families),
        "arms": arms,
        "family_1": c.block(FAMILY_1, tables, group.complete),
        "family_2": c.block(FAMILY_2, tables, group.complete),
        "descriptive": descriptive,
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified Honcho features evaluation analysis.",
        rows_from_runs,
        analyse,
        FIELDS,
        run="hf-eval-v1",
    )


if __name__ == "__main__":
    main()
