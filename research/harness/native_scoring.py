from __future__ import annotations

import argparse
import json
import os
import sys
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tau2.data_model.message import Message
    from tau2.data_model.simulation import RewardInfo, SimulationRun
    from tau2.data_model.tasks import Task


REFERENCE_POLICY = "strict-except-scripted-lookups-v2"


@lru_cache(maxsize=1)
def _initial_retail_db() -> dict[str, Any]:
    from research.harness.task_audit import DATA
    from research.harness.tau_pilot import VENDOR

    return json.loads((VENDOR / DATA / "db.json").read_text(encoding="utf-8"))


def scripted_lookup(task: Task, index: int) -> bool:
    """Whether 1-based reference action `index` is a lookup the user is scripted to misstate.

    Judged against the pinned JSON database, so tasks that alter the initial state
    never qualify. The caller must separately require a non-mutating tool.
    """
    from research.harness.task_audit import invalid_references

    initial = task.initial_state
    if initial and (initial.initialization_data or initial.initialization_actions):
        return False
    problems = [
        problem
        for problem in invalid_references(task.model_dump(mode="json"), _initial_retail_db())
        if problem["action"] == index
    ]
    return bool(problems) and all(p["scripted_in_user_instructions"] for p in problems)


def reference_trajectory(task: Task) -> tuple[list[Message], bool, list[dict[str, object]]]:
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage
    from tau2.domains.retail.environment import get_environment

    criteria = task.evaluation_criteria
    if criteria is None:
        raise ValueError("A baseline task must have explicit evaluation criteria.")
    initial = task.initial_state
    history = list(initial.message_history or []) if initial else []
    environment = get_environment()
    environment.set_state(
        initialization_data=initial.initialization_data if initial else None,
        initialization_actions=initial.initialization_actions if initial else None,
        message_history=history,
    )
    initial_hashes = (environment.get_db_hash(), environment.get_user_db_hash())
    if initial_hashes[0] is None:
        raise ValueError("The retail reference must expose an actual agent database.")
    allowed: list[dict[str, object]] = []
    for index, action in enumerate(criteria.actions or []):
        call = ToolCall(
            id=f"reference_control_{index}",
            name=action.name,
            arguments=action.arguments,
            requestor=action.requestor,
        )
        # Upstream ENV scoring logs reference exceptions and continues; preflight must not,
        # except for a non-mutating lookup the user instructions deliberately misstate.
        try:
            result = environment.make_tool_call(
                action.name, requestor=action.requestor, **action.arguments
            )
            content, failed = environment.to_json_str(result), False
        except (ValueError, KeyError, TypeError) as error:
            if not (
                isinstance(error, ValueError)
                and "not found" in str(error).lower()
                and not environment._is_mutating_tool(action.name)
                and scripted_lookup(task, index + 1)
            ):
                raise ValueError(
                    f"Task {task.id}: reference action {index + 1} ({action.name}) failed: {error}"
                ) from error
            allowed.append({"action": index + 1, "tool": action.name, "error": str(error)})
            content, failed = environment.to_json_str(f"Error: {error}"), True
        if action.requestor == "assistant":
            message = AssistantMessage(role="assistant", tool_calls=[call])
        else:
            message = UserMessage(role="user", tool_calls=[call])
        history.extend(
            [
                message,
                ToolMessage(
                    role="tool",
                    id=call.id,
                    requestor=action.requestor,
                    content=content,
                    error=failed,
                ),
            ]
        )
    changed = initial_hashes != (environment.get_db_hash(), environment.get_user_db_hash())
    return history, changed, allowed


