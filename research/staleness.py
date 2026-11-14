"""Offline pieces of the proposed stale-memory diagnostic (approval pending; not tagged, not run).

Controlled synthetic diagnostic of stale-memory handling. Not a tau2 score, not memory
distilled from agent experience, and not a re-test of memory study v1. Memory records are
seeded fixtures. Paid conditions would be None, Plain (records without provenance), and
Annotated (the same records with epochs, supersession, and the restore note). Filtered, a
deterministic validity filter, is an offline zero-inference control only. This module has
no episode runner and calls no model. See research/DESIGN.md,
"Proposed follow-up: staleness-aware memory".
"""

from __future__ import annotations

import hashlib
import math
import random
import re
import statistics
from dataclasses import dataclass
from typing import Any

from research.costing import summarize_micro

REGIMES = ("current", "reset", "corrected")
PRIMARY_REGIMES = ("reset", "corrected")
PAID_CONDITIONS = ("none", "plain", "annotated")
CONDITIONS = (*PAID_CONDITIONS, "filtered")
DEV_SEED = 20261113
DEV_FAMILIES, EVAL_FAMILIES = 4, 48
REQUESTS_PER_EPISODE = 4
DEV_REQUEST_CAP = DEV_FAMILIES * len(REGIMES) * len(PAID_CONDITIONS) * REQUESTS_PER_EPISODE
EVAL_REQUEST_CAP = EVAL_FAMILIES * len(REGIMES) * len(PAID_CONDITIONS) * 2 * REQUESTS_PER_EPISODE
STORE_NOTE = {"restored_to_epoch": 2, "at_epoch": 4}
FIRST = ("Ada", "Bram", "Cleo", "Dev", "Esme", "Femi", "Gus", "Hana", "Ivo", "Juno", "Kai", "Lena")
LAST = ("Arden", "Bose", "Cruz", "Dahl", "Eze", "Frost", "Gale", "Holt", "Iqbal", "Jory", "Kemp")
STREETS = ("Alder", "Birch", "Cedar", "Dune", "Elm", "Fern", "Grove", "Heath", "Iris", "Juniper")
CITIES = ("Northam", "Easton", "Westby", "Southwell", "Midvale", "Brookfield", "Lakeport")
BRANDS = ("Visa", "Mastercard", "Amex", "Discover")

ACTOR_INSTRUCTIONS = (
    "You are a store assistant completing one customer request. The account is visible only "
    "through lookup_account. Memory notes, if any, come from earlier sessions and may be "
    "outdated. Finish by calling submit_target with exactly one value from the account, or "
    "abstain if you cannot determine the right value."
)
TOOLS = (
    {"name": "lookup_account", "parameters": {}},
    {"name": "submit_target", "parameters": {"value": "string"}},
    {"name": "abstain", "parameters": {"reason": "string"}},
)


@dataclass(frozen=True)
class Family:
    family_id: str
    customer: str
    kind: str  # "shipping address" or "payment card"
    old: str
    new: str
    decoys: tuple[str, str]
    on_file: tuple[str, ...]  # seeded order; never sorted by role


def _value(rng: random.Random, kind: str) -> str:
    if kind == "payment card":
        return f"{rng.choice(BRANDS)} card ending {rng.randrange(1000, 10000)}"
    return f"{rng.randrange(10, 1000)} {rng.choice(STREETS)} St, {rng.choice(CITIES)}"


def generate_families(seed: int, count: int, exclude: frozenset[str] = frozenset()) -> list[Family]:
    """Deterministic families with four distinct values on file; nothing repeats or hits `exclude`."""
    rng = random.Random(seed)
    used, families = set(exclude), []
    while len(families) < count:
        kind = ("shipping address", "payment card")[len(families) % 2]
        customer = f"{rng.choice(FIRST)} {rng.choice(LAST)} {rng.randrange(100, 1000)}"
        values = [_value(rng, kind) for _ in range(4)]
        if len(set(values)) < 4 or {customer, *values} & used:
            continue
        used |= {customer, *values}
        on_file = values[:]
        rng.shuffle(on_file)
        family_id = f"s{seed % 10_000:04d}-{len(families):02d}"
        families.append(
            Family(family_id, customer, kind, values[0], values[1], (values[2], values[3]), tuple(on_file))
        )  # fmt: skip
    return families


