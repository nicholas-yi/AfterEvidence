"""Study 3: does deleting a source episode remove what memory derived from it?

Provider stores (in an isolated scope) ingest three episodes from three different
customers, then the first is deleted. Probes are identifiers appearing in exactly one
episode (order numbers and the customer's name). The deleted episode's identifiers
should disappear; the others' should survive. Internal lesson stores are checked
offline from their recorded provenance. Model calls happen only inside provider
ingestion (through the metered shims).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from research.harness.memory_methods import Condition, Experience, Lesson, retrieve
from research.harness.provider_ingest import post

ORDER = re.compile(r"#W\d{7}")


def identifiers(episode: dict[str, Any]) -> set[str]:
    found = set(ORDER.findall(episode["text"]))
    names = re.findall(r'"first_name": "([A-Za-z]+)", "last_name": "([A-Za-z]+)"', episode["text"])
    found.update(f"{first} {last}" for first, last in names)
    return found


def mentions(texts: list[str], probes: set[str]) -> set[str]:
    joined = "\n".join(texts).casefold()
    return {probe for probe in probes if probe.casefold() in joined}


def choose(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for episode in episodes:
        ids = identifiers(episode)
        if len(ids) >= 2 and all(not (ids & identifiers(other)) for other in chosen):
            chosen.append(episode)
        if len(chosen) == 3:
            return chosen
    raise ValueError("Could not find three episodes with disjoint identifiers.")


def provider_lifecycle(provider: str, trio: list[dict[str, Any]], gateway: str) -> dict[str, Any]:
    scope = f"lifecycle-{provider}"
    deleted, kept = trio[0], trio[1:]
    only_deleted = identifiers(deleted)
    only_kept = set().union(*(identifiers(e) for e in kept))
    for episode in trio:
        post(
            "/ingest",
            {
                "provider": provider,
                "scope": scope,
                "episode": dict(episode, id="life-" + episode["id"]),
            },
            url=gateway,
        )
    before = post("/dump", {"provider": provider, "scope": scope}, url=gateway)["results"]
    post(
        "/delete",
        {"provider": provider, "scope": scope, "episode_id": "life-" + deleted["id"]},
        url=gateway,
    )
    after = post("/dump", {"provider": provider, "scope": scope}, url=gateway)["results"]
    removed_before, removed_after = mentions(before, only_deleted), mentions(after, only_deleted)
    kept_before, kept_after = mentions(before, only_kept), mentions(after, only_kept)
    return {
        "provider": provider,
        "deleted_episode": deleted["id"],
        "items_before": len(before),
        "items_after": len(after),
        "deleted_identifiers_visible_before": sorted(removed_before),
        "deleted_identifiers_visible_after": sorted(removed_after),
        "kept_identifiers_visible_before": sorted(kept_before),
        "kept_identifiers_visible_after": sorted(kept_after),
        "removal_complete": bool(removed_before) and not removed_after,
        "preservation": round(len(kept_after & kept_before) / len(kept_before), 3)
        if kept_before
        else None,
    }


def internal_lifecycle(memory_dir: Path, deleted_id: str) -> dict[str, Any]:
    """Offline provenance check for the lesson stores (no identifiers by construction)."""
    episodes = json.loads((memory_dir / "episodes.json").read_text(encoding="utf-8"))
    experiences = tuple(
        Experience(e["id"], e["task_id"], "p", (e["text"],), e["outcome"]) for e in episodes
    )
    active = frozenset(e["id"] for e in episodes) - {deleted_id}
    consolidated = json.loads((memory_dir / "consolidated.json").read_text(encoding="utf-8"))[
        "items"
    ]
    lessons = tuple(
        Lesson(i["id"], i["text"], (tuple(sorted(e["id"] for e in episodes)),), "p")
        for i in consolidated
    )
    _, revised_ids = retrieve(
        Condition.REVISED, "", experiences, lessons, active, "p", max_chars=10000
    )
    sleep = json.loads((memory_dir / "sleep.json").read_text(encoding="utf-8"))["items"]
    sleep_kept = [i["id"] for i in sleep if set(i["support"]) - {deleted_id}]
    sleep_reweighted = {i["id"]: len(set(i["support"]) - {deleted_id}) for i in sleep}
    return {
        "deleted_episode": deleted_id,
        "raw_items_after": len(active),
        "revised_conservative_lessons_kept": f"{len(revised_ids)}/{len(lessons)}",
        "sleep_support_aware_lessons_kept": f"{len(sleep_kept)}/{len(sleep)}",
        "sleep_support_after_deletion": sleep_reweighted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Deletion lifecycle checks across memory systems.")
    parser.add_argument("--memory", type=Path, default=Path("research/runs/memory-study/memory"))
    parser.add_argument(
        "--providers", nargs="+", default=["mem0", "graphiti", "hindsight", "honcho"]
    )
    parser.add_argument("--gateway", default="http://127.0.0.1:8900")
    parser.add_argument("--out", type=Path, default=Path("research/runs/memory-study/study3.json"))
    args = parser.parse_args()
    episodes = json.loads((args.memory / "episodes.json").read_text(encoding="utf-8"))
    trio = choose(episodes)
    results: dict[str, Any] = {"episodes": [e["id"] for e in trio], "providers": []}
    for provider in args.providers:
        try:
            results["providers"].append(provider_lifecycle(provider, trio, args.gateway))
        except Exception as error:  # recorded as a lifecycle failure, not hidden
            results["providers"].append(
                {"provider": provider, "error": f"{type(error).__name__}: {error}"[:400]}
            )
    results["internal"] = internal_lifecycle(args.memory, trio[0]["id"])
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
