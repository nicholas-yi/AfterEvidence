"""Offline builders for the internal memory conditions of the memory study.

Inputs are recorded learning-pool episodes: what the agent saw and did, plus a
binary outcome label (native ENV reward 1 or not), which the protocol permits as
development feedback. Reference actions, task instructions, and scorer details are
never read. Builder LLM calls go through the isolated Copilot backend, journaled
under their own cap.

Conditions built here:
- raw: one retrievable item per past episode transcript (trajectory exemplars).
- consolidated: one-pass global lessons with provenance (ExpeL-style insights).
- sleep: a non-parametric analogue of sleep consolidation. Per-episode "wake"
  encoding, then replay that merges similar lessons, reweights them by how many
  distinct episodes support them, downscales weights to the strongest lesson
  (homeostasis), prunes weak ones, and rewrites survivors.
- workflows: reusable step sequences induced from successful episodes (AWM-style).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from research.memory_methods import Experience, validate_lessons
from research.memory_retrievers import cosine, embed

GENERAL = (
    "Write general, reusable guidance for future conversations with different customers. "
    "Never include customer names, user IDs, emails, order numbers, item IDs, or prices."
)


def episode_messages(report: dict[str, Any]) -> list[dict[str, Any]]:
    simulation = report.get("simulation")
    if isinstance(simulation, dict):
        return list(simulation.get("messages") or [])
    return list(report.get("partial_observed_messages") or [])


def episode_digest(report: dict[str, Any], limit: int = 6000) -> dict[str, Any]:
    lines: list[str] = []
    structured: list[tuple[str, str]] = []
    for message in episode_messages(report):
        role = message.get("role")
        content = (message.get("content") or "").strip()
        if role == "user" and content:
            lines.append(f"Customer: {content}")
            structured.append(("customer", content))
        elif role == "assistant":
            for call in message.get("tool_calls") or []:
                call_text = f"{call['name']}({json.dumps(call['arguments'], sort_keys=True)})"
                lines.append(f"Agent tool: {call_text}")
                structured.append(("tool", "call " + call_text))
            if content:
                lines.append(f"Agent: {content}")
                structured.append(("agent", content))
        elif role == "tool":
            prefix = "Tool error" if message.get("error") else "Tool result"
            lines.append(f"{prefix}: {content[:300]}")
            structured.append(("tool", f"{prefix.lower()}: {content[:300]}"))
    success = report.get("status") == "scored" and report.get("native_env_reward") == 1
    text = "\n".join(lines)
    return {
        "id": f"ep-{report['task_id']}",
        "task_id": str(report["task_id"]),
        "outcome": "success" if success else f"failure ({report.get('status')})",
        "text": text[:limit],
        "lines": structured,
    }


def load_bank(directory: Path) -> list[dict[str, Any]]:
    reports = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("task-*.json"))
    ]
    return [episode_digest(r) for r in sorted(reports, key=lambda r: int(r["task_id"]))]


def with_embeddings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vectors = embed([item["text"] for item in items], "document")
    return [dict(item, embedding=vector) for item, vector in zip(items, vectors)]


def build_raw(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"id": ep["id"], "text": f"Past episode (outcome: {ep['outcome']}).\n{ep['text'][:2200]}"}
        for ep in episodes
    ]


def corpus(episodes: list[dict[str, Any]], limit: int = 2500) -> str:
    return "\n\n".join(
        f"=== {ep['id']} (outcome: {ep['outcome']})\n{ep['text'][:limit]}" for ep in episodes
    )


LESSONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["lessons"],
    "properties": {
        "lessons": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "support_sets"],
                "properties": {
                    "text": {"type": "string"},
                    "support_sets": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        }
    },
}

CANDIDATES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["lessons"],
    "properties": {"lessons": {"type": "array", "items": {"type": "string"}}},
}

MERGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["lessons"],
    "properties": {
        "lessons": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["cluster", "text"],
                "properties": {"cluster": {"type": "integer"}, "text": {"type": "string"}},
            },
        }
    },
}

WORKFLOW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["workflows"],
    "properties": {
        "workflows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "steps"],
                "properties": {
                    "name": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


class Builder:
    """Synchronous facade over the isolated Copilot backend for offline builds."""

    def __init__(self, journal: Path, cap: int, model: str = "claude-haiku-5.5"):
        from research.copilot_backend import CopilotBackend, isolated_client

        class BuildBackend(CopilotBackend):
            max_request_limit = 500

        self.loop = asyncio.new_event_loop()
        self.client = isolated_client()
        self.loop.run_until_complete(self.client.start())
        journal.parent.mkdir(parents=True, exist_ok=True)
        self.handle = journal.open("x", encoding="utf-8", newline="\n")
        self.backend = BuildBackend(
            self.client, model, journal.parent / "builder-sessions", self.handle, request_limit=cap
        )

    def ask(self, system: str, prompt: str, schema: dict[str, Any]) -> Any:
        text = self.loop.run_until_complete(self.backend.complete(system, prompt, schema))
        return json.loads(text)

    def close(self) -> None:
        self.handle.close()
        self.loop.run_until_complete(self.client.stop())
        self.loop.close()


def build_consolidated(builder: Builder, episodes: list[dict[str, Any]], policy: str) -> list[dict]:
    value = builder.ask(
        "You distill lessons for a retail customer-service agent from its past episodes. "
        "Each episode is labeled by an automatic success check. Return at most six lessons, "
        "each under 500 characters, each citing the episode IDs that support it. " + GENERAL,
        corpus(episodes),
        LESSONS_SCHEMA,
    )
    experiences = tuple(
        Experience(ep["id"], ep["task_id"], policy, (ep["text"],), ep["outcome"]) for ep in episodes
    )
    lessons = validate_lessons(value, experiences, policy)
    return [{"id": lesson.id, "text": lesson.text} for lesson in lessons]


def cluster(candidates: list[dict[str, Any]], threshold: float) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        for group in groups:
            if cosine(candidate["embedding"], group[0]["embedding"]) >= threshold:
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    return groups


def sleep_weights(
    groups: list[list[dict[str, Any]]], keep_floor: float, minimum: int
) -> list[dict]:
    """Replay strength = distinct supporting episodes; homeostatic downscale; prune."""
    scored = []
    for index, group in enumerate(groups):
        support = sorted({c["episode"] for c in group})
        scored.append(
            {"cluster": index, "support": support, "strength": len(support), "members": group}
        )
    peak = max((s["strength"] for s in scored), default=1)
    for s in scored:
        s["weight"] = round(s["strength"] / peak, 4)
    scored.sort(key=lambda s: (-s["weight"], s["cluster"]))
    kept = [s for s in scored if s["weight"] >= keep_floor]
    return kept if len(kept) >= minimum else scored[:minimum]


def build_sleep(
    builder: Builder,
    episodes: list[dict[str, Any]],
    threshold: float = 0.85,
    keep_floor: float = 0.25,
    minimum: int = 4,
    cap: int = 8,
) -> tuple[list[dict], dict]:
    candidates = []
    for ep in episodes:
        value = builder.ask(
            "From one past customer-service episode (labeled by an automatic success check), "
            "write one to three short lessons it teaches (under 250 characters each). " + GENERAL,
            f"=== {ep['id']} (outcome: {ep['outcome']})\n{ep['text']}",
            CANDIDATES_SCHEMA,
        )
        for text in [t for t in value["lessons"] if isinstance(t, str) and t.strip()][:3]:
            candidates.append({"episode": ep["id"], "text": text.strip()[:400]})
    vectors = embed([c["text"] for c in candidates], "document")
    for candidate, vector in zip(candidates, vectors):
        candidate["embedding"] = vector
    groups = cluster(candidates, threshold)
    kept = sleep_weights(groups, keep_floor, minimum)[:cap]
    prompt = json.dumps(
        [{"cluster": s["cluster"], "lessons": [m["text"] for m in s["members"]]} for s in kept]
    )
    merged = builder.ask(
        "Each cluster holds similar lessons a customer-service agent learned in different episodes. "
        "Rewrite each cluster as one clear lesson under 400 characters. Return exactly one lesson per "
        "cluster with its cluster number. " + GENERAL,
        prompt,
        MERGE_SCHEMA,
    )
    texts = {int(item["cluster"]): item["text"].strip() for item in merged["lessons"]}
    if set(texts) != {s["cluster"] for s in kept}:
        raise ValueError("Sleep rewrite must return exactly one lesson per kept cluster.")
    items = [
        {
            "id": f"sleep-{s['cluster']}",
            "text": texts[s["cluster"]],
            "weight": s["weight"],
            "support": s["support"],
        }
        for s in kept
    ]
    stats = {
        "candidates": len(candidates),
        "clusters": len(groups),
        "kept": len(kept),
        "threshold": threshold,
        "keep_floor": keep_floor,
    }
    return items, stats


def build_workflows(builder: Builder, episodes: list[dict[str, Any]]) -> list[dict]:
    successes = [ep for ep in episodes if ep["outcome"] == "success"]
    value = builder.ask(
        "Induce reusable workflows for a retail customer-service agent from successful past episodes. "
        "Group similar requests (for example returns, exchanges, cancellations, address or item changes) "
        "and write at most six workflows, each a name and up to eight concise steps. " + GENERAL,
        corpus(successes),
        WORKFLOW_SCHEMA,
    )
    items = []
    for index, flow in enumerate(value["workflows"][:6], 1):
        steps = "\n".join(f"{n}. {s}" for n, s in enumerate(flow["steps"][:8], 1))
        items.append({"id": f"workflow-{index}", "text": f"Workflow: {flow['name']}\n{steps}"})
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="Build internal memory conditions from the bank.")
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cap", type=int, default=60)
    args = parser.parse_args()
    from research.tau_pilot import VENDOR
    from research.memory_methods import digest

    episodes = load_bank(args.bank)
    policy = digest((VENDOR / "data/tau2/domains/retail/policy.md").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "episodes.json").write_text(json.dumps(episodes, indent=1), encoding="utf-8")
    builder = Builder(args.out / "builder.calls.jsonl", args.cap)
    try:
        outputs = {
            "raw": build_raw(episodes),
            "consolidated": build_consolidated(builder, episodes, policy),
            "workflows": build_workflows(builder, episodes),
        }
        sleep_items, sleep_stats = build_sleep(builder, episodes)
        outputs["sleep"] = sleep_items
    finally:
        builder.close()
    for name, items in outputs.items():
        path = args.out / f"{name}.json"
        path.write_text(
            json.dumps({"condition": name, "items": with_embeddings(items)}), encoding="utf-8"
        )
        spec = {"kind": "items", "path": str(path.resolve())}
        (args.out / f"{name}.spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (args.out / "sleep-stats.json").write_text(json.dumps(sleep_stats, indent=1), encoding="utf-8")
    print(
        json.dumps({name: len(items) for name, items in outputs.items()} | {"sleep": sleep_stats})
    )


if __name__ == "__main__":
    main()