def preflight_task(task: Task) -> dict[str, object]:
    from tau2.domains.retail.environment import get_environment
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator

    history, changed, allowed = reference_trajectory(task)
    positive = EnvironmentEvaluator.calculate_reward(get_environment, task, history)
    if positive.db_check is None or not positive.db_check.db_match or positive.reward != 1:
        raise ValueError(f"Task {task.id}: native reference replay did not pass ENV scoring.")
    initial = task.initial_state
    empty_history = list(initial.message_history or []) if initial else []
    empty = EnvironmentEvaluator.calculate_reward(get_environment, task, empty_history)
    if empty.db_check is None or empty.db_check.db_match != (not changed):
        raise ValueError(f"Task {task.id}: empty-trajectory DB control disagrees with reference.")
    criteria = task.evaluation_criteria
    if criteria is None:
        raise ValueError("A baseline task must have explicit evaluation criteria.")
    return {
        "task_id": task.id,
        "model_calls": 0,
        "reference_policy": REFERENCE_POLICY,
        "reference_actions_validated": len(criteria.actions or []),
        "scripted_failed_lookups": allowed,
        "reference_changes_db": changed,
        "reference_env_reward": positive.reward,
        "empty_db_match": empty.db_check.db_match,
        "required_reward_basis": [basis.value for basis in criteria.reward_basis],
        "nl_assertion_count": len(criteria.nl_assertions or []),
        "communicate_count": len(criteria.communicate_info or []),
        "limitations": "Scripted scorer controls, not agent success or simulator validation.",
    }


def score_episode(simulation: SimulationRun, task: Task) -> tuple[RewardInfo, dict[str, object]]:
    from tau2.data_model.semantic_communication import CommunicateScorer, CommunicateScoring
    from tau2.data_model.simulation import TerminationReason
    from tau2.data_model.tasks import RewardType
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    from tau2.orchestrator.modes import CommunicationMode

    criteria = task.evaluation_criteria
    if criteria is None:
        raise ValueError("A baseline task must have explicit evaluation criteria.")
    complete = simulation.termination_reason in {
        TerminationReason.AGENT_STOP,
        TerminationReason.USER_STOP,
    }

    def evaluate(kind: EvaluationType) -> RewardInfo:
        return evaluate_simulation(
            simulation,
            task,
            kind,
            False,
            "retail",
            mode=CommunicationMode.HALF_DUPLEX,
            communicate_scoring=CommunicateScoring(scorer=CommunicateScorer.SUBSTRING, judge=None),
        )

    environment_reward = evaluate(EvaluationType.ENV)
    required = set(criteria.reward_basis)
    covered: set[RewardType] = set()
    overall = None
    communication_reward = None
    needs_judge = RewardType.NL_ASSERTION in required and bool(criteria.nl_assertions)
    if complete:
        communication_reward = evaluate(EvaluationType.COMMUNICATE).reward
        covered = {RewardType.DB, RewardType.ENV_ASSERTION, RewardType.COMMUNICATE}
        if not needs_judge:
            # ALL is inference-free only when its NL-assertion branch has no assertions.
            overall = evaluate(EvaluationType.ALL).reward
            covered = required
    return environment_reward, {
        "termination_complete": complete,
        "native_task_reward": overall,
        "native_communicate_reward": communication_reward,
        "required_reward_basis": sorted(basis.value for basis in required),
        "unassessed_reward_basis": sorted(basis.value for basis in required - covered),
        "nl_assertion_count": len(criteria.nl_assertions or []),
        "nl_judge_called": False,
        "simulator_fidelity": "not-independently-validated",
    }


def main() -> None:
    from research.harness.tau_pilot import VENDOR, check_source

    parser = argparse.ArgumentParser(description="Zero-inference native retail scorer controls.")
    parser.add_argument("--tasks", nargs="+", required=True)
    parser.add_argument("--split", choices=["train", "test"], default="train")
    args = parser.parse_args()
    check_source()
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")
    from loguru import logger
    from tau2.domains.retail.environment import get_tasks

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    tasks = {task.id: task for task in get_tasks(args.split)}
    if len(set(args.tasks)) != len(args.tasks) or not set(args.tasks) <= tasks.keys():
        parser.error(f"Use distinct task IDs from the official {args.split} split only.")
    reports = []
    failed = False
    for task_id in args.tasks:
        try:
            reports.append({"status": "validated", **preflight_task(tasks[task_id])})
        except ValueError as error:
            failed = True
            reports.append(
                {
                    "status": "reference-preflight-failed",
                    "task_id": task_id,
                    "model_calls": 0,
                    "error": str(error),
                }
            )
    print(json.dumps(reports, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
