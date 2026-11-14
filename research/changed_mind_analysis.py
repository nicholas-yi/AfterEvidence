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

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from research.memory_analysis import holm, mcnemar_exact, wilson

ARMS = ("N", "Hn", "M", "Ho", "Hoh")
PROVIDER_ARMS = ("M", "Ho", "Hoh")
FIELDS: tuple[str, ...] = (
    "family", "session", "arm", "included", "status", "success", "commitment", "stale_commitment",
    "declined", "wrong_variant_other", "unauthorized_attempts", "proposals_before_consent",
    "attempts", "infra_failed", "requests", "credits", "leakage", "memory_chars", "memory_error",
    "memory_has_Y", "memory_has_X",
)  # fmt: skip


def _flag(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true")


def _num(value: Any) -> float:
    return float(value) if str(value).strip() not in ("", "None") else 0.0


def rows_from_runs(directory: Path) -> list[dict[str, Any]]:
    """One public row per session (final attempt; requests and credits over all attempts)."""
    from research.commitment_pilot import final_reports, job_id, pilot_ledger

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
                       unauthorized_attempts=r.get("unauthorized_attempts"),
                       proposals_before_consent=r.get("proposals_before_consent"), leakage=bool(r.get("leakage")))  # fmt: skip
            path = directory / "memory" / f"{r['family']}-{r['arm']}.json"
            if r["arm"] in PROVIDER_ARMS and path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                text = record.get("text") or ""
                row.update(memory_chars=record.get("chars"), memory_error=bool(record.get("error")),
                           memory_has_Y=family["target_id"] in text, memory_has_X=family["stale_id"] in text)  # fmt: skip
        rows.append(row)
    order = {a: i for i, a in enumerate(("S1a", "S1b", *ARMS))}
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


def _paired(by: dict[str, dict[str, bool]], arm: str, reference: str) -> dict[str, Any]:
    pairs = [f for f, arms in by.items() if arm in arms and reference in arms]
    wins = sum(by[f][arm] and not by[f][reference] for f in pairs)
    losses = sum(by[f][reference] and not by[f][arm] for f in pairs)
    return {"arm": arm, "reference": reference, "pairs": len(pairs), "arm_only": wins,
            "reference_only": losses, "p": round(mcnemar_exact(wins, losses), 6)}  # fmt: skip


def analyse(rows: list[dict[str, Any]], planned_families: int = 32) -> dict[str, Any]:
    first = [r for r in rows if str(r["session"]) == "1"]
    agreed: dict[str, set[str]] = {}
    for r in first:
        if _flag(r.get("commitment")):
            agreed.setdefault(r["family"], set()).add(r["arm"])
    families = sorted({r["family"] for r in first})
    included = sorted(f for f in families if agreed.get(f) == {"S1a", "S1b"})
    second = [r for r in rows if str(r["session"]) == "2" and r["family"] in included]
    success: dict[str, dict[str, bool]] = {}
    stale: dict[str, dict[str, bool]] = {}
    for r in second:
        success.setdefault(r["family"], {})[r["arm"]] = _flag(r.get("success"))
        stale.setdefault(r["family"], {})[r["arm"]] = _num(r.get("stale_commitment")) > 0
    arms: dict[str, Any] = {}
    for arm in ARMS:
        cell = [r for r in second if r["arm"] == arm]
        n = len(cell)
        k = sum(_flag(r.get("success")) for r in cell)
        s = sum(_num(r.get("stale_commitment")) > 0 for r in cell)
        arms[arm] = {"successes": k, "n": n, "wilson95": wilson(k, n), "stale": s, "stale_wilson95": wilson(s, n),
                     "declined": sum(_flag(r.get("declined")) for r in cell),
                     "infra_failed": sum(_flag(r.get("infra_failed")) for r in cell),
                     "credits_per_session": round(sum(_num(r.get("credits")) for r in cell) / n, 3) if n else None,
                     "requests_per_session": round(sum(_num(r.get("requests")) for r in cell) / n, 2) if n else None,
                     "proposals_before_consent_mean": round(
                         sum(_num(r.get("proposals_before_consent")) for r in cell) / n, 2) if n else None,
                     "wrong_variant_other": int(sum(_num(r.get("wrong_variant_other")) for r in cell)),
                     "unauthorized": int(sum(_num(r.get("unauthorized_attempts")) for r in cell))}  # fmt: skip
    pairs = [(a, "Hn") for a in PROVIDER_ARMS]
    primary = {f"{a} vs {b}": _paired(success, a, b) for a, b in pairs}
    secondary = {f"{a} vs {b}": _paired(stale, a, b) for a, b in pairs}
    for block in (primary, secondary):
        adjusted = holm({k: v["p"] for k, v in block.items()})
        for key, value in block.items():
            value["p_holm"] = adjusted[key]
    memory = {}
    for arm in PROVIDER_ARMS:
        cell = [r for r in second if r["arm"] == arm]
        memory[arm] = {"retrieval_errors": sum(_flag(r.get("memory_error")) for r in cell),
                       "has_Y": sum(_flag(r.get("memory_has_Y")) for r in cell),
                       "has_X": sum(_flag(r.get("memory_has_X")) for r in cell),
                       "has_both": sum(_flag(r.get("memory_has_Y")) and _flag(r.get("memory_has_X")) for r in cell)}  # fmt: skip
    return {"planned_families": planned_families, "session1_families": len(families), "included": len(included),
            "excluded": sorted(set(families) - set(included)),
            "complete": len(families) == planned_families and len(second) == len(included) * len(ARMS),
            "arms": arms, "primary_success": primary, "secondary_stale": secondary,
            "hoh_vs_ho_success": _paired(success, "Hoh", "Ho"), "manipulation_hn_vs_n": _paired(success, "Hn", "N"),
            "provider_memory": memory, "leakage_sessions": sum(_flag(r.get("leakage")) for r in rows),
            "requests_total": int(sum(_num(r.get("requests")) for r in rows)),
            "credits_total": round(sum(_num(r.get("credits")) for r in rows), 2)}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-specified changed-mind evaluation analysis.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--root", type=Path, help="Private run directory (research/runs/commitment/cm-eval-v1)."
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
