from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import time
from pathlib import Path

from research import RESEARCH
from research.harness.copilot_backend import (
    CopilotBackend,
    data_value,
    isolated_client,
    quota_snapshot,
)
from research.harness.tau_pilot import check_source


async def run(output: Path, model: str) -> None:
    check_source()
    if output.exists():
        raise ValueError("Micro-pilot output exists; choose a fresh path.")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["TAU2_DATA_DIR"] = str(RESEARCH / "vendor" / "tau2-bench" / "data")
    from tau2.domains.retail.environment import get_environment, get_tasks
    from tau2.user.user_simulator import UserSimulator

    task = next(item for item in get_tasks("train") if item.id == "0")
    environment = get_environment()
    user_prompt = UserSimulator(
        llm="unused-no-provider-call", instructions=str(task.user_scenario)
    ).system_prompt
    output.parent.mkdir(parents=True, exist_ok=True)
    client = isolated_client()
    try:
        await asyncio.wait_for(client.start(), timeout=45)
        with output.open("x", encoding="utf-8", newline="\n") as journal:
            models = await client.list_models()
            selected = next((item for item in models if item.id == model), None)
            if selected is None or (
                selected.policy is not None and selected.policy.state != "enabled"
            ):
                raise ValueError("Selected model is not enabled for this Copilot account.")
            backend = CopilotBackend(
                client, model, output.parent / "isolated-copilot", journal, request_limit=3
            )
            before = await quota_snapshot(client)
            backend.write(
                "quota-before",
                quota=data_value(before),
                sdk=importlib.metadata.version("github-copilot-sdk"),
                runtime=data_value(await client.get_status()),
                purpose="three requests only; not a scored episode",
            )
            backend.write(
                "selected-model",
                metadata=data_value(selected),
                per_request_ai_credit_cap=30,
                cap_reason="The pinned runtime rejects smaller session limits; three requests remain the total cap.",
            )
            quota = before.quota_snapshots.get("premium_interactions")
            if quota is None or quota.remaining_percentage < 1:
                raise RuntimeError("Quota unavailable or below 1%; no model prompt will be sent.")
            started = time.monotonic()
            print("Micro-pilot 1/3: native retail user-simulator opening.", flush=True)
            opening = await backend.complete(user_prompt, "Hi! How can I help you today?")
            tool_schemas = [tool.openai_schema for tool in environment.get_tools()]
            system = (
                "You are a customer service agent in a benchmark. Follow the supplied policy. "
                "Output one JSON object with kind='message' and content, OR kind='tool' with name and arguments. "
                "Use only the supplied tool names and documented arguments. Do not execute anything yourself. "
                "Do not combine a message and a tool request.\nPOLICY:\n" + environment.get_policy()
            )
            agent_input = json.dumps({"tools": tool_schemas, "user": opening}, ensure_ascii=True)
            print(
                "Micro-pilot 2/3: native-policy action selection, no hidden task goals.", flush=True
            )
            response = await backend.complete(system, agent_input)
            payload: object = json.loads(
                response.strip().removeprefix("```json").removesuffix("```").strip()
            )
            if not isinstance(payload, dict) or payload.get("kind") not in {"message", "tool"}:
                raise ValueError("Agent returned a malformed benchmark action.")
            feedback: dict[str, object] = {}
            if payload["kind"] == "tool":
                name, arguments = payload.get("name"), payload.get("arguments")
                if (
                    not isinstance(name, str)
                    or name not in {tool.name for tool in environment.get_tools()}
                    or not isinstance(arguments, dict)
                ):
                    raise ValueError("Agent returned an unsupported tool action.")
                observation = environment.make_tool_call(name, **arguments)
                feedback = {"tool": name, "arguments": arguments, "observation": observation}
            else:
                content = payload.get("content")
                if not isinstance(content, str) or not content:
                    raise ValueError("Agent message has no content.")
            if payload["kind"] == "tool":
                print("Micro-pilot 3/3: follow-up using the actual tool observation.", flush=True)
                await backend.complete(
                    system,
                    json.dumps(
                        {
                            "tools": tool_schemas,
                            "user": opening,
                            "previous_action": payload,
                            "feedback": feedback,
                        },
                        default=str,
                    ),
                )
            else:
                print(
                    "Micro-pilot 3/3: native user-simulator reply to the agent's question.",
                    flush=True,
                )
                await backend.complete(user_prompt, str(payload["content"]))
            after = await quota_snapshot(client)
            backend.write(
                "quota-after",
                quota=data_value(after),
                calls=backend.calls,
                seconds=time.monotonic() - started,
                official_task_score=None,
            )
            print(
                json.dumps(
                    {
                        "calls": backend.calls,
                        "seconds": time.monotonic() - started,
                        "quota_after": data_value(after),
                        "official_task_score": None,
                    },
                    indent=2,
                    default=str,
                )
            )
    finally:
        await client.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Three-request included-allowance Copilot pilot.")
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output, args.model))
