from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256


class Topology(StrEnum):
    CONJUNCTION = "conjunction"
    ALTERNATIVE = "alternative-proof"
    REDUNDANT = "redundant-direct"


@dataclass(frozen=True)
class Evidence:
    id: str
    session_id: str
    proposition: str

    def __post_init__(self) -> None:
        if not self.id or not self.session_id or not self.proposition:
            raise ValueError("Evidence fields must be nonempty.")


@dataclass(frozen=True)
class Rule:
    premises: tuple[str, ...]
    conclusion: str

    def __post_init__(self) -> None:
        if not self.premises or not all(self.premises) or not self.conclusion:
            raise ValueError("Rules require nonempty premises and a conclusion.")
        if len(set(self.premises)) != len(self.premises):
            raise ValueError("Rule premises must be distinct.")


@dataclass(frozen=True)
class World:
    id: str
    topology: Topology
    evidence: tuple[Evidence, ...]
    rules: tuple[Rule, ...]
    target: str
    control: str
    partial_delete: tuple[str, ...]
    final_delete: tuple[str, ...]


def generate_world(seed: int, index: int, topology: Topology) -> World:
    if seed < 0 or index < 0:
        raise ValueError("Seed and world index must be nonnegative.")
    prefix = sha256(f"{seed}:{index}:{topology}".encode()).hexdigest()[:16]
    a, b, c, intermediate, target, control = (
        f"{prefix}:{name}" for name in ("a", "b", "c", "d", "q", "control")
    )
    first = Evidence(f"{prefix}:e1", f"{prefix}:s1", a)
    second = Evidence(f"{prefix}:e2", f"{prefix}:s2", b)
    preserved = Evidence(f"{prefix}:e0", f"{prefix}:s0", control)
    evidence = [first, second, preserved]
    rules = [Rule((a, b), intermediate), Rule((intermediate,), target)]
    final_delete = (first.id,)
    if topology == Topology.ALTERNATIVE:
        alternative = Evidence(f"{prefix}:e3", f"{prefix}:s3", c)
        evidence.append(alternative)
        rules.append(Rule((c,), target))
        final_delete = (alternative.id,)
    elif topology == Topology.REDUNDANT:
        evidence[0] = Evidence(first.id, first.session_id, target)
        evidence[1] = Evidence(second.id, second.session_id, target)
        rules = []
    evidence.sort(key=lambda item: sha256(f"{seed}:{item.id}".encode()).digest())
    return World(
        prefix,
        topology,
        tuple(evidence),
        tuple(rules),
        target,
        control,
        (second.id,),
        final_delete,
    )


def oracle(
    evidence: tuple[Evidence, ...],
    rules: tuple[Rule, ...],
    active: set[str],
) -> set[str]:
    known_ids = {item.id for item in evidence}
    if not active <= known_ids:
        raise ValueError("Oracle received an unknown source ID.")
    facts = {item.proposition for item in evidence if item.id in active}
    while True:
        added = {
            rule.conclusion for rule in rules if all(premise in facts for premise in rule.premises)
        } - facts
        if not added:
            return facts
        facts.update(added)
