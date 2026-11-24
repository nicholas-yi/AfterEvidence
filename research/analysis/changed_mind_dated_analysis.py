"""Pre-specified analysis of the dated changed-mind evaluation (tag changed-mind-dated-eval-v1).

Standard library only, so CI can recompute the published table from the public CSV.

Arms: Hn (labelled, dated transcripts), M (Mem0, undated), Mi (Mem0, dated first line in each
session), Ho (Honcho, undated) and Hod (Honcho, backdated created_at). Every arm's session-2
prompt states the same "Today is <T>". Unit: family; a family without both 1a and 1b agreements
is excluded from every arm (reported, not replaced). Success and stale commitment as in the
changed-mind evaluation. Family-paired exact McNemar tests:
- Primary (success), Holm across 2: Mi vs M, Hod vs Ho (does dating help each provider?).
- Secondary (stale commitment), Holm across the same 2 pairs.
Each provider arm vs Hn is descriptive (unadjusted).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis.common import count, mean, num, paired, positive, with_holm
from research.analysis.stats import wilson

ARMS = ("Hn", "M", "Mi", "Ho", "Hod")
PROVIDER_ARMS = ("M", "Mi", "Ho", "Hod")
PAIRS = (("Mi", "M"), ("Hod", "Ho"))
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
    "memory_date_correct",
    "memory_deferral_present",
)


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    """One public row per session (final attempt; requests and credits over all attempts)."""
    from research.studies.changed_mind import date_mentions, deferral_present

    today = dt.date.fromisoformat(
        json.loads((directory / "plan.json").read_text(encoding="utf-8"))["today_utc"]
    )
    backdated = (today - dt.timedelta(days=3), today - dt.timedelta(days=1))
    rows = []
    for r, families, row in c.report_rows(directory):
        if r["session"] == 2:
            family = families[r["family"]]
            row.update(c.session_two(r, c.stale_exchanges(r, family)))
            record = c.memory_record(directory, r) if r["arm"] in PROVIDER_ARMS else None
            if record is not None:
                text = record.get("text") or ""
                shows = any(date_mentions(text, d) for d in backdated)
                row.update(
                    c.memory_columns(record, family),
                    memory_date_correct=shows and not date_mentions(text, today),
                    memory_deferral_present=deferral_present(text),
                )
        rows.append(row)
    return c.ordered(rows, ("S1a", "S1b", *ARMS))


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    group = c.cohort(rows, ARMS)
    tables = c.outcome_tables(group.second)
    success, stale = tables["success"], tables["stale"]
    arms: dict[str, Any] = {}
    for arm in ARMS:
        cell = group.cell(arm)
        n, k = len(cell), count(cell, "success")
        arms[arm] = {
            "successes": k,
            "n": n,
            "wilson95": wilson(k, n),
            "stale": positive(cell, "stale_commitment"),
            "declined": count(cell, "declined"),
            "infra_failed": count(cell, "infra_failed"),
            "credits_per_session": mean(cell, "credits", 3) if n else None,
            "requests_per_session": mean(cell, "requests", 2) if n else None,
            "wrong_variant_other": int(sum(num(r.get("wrong_variant_other")) for r in cell)),
            "unauthorized": int(sum(num(r.get("unauthorized_attempts")) for r in cell)),
        }
    versus_hn = {
        f"{a} vs Hn": {"success": paired(success, a, "Hn"), "stale": paired(stale, a, "Hn")}
        for a in PROVIDER_ARMS
    }
    memory = {
        arm: {
            key: count(group.cell(arm), f"memory_{key}")
            for key in ("error", "has_Y", "has_X", "date_correct", "deferral_present")
        }
        for arm in PROVIDER_ARMS
    }
    return {
        "planned_families": planned_families,
        "session1_families": len(group.families),
        "included": len(group.included),
        "excluded": group.excluded,
        "complete": len(group.families) == planned_families
        and len(group.second) == len(group.included) * len(ARMS),
        "arms": arms,
        "primary_success": with_holm({f"{a} vs {b}": paired(success, a, b) for a, b in PAIRS}),
        "secondary_stale": with_holm({f"{a} vs {b}": paired(stale, a, b) for a, b in PAIRS}),
        "descriptive_vs_hn": versus_hn,
        "provider_memory": memory,
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified dated changed-mind evaluation analysis.",
        rows_from_runs,
        analyse,
        FIELDS,
        run="cm-dated-eval-v1",
    )


if __name__ == "__main__":
    main()
