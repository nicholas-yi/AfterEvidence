from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import os
import time
from pathlib import Path
from typing import Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field

from research.copilot_backend import (
    CopilotBackend,
    PilotRequestLimit,
    data_value,
    isolated_client,
    quota_snapshot,
)
from research.native_scoring import preflight_task, score_episode
from research.tau_pilot import PIN, VENDOR, check_source


class MessageAction(TypedDict):
    kind: Literal["message"]
    content: str


class ToolAction(TypedDict):
    kind: Literal["tool"]
    name: str
    arguments: dict[str, object]


# Historical wire shapes are retained only for recorded-journal replay.
class WireAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["message", "tool"]
    content: str
    name: str
    arguments_json: str

    def native(self, tool_names: set[str]) -> MessageAction | ToolAction:
        if self.kind == "message":
            if self.name or self.arguments_json not in {"", "{}"}:
                raise ValueError("A message action cannot also request a tool.")
            return parse_action(
                json.dumps({"kind": "message", "content": self.content}), tool_names
            )
        if self.content:
            raise ValueError("A tool action cannot also contain a user message.")
        return parse_action(
            json.dumps(
                {
                    "kind": "tool",
                    "name": self.name,
                    "arguments": json.loads(self.arguments_json),
                }
            ),
            tool_names,
        )


class MessageWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["message"]
    content: str


class ToolWire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["tool"]
    name: str
    arguments_json: str


class ActionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: MessageWire | ToolWire

    def native(self, tool_names: set[str]) -> MessageAction | ToolAction:
        if isinstance(self.action, MessageWire):
            value = {"kind": "message", "content": self.action.content}
        else:
            value = {
                "kind": "tool",
                "name": self.action.name,
                "arguments": json.loads(self.action.arguments_json),
            }
        return parse_action(json.dumps(value), tool_names)


class WireCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["message", "tool"]
    value: str = Field(min_length=1, pattern=r"\S")
    arguments_json: str = Field(min_length=2)

    def native(self, tool_names: set[str]) -> MessageAction | ToolAction:
        arguments = json.loads(self.arguments_json)
        if self.kind == "message":
            if arguments != {}:
                raise ValueError("A message action cannot also request tool arguments.")
            value = {"kind": "message", "content": self.value}
        else:
            value = {"kind": "tool", "name": self.value, "arguments": arguments}
        return parse_action(json.dumps(value), tool_names)


def parse_recorded_action(text: str, tool_names: set[str]) -> MessageAction | ToolAction:
    value = json.loads(text)
    if isinstance(value, dict) and set(value) == {"action"}:
        return ActionEnvelope.model_validate(value).native(tool_names)
    if isinstance(value, dict) and set(value) == {"kind", "value", "arguments_json"}:
        return WireCommand.model_validate(value).native(tool_names)
    return WireAction.model_validate(value).native(tool_names)


def parse_action(text: str, tool_names: set[str]) -> MessageAction | ToolAction:
    cleaned = text.strip().removeprefix("```json").removesuffix("```").strip()
    value: object = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Agent action must be a JSON object.")
    if value.get("kind") == "message":
        if (
            set(value) != {"kind", "content"}
            or not isinstance(value["content"], str)
            or not value["content"].strip()
        ):
            raise ValueError("Message actions require only kind and nonempty content.")
        return {"kind": "message", "content": value["content"]}
    elif value.get("kind") == "tool":
        if set(value) != {"kind", "name", "arguments"}:
            raise ValueError("Tool actions require exactly kind, name, and arguments.")
        name, arguments = value["name"], value["arguments"]
        if not isinstance(name, str) or name not in tool_names or not isinstance(arguments, dict):
            raise ValueError("Unknown tool or invalid tool arguments.")
        if not all(isinstance(key, str) for key in arguments):
            raise ValueError("Tool argument names must be strings.")
        return {"kind": "tool", "name": name, "arguments": dict(arguments)}
    else:
        raise ValueError("Agent action kind must be message or tool.")


