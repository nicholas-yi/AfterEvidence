from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO, TypeVar

from research import RESEARCH

ROOT = RESEARCH
VENDOR = ROOT / "vendor" / "tau2-bench"
PIN = json.loads((ROOT / "locks" / "benchmark-lock.json").read_text(encoding="utf-8"))["commit"]


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)


def check_source() -> None:
    revision = subprocess.check_output(
        ["git", "-C", str(VENDOR), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(VENDOR), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    ).strip()
    if revision != PIN or dirty:
        raise ValueError("Benchmark checkout differs from the pinned unmodified source.")


class Journal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream: TextIO = path.open("x", encoding="utf-8", newline="\n")
        self.calls = 0

    def write(self, event: str, **fields: object) -> None:
        self.stream.write(canonical({"event": event, **fields}) + "\n")
        self.stream.flush()

    def close(self) -> None:
        self.stream.close()


def run(task_ids: tuple[str, ...], model: str, seed: int, max_steps: int, output: Path) -> int:
    check_source()
    if output.exists() or output.with_suffix(".calls.jsonl").exists():
        raise ValueError("Output already exists; choose a fresh path.")
    if model not in {"qwen3.5:4b", "qwen3.5:9b"}:
        raise ValueError("Only the explicitly installed stock local Qwen models are permitted.")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")

    from litellm.exceptions import APIError
    from loguru import logger
    from pydantic import BaseModel, ValidationError
    from tau2.agent.base_agent import ValidAgentInputMessage
    from tau2.agent.llm_agent import LLMAgent, LLMAgentState
    from tau2.data_model.message import AssistantMessage, UserMessage
    from tau2.data_model.semantic_communication import CommunicateScorer, CommunicateScoring
    from tau2.domains.retail.environment import get_environment, get_tasks
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    from tau2.orchestrator.modes import CommunicationMode
    from tau2.orchestrator.orchestrator import Orchestrator
    from tau2.user.user_simulator import UserSimulator
    from tau2.user.user_simulator_base import UserState, ValidUserInputMessage

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    native_tasks = {task.id: task for task in get_tasks("train")}
    if (
        not task_ids
        or len(set(task_ids)) != len(task_ids)
        or not set(task_ids) <= native_tasks.keys()
    ):
        raise ValueError("Pilot uses distinct task IDs from the official train split only.")
    arguments = {
        "api_base": "http://127.0.0.1:11434",
        "temperature": 0,
        "max_tokens": 512,
        "num_ctx": 16384,
        "think": False,
        "presence_penalty": 0,
        "timeout": 180,
        "num_retries": 0,
        "seed": seed,
    }
    journal = Journal(output.with_suffix(".calls.jsonl"))
    results: list[dict[str, object]] = []
    started = time.monotonic()
    journal.write(
        "configuration",
        benchmark_commit=PIN,
        model=model,
        model_args=arguments,
        split="train",
        task_ids=task_ids,
        max_steps=max_steps,
        scoring="native ENV only; no NL judge; not full official reward",
    )

    InputT = TypeVar("InputT", bound=BaseModel)
    StateT = TypeVar("StateT", LLMAgentState, UserState)
    ResponseT = TypeVar("ResponseT", AssistantMessage, UserMessage)
    failures = (APIError, ValidationError, ValueError, TypeError, OSError, RuntimeError)

    def record(
        actor: str,
        message: InputT,
        state: StateT,
        invoke: Callable[[InputT, StateT], tuple[ResponseT, StateT]],
    ) -> tuple[ResponseT, StateT]:
        journal.calls += 1
        call_id = journal.calls
        messages = [item.model_dump(mode="json") for item in state.system_messages + state.messages]
        incoming = message.model_dump(mode="json")
        journal.write(
            "call-started",
            call_id=call_id,
            actor=actor,
            incoming=incoming,
            history=messages,
            input_sha256=hashlib.sha256(canonical([messages, incoming]).encode()).hexdigest(),
        )
        before = time.monotonic()
        try:
            response, next_state = invoke(message, state)
        except failures as error:
            journal.write(
                "call-failed",
                call_id=call_id,
                actor=actor,
                error_type=type(error).__name__,
                error=str(error),
                seconds=time.monotonic() - before,
            )
            raise
        journal.write(
            "call-completed",
            call_id=call_id,
            actor=actor,
            response=response.model_dump(mode="json"),
            seconds=time.monotonic() - before,
        )
        return response, next_state

    class ObservedAgent(LLMAgent):
        def generate_next_message(
            self, message: ValidAgentInputMessage, state: LLMAgentState
        ) -> tuple[AssistantMessage, LLMAgentState]:
            return record("agent", message, state, super().generate_next_message)

    class ObservedUser(UserSimulator):
        def generate_next_message(
            self, message: ValidUserInputMessage, state: UserState
        ) -> tuple[UserMessage, UserState]:
            return record("user-simulator", message, state, super().generate_next_message)

    try:
        for task_id in task_ids:
            task = native_tasks[task_id]
            env = get_environment()
            agent = ObservedAgent(
                tools=env.get_tools(),
                domain_policy=env.get_policy(),
                llm="ollama_chat/" + model,
                llm_args=arguments,
            )
            user = ObservedUser(
                llm="ollama_chat/" + model, instructions=str(task.user_scenario), llm_args=arguments
            )
            orchestrator = Orchestrator(
                domain="retail",
                agent=agent,
                user=user,
                environment=env,
                task=task,
                seed=seed,
                max_steps=max_steps,
                max_errors=3,
                timeout=600,
            )
            journal.write("task-started", task_id=task_id)
            print(
                f"Native retail task {task_id}: starting real local user/agent/tool interaction.",
                flush=True,
            )
            try:
                simulation = orchestrator.run()
                reward = evaluate_simulation(
                    simulation,
                    task,
                    EvaluationType.ENV,
                    solo_mode=False,
                    domain="retail",
                    mode=CommunicationMode.HALF_DUPLEX,
                    communicate_scoring=CommunicateScoring(
                        scorer=CommunicateScorer.SUBSTRING, judge=None
                    ),
                )
                simulation.reward_info = reward
                result: dict[str, object] = {
                    "task_id": task_id,
                    "status": "scored",
                    "native_env_reward": reward.reward,
                    "termination": str(simulation.termination_reason),
                    "trajectory": simulation.model_dump(mode="json"),
                    "full_official_reward": None,
                    "task_has_nl_assertions": bool(
                        task.evaluation_criteria and task.evaluation_criteria.nl_assertions
                    ),
                }
                print(
                    f"Task {task_id}: ENV reward={reward.reward}; termination={simulation.termination_reason}",
                    flush=True,
                )
            except failures as error:
                result = {
                    "task_id": task_id,
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                print(f"Task {task_id}: FAILED {type(error).__name__}: {error}", flush=True)
            results.append(result)
            journal.write("task-completed", **result)
            report = {
                "mode": "native-tau2-retail-feasibility",
                "benchmark_commit": PIN,
                "model": model,
                "seed": seed,
                "model_args": arguments,
                "max_steps": max_steps,
                "split": "train",
                "results": results,
                "model_calls_started": journal.calls,
                "seconds": time.monotonic() - started,
                "external_spend_usd": 0,
                "limitations": [
                    "Feasibility only; no memory-method comparison or preregistered main outcome.",
                    "Native ENV reward is not the full official reward; NL and communication judges are not run.",
                    "Agent and user simulator share the local Qwen model; simulator fidelity is not independently established.",
                ],
            }
            output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    finally:
        journal.close()
    return 0 if all(item["status"] == "scored" for item in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Real native benchmark feasibility; no cloud model calls."
    )
    parser.add_argument("--tasks", nargs="+", required=True)
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.max_steps <= 60 or not 0 <= args.seed < 2**32:
        parser.error("Use 1-60 max steps and an unsigned 32-bit seed.")
    try:
        return run(tuple(args.tasks), args.model, args.seed, args.max_steps, args.output)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
