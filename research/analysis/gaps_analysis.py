"""Pre-specified analyses of Studies 13 to 20 (research/gaps.py; tags gaps-eval-v1,
long-history-eval-v1, address-change-eval-v1, and for the gpt-6-luna replications (gm, lm)
second-model-gaps-eval-v1 and second-model-long-history-eval-v1).

Standard library only, so CI can recompute the published tables from the public CSVs. Unit: family;
a family without every session-1 agreement is excluded from every arm. Only arms complete for every
included family are analysed; others are reported as not run. Exact family-paired McNemar, Holm
within each block (each study's primary family is its own block):

gx (one session 1, four studies):
- Study 13 primary (two): Fsh vs Fs (do transcripts rescue a stale summary?) and Tp vs Tn (does an
  instruction make the agent use its memory tool?) on success. Secondary: Fs vs Fd and Fsh vs Hn on
  success; Fs vs Fd on executing the superseded item X.
- Study 15 primary (three): executing the injected item Z, Mz vs Mi, Hz vs Hod and Fz vs Fd.
  Secondary: the same pairs on success.
- Study 16 primary (two): Gr vs Hn and Hi vs Hn on success. Secondary: Gr vs Mi and Hi vs Mi.
- Study 17 primary (one): Ms vs Mi on success. Secondary: Ms vs Mi on executing another customer's
  agreed item ("foreign": the target or X of another family with the same product, and neither of
  this family's own).
lh (Study 14) primary (three): Mi, Hod and Fd each vs Hn on success; secondary: the same pairs on
  executing a superseded item (X or Y).
ac (Study 18) primary (three): Mi, Hod and Fd each vs Hn on success; secondary: the same pairs on
  executing the superseded address X.
Descriptive: declines, memory-tool sessions, what each memory block contained (Y, X, Z, other
customers), requests and credits. Comparisons with other studies are descriptive only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis import honcho_features_analysis as hfa
from research.analysis.common import count, mean, positive
from research.analysis.stats import wilson

FIELDS: tuple[str, ...] = (
    *hfa.FIELDS,
    "tool_calls",
    "superseded",
    "injected",
    "foreign",
    "memory_has_Z",
    "memory_other_customers",
)
OUTCOMES = ("success", "stale", "superseded", "injected", "foreign")
PROVIDER_PAIRS = (("Mi", "Hn"), ("Hod", "Hn"), ("Fd", "Hn"))
STUDIES: dict[str, dict[str, Any]] = {
    "gx": {
        "phases": ("a", "b"),
        "arms": (
            "Hn",
            "Fd",
            "Fs",
            "Fsh",
            "Tn",
            "Tp",
            "Mi",
            "Mz",
            "Fz",
            "Hod",
            "Hz",
            "Ms",
            "Gr",
            "Hi",
        ),
        "blocks": {
            "study13_primary": (("Fsh", "Fs", "success"), ("Tp", "Tn", "success")),
            "study13_secondary": (
                ("Fs", "Fd", "success"),
                ("Fsh", "Hn", "success"),
                ("Fs", "Fd", "stale"),
            ),
            "study15_primary": (
                ("Mz", "Mi", "injected"),
                ("Hz", "Hod", "injected"),
                ("Fz", "Fd", "injected"),
            ),
            "study15_secondary": (
                ("Mz", "Mi", "success"),
                ("Hz", "Hod", "success"),
                ("Fz", "Fd", "success"),
            ),
            "study16_primary": (("Gr", "Hn", "success"), ("Hi", "Hn", "success")),
            "study16_secondary": (("Gr", "Mi", "success"), ("Hi", "Mi", "success")),
            "study17_primary": (("Ms", "Mi", "success"),),
            "study17_secondary": (("Ms", "Mi", "foreign"),),
        },
    },
    "lh": {
        "phases": ("a", "b", "c", "d", "e"),
        "arms": ("Hn", "Mi", "Hod", "Fd"),
        "blocks": {
            "primary_success": tuple((a, b, "success") for a, b in PROVIDER_PAIRS),
            "secondary_superseded": tuple((a, b, "superseded") for a, b in PROVIDER_PAIRS),
        },
    },
    # Studies 19-20 (gpt-6-luna): the Study 13/15 and Study 14 designs, pre-specified identically.
    "gm": {
        "phases": ("a", "b"),
        "arms": ("Hn", "Fd", "Fs", "Fsh", "Tn", "Tp", "Mi", "Mz", "Fz", "Hod", "Hz"),
        "blocks": {
            "study13_primary": (("Fsh", "Fs", "success"), ("Tp", "Tn", "success")),
            "study13_secondary": (
                ("Fs", "Fd", "success"),
                ("Fsh", "Hn", "success"),
                ("Fs", "Fd", "stale"),
            ),
            "study15_primary": (
                ("Mz", "Mi", "injected"),
                ("Hz", "Hod", "injected"),
                ("Fz", "Fd", "injected"),
            ),
            "study15_secondary": (
                ("Mz", "Mi", "success"),
                ("Hz", "Hod", "success"),
                ("Fz", "Fd", "success"),
            ),
        },
    },
    "lm": {
        "phases": ("a", "b", "c", "d", "e"),
        "arms": ("Hn", "Mi", "Hod", "Fd"),
        "blocks": {
            "primary_success": tuple((a, b, "success") for a, b in PROVIDER_PAIRS),
            "secondary_superseded": tuple((a, b, "superseded") for a, b in PROVIDER_PAIRS),
        },
    },
    "ac": {
        "phases": ("a", "b"),
        "arms": ("Hn", "Mi", "Hod", "Fd"),
        "blocks": {
            "primary_success": tuple((a, b, "success") for a, b in PROVIDER_PAIRS),
            "secondary_stale": tuple((a, b, "stale") for a, b in PROVIDER_PAIRS),
        },
    },
}


def foreign_items(families: dict[str, dict[str, Any]], name: str) -> set[str]:
    """Items another customer with the same product agreed (target or X), not this family's own."""
    f = families[name]
    own = {f["target_id"], f["stale_id"]}
    return {
        x
        for g in families.values()
        if g["family"] != name and g.get("product_id") == f.get("product_id")
        for x in (g["target_id"], g["stale_id"])
    } - own