async def run(output: Path, task_id: str, model: str, request_limit: int, max_steps: int) -> int:
    check_source()
    if output.exists() or output.with_suffix(".calls.jsonl").exists():
        raise ValueError("Output exists; choose a fresh path before any model calls.")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")
    from loguru import logger
    from tau2.agent.llm_agent import LLMAgent, LLMAgentState
    from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, UserMessage
    from tau2.domains.retail.environment import get_environment, get_tasks
    from tau2.orchestrator.orchestrator import Orchestrator
    from tau2.user.user_simulator import UserSimulator
    from tau2.user.user_simulator_base import UserState

    logger.remove()
    logger.add(lambda message: print(message, end="", flush=True), level="WARNING")
    task = next((item for item in get_tasks("train") if item.id == task_id), None)
    if task is None:
        raise ValueError("Development feasibility permits only the official train split.")
    preflight = await asyncio.to_thread(preflight_task, task)
    output.parent.mkdir(parents=True, exist_ok=True)
    client = isolated_client()
    loop = asyncio.get_running_loop()
    try:
        await client.start()
        models = await client.list_models()
        selected = next((item for item in models if item.id == model), None)
        if selected is None or (selected.policy is not None and selected.policy.state != "enabled"):
            raise ValueError("Model is not enabled for this Copilot account.")
        with output.with_suffix(".calls.jsonl").open(
            "x", encoding="utf-8", newline="\n"
        ) as journal:
            backend = CopilotBackend(
                client, model, output.parent / "isolated-copilot", journal, request_limit
            )
            before = await quota_snapshot(client)
            quota = before.quota_snapshots.get("premium_interactions")
            if quota is None or quota.remaining_percentage < 1:
                raise RuntimeError("Quota unavailable or below 1%; no inference permitted.")
            env = get_environment()
            schemas = [tool.openai_schema for tool in env.get_tools()]
            names = {tool.name for tool in env.get_tools()}
            system = (
                "You are a customer service agent. Follow the supplied current policy. "
                "Each turn return exactly one JSON action: "
                '{"kind":"message","value":"nonempty message for the customer","arguments_json":"{}"} OR '
                '{"kind":"tool","value":"one supplied tool name","arguments_json":"JSON-encoded argument object"}. '
                "The value field is required and nonempty for both action kinds. "
                "Do not combine a message and tool call. Use only supplied tools and documented arguments. "
                "Always verify current customer information; do not assume past customers' facts apply.\n"
                "POLICY:\n" + env.get_policy()
            )

            def invoke(instructions: str, prompt: str, structured: bool = False) -> str:
                future = asyncio.run_coroutine_threadsafe(
                    backend.complete(instructions, prompt, WireCommand if structured else None),
                    loop,
                )
                try:
                    return future.result(timeout=150)
                except concurrent.futures.TimeoutError:
                    future.cancel()
                    raise TimeoutError("Copilot benchmark response exceeded 150 seconds.")

            class Agent(LLMAgent):
                def _generate_next_message(self, message, state: LLMAgentState) -> AssistantMessage:
                    if isinstance(message, MultiToolMessage):
                        state.messages.extend(message.tool_messages)
                    else:
                        state.messages.append(message)
                    prompt = json.dumps(
                        {
                            "tools": schemas,
                            "messages": [item.model_dump(mode="json") for item in state.messages],
                        },
                        default=str,
                    )
                    text = invoke(system, prompt, structured=True)
                    value = WireCommand.model_validate_json(text).native(names)
                    if value["kind"] == "message":
                        return AssistantMessage(role="assistant", content=value["content"])
                    tool = next(item for item in env.get_tools() if item.name == value["name"])
                    arguments = tool.params.model_validate(value["arguments"]).model_dump()
                    return AssistantMessage(
                        role="assistant",
                        content=None,
                        tool_calls=[
                            ToolCall(
                                id=f"study_call_{backend.calls}",
                                name=tool.name,
                                arguments=arguments,
                                requestor="assistant",
                            ),
                        ],
                    )

            class User(UserSimulator):
                def _generate_next_message(self, message, state: UserState) -> UserMessage:
                    if isinstance(message, MultiToolMessage):
                        state.messages.extend(message.tool_messages)
                    else:
                        state.messages.append(message)
                    prompt = json.dumps(
                        {"messages": [item.model_dump(mode="json") for item in state.flip_roles()]},
                        default=str,
                    )
                    return UserMessage(role="user", content=invoke(self.system_prompt, prompt))

            agent = Agent(
                tools=env.get_tools(),
                domain_policy=env.get_policy(),
                llm="copilot-json-adapter",
                llm_args={},
            )
            user = User(
                llm="copilot-user-adapter", instructions=str(task.user_scenario), llm_args={}
            )
            orchestrator = Orchestrator(
                "retail",
                agent,
                user,
                env,
                task,
                max_steps=max_steps,
                max_errors=3,
                seed=42,
                timeout=600,
            )
            backend.write(
                "study-pilot-started",
                benchmark_commit=PIN,
                task_id=task_id,
                model_metadata=data_value(selected),
                quota=data_value(before),
                condition="none",
                request_limit=request_limit,
                preflight=preflight,
                limitations="Custom JSON-action Copilot adapter; native scoring; pending NL assertions are not judged.",
            )
            started = time.monotonic()
            try:
                simulation = await asyncio.to_thread(orchestrator.run)
                reward, assessment = await asyncio.to_thread(score_episode, simulation, task)
                simulation.reward_info = reward
                report: dict[str, object] = {
                    "status": "scored" if assessment["termination_complete"] else "incomplete",
                    "native_env_reward": reward.reward,
                    "termination": str(simulation.termination_reason),
                    "simulation": simulation.model_dump(mode="json"),
                    "full_official_reward": None,
                    "assessment": assessment,
                }
            except (ValueError, RuntimeError, TypeError, OSError) as error:
                report = {
                    "status": "budget-capped" if isinstance(error, PilotRequestLimit) else "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "partial_observed_messages": [
                        message.model_dump(mode="json") for message in orchestrator.get_messages()
                    ],
                }
            report.update(
                {
                    "mode": "native-retail-copilot-development",
                    "benchmark_commit": PIN,
                    "task_id": task_id,
                    "condition": "none",
                    "model": model,
                    "requests_started": backend.calls,
                    "request_limit": request_limit,
                    "preflight": preflight,
                    "seconds": time.monotonic() - started,
                    "quota_before": data_value(before),
                    "quota_after": data_value(await quota_snapshot(client)),
                    "full_official_reward": None,
                }
            )
            output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
            print(
                json.dumps(
                    {
                        key: value
                        for key, value in report.items()
                        if key not in {"simulation", "partial_observed_messages"}
                    },
                    indent=2,
                )
            )
            return 0 if report["status"] == "scored" else 1
    finally:
        await client.stop()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One real development conversation; requires explicit Copilot allowance authorization."
    )
    parser.add_argument("--task", default="0")
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.requests <= 30 or not 1 <= args.max_steps <= 60:
        parser.error("Use 1-30 model requests and 1-60 orchestrator steps for a development pilot.")
    return asyncio.run(run(args.output, args.task, args.model, args.requests, args.max_steps))


if __name__ == "__main__":
    raise SystemExit(main())
