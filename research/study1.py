"""Study 1: cross-customer transfer of memory built from the learning pool.

Jobs are the frozen test-task list x conditions x replicates, shuffled with a
fixed seed so time-of-run effects spread across conditions. Every job carries the
protocol tag; `tau_copilot` refuses the test split unless that tag exists.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from research.study_runner import run_jobs

TEST_TASKS = (
    "5", "9", "17", "18", "26", "27", "32", "33", "42", "49", "51", "53", "55",
    "56", "61", "71", "74", "77", "79", "86", "90", "94", "97", "100", "101", "102",
)  # fmt: skip
INTERNAL = ("raw", "consolidated", "sleep", "workflows")
PROVIDERS = ("mem0", "graphiti", "hindsight", "honcho")
CONDITIONS = ("none",) + INTERNAL + PROVIDERS
REPLICATES = (1, 2)
ORDER_SEED = 20261113


def specs(memory_dir: Path, gateway: str) -> dict[str, Path | None]:
    result: dict[str, Path | None] = {"none": None}
    for name in INTERNAL:
        result[name] = (memory_dir / f"{name}.spec.json").resolve()
    for provider in PROVIDERS:
        path = memory_dir / f"{provider}.spec.json"
        path.write_text(
            json.dumps({"kind": "gateway", "url": gateway, "provider": provider, "scope": "bank"})
        )
        result[provider] = path.resolve()
    return result


def jobs(root: Path, memory_dir: Path, tag: str, gateway: str) -> list[dict[str, object]]:
    spec_paths = specs(memory_dir, gateway)
    result = []
    for replicate in REPLICATES:
        for task in TEST_TASKS:
            for condition in CONDITIONS:
                job: dict[str, object] = {
                    "task": task, "split": "test", "condition": condition, "seed": replicate,
                    "protocol_tag": tag,
                    "output": str(root / condition / f"task-{task}-r{replicate}.json"),
                }  # fmt: skip
                if spec_paths[condition] is not None:
                    job["memory_spec"] = str(spec_paths[condition])
                result.append(job)
    random.Random(ORDER_SEED).shuffle(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the cross-customer memory study.")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--memory", type=Path, default=Path("research/runs/memory-study/memory"))
    parser.add_argument("--root", type=Path, default=Path("research/runs/memory-study/study1"))
    parser.add_argument("--gateway", default="http://127.0.0.1:8900")
    parser.add_argument("--cap", type=int, default=16000)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--write-only", action="store_true")
    args = parser.parse_args()
    planned = jobs(args.root, args.memory, args.tag, args.gateway)
    args.root.mkdir(parents=True, exist_ok=True)
    (args.root / "jobs.json").write_text(json.dumps(planned, indent=1), encoding="utf-8")
    if not args.write_only:
        run_jobs(planned, args.root.parent, args.cap, args.workers)


if __name__ == "__main__":
    main()
