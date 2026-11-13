from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from research.tau_copilot import parse_recorded_action
from research.native_scoring import preflight_task
from research.tau_pilot import VENDOR, check_source


def replay(journal: Path, task_id: str) -> dict[str, object]:
    check_source()
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")
    from pydantic import TypeAdapter
    from tau2.data_model.message import AssistantMessage, Message
    from tau2.domains.retail.environment import get_environment, get_tasks
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator

    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    starts = {row["call_id"]: row for row in rows if row["event"] == "copilot-request-started"}
    replies = [
        row
        for row in rows
        if row["event"] == "copilot-response-received"
        and starts[row["call_id"]].get("response_schema") is not None
    ]
    if not replies:
        raise ValueError("No recorded structured agent reply exists.")
    last = replies[-1]
    prompt = json.loads(starts[last["call_id"]]["prompt"])
    messages = TypeAdapter(list[Message]).validate_python(prompt["messages"])
    environment = get_environment()
    action = parse_recorded_action(
        last["response"], {tool.name for tool in environment.get_tools()}
    )
    if action["kind"] != "message":
        raise ValueError(
            "The final action is a tool; its resulting observation is not recorded. Do not invent it."
        )
    messages.append(AssistantMessage(role="assistant", content=action["content"]))
    task = next((item for item in get_tasks("train") if item.id == task_id), None)
    if task is None or task.evaluation_criteria is None:
        raise ValueError("Use an official development task with explicit criteria.")
    preflight = preflight_task(task)
    if not preflight["reference_changes_db"]:
        raise ValueError(
            "This reference has no nontrivial DB change; do not present no-action matching as task success."
        )
    reward = EnvironmentEvaluator.calculate_reward(get_environment, task, messages)
    return {
        "mode": "post-hoc-partial-trajectory-db-check",
        "task_id": task_id,
        "model_calls": 0,
        "observed_messages_replayed": len(messages),
        "reference_actions_validated": preflight["reference_actions_validated"],
        "reference_changes_db": preflight["reference_changes_db"],
        "partial_db_match": reward.db_check.db_match if reward.db_check else None,
        "official_task_completion": None,
        "limitations": [
            "Replays actual recorded actor history plus the recorded final assistant message.",
            "No terminal user reply is invented, no model is called, and no complete task pass is claimed.",
            "Policy/communication assertions and user-simulator fidelity are not certified by this check.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-inference native replay of a capped development trajectory."
    )
    parser.add_argument("journal", type=Path)
    parser.add_argument("--task", default="0")
    args = parser.parse_args()
    print(json.dumps(replay(args.journal, args.task), indent=2))


if __name__ == "__main__":
    main()
