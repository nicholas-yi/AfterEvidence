"""Zero-inference simulator-calibration worksheets for recorded development episodes.

Reads a run report written by `research.harness.tau_copilot` and the pinned task JSON,
computes conservative heuristic flags, and renders a review worksheet with a
fixed checklist. It calls no model and is not a judge: flags only point a
reviewer at turns to read. Worksheets quote episode transcripts, so they may
only be written under the git-ignored `research/runs` directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from research import RESEARCH
from research.harness.memory_bank import episode_messages
from research.harness.task_audit import DEFAULT_VENDOR, load

RUNS = RESEARCH / "runs"
STOP, TRANSFER, OUT_OF_SCOPE = "###STOP###", "###TRANSFER###", "###OUT-OF-SCOPE###"
# Identifier patterns checked only when the unknown_info says the user lacks that fact.
UNKNOWN_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "order": re.compile(r"#?W\d{7}\b"),
    "zip": re.compile(r"\b\d{5}\b"),
}
CHECKLIST = (
    "Every fact the simulator stated is in its instructions (no invented IDs, items, or preferences).",
    "Information listed as unknown was not disclosed.",
    "Conditional or fallback instructions were applied when, and only when, their condition arose.",
    "Substitutions were accepted only as the instructions allow; note catalog terminology gaps "
    "(for example Google Home requested, only Google Assistant offered).",
    "The simulator confirmed the actions its instructions call for and no others.",
    "It ended only after the goal was resolved or impossible, using the stop marker.",
    "Persona instructions were followed without overriding the goal.",
)


def _text(message: dict[str, Any]) -> str:
    return message.get("content") or ""


def review_flags(report: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    messages = episode_messages(report)
    user = [m for m in messages if m.get("role") == "user"]
    spoken = [m for m in user if _text(m).strip()]
    unknown = str(task["user_scenario"]["instructions"].get("unknown_info") or "").lower()
    disclosed: dict[str, list[str]] = {}
    for key, pattern in UNKNOWN_PATTERNS.items():
        if key in unknown:
            hits = sorted({hit for m in spoken for hit in pattern.findall(_text(m))})
            if hits:
                disclosed[key] = hits
    return {
        "task_id": report.get("task_id"),
        "condition": report.get("condition"),
        "seed": report.get("seed"),
        "status": report.get("status"),
        "termination": report.get("termination"),
        "native_env_reward": report.get("native_env_reward"),
        "requests_started": report.get("requests_started"),
        "user_turns": len(spoken),
        "empty_user_messages": sum(
            1 for m in user if not _text(m).strip() and not m.get("tool_calls")
        ),
        "ended_with_stop_marker": bool(spoken) and STOP in _text(spoken[-1]),
        "transfer_or_out_of_scope": any(
            token in _text(m) for m in spoken for token in (TRANSFER, OUT_OF_SCOPE)
        ),
        "agent_tool_errors": sum(
            1 for m in messages if m.get("role") == "tool" and m.get("error") is True
        ),
        "unknown_info_possibly_disclosed": disclosed,
        "heuristic_only": True,
    }


def needs_attention(flags: dict[str, Any]) -> bool:
    """Deterministic triage hint for ordering human review; not a fidelity judgement."""
    return bool(
        flags["status"] != "scored"
        or not flags["ended_with_stop_marker"]
        or flags["transfer_or_out_of_scope"]
        or flags["unknown_info_possibly_disclosed"]
        or flags["empty_user_messages"]
    )


def worksheet(report: dict[str, Any], task: dict[str, Any], source: str | None = None) -> str:
    flags = review_flags(report, task)
    instructions = task["user_scenario"]["instructions"]
    episode = ", ".join(
        str(part)
        for part in (
            flags["condition"],
            flags["seed"] is not None and f"seed {flags['seed']}",
        )
        if part
    )
    lines = [
        f"## Task {flags['task_id']}{f' ({episode})' if episode else ''}: {flags['status']}",
        "",
        *([f"Source: `{source}`", ""] if source else []),
        "Simulator instructions (visible to the simulator, never to the actor):",
        "",
        "```json",
        json.dumps(instructions, indent=2),
        "```",
        "",
        "Automated heuristic flags (not a judgement):",
        "",
        "```json",
        json.dumps(flags, indent=2),
        "```",
        "",
        "Transcript:",
        "",
    ]
    for number, message in enumerate(episode_messages(report), start=1):
        role = message.get("role")
        if message.get("tool_calls"):
            calls = "; ".join(
                f"{c.get('name')}({json.dumps(c.get('arguments'), sort_keys=True)})"
                for c in message["tool_calls"]
            )
            lines.append(f"{number}. **{role}** tool call: {calls}")
        elif role == "tool":
            prefix = "ERROR " if message.get("error") else ""
            lines.append(f"{number}. tool result: {prefix}{_text(message)[:300]}")
        else:
            lines.append(f"{number}. **{role}**: {_text(message)}")
    lines += ["", "Checklist (yes / no / unclear, with message numbers):", ""]
    lines += [f"- [ ] {item}" for item in CHECKLIST]
    lines += ["", "Labels: user_error = ? ; agent_error = ? ; reviewer = ? ; notes = ?", ""]
    return "\n".join(lines)


INDEX_FIELDS: tuple[str, ...] = (
    "source",
    "task_id",
    "condition",
    "seed",
    "status",
    "native_env_reward",
    "requests_started",
    "user_turns",
    "ended_with_stop_marker",
    "transfer_or_out_of_scope",
    "unknown_info_possibly_disclosed",
    "empty_user_messages",
    "needs_attention",
    "reviewer",
    "fidelity_ok",
    "notes",
)


def write_index(path: Path, summary: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> None:
    """One row per episode, with blank reviewer columns; missing planned reports stay visible."""
    rows = [{**flags, "needs_attention": needs_attention(flags)} for flags in summary]
    seen = {(str(r["task_id"]), str(r["condition"]), str(r["seed"])) for r in rows}
    for job in jobs:
        key = (str(job.get("task")), str(job.get("condition")), str(job.get("seed")))
        if key not in seen:
            rows.append(
                {
                    "task_id": key[0],
                    "condition": key[1],
                    "seed": key[2],
                    "status": "no-report",
                    "needs_attention": True,
                }
            )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, INDEX_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: json.dumps(v) if isinstance(v, dict) else v for k, v in row.items()}
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render zero-inference simulator review worksheets for recorded episodes."
    )
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vendor", type=Path, default=DEFAULT_VENDOR)
    parser.add_argument(
        "--index", type=Path, help="Also write a per-episode CSV index (under research/runs)."
    )
    parser.add_argument(
        "--jobs",
        type=Path,
        help="Planned jobs JSON; planned episodes without a report are indexed.",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    index = args.index.resolve() if args.index else None
    if not output.is_relative_to(RUNS) or (index and not index.is_relative_to(RUNS)):
        parser.error("Worksheets quote transcripts; write them only under research/runs.")
    tasks = {task["id"]: task for task in load(args.vendor)[0]}
    parts = ["# Simulator calibration worksheet", ""]
    summary = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        task = tasks[str(report["task_id"])]
        source = path.resolve().relative_to(RUNS).as_posix()
        parts.append(worksheet(report, task, source))
        summary.append({"source": source, **review_flags(report, task)})
    output.write_text("\n".join(parts), encoding="utf-8")
    if index:
        write_index(index, summary, json.loads(args.jobs.read_text("utf-8")) if args.jobs else [])
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
