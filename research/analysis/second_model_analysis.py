"""Pre-specified analysis of the second-model replication (tag second-model-eval-v1; gpt-6-luna).

Standard library only, so CI can recompute the published table from the public CSV. Unit: family;
exclusion as before. Only arms complete for every included family are analysed; others are not run.
Exact family-paired McNemar:
- Primary (Holm across three): Mi, Hod and Hs each vs Hn on success.
- Secondary (Holm across three): the same pairs on executing the superseded item X.
Comparisons with the Claude Haiku 5.5 studies are descriptive only (different families).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis import honcho_features_analysis as hfa

ARMS = ("Hn", "Mi", "Hod", "Hs")
MEMORY_ARMS = ("Mi", "Hod", "Hs")
PRIMARY = (("Mi", "Hn", "success"), ("Hod", "Hn", "success"), ("Hs", "Hn", "success"))
SECONDARY = (("Mi", "Hn", "stale"), ("Hod", "Hn", "stale"), ("Hs", "Hn", "stale"))
FIELDS = hfa.FIELDS


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    return hfa.rows_from_runs(directory, MEMORY_ARMS)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    group = c.cohort(rows, ARMS)
    tables = c.outcome_tables(group.second)
    arms = c.exchange_arms(group, ARMS, MEMORY_ARMS)
    return {
        **c.arm_summary(group, ARMS, planned_families),
        "arms": arms,
        "primary_success": c.block(PRIMARY, tables, group.complete),
        "secondary_stale": c.block(SECONDARY, tables, group.complete),
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified second-model replication analysis.",
        rows_from_runs,
        analyse,
        FIELDS,
        run="m2-eval-v1",
    )


if __name__ == "__main__":
    main()