def family_values(families: list[Family]) -> frozenset[str]:
    return frozenset(v for f in families for v in (f.customer, *f.on_file))


def dev_families() -> list[Family]:
    return generate_families(DEV_SEED, DEV_FAMILIES)


def eval_seed(tag_commit: str) -> int:
    """Evaluation families derive from the protocol tag commit, so they cannot exist before it."""
    if not re.fullmatch(r"[0-9a-f]{40}", tag_commit):
        raise ValueError("Evaluation seed needs the full 40-hex protocol tag commit.")
    return int(hashlib.sha256(f"staleness-eval:{tag_commit}".encode()).hexdigest()[:16], 16)


def eval_families(tag_commit: str) -> list[Family]:
    return generate_families(eval_seed(tag_commit), EVAL_FAMILIES, family_values(dev_families()))


def _record(rid: str, epoch: int, text: str, superseded_by: str | None = None) -> dict[str, Any]:
    return {"id": rid, "session": f"S{rid[1:]}", "epoch": epoch, "superseded_by": superseded_by,
            "text": text}  # fmt: skip


def scenario(family: Family, regime: str) -> dict[str, Any]:
    """Visible inputs plus hidden labels. Only `visible` may reach the actor or its tools."""
    kind, old, new = family.kind, family.old, family.new
    changed = f"Customer changed their default {kind} from {old} to {new}."
    if regime == "current":
        # Valid preference recorded after the restore (epoch 5 > at_epoch 4).
        records = [_record("m1", 5, f"Customer asked that {new} become their default {kind}; "
                           "the account had not been updated yet.")]  # fmt: skip
        default, correct, obsolete = None, new, None
    elif regime == "reset":
        records = [_record("m1", 3, changed)]  # lost by the restore to epoch 2 at epoch 4
        default, correct, obsolete = old, old, new
    elif regime == "corrected":
        records = [_record("m1", 3, changed, superseded_by="m2"),
                   _record("m2", 4, f"Customer's default {kind} is {old}.")]  # fmt: skip
        default, correct, obsolete = old, old, new
    else:
        raise ValueError(f"unknown regime {regime!r}")
    account = {"customer": family.customer, f"{kind}s on file": list(family.on_file),
               f"default {kind}": default}  # fmt: skip
    return {
        "visible": {
            "request": f"Please use my default {kind} for this order.",
            "account": account,
            "store_note": None if regime == "corrected" else STORE_NOTE,
            "records": records,
        },
        "hidden": {"correct": correct, "obsolete": obsolete},
    }


def is_valid(record: dict[str, Any], store_note: dict[str, Any] | None) -> bool:
    """Retrieval-time validity, no oracle: superseded records, and records written in the
    window a restore rolled back (restored_to_epoch < epoch <= at_epoch), are invalid."""
    if record.get("superseded_by"):
        return False
    if store_note is None:
        return True
    return not store_note["restored_to_epoch"] < record["epoch"] <= store_note["at_epoch"]


def render_memory(visible: dict[str, Any], condition: str) -> str:
    """None: empty. Plain: record text only, as v1 memory was. Annotated: the same records with
    provenance and the restore note. Filtered (offline control): Annotated minus invalid records."""
    if condition == "none":
        return ""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}")
    header = "Memory notes from earlier sessions (may be outdated):"
    records, note = visible["records"], visible["store_note"]
    if condition == "plain":
        return "\n".join([header, *(f"- {r['text']}" for r in records)])
    lines = [header]
    if note:
        lines.append(
            f"Store note: account data was restored to its epoch-{note['restored_to_epoch']} "
            f"state at epoch {note['at_epoch']}."
        )
    for r in records:
        if condition == "filtered" and not is_valid(r, note):
            continue
        superseded = f"; superseded by {r['superseded_by']}" if r["superseded_by"] else ""
        lines.append(
            f"- [{r['id']}; session {r['session']}; epoch {r['epoch']}{superseded}] {r['text']}"
        )
    return "\n".join(lines)


