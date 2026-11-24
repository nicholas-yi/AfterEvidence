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

from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis import honcho_features_analysis as hfa

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
    rows = hfa.rows_from_runs(directory, STUDIES[study]["memory_arms"])
    return c.with_tool_calls(directory, rows)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def analyse(study: str, rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    spec = STUDIES[study]
    arms_order, memory_arms = spec["arms"], spec["memory_arms"]
    group = c.cohort(rows, arms_order)
    tables = c.outcome_tables(group.second)
    arms = c.exchange_arms(group, arms_order, memory_arms, tools=True)
    blocks = {
        name: c.block(pairs, tables, group.complete) for name, pairs in spec["blocks"].items()
    }
    return {
        "study": study,
        **c.arm_summary(group, arms_order, planned_families),
        "arms": arms,
        **blocks,
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified analyses of Studies 10, 11 and 12.",
        rows_from_runs,
        analyse,
        FIELDS,
        studies=STUDIES,
    )


if __name__ == "__main__":
    main()
