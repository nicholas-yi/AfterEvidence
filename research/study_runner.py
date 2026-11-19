"""Parallel, resumable runner for memory-study episodes under one global request cap.

Each job runs `research.tau_copilot` in its own process. Before starting a job the
runner counts every started Copilot request recorded in the study directory (actor,
simulator, shim, and builder journals) and refuses to start if the job's own cap
could push the total past the approved ceiling. Jobs whose report or journal already
exists are skipped, never retried.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

PER_EPISODE = 30


def started_requests(root: Path) -> int:
    total = 0
    for journal in root.rglob("*.calls.jsonl"):
        with journal.open(encoding="utf-8") as handle:
            total += sum('"event": "copilot-request-started"' in line for line in handle)
    return total


def job_command(job: dict[str, object], python: str) -> list[str]:
    command = [
        python,
        "-m",
        "research.tau_copilot",
        "--task",
        str(job["task"]),
        "--split",
        str(job.get("split", "train")),
        "--condition",
        str(job.get("condition", "none")),
        "--requests",
        str(PER_EPISODE),
        "--max-steps",
        "60",
        "--reasks",
        "1",
        "--seed",
        str(job.get("seed", 42)),
        "--output",
        str(job["output"]),
    ]
    if job.get("memory_spec"):
        command += ["--memory-spec", str(job["memory_spec"])]
    if job.get("protocol_tag"):
        command += ["--protocol-tag", str(job["protocol_tag"])]
    return command


def run_jobs(jobs: list[dict[str, object]], root: Path, cap: int, workers: int) -> list[dict]:
    lock = Lock()
    in_flight = [0]
    results: list[dict] = []

    def one(job: dict[str, object]) -> None:
        output = Path(str(job["output"]))
        if output.exists() or output.with_suffix(".calls.jsonl").exists():
            results.append({"job": job, "status": "skipped-existing"})
            return
        with lock:
            spent = started_requests(root)
            if spent + PER_EPISODE * (in_flight[0] + 1) > cap:
                results.append({"job": job, "status": "skipped-cap", "spent": spent})
                return
            in_flight[0] += 1
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            with output.with_suffix(".stderr.txt").open("w", encoding="utf-8") as err:
                code = subprocess.run(
                    job_command(job, sys.executable), stdout=subprocess.DEVNULL, stderr=err
                ).returncode
            report = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
            row = {
                "task": job["task"],
                "condition": job.get("condition"),
                "seed": job.get("seed"),
                "status": report.get("status", f"no-report-exit-{code}"),
                "reward": report.get("native_env_reward"),
                "requests": report.get("requests_started"),
                "reasks": report.get("actor_reasks"),
                "seconds": round(time.monotonic() - started, 1),
            }
            results.append(row)
            print(json.dumps(row), flush=True)
        finally:
            with lock:
                in_flight[0] -= 1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run memory-study episodes under a global cap.")
    parser.add_argument("jobs", type=Path, help="JSON list of jobs.")
    parser.add_argument("--root", type=Path, default=Path("research/runs/memory-study"))
    parser.add_argument("--cap", type=int, default=16000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    jobs = json.loads(args.jobs.read_text(encoding="utf-8"))
    results = run_jobs(jobs, args.root, args.cap, args.workers)
    print(json.dumps({"finished": len(results), "spent": started_requests(args.root)}))


if __name__ == "__main__":
    main()
