from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from research.harness.native_scoring import preflight_task, reference_trajectory, score_episode
from research.harness.tau_copilot import run
from research.harness.tau_pilot import VENDOR, check_source
from research.tests.support import BENCHMARK, require

require(*BENCHMARK)

if TYPE_CHECKING:
    from tau2.data_model.simulation import SimulationRun


class NativeScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        check_source()
        os.environ["PYTHON_DOTENV_DISABLED"] = "1"
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")
        from loguru import logger
        from tau2.domains.retail.environment import get_tasks

        logger.remove()
        logger.add(sys.stderr, level="WARNING")
        cls.tasks = {task.id: task for task in get_tasks("train")}

    def test_executable_references_have_discriminating_native_controls(self) -> None:
        for task_id in ("0", "1"):
            with self.subTest(task=task_id):
                result = preflight_task(self.tasks[task_id])
                self.assertEqual(result["reference_env_reward"], 1)
                self.assertTrue(result["reference_changes_db"])
                self.assertFalse(result["empty_db_match"])
                self.assertEqual(result["model_calls"], 0)

    def test_task_two_strict_reference_failure_is_not_silently_ignored(self) -> None:
        with self.assertRaisesRegex(
            ValueError, r"Task 2: reference action .*get_product_details.*Product not found"
        ):
            preflight_task(self.tasks["2"])

    def test_only_scripted_non_mutating_lookup_failures_are_allowed(self) -> None:
        result = preflight_task(self.tasks["35"])
        self.assertEqual(result["reference_env_reward"], 1)
        self.assertEqual(
            [(f["action"], f["tool"]) for f in result["scripted_failed_lookups"]],  # type: ignore[union-attr]
            [(1, "find_user_id_by_email")],
        )
        unscripted = self.tasks["35"].model_copy(deep=True)
        if unscripted.evaluation_criteria is None or not unscripted.evaluation_criteria.actions:
            self.fail("Task 35 has no reference actions.")
        unscripted.evaluation_criteria.actions[0].arguments["email"] = "unscripted@example.com"
        with self.assertRaisesRegex(ValueError, "reference action 1"):
            preflight_task(unscripted)
        with self.assertRaisesRegex(ValueError, "Task 105: .*Insufficient gift card balance"):
            preflight_task(self.tasks["105"])

    def test_reference_failure_stops_before_copilot_initialization(self) -> None:
        task = self.tasks["0"].model_copy(deep=True)
        if task.evaluation_criteria is None or not task.evaluation_criteria.actions:
            self.fail("Development task has no reference actions.")
        task.evaluation_criteria.actions[0].name = "invalid_reference_tool"
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("tau2.domains.retail.environment.get_tasks", return_value=[task]),
            patch("research.harness.tau_copilot.isolated_client") as client,
        ):
            with self.assertRaises((ValueError, KeyError)):
                asyncio.run(run(Path(directory) / "never-created.json", "0", "test", 1, 1))
            client.assert_not_called()

    def test_test_split_requires_an_existing_protocol_tag_before_copilot(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("research.harness.tau_copilot.isolated_client") as client,
        ):
            for tag in (None, "no-such-protocol-tag"):
                with self.assertRaisesRegex(ValueError, "protocol"):
                    asyncio.run(
                        run(
                            Path(directory) / "x.json",
                            "5",
                            "test",
                            1,
                            1,
                            split="test",
                            protocol_tag=tag,
                        )
                    )
            client.assert_not_called()

    def simulation(self, task_id: str, reason: str) -> SimulationRun:
        from tau2.data_model.simulation import SimulationRun, TerminationReason

        return SimulationRun(
            id="scripted-scorer-unit-test",
            task_id=task_id,
            start_time="2026-11-13T00:00:00Z",
            end_time="2026-11-13T00:00:00Z",
            duration=0,
            termination_reason=TerminationReason(reason),
            messages=[],
        )

    def test_premature_termination_is_not_completed_or_fully_scored(self) -> None:
        simulation = self.simulation("0", "max_steps")
        reward, result = score_episode(simulation, self.tasks["0"])
        self.assertEqual(reward.reward, 0)
        self.assertFalse(result["termination_complete"])
        self.assertIsNone(result["native_task_reward"])
        self.assertTrue(result["unassessed_reward_basis"])

    def test_no_judge_call_and_no_full_reward_for_pending_policy_assertion(self) -> None:
        task = self.tasks["0"].model_copy(deep=True)
        if task.evaluation_criteria is None:
            self.fail("Development task has no criteria.")
        task.evaluation_criteria.nl_assertions = ["The agent follows the supplied policy."]
        simulation = self.simulation("0", "user_stop")
        with patch("tau2.evaluator.evaluator_nl_assertions.generate") as generate:
            _, result = score_episode(simulation, task)
            generate.assert_not_called()
        self.assertIsNone(result["native_task_reward"])
        self.assertEqual(result["unassessed_reward_basis"], ["NL_ASSERTION"])
        self.assertEqual(result["nl_assertion_count"], 1)

    def test_native_all_score_is_inference_free_when_assertions_are_empty(self) -> None:
        simulation = self.simulation("0", "user_stop")
        simulation.messages, _, _ = reference_trajectory(self.tasks["0"])
        with patch("tau2.evaluator.evaluator_nl_assertions.generate") as generate:
            _, result = score_episode(simulation, self.tasks["0"])
            generate.assert_not_called()
        self.assertEqual(result["native_task_reward"], 1)
        self.assertEqual(result["unassessed_reward_basis"], [])


if __name__ == "__main__":
    unittest.main()
