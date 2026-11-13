from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum


class Condition(StrEnum):
    NONE = "none"
    RAW = "raw"
    CONSOLIDATED = "consolidated"
    REVISED = "revised"


@dataclass(frozen=True)
class Experience:
    id: str
    task_id: str
    policy_sha256: str
    observations: tuple[str, ...]
    outcome: str

    def public(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Lesson:
    id: str
    text: str
    support_sets: tuple[tuple[str, ...], ...]
    policy_sha256: str


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def terms(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z][a-z_]{2,}", text.casefold()))


def retrieve(
    condition: Condition,
    query: str,
    experiences: tuple[Experience, ...],
    lessons: tuple[Lesson, ...],
    active_sources: frozenset[str],
    policy_sha256: str,
    max_chars: int = 1800,
) -> tuple[str, tuple[str, ...]]:
    if not 0 <= max_chars <= 10000:
        raise ValueError("Memory character budget must be between 0 and 10000.")
    if condition == Condition.NONE:
        return "", ()
    known = {experience.id for experience in experiences}
    if not active_sources <= known:
        raise ValueError("Active memory sources include an unknown experience.")
    candidates: list[tuple[str, str]] = []
    if condition == Condition.RAW:
        for experience in experiences:
            if experience.id in active_sources:
                candidates.extend(
                    (f"{experience.id}/turn{index}", observation)
                    for index, observation in enumerate(experience.observations)
                )
                candidates.append(
                    (experience.id + "/outcome", "Observed outcome: " + experience.outcome)
                )
    else:
        for lesson in lessons:
            if not lesson.support_sets or any(
                not proof or not set(proof) <= known for proof in lesson.support_sets
            ):
                raise ValueError("Lesson has invalid or invented source dependencies.")
            if condition == Condition.REVISED:
                valid_source = any(set(proof) <= active_sources for proof in lesson.support_sets)
                if not valid_source or lesson.policy_sha256 != policy_sha256:
                    continue
            candidates.append((lesson.id, lesson.text))
    query_terms = terms(query)
    ranked = sorted(candidates, key=lambda item: (-len(terms(item[1]) & query_terms), item[0]))
    selected: list[str] = []
    identifiers: list[str] = []
    used = 0
    for identifier, text in ranked:
        entry = f"[{identifier}]\n{text}"
        separator = 2 if selected else 0
        available = max_chars - used - separator
        if available < len(identifier) + 10:
            break
        if len(entry) > available:
            entry = entry[: available - 4] + " ..."
        selected.append(entry)
        identifiers.append(identifier)
        used += len(entry) + separator
    return "\n\n".join(selected), tuple(identifiers)


def validate_lessons(
    value: object, experiences: tuple[Experience, ...], policy_sha256: str
) -> tuple[Lesson, ...]:
    if (
        not isinstance(value, dict)
        or set(value) != {"lessons"}
        or not isinstance(value["lessons"], list)
    ):
        raise ValueError("Consolidator must return one lessons array.")
    known = {experience.id for experience in experiences}
    result: list[Lesson] = []
    for item in value["lessons"]:
        if not isinstance(item, dict) or set(item) != {"text", "support_sets"}:
            raise ValueError("Each lesson requires only text and support_sets.")
        text = item["text"]
        if not isinstance(text, str) or not text.strip() or len(text) > 600:
            raise ValueError("Each lesson requires 1-600 characters.")
        raw_proofs = item["support_sets"]
        if not isinstance(raw_proofs, list) or not raw_proofs or len(raw_proofs) > 8:
            raise ValueError("A lesson requires 1-8 alternative source proofs.")
        proofs: list[tuple[str, ...]] = []
        for raw_proof in raw_proofs:
            if (
                not isinstance(raw_proof, list)
                or not raw_proof
                or any(not isinstance(key, str) for key in raw_proof)
            ):
                raise ValueError("Proofs must be nonempty source-ID arrays.")
            if len(set(raw_proof)) != len(raw_proof) or not set(raw_proof) <= known:
                raise ValueError("A lesson cited unknown or duplicated source IDs.")
            proofs.append(tuple(sorted(raw_proof)))
        # A model's proposed narrower citation is not evidence that omitted inputs had no influence.
        conservative = (tuple(sorted(known)),)
        result.append(
            Lesson(
                "lesson_" + digest([text, conservative])[:16],
                text.strip(),
                conservative,
                policy_sha256,
            )
        )
    if len(result) > 6:
        raise ValueError("At most six consolidated lessons are supported.")
    return tuple(result)
