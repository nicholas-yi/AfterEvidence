from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from itertools import product

from .model import Evidence, Rule

Proof = frozenset[str]
Proofs = frozenset[Proof]


class Policy(StrEnum):
    REFERENCE = "proof-aware"
    FLAT_UNION = "flat-union-negative-control"
    DELETE_AFFECTED = "delete-all-affected-negative-control"


def _minimal(proofs: set[Proof]) -> Proofs:
    return frozenset(proof for proof in proofs if not any(other < proof for other in proofs))


def combine_proofs(premises: Iterable[Proofs], *, limit: int | None = None) -> Proofs:
    choices = tuple(premises)
    if not choices:
        raise ValueError("A derivation requires at least one premise.")
    candidates: set[Proof] = set()
    for combination in product(*choices):
        candidates.add(frozenset[str]().union(*combination))
        if limit is not None and len(candidates) > limit:
            raise ValueError(f"Proof family exceeds the supported limit of {limit}.")
    return _minimal(candidates)


def derive_proofs(evidence: tuple[Evidence, ...], rules: tuple[Rule, ...]) -> dict[str, Proofs]:
    if len({item.id for item in evidence}) != len(evidence):
        raise ValueError("Source IDs must be unique.")
    proofs: dict[str, Proofs] = {}
    for item in evidence:
        proofs[item.proposition] = proofs.get(item.proposition, frozenset()) | {
            frozenset((item.id,))
        }
    changed = True
    while changed:
        changed = False
        for rule in rules:
            if not all(premise in proofs for premise in rule.premises):
                continue
            candidates = combine_proofs(proofs[premise] for premise in rule.premises)
            previous = proofs.get(rule.conclusion, frozenset())
            updated = _minimal(set(previous) | candidates)
            if updated != previous:
                proofs[rule.conclusion] = updated
                changed = True
    return proofs


class Memory:
    def __init__(self, evidence: tuple[Evidence, ...], rules: tuple[Rule, ...], policy: Policy):
        if len({item.id for item in evidence}) != len(evidence):
            raise ValueError("Source IDs must be unique.")
        self.evidence = evidence
        self.rules = rules
        self.policy = policy
        self.active = {item.id for item in evidence}
        self._known_ids = frozenset(self.active)
        self._cache: dict[str, Proofs] | None = None

    def delete(self, source_id: str) -> None:
        if source_id not in self._known_ids:
            raise ValueError(f"Unknown source ID: {source_id}")
        self.active.discard(source_id)

    def delete_session(self, session_id: str) -> None:
        members = [item.id for item in self.evidence if item.session_id == session_id]
        if not members:
            raise ValueError(f"Unknown session ID: {session_id}")
        for source_id in members:
            self.delete(source_id)

    def consolidate(self) -> None:
        surviving = tuple(item for item in self.evidence if item.id in self.active)
        self._cache = derive_proofs(surviving, self.rules)

    def query(self, proposition: str) -> bool:
        if self._cache is None:
            surviving = tuple(item for item in self.evidence if item.id in self.active)
            return proposition in derive_proofs(surviving, self.rules)
        proofs = self._cache.get(proposition, frozenset())
        if not proofs:
            return False
        if self.policy == Policy.REFERENCE:
            return any(proof <= self.active for proof in proofs)
        union = frozenset().union(*proofs)
        if self.policy == Policy.FLAT_UNION:
            return bool(union & self.active)
        return union <= self.active
