from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from research.simulator_review import review_flags, worksheet, write_index

TASK = {
    "id": "9",
    "user_scenario": {
        "instructions": {
            "reason_for_call": "Return the lamp.",
            "unknown_info": "You do not remember your email address.",
        }
    },
}


def message(role: str, content: str | None = None, **extra: object) -> dict[str, object]:
    return {"role": role, "content": content, **extra}


class SimulatorReviewTests(unittest.TestCase):
    def test_flags_disclosed_unknown_info_and_stop_marker(self) -> None:
        report = {
            "task_id": "9",
            "status": "scored",
            "simulation": {
                "messages": [
                    message("user", "Hi, my email is lamp.fan@example.com"),
                    message(
                        "assistant", tool_calls=[{"name": "find_user_id_by_email", "arguments": {}}]
                    ),
                    message("tool", "Error: User not found", error=True),
                    message("user", ""),
                    message("user", "Thanks! ###STOP###"),
                ]
            },
        }
        flags = review_flags(report, TASK)
        self.assertEqual(
            flags["unknown_info_possibly_disclosed"], {"email": ["lamp.fan@example.com"]}
        )
        self.assertTrue(flags["ended_with_stop_marker"])
        self.assertEqual(flags["user_turns"], 2)
        self.assertEqual(flags["empty_user_messages"], 1)
        self.assertEqual(flags["agent_tool_errors"], 1)

    def test_capped_reports_use_partial_messages_and_render_checklist(self) -> None:
        report = {
            "task_id": "9",
            "status": "budget-capped",
            "partial_observed_messages": [message("user", "I want to return a lamp.")],
        }
        flags = review_flags(report, TASK)
        self.assertFalse(flags["ended_with_stop_marker"])
        self.assertEqual(flags["unknown_info_possibly_disclosed"], {})
        text = worksheet(report, TASK)
        self.assertIn("1. **user**: I want to return a lamp.", text)
        self.assertIn("- [ ] Information listed as unknown was not disclosed.", text)

    def test_index_links_episodes_and_keeps_missing_planned_reports(self) -> None:
        report = {
            "task_id": "9",
            "condition": "mem0",
            "seed": 2,
            "status": "scored",
            "simulation": {"messages": [message("user", "Done ###STOP###")]},
        }
        self.assertIn("## Task 9 (mem0, seed 2): scored", worksheet(report, TASK, "s/t.json"))
        summary = [{"source": "s/t.json", **review_flags(report, TASK)}]
        jobs = [
            {"task": "9", "condition": "mem0", "seed": 2},
            {"task": "9", "condition": "mem0", "seed": 1},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.csv"
            write_index(path, summary, jobs)
            rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
        self.assertEqual([r["status"] for r in rows], ["scored", "no-report"])
        self.assertEqual([r["needs_attention"] for r in rows], ["False", "True"])
        self.assertEqual(rows[0]["source"], "s/t.json")
        self.assertEqual(rows[1]["reviewer"], "")


if __name__ == "__main__":
    unittest.main()
