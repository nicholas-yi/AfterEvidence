from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research.harness.copilot_backend import PilotRequestLimit
from research.harness.staleness import PAID_CONDITIONS, REGIMES, dev_families
from research.studies.staleness_runner import run_episode, run_stage, stage_plan


def tool(name: str, **arguments: str) -> str:
    return json.dumps({"kind": "tool", "value": name, "arguments_json": json.dumps(arguments)})


class ScriptedBackend:
    """Fake actor: replays scripted replies and journals like CopilotBackend, with fake billing."""

    def __init__(self, replies: list[str], journal: Any = None, limit: int = 4) -> None:
        self.replies, self.journal, self.limit = list(replies), journal, limit
        self.calls, self.prompts = 0, []

    def write(self, event: str, **fields: object) -> None:
        if self.journal:
            self.journal.write(json.dumps({"event": event, **fields}) + "\n")

    async def complete(self, system: str, prompt: str, response_schema: Any = None) -> str:
        if self.calls >= self.limit:
            raise PilotRequestLimit("cap")
        self.calls += 1
        self.prompts.append(system + prompt)
        usage = {"usage": {"input_tokens": 1, "output_tokens": 1}, "requests": {"count": 1}}
        metrics = {
            "ai_credits_status": "complete",
            "total_nano_aiu": 1e8,
            "model_metrics": {"m": usage},
        }
        self.write("copilot-request-started", call_id=self.calls)
        self.write("copilot-request-completed", call_id=self.calls, metrics=metrics)
        return self.replies.pop(0) if self.replies else tool("lookup_account")


FAMILY = dev_families()[0]


def episode(
    replies: list[str], regime: str = "reset", condition: str = "plain"
) -> tuple[dict, ScriptedBackend]:
    backend = ScriptedBackend(replies)
    return asyncio.run(run_episode(backend, FAMILY, regime, condition)), backend


class StalenessRunnerTests(unittest.TestCase):
    def test_lookup_then_submit_correct(self) -> None:
        report, _ = episode([tool("lookup_account"), tool("submit_target", value=FAMILY.old)])
        self.assertEqual(
            (
                report["status"],
                report["outcome"],
                report["looked_up_before_submit"],
                report["requests_started"],
            ),
            ("completed", "correct", True, 2),
        )

    def test_submit_without_lookup_is_obsolete(self) -> None:
        report, _ = episode([tool("submit_target", value=FAMILY.new)])
        self.assertEqual(
            (report["outcome"], report["looked_up_before_submit"]), ("obsolete", False)
        )

    def test_malformed_then_valid_counts_the_reask(self) -> None:
        report, backend = episode(["not json", tool("submit_target", value=FAMILY.old)])
        self.assertEqual((report["outcome"], report["reasks"], backend.calls), ("correct", 1, 2))
        report, _ = episode(["not json", "still not json"])
        self.assertEqual((report["status"], report["outcome"]), ("failed", "failed"))

    def test_cap_hit_is_an_incomplete_failure(self) -> None:
        report, backend = episode([])
        self.assertEqual(
            (report["status"], report["outcome"], backend.calls), ("budget-capped", "failed", 4)
        )

    def test_ledger_stop_refuses_to_start(self) -> None:
        plan = stage_plan("a")
        made: list[ScriptedBackend] = []
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "orphan.calls.jsonl").write_text(
                json.dumps({"event": "copilot-request-started", "call_id": 1}) + "\n",
                encoding="utf-8",
            )
            result = asyncio.run(
                run_stage(plan, directory, lambda j: made.append(ScriptedBackend([], j)))
            )
        self.assertEqual(made, [])
        self.assertTrue(any(r.startswith("count mismatch") for r in result["refused"]))

    def test_stage_a_plan_and_stage_b_needs_a_v2_tag(self) -> None:
        plan = stage_plan("a")
        self.assertEqual(
            (len(plan["jobs"]), plan["request_cap"], plan["shuffle_seed"]), (36, 144, 20261113)
        )
        for tag in (None, "memory-study-v1"):
            with self.assertRaises(ValueError):
                stage_plan("b", tag)

    def test_hidden_labels_never_reach_prompts(self) -> None:
        for regime in REGIMES:
            for condition in PAID_CONDITIONS:
                _, backend = episode(
                    ["bad", tool("lookup_account"), tool("abstain", reason="x")], regime, condition
                )
                for prompt in backend.prompts:
                    lowered = prompt.casefold()
                    for label in ("correct", "obsolete", "hidden"):
                        self.assertNotIn(label, lowered)


if __name__ == "__main__":
    unittest.main()
