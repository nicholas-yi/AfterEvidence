from __future__ import annotations

import json
import platform
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from .memory import Memory, Policy
from .model import Topology, World, generate_world, oracle


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def public_payload(world: World) -> dict[str, object]:
    return {
        "evidence": [asdict(item) for item in world.evidence],
        "rules": [asdict(rule) for rule in world.rules],
    }


@dataclass(frozen=True)
class Observation:
    world_id: str
    topology: str
    policy: str
    preconsolidated: bool
    branch: str
    checkpoint: str
    proposition: str
    expected: bool
    actual: bool
    outcome: str
    active_sources: tuple[str, ...]
    public_input_sha256: str


def run_case(world: World, policy: Policy, preconsolidated: bool, sham: bool) -> list[Observation]:
    memory = Memory(world.evidence, world.rules, policy)
    if preconsolidated:
        memory.consolidate()
    active = {item.id for item in world.evidence}
    input_hash = sha256(canonical(public_payload(world)).encode()).hexdigest()
    observations: list[Observation] = []
    for checkpoint, deletions in (
        ("ready", ()),
        ("after-partial-deletion", world.partial_delete),
        ("after-final-deletion", world.final_delete),
        ("after-reconsolidation", ()),
    ):
        if not sham:
            for source_id in deletions:
                memory.delete(source_id)
                active.discard(source_id)
        if checkpoint == "after-reconsolidation":
            memory.consolidate()
        for proposition in (world.target, world.control):
            actual = memory.query(proposition)
            expected = proposition in oracle(world.evidence, world.rules, active)
            outcome = "correct"
            if actual and not expected:
                outcome = "stale"
            elif expected and not actual:
                outcome = "over-deleted"
            observations.append(
                Observation(
                    world.id,
                    world.topology,
                    policy,
                    preconsolidated,
                    "sham" if sham else "intervention",
                    checkpoint,
                    proposition,
                    expected,
                    actual,
                    outcome,
                    tuple(sorted(active)),
                    input_hash,
                )
            )
    return observations


def summarize(records: list[Observation]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for record in records:
        counts = result.setdefault(
            record.policy,
            {
                "observations": 0,
                "correct": 0,
                "stale": 0,
                "over-deleted": 0,
            },
        )
        counts["observations"] += 1
        counts[record.outcome] += 1
    return result


def source_digest() -> str:
    digest = sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_suite(worlds_per_topology: int, seed: int) -> dict[str, object]:
    if type(worlds_per_topology) is not int or not 1 <= worlds_per_topology <= 1000:
        raise ValueError("Worlds per topology must be between 1 and 1000.")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("Seed must be an unsigned 64-bit integer.")
    observations = [
        observation
        for topology in Topology
        for index in range(worlds_per_topology)
        for policy in Policy
        for preconsolidated in (False, True)
        for sham in (False, True)
        for observation in run_case(
            generate_world(seed, index, topology),
            policy,
            preconsolidated,
            sham,
        )
    ]
    report: dict[str, object] = {
        "schema_version": 1,
        "mode": "offline-development",
        "external_spend_usd": 0,
        "python_version": platform.python_version(),
        "source_sha256": source_digest(),
        "seed": seed,
        "worlds_per_topology": worlds_per_topology,
        "world_count": len(Topology) * worlds_per_topology,
        "summary": summarize(observations),
        "observations": [asdict(record) for record in observations],
    }
    report["report_sha256"] = sha256(canonical(report).encode()).hexdigest()
    return report


def verify_report(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError("Report must be a JSON object.")
    seed = value.get("seed")
    count = value.get("worlds_per_topology")
    if type(seed) is not int or type(count) is not int:
        raise ValueError("Report requires integer seed and worlds_per_topology.")
    expected = run_suite(count, seed)
    if canonical(value) != canonical(expected):
        raise ValueError(
            "Report does not match deterministic replay with the current source/runtime."
        )
