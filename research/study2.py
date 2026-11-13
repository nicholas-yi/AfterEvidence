"""Study 2: does memory of a returning customer's earlier sessions help (or mislead)?

For each training-task family that shares one customer, sessions run in task order.
Every session first runs without memory; that baseline transcript is the shared
history. Each later session also runs under three memory conditions built only from
the same customer's earlier baseline transcripts:

- session: earlier transcripts, most recent first (plain session memory);
- mem0 / honcho: the providers' per-customer stores, fed the same transcripts.

The benchmark database resets between sessions, so remembered actions may be stale;
that risk is part of what is measured. Runs through the capped study runner.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from research.memory_bank import episode_digest
from research.provider_ingest import post
from research.study_runner import run_jobs

PROVIDERS = ("mem0", "honcho")


def session_text(history: list[dict]) -> str:
    parts = [
        f"Earlier session (most recent first, outcome: {ep['outcome']}):\n{ep['text']}"
        for ep in reversed(history)
    ]
    return "\n\n".join(parts)


def run_family(family: list[dict], root: Path, cap: int, gateway: str) -> None:
    customer = family[0]["customer"]
    scope = f"customer:{customer}"
    history: list[dict] = []
    for index, session in enumerate(family):
        task = session["task"]
        baseline = root / "none" / f"task-{task}.json"
        jobs = [{"task": task, "condition": "none", "seed": 1, "output": str(baseline)}]
        if history:
            spec_path = root / "specs" / f"session-{task}.json"
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(
                json.dumps({"kind": "text", "text": session_text(history)}), encoding="utf-8"
            )
            jobs.append({"task": task, "condition": "session", "seed": 1, "memory_spec": str(spec_path),
                         "output": str(root / "session" / f"task-{task}.json")})  # fmt: skip
            for provider in PROVIDERS:
                spec = root / "specs" / f"{provider}-{task}.json"
                spec.write_text(json.dumps({"kind": "gateway", "url": gateway, "provider": provider,
                                            "scope": scope}), encoding="utf-8")  # fmt: skip
                jobs.append({"task": task, "condition": provider, "seed": 1, "memory_spec": str(spec),
                             "output": str(root / provider / f"task-{task}.json")})  # fmt: skip
        run_jobs(jobs, root.parent, cap, workers=len(jobs))
        if index == len(family) - 1 or not baseline.exists():
            continue
        episode = episode_digest(json.loads(baseline.read_text(encoding="utf-8")))
        episode["id"] = f"s2-{task}"
        history.append(episode)
        for provider in PROVIDERS:
            post("/ingest", {"provider": provider, "scope": scope, "episode": episode}, url=gateway)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the same-customer multi-session study.")
    parser.add_argument("--families", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("research/runs/memory-study/study2"))
    parser.add_argument("--cap", type=int, default=16000)
    parser.add_argument("--gateway", default="http://127.0.0.1:8900")
    parser.add_argument("--parallel-families", type=int, default=2)
    args = parser.parse_args()
    families = list(json.loads(args.families.read_text(encoding="utf-8")).values())
    with ThreadPoolExecutor(max_workers=args.parallel_families) as pool:
        list(pool.map(lambda fam: run_family(fam, args.root, args.cap, args.gateway), families))


if __name__ == "__main__":
    main()