class AccountEnv:
    """Deterministic tool side of one episode; records lookup-before-act and the final choice."""

    def __init__(self, case: dict[str, Any]) -> None:
        self._case = case
        self.looked_up = False
        self.looked_up_before_submit: bool | None = None
        self.submitted: str | None = None
        self.terminal: str | None = None

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.terminal:
            return {"error": "episode already ended"}
        if name == "lookup_account":
            self.looked_up = True
            return dict(self._case["visible"]["account"])
        if name in ("submit_target", "abstain"):
            self.terminal = name
            self.looked_up_before_submit = self.looked_up
            self.submitted = str(arguments.get("value") or "") if name == "submit_target" else None
            return {"ok": True}
        return {"error": f"unknown tool {name}"}

    def outcome(self) -> dict[str, Any]:
        result = score(self._case["hidden"], self.submitted) if self.terminal else "failed"
        return {"outcome": result, "looked_up_before_submit": self.looked_up_before_submit}


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


def _family_rates(
    rows: list[dict[str, Any]], condition: str, regimes: tuple[str, ...], outcome: str
) -> dict[str, float]:
    groups: dict[str, list[bool]] = {}
    for r in rows:
        if r["condition"] == condition and r["regime"] in regimes:
            groups.setdefault(r["family"], []).append(r["outcome"] == outcome)
    return {family: sum(v) / len(v) for family, v in groups.items()}


def paired(
    rows: list[dict[str, Any]], a: str, b: str, regimes: tuple[str, ...], outcome: str
) -> list[float]:
    ra, rb = (_family_rates(rows, c, regimes, outcome) for c in (a, b))
    if not ra or set(ra) != set(rb):
        raise ValueError("Every family needs both conditions in the compared regimes.")
    return [ra[f] - rb[f] for f in sorted(ra)]


def lower_bound(diffs: list[float], resamples: int = 10_000, seed: int = 0) -> float:
    """One-sided 95% family-cluster percentile-bootstrap lower bound of the mean."""
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(resamples))
    return means[int(0.05 * resamples)]


def decide(rows: list[dict[str, Any]], min_effect: float = 0.20) -> dict[str, Any]:
    """Primary rule plus gates. Rows: family, regime, condition, outcome (one per paid episode)."""
    primary = paired(rows, "plain", "annotated", PRIMARY_REGIMES, "obsolete")
    control = statistics.fmean(paired(rows, "annotated", "none", ("current",), "correct"))
    harm = paired(rows, "annotated", "plain", ("current",), "correct")
    effect, bound, harm_bound = statistics.fmean(primary), lower_bound(primary), lower_bound(harm)
    gates = {"positive_control": control >= 0.50, "non_harm": harm_bound >= -0.10}
    return {
        "families": len(primary),
        "effect_plain_minus_annotated_obsolete": round(effect, 4),
        "lower_bound_95": round(bound, 4),
        "positive_control_annotated_minus_none": round(control, 4),
        "non_harm_lower_bound_95": round(harm_bound, 4),
        "gates": gates,
        "supported": all(gates.values()) and effect >= min_effect and bound > 0,
        "descriptive": {
            c: {
                "obsolete_rate": round(
                    statistics.fmean(_family_rates(rows, c, PRIMARY_REGIMES, "obsolete").values()),
                    4,
                ),
                "abstain_rate": round(
                    statistics.fmean(_family_rates(rows, c, REGIMES, "abstain").values()), 4
                ),
                "lookup_before_submit": round(
                    statistics.fmean(
                        bool(r.get("looked_up_before_submit")) for r in rows if r["condition"] == c
                    ),
                    4,
                ),
            }  # fmt: skip
            for c in PAID_CONDITIONS
        },
    }


def feasibility(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stage A floor check: zero Plain obsolete choices means Stage B is not requested as designed."""
    plain = [r for r in rows if r["condition"] == "plain" and r["regime"] in PRIMARY_REGIMES]
    count = sum(r["outcome"] == "obsolete" for r in plain)
    return {"plain_obsolete": count, "plain_episodes": len(plain), "request_stage_b": count > 0}


def ledger_stops(
    rows: list[dict[str, Any]], request_cap: int, credit_stop: float = 825.0, call_max: float = 1.0
) -> list[str]:
    """Study-level stop reasons from driver journal events; empty means continue."""
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
    if not math.isfinite(total) or total > credit_stop:
        reasons.append(f"settled credits {total:.2f} > {credit_stop}")
    return reasons
