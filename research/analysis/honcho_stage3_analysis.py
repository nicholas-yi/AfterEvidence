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

from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis import honcho_features_analysis as hfa

ARMS = ("Hod", "Hdr", "Ht", "Hw", "Fd")
MEMORY_ARMS = ("Hod", "Hdr", "Hw", "Fd")
PRIMARY = (("Hdr", "Hod", "success"), ("Ht", "Hod", "success"), ("Hw", "Hod", "success"))
SECONDARY_A = (("Hw", "Fd", "success"), ("Fd", "Hod", "success"))
SECONDARY_B = (("Hdr", "Hod", "stale"), ("Ht", "Hod", "stale"), ("Hw", "Hod", "stale"))
FIELDS: tuple[str, ...] = (*hfa.FIELDS, "tool_calls")


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    return c.with_tool_calls(directory, hfa.rows_from_runs(directory, MEMORY_ARMS))


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    group = c.cohort(rows, ARMS)
    tables = c.outcome_tables(group.second)
    arms = c.exchange_arms(group, ARMS, MEMORY_ARMS, tools=True)
    return {
        **c.arm_summary(group, ARMS, planned_families),
        "arms": arms,
        "primary_success": c.block(PRIMARY, tables, group.complete),
        "secondary_facts": c.block(SECONDARY_A, tables, group.complete),
        "secondary_stale": c.block(SECONDARY_B, tables, group.complete),
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified Honcho Stage 3 evaluation analysis.",
        rows_from_runs,
        analyse,
        FIELDS,
        run="hf3-eval-v1",
    )


if __name__ == "__main__":
    main()
