"""Offline pieces of the proposed stale-memory diagnostic (approval pending; not tagged, not run).

Controlled synthetic diagnostic of stale-memory handling. Not a tau2 score, not memory
distilled from agent experience, and not a re-test of memory study v1. Memory records are
seeded fixtures. This module generates families, renders condition inputs, filters memory by
retrieval-time validity metadata, scores submitted targets, applies the decision rule, and
checks the spend ledger. It contains no episode runner and calls no model.
See research/DESIGN.md, "Proposed follow-up: staleness-aware memory".
"""

from __future__ import annotations

import hashlib
import random
import re
import statistics
from dataclasses import dataclass
from typing import Any

from research.costing import summarize_micro

REGIMES = ("current", "reset", "corrected")
PRIMARY_REGIMES = ("reset", "corrected")
CONDITIONS = ("none", "ordinary", "validity")
DEV_SEED = 20261113
DEV_FAMILIES = 4
EVAL_FAMILIES = 48
FIRST = ("Ada", "Bram", "Cleo", "Dev", "Esme", "Femi", "Gus", "Hana", "Ivo", "Juno", "Kai", "Lena")
LAST = ("Arden", "Bose", "Cruz", "Dahl", "Eze", "Frost", "Gale", "Holt", "Iqbal", "Jory", "Kemp")
STREETS = ("Alder", "Birch", "Cedar", "Dune", "Elm", "Fern", "Grove", "Heath", "Iris", "Juniper")
CITIES = ("Northam", "Easton", "Westby", "Southwell", "Midvale", "Brookfield", "Lakeport")
BRANDS = ("Visa", "Mastercard", "Amex", "Discover")


@dataclass(frozen=True)
class Family:
    family_id: str
    customer: str
    kind: str  # "shipping address" or "payment card"
    old: str
    new: str


def _value(rng: random.Random, kind: str) -> str:
    if kind == "payment card":
        return f"{rng.choice(BRANDS)} card ending {rng.randrange(1000, 10000)}"
    return f"{rng.randrange(10, 1000)} {rng.choice(STREETS)} St, {rng.choice(CITIES)}"


def generate_families(seed: int, count: int, exclude: frozenset[str] = frozenset()) -> list[Family]:
    """Deterministic families; customers and values never repeat or collide with `exclude`."""
    rng = random.Random(seed)
    used, families = set(exclude), []
    while len(families) < count:
        kind = ("shipping address", "payment card")[len(families) % 2]
        customer = f"{rng.choice(FIRST)} {rng.choice(LAST)} {rng.randrange(100, 1000)}"
        old, new = _value(rng, kind), _value(rng, kind)
        if old == new or {customer, old, new} & used:
            continue
        used |= {customer, old, new}
        families.append(
            Family(f"s{seed % 10_000:04d}-{len(families):02d}", customer, kind, old, new)
        )
    return families


def family_values(families: list[Family]) -> frozenset[str]:
    return frozenset(v for f in families for v in (f.customer, f.old, f.new))


def dev_families() -> list[Family]:
    return generate_families(DEV_SEED, DEV_FAMILIES)


def eval_seed(tag_commit: str) -> int:
    """Evaluation families derive from the protocol tag commit, so they cannot exist before it."""
    if not re.fullmatch(r"[0-9a-f]{40}", tag_commit):
        raise ValueError("Evaluation seed needs the full 40-hex protocol tag commit.")
    return int(hashlib.sha256(f"staleness-eval:{tag_commit}".encode()).hexdigest()[:16], 16)


def eval_families(tag_commit: str) -> list[Family]:
    exclude = family_values(dev_families())
    return generate_families(eval_seed(tag_commit), EVAL_FAMILIES, exclude)


def scenario(family: Family, regime: str) -> dict[str, Any]:
    """Visible inputs plus hidden labels. Only `visible` may reach the actor."""
    kind, old, new = family.kind, family.old, family.new
    change = {"id": "m1", "session": "S1", "epoch": 3, "superseded_by": None,
              "text": f"Customer changed their default {kind} from {old} to {new}."}  # fmt: skip
    store_note, records = None, [change]
    if regime == "current":
        records = [{**change, "text": f"Customer asked that future orders use {new} as their "
                    f"{kind}; this preference is not stored in the account."}]  # fmt: skip
        tool = {"customer": family.customer, f"{kind}s on file": sorted([old, new]),
                f"default {kind}": None}  # fmt: skip
        request = f"Please use my usual {kind} for this order."
        correct, obsolete = new, None
    else:
        tool = {"customer": family.customer, f"{kind}s on file": [old], f"default {kind}": old}
        request = f"Please use my default {kind} for this order."
        correct, obsolete = old, new
        if regime == "reset":
            store_note = {"restored_to_epoch": 2, "at_epoch": 4}
        elif regime == "corrected":
            change = {**change, "superseded_by": "m2"}
            records = [change, {"id": "m2", "session": "S2", "epoch": 4, "superseded_by": None,
                                "text": f"Correction: the change to {new} was entered by mistake "
                                        f"and reverted; the default is {old}."}]  # fmt: skip
        else:
            raise ValueError(f"unknown regime {regime!r}")
    return {
        "visible": {
            "request": request,
            "tool_view": tool,
            "store_note": store_note,
            "records": records,
        },  # fmt: skip
        "hidden": {"correct": correct, "obsolete": obsolete},
    }


