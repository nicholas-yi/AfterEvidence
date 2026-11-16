"""Read-only, outcome-blind snapshots of a commitment run; never launch or retry jobs."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT = re.compile(r"^(.+-s\d+-\w+?)(?:-a([1-9]\d*))?\.json$")
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timestamps need an explicit UTC offset.")
    return parsed.astimezone(timezone.utc)


def sleep_seconds(
    start: datetime, end: datetime, windows: list[tuple[datetime, datetime]]
) -> float:
    clipped = []
    for left, right in windows:
        if right <= left:
            raise ValueError("Each sleep interval must end after it starts.")
        if max(left, start) < min(right, end):
            clipped.append((max(left, start), min(right, end)))
    merged: list[tuple[datetime, datetime]] = []
    for left, right in sorted(clipped):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return sum((right - left).total_seconds() for left, right in merged)


def planned_jobs(root: Path, session: int) -> dict[str, dict[str, Any]]:
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("The plan must contain a nonempty jobs list.")
    excluded = set()
    exclusion_path = root / "exclusions.json"
    if exclusion_path.exists():
        exclusions = json.loads(exclusion_path.read_text(encoding="utf-8")).get("excluded")
        if not isinstance(exclusions, list) or any(type(x) is not str for x in exclusions):
            raise ValueError("Invalid exclusion metadata.")
        excluded = set(exclusions)
    selected = {}
    seen = set()
    for job in jobs:
        if not isinstance(job, dict) or type(job.get("session")) is not int:
            raise ValueError("Every planned job needs an integer session.")
        for field in ("family", "arm"):
            if not isinstance(job.get(field), str) or not IDENTIFIER.fullmatch(job[field]):
                raise ValueError(f"Invalid planned {field}.")
        key = f"{job['family']}-s{job['session']}-{job['arm']}"
        if key in seen:
            raise ValueError(f"Duplicate planned job: {key}")
        seen.add(key)
        if job["session"] == session and (session == 1 or job["family"] not in excluded):
            selected[key] = job
    if not selected:
        raise ValueError("No jobs are planned for this session after exclusions.")
    return selected


def snapshot(
    root: Path,
    session: int = 2,
    *,
    now: datetime | None = None,
    started_at: datetime | None = None,
    sleeps: list[tuple[datetime, datetime]] | None = None,
    stale_after: float = 300,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None or (started_at and started_at.utcoffset() is None):
        raise ValueError("Snapshot and start times must have UTC offsets.")
    if not math.isfinite(stale_after) or stale_after <= 0:
        raise ValueError("The stale-activity threshold must be finite and positive.")
    sleeps = sleeps or []
    if sleeps and started_at is None:
        raise ValueError("Sleep accounting requires a known phase start.")
    if started_at and started_at > now:
        raise ValueError("Phase start is after the snapshot time.")
    for left, right in sleeps:
        if left.utcoffset() is None or right.utcoffset() is None:
            raise ValueError("Sleep times need UTC offsets.")
        if right <= left:
            raise ValueError("Each sleep interval must end after it starts.")
    jobs = planned_jobs(root, session)
    reports: dict[str, list[tuple[int, float]]] = {}
    activity = []
    warnings = []
    unexpected = []
    for path in root.iterdir():
        match = REPORT.fullmatch(path.name)
        journal = path.name.endswith(".calls.jsonl")
        stem = path.name.removesuffix(".calls.jsonl")
        journal_job = re.sub(r"-a[1-9]\d*$", "", stem)
        if not match and not (journal and journal_job in jobs):
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            warnings.append(f"File disappeared during snapshot: {path.name}")
            continue
        if not path.is_file():
            continue
        if journal:
            activity.append(stat.st_mtime)
        elif match:
            key = match[1]
            if key not in jobs:
                # Other sessions are expected in the same directory.
                if f"-s{session}-" in key:
                    unexpected.append(key)
                continue
            reports.setdefault(key, []).append((int(match[2] or 1), stat.st_mtime))
            activity.append(stat.st_mtime)
    age = max(0.0, now.timestamp() - max(activity)) if activity else None
    if age is not None and age > stale_after:
        warnings.append("No recent file activity; check the worker. Do not retry automatically.")
    if unexpected:
        warnings.append("Report filenames exist outside the selected plan; reconcile them.")
    latest = {key: max(rows, key=lambda row: row[0])[1] for key, rows in reports.items()}
    timing: dict[str, Any] | None = None
    if started_at:
        wall = (now - started_at).total_seconds()
        asleep = sleep_seconds(started_at, now, sleeps)
        rate_start = max([started_at] + [right for _, right in sleeps if right <= now])
        span = (now - rate_start).total_seconds()
        since = sum(rate_start.timestamp() <= stamp <= now.timestamp() for stamp in latest.values())
        rate = since / span if span > 0 else None
        remaining = len(jobs) - len(reports)
        timing = {
            "wall_seconds": wall,
            "reported_sleep_seconds": asleep,
            "awake_wall_seconds": wall - asleep,
            "CPU_seconds": None,
            "rate_window_start": rate_start.isoformat(),
            "report_presence_per_hour": rate * 3600 if rate else None,
            "conditional_seconds_to_remaining_report_presence": (
                remaining / rate
                if rate and remaining and age is not None and age <= stale_after
                else None
            ),
        }
    return {
        "snapshot_utc": now.astimezone(timezone.utc).isoformat(),
        "session": session,
        "planned_jobs": len(jobs),
        "job_ids_with_reports": len(reports),
        "attempt_report_files": sum(map(len, reports.values())),
        "multiple_attempt_job_ids": sorted(k for k, rows in reports.items() if len(rows) > 1),
        "missing_job_ids": sorted(set(jobs) - set(reports)),
        "unexpected_job_ids": sorted(set(unexpected)),
        "all_planned_job_ids_have_reports": len(reports) == len(jobs),
        "seconds_since_file_activity": age,
        "by_arm": {
            arm: {
                "planned": sum(j["arm"] == arm for j in jobs.values()),
                "job_ids_with_reports": sum(jobs[k]["arm"] == arm for k in reports),
            }
            for arm in sorted({j["arm"] for j in jobs.values()})
        },
        "timing": timing,
        "warnings": warnings,
        "boundary": (
            "Filename presence only, not success, a final attempt, or scientific completion. "
            "Report bodies are never opened. Awake wall time is not CPU time. "
            "ETA assumes unchanged throughput; no process control or power changes."
        ),
    }


def budget_snapshot(root: Path) -> dict[str, Any]:
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    nested = plan.get("budget") or {}  # dated changed-mind plans nest the caps
    cap = plan.get("request_cap", nested.get("hard_cap"))
    stop = plan.get("credit_stop", nested.get("credit_stop"))
    if (
        type(cap) is not int
        or cap <= 0
        or type(stop) not in (int, float)
        or not math.isfinite(stop)
        or stop <= 0
    ):
        raise ValueError("Budget metadata needs a positive integer cap and finite positive stop.")
    # Reuse the runner's accounting, rather than invent a second budget policy.
    from research.commitment_pilot import journal_rows, pilot_ledger

    ledger = pilot_ledger(journal_rows(root), cap, stop)
    return {
        **ledger,
        "request_cap": cap,
        "credit_stop": stop,
        "request_headroom": cap - ledger["started"],
        "provisional_credit_headroom": stop - ledger["charged_credits"],
        "note": (
            "Read-only runner-accounting snapshot, not enforcement. An in-flight request may "
            "appear as an un-journaled mismatch; unresolved billing is unknown, not free. "
            "Raw journals may contain prompts but none are included in this output."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--session", type=int, choices=(1, 2), default=2)
    parser.add_argument("--started-at", type=instant)
    parser.add_argument("--sleep", type=instant, nargs=2, action="append", default=[])
    parser.add_argument("--stale-after", type=float, default=300)
    parser.add_argument("--budget", action="store_true", help="Requires the research environment.")
    args = parser.parse_args()
    result = snapshot(
        args.root,
        args.session,
        started_at=args.started_at,
        sleeps=args.sleep,
        stale_after=args.stale_after,
    )
    if args.budget:
        result["budget"] = budget_snapshot(args.root)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
