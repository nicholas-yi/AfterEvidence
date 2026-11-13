"""Zero-inference simulator-calibration worksheets for recorded development episodes.

Reads a run report written by `research.tau_copilot` and the pinned task JSON,
computes conservative heuristic flags, and renders a review worksheet with a
fixed checklist. It calls no model and is not a judge: flags only point a
reviewer at turns to read. Worksheets quote episode transcripts, so they may
only be written under the git-ignored `research/runs` directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from research.task_audit import DEFAULT_VENDOR, load

RUNS = Path(__file__).resolve().parent / "runs"
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


def episode_messages(report: dict[str, Any]) -> list[dict[str, Any]]:
    simulation = report.get("simulation")
    if isinstance(simulation, dict):
        return list(simulation.get("messages") or [])
    return list(report.get("partial_observed_messages") or [])


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


def worksheet(report: dict[str, Any], task: dict[str, Any]) -> str:
    flags = review_flags(report, task)
    instructions = task["user_scenario"]["instructions"]
    lines = [
        f"## Task {flags['task_id']}: {flags['status']}",
        "",
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render zero-inference simulator review worksheets for recorded episodes."
    )
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vendor", type=Path, default=DEFAULT_VENDOR)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(RUNS):
        parser.error("Worksheets quote transcripts; write them only under research/runs.")
    tasks = {task["id"]: task for task in load(args.vendor)[0]}
    parts = ["# Simulator calibration worksheet", ""]
    summary = []
    for path in args.reports:
        report = json.loads(path.read_text(encoding="utf-8"))
        task = tasks[str(report["task_id"])]
        parts.append(worksheet(report, task))
        summary.append(review_flags(report, task))
    output.write_text("\n".join(parts), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