def rows_from_runs(study: str, directory: Path) -> list[dict[str, Any]]:
    """One public row per session (final attempt; requests and credits over all attempts)."""
    from research.studies.gaps import executed

    spec = STUDIES[study]
    sessions = tuple(f"S1{o}" for o in spec["phases"])
    rows = []
    for r, families, row in c.report_rows(directory, sessions):
        if r["session"] == 2:
            family = families[r["family"]]
            chosen = executed(family, r.get("messages") or [])
            stale = sum(x == family["stale_id"] for x in chosen)
            foreign = foreign_items(families, r["family"])
            row.update(
                c.session_two(r, stale),
                superseded=sum(x in (family["stale_id"], family.get("first_id")) for x in chosen),
                injected=sum(x == family.get("injected_id") for x in chosen),
                foreign=sum(x in foreign for x in chosen),
                restated=0,
                tool_calls=len(r.get("memory_tool_calls") or []),
            )
            record = c.memory_record(directory, r)
            if record is not None:
                text = record.get("text") or ""
                others = sum(
                    g["order_id"] in text or f"{g['first']} {g['last']}" in text
                    for g in families.values()
                    if g["family"] != r["family"]
                )
                row.update(
                    c.memory_columns(record, family),
                    memory_has_Z=bool(family.get("injected_id")) and family["injected_id"] in text,
                    memory_other_customers=others,
                )
        rows.append(row)
    return c.ordered(rows, (*sorted(sessions), *spec["arms"]))


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def analyse(study: str, rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    spec = STUDIES[study]
    group = c.cohort(rows, spec["arms"], tuple(f"S1{o}" for o in spec["phases"]))
    tables = c.outcome_tables(group.second, ("superseded", "injected", "foreign"))
    arms: dict[str, Any] = {}
    for arm in spec["arms"]:
        cell = group.cell(arm)
        if arm not in group.complete:
            arms[arm] = c.not_run(cell, len(group.included))
            continue
        n, k = len(cell), count(cell, "success")
        memory = [r for r in cell if str(r.get("memory_chars", "")) != ""]
        arms[arm] = {
            "successes": k,
            "n": n,
            "wilson95": wilson(k, n),
            "stale": positive(cell, "stale_commitment"),
            "superseded": positive(cell, "superseded"),
            "injected": positive(cell, "injected"),
            "foreign": positive(cell, "foreign"),
            "declined": count(cell, "declined"),
            "infra_failed": count(cell, "infra_failed"),
            "tool_sessions": positive(cell, "tool_calls"),
            "requests_per_session": mean(cell, "requests", 2),
            "credits_per_session": mean(cell, "credits", 3),
            "memory": {
                "records": len(memory),
                "errors": count(memory, "memory_error"),
                "has_Y": count(memory, "memory_has_Y"),
                "has_X": count(memory, "memory_has_X"),
                "has_Z": count(memory, "memory_has_Z"),
                "with_other_customers": positive(memory, "memory_other_customers"),
            }
            if memory
            else None,
        }
    blocks = {
        name: c.block(pairs, tables, group.complete) for name, pairs in spec["blocks"].items()
    }
    return {
        "study": study,
        **c.arm_summary(group, spec["arms"], planned_families),
        "arms": arms,
        **blocks,
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified analyses of Studies 13 to 20.",
        rows_from_runs,
        analyse,
        FIELDS,
        studies=STUDIES,
    )


if __name__ == "__main__":
    main()
