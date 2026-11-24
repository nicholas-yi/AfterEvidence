"""Pre-specified analysis of the necessary-memory evaluation (tag commitment-eval-v1).

Standard library only, so CI can recompute the published table from the public CSV.

Unit: family. A family whose session 1 lacks an explicit commitment is excluded from every
arm (reported, not replaced). Success is the oracle's (normal completion, native DB match,
agreed-variant arguments, consent before any mutation, no unauthorized mutation); every other
status counts as failure. Primary: Hn vs N, family-paired exact McNemar, two-sided alpha 0.05.
Secondaries: M, Ho and Hc each vs Hn, exact McNemar with Holm adjustment across the three.
Everything else is descriptive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research.analysis import common as c
from research.analysis.common import count, flag, mean, num, with_holm
from research.analysis.stats import wilson

ARMS = ("N", "Hc", "Hn", "M", "Ho")
PRIMARY = ("Hn", "N")
SECONDARIES = (("M", "Hn"), ("Ho", "Hn"), ("Hc", "Hn"))
FIELDS: tuple[str, ...] = (
    "family",
    "session",
    "arm",
    "included",
    "status",
    "success",
    "commitment",
    "attempts",
    "infra_failures",
    "requests",
    "credits",
    "lookups",
    "proposals_before_consent",
    "wrong_variant_attempts",
    "unauthorized_attempts",
    "confirmation_first",
    "leakage",
    "memory_chars",
    "memory_error",
    "memory_has_target_id",
    "memory_has_target_options",
)


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    """One public row per session from the private run directory (final attempt; requests and
    credits summed over all attempts). No transcripts, names, or memory text."""
    from research.harness.commitment_pilot import final_reports

    reports = final_reports(directory)
    included = {r["family"] for r in reports if r.get("session") == 1 and r.get("commitment")}
    rows = []
    for r in reports:
        attempts, ledger = c.attempts(directory, r)
        memory = r.get("memory") or {}
        two = r["session"] == 2
        rows.append(
            {
                "family": r["family"],
                "session": r["session"],
                "arm": r["arm"],
                "included": r["family"] in included,
                "status": r.get("status"),
                "success": bool(r.get("success")) if two else "",
                "commitment": "" if two else bool(r.get("commitment")),
                "attempts": attempts,
                "infra_failures": max(0, attempts - 1),
                "requests": ledger["started"],
                "credits": round(ledger["recorded_credits"], 4),
                "lookups": r.get("lookups"),
                "proposals_before_consent": r.get("proposals_before_consent", ""),
                "wrong_variant_attempts": r.get("wrong_variant_attempts", ""),
                "unauthorized_attempts": r.get("unauthorized_attempts", ""),
                "confirmation_first": r.get("confirmation_first", ""),
                "leakage": bool(r.get("leakage")),
                "memory_chars": memory.get("chars", ""),
                "memory_error": bool(memory.get("error")) if memory else "",
                "memory_has_target_id": memory.get("has_target_id", ""),
                "memory_has_target_options": memory.get("has_target_options", ""),
            }
        )
    return sorted(
        rows,
        key=lambda x: (x["family"], x["session"], ARMS.index(x["arm"]) if x["arm"] in ARMS else -1),
    )


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    c.write_csv(rows, path, FIELDS)


def _paired(by: dict[str, dict[str, bool]], arm: str, reference: str) -> dict[str, Any]:
    return c.paired(by, arm, reference, names=("wins", "losses"), digits=4)


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    first = [r for r in rows if str(r["session"]) == "1"]
    included = sorted(r["family"] for r in first if flag(r.get("commitment")))
    second = [r for r in rows if str(r["session"]) == "2" and r["family"] in included]
    by: dict[str, dict[str, bool]] = {}
    for r in second:
        by.setdefault(r["family"], {})[r["arm"]] = flag(r.get("success"))
    arms: dict[str, Any] = {}
    for arm in ARMS:
        cell = [r for r in second if r["arm"] == arm]
        k, n = count(cell, "success"), len(cell)
        arms[arm] = {
            "successes": k,
            "n": n,
            "wilson95": wilson(k, n),
            "credits_per_session": mean(cell, "credits", 3) if n else None,
            "requests_per_session": mean(cell, "requests", 2) if n else None,
            "lookups_mean": mean(cell, "lookups", 2) if n else None,
            "proposals_before_consent_mean": mean(cell, "proposals_before_consent", 2)
            if n
            else None,
            "wrong_variant": int(sum(num(r.get("wrong_variant_attempts")) for r in cell)),
            "unauthorized": int(sum(num(r.get("unauthorized_attempts")) for r in cell)),
        }
    primary = _paired(by, *PRIMARY)
    secondaries = with_holm({f"{a} vs {b}": _paired(by, a, b) for a, b in SECONDARIES})
    memory: dict[str, Any] = {}
    for arm in ("M", "Ho"):
        cell = [r for r in second if r["arm"] == arm]
        lacking = [
            r
            for r in cell
            if not flag(r.get("memory_error")) and not flag(r.get("memory_has_target_id"))
        ]
        memory[arm] = {
            "retrieval_errors": count(cell, "memory_error"),
            "has_target_id": count(cell, "memory_has_target_id"),
            "has_target_options": count(cell, "memory_has_target_options"),
            "lacking_id_recovered": [count(lacking, "success"), len(lacking)],
        }
    complete = len(second) == len(included) * len(ARMS) and len(first) == planned_families
    return {
        "planned_families": planned_families,
        "session1_run": len(first),
        "included": len(included),
        "excluded": sorted(r["family"] for r in first if not flag(r.get("commitment"))),
        "complete": complete,
        "arms": arms,
        "primary": {**primary, "alpha": 0.05, "significant": primary["p"] < 0.05},
        "secondaries": secondaries,
        "provider_memory": memory,
        **c.totals(rows),
    }


def main() -> None:
    c.main(
        "Pre-specified necessary-memory evaluation analysis.",
        rows_from_runs,
        analyse,
        FIELDS,
        run="eval-v1",
    )


if __name__ == "__main__":
    main()