def is_valid(record: dict[str, Any], store_note: dict[str, Any] | None) -> bool:
    """Validity from retrieval-time metadata only: supersession and restore epochs, no oracle."""
    if record.get("superseded_by"):
        return False
    return not (store_note and record["epoch"] > store_note["restored_to_epoch"])


def render_memory(visible: dict[str, Any], condition: str) -> str:
    """Ordinary and validity-aware conditions show identical metadata; validity also filters."""
    if condition == "none":
        return ""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}")
    note = visible["store_note"]
    keep = [r for r in visible["records"] if condition == "ordinary" or is_valid(r, note)]
    lines = ["Memory records (may be outdated; check live tools before acting):"]
    if note:
        lines.append(
            f"Store note: account data was restored to the epoch-{note['restored_to_epoch']} "
            f"snapshot at epoch {note['at_epoch']}."
        )
    for r in keep:
        superseded = f"; superseded by {r['superseded_by']}" if r["superseded_by"] else ""
        lines.append(
            f"- [{r['id']}; session {r['session']}; epoch {r['epoch']}{superseded}] {r['text']}"
        )
    return "\n".join(lines)


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()


def score(hidden: dict[str, Any], submitted: str | None) -> str:
    """Deterministic outcome: correct, obsolete, abstain, or other."""
    if not _norm(submitted):
        return "abstain"
    if _norm(submitted) == _norm(hidden["correct"]):
        return "correct"
    if hidden["obsolete"] and _norm(submitted) == _norm(hidden["obsolete"]):
        return "obsolete"
    return "other"


def _family_rate(
    rows: list[dict[str, Any]], condition: str, regimes: tuple[str, ...], outcome: str
) -> dict[str, float]:
    groups: dict[str, list[int]] = {}
    for r in rows:
        if r["condition"] == condition and r["regime"] in regimes:
            groups.setdefault(r["family"], []).append(r["outcome"] == outcome)
    return {family: sum(v) / len(v) for family, v in groups.items()}


def lower_bound(diffs: list[float], resamples: int = 10_000, seed: int = 0) -> float:
    """One-sided 95% family-cluster percentile-bootstrap lower bound of the mean."""
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(resamples))
    return means[int(0.05 * resamples)]


def decide(rows: list[dict[str, Any]], min_effect: float = 0.20) -> dict[str, Any]:
    """Primary rule plus gates. Rows: family, regime, condition, outcome (one per episode)."""

    def paired(a: str, b: str, regimes: tuple[str, ...], outcome: str) -> list[float]:
        ra, rb = (_family_rate(rows, c, regimes, outcome) for c in (a, b))
        if set(ra) != set(rb):
            raise ValueError("Every family needs both conditions in the compared regimes.")
        return [ra[f] - rb[f] for f in sorted(ra)]

    primary = paired("ordinary", "validity", PRIMARY_REGIMES, "obsolete")
    control = statistics.fmean(paired("ordinary", "none", ("current",), "correct"))
    non_harm = statistics.fmean(paired("validity", "ordinary", ("current",), "correct"))
    effect, bound = statistics.fmean(primary), lower_bound(primary)
    gates = {"positive_control": control >= 0.50, "non_harm": non_harm >= -0.05}
    return {
        "families": len(primary),
        "effect_o_minus_v_obsolete": round(effect, 4),
        "lower_bound_95": round(bound, 4),
        "positive_control_o_minus_none": round(control, 4),
        "non_harm_v_minus_o": round(non_harm, 4),
        "gates": gates,
        "supported": all(gates.values()) and effect >= min_effect and bound > 0,
        "o_minus_none_obsolete": round(
            statistics.fmean(paired("ordinary", "none", PRIMARY_REGIMES, "obsolete")), 4
        ),
    }


def ledger_stops(
    rows: list[dict[str, Any]], request_cap: int, credit_stop: float = 825.0, call_max: float = 1.0
) -> list[str]:
    """Study-level stop reasons from shim/driver journal events; empty means continue."""
    started = sum(r.get("event") == "copilot-request-started" for r in rows)
    completed = [r for r in rows if r.get("event") == "copilot-request-completed"]
    reasons = []
    if started > request_cap:
        reasons.append(f"request cap exceeded: {started} > {request_cap}")
    if len(completed) != started:
        reasons.append(f"count mismatch: {started} started, {len(completed)} billed")
    total = 0.0
    for row in completed:
        try:
            credits = float(str(summarize_micro([row])["ai_credits"]))
        except ValueError as error:
            reasons.append(f"missing billing for call {row.get('call_id')}: {error}")
            continue
        total += credits
        if credits > call_max:
            reasons.append(f"call {row.get('call_id')} cost {credits:.3f} > {call_max} credit")
    if total > credit_stop:
        reasons.append(f"settled credits {total:.2f} > {credit_stop}")
    return reasons
