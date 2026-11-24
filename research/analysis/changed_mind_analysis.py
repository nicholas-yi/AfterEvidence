"""Pre-specified analysis of the changed-mind evaluation (tag changed-mind-eval-v1).

Standard library only, so CI can recompute the published table from the public CSV.

Unit: family. A family without explicit agreements in both session 1a and session 1b is
excluded from every arm (reported, not replaced). Success is the commitment oracle's (Y executed,
native DB match, agreed-variant arguments, consent first, no unauthorized mutation); any other
status is a failure. Stale commitment = an exchange to the superseded item X.
Family-paired exact McNemar tests:
- Primary (success), Holm across 3: M vs Hn, Ho vs Hn, Hoh vs Hn.
- Secondary (stale commitment), Holm across the same 3 pairs.
- Hoh vs Ho (success), reported separately, unadjusted.
- Manipulation check: Hn vs N (success).
Everything else is descriptive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis.common import count, flag, mean, num, paired, positive, with_holm
from research.analysis.stats import wilson

ARMS = ("N", "Hn", "M", "Ho", "Hoh")
PROVIDER_ARMS = ("M", "Ho", "Hoh")
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


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    """One public row per session (final attempt; requests and credits over all attempts)."""
    rows = []
    for r, families, row in c.report_rows(directory):
        if r["session"] == 2:
            family = families[r["family"]]
            row.update(c.session_two(r, c.stale_exchanges(r, family)))
            record = c.memory_record(directory, r) if r["arm"] in PROVIDER_ARMS else None
            if record is not None:
                row.update(c.memory_columns(record, family))
        rows.append(row)
    return c.ordered(rows, ("S1a", "S1b", *ARMS))


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    group = c.cohort(rows, ARMS)
    tables = c.outcome_tables(group.second)
    arms: dict[str, Any] = {}
    for arm in ARMS:
        cell = group.cell(arm)
        n, k, s = len(cell), count(cell, "success"), positive(cell, "stale_commitment")
        arms[arm] = {
            "successes": k,
            "n": n,
            "wilson95": wilson(k, n),
            "stale": s,
            "stale_wilson95": wilson(s, n),
            "declined": count(cell, "declined"),
            "infra_failed": count(cell, "infra_failed"),
            "credits_per_session": mean(cell, "credits", 3) if n else None,
            "requests_per_session": mean(cell, "requests", 2) if n else None,
            "proposals_before_consent_mean": mean(cell, "proposals_before_consent", 2)
            if n
            else None,
            "wrong_variant_other": int(sum(num(r.get("wrong_variant_other")) for r in cell)),
            "unauthorized": int(sum(num(r.get("unauthorized_attempts")) for r in cell)),
        }
    pairs = [(a, "Hn") for a in PROVIDER_ARMS]
    memory = {}
    for arm in PROVIDER_ARMS:
        cell = group.cell(arm)
        memory[arm] = {
            "retrieval_errors": count(cell, "memory_error"),
            "has_Y": count(cell, "memory_has_Y"),
            "has_X": count(cell, "memory_has_X"),
            "has_both": sum(
                flag(r.get("memory_has_Y")) and flag(r.get("memory_has_X")) for r in cell
            ),
        }
    return {
        "planned_families": planned_families,
        "session1_families": len(group.families),
        "included": len(group.included),
        "excluded": group.excluded,
        "complete": len(group.families) == planned_families
        and len(group.second) == len(group.included) * len(ARMS),
        "arms": arms,
        "primary_success": with_holm(
            {f"{a} vs {b}": paired(tables["success"], a, b) for a, b in pairs}
        ),
        "secondary_stale": with_holm(
            {f"{a} vs {b}": paired(tables["stale"], a, b) for a, b in pairs}
        ),
        "hoh_vs_ho_success": paired(tables["success"], "Hoh", "Ho"),
        "manipulation_hn_vs_n": paired(tables["success"], "Hn", "N"),
        "provider_memory": memory,
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified changed-mind evaluation analysis.",
        rows_from_runs,
        analyse,
        FIELDS,
        run="cm-eval-v1",
    )


if __name__ == "__main__":
    main()
