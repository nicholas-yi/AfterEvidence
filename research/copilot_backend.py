from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path
from typing import Any, TextIO

from copilot import CopilotClient
from copilot.client import RuntimeConnection
from copilot.generated.session_events import AssistantMessageData
from copilot.generated.rpc import AccountGetQuotaRequest, PermissionDecisionReject
from copilot.session import PermissionInvocation, PermissionRequest
from pydantic import BaseModel


def data_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {str(key): data_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [data_value(item) for item in value]
    return value


def isolated_client() -> CopilotClient:
    configured = os.environ.get("AFTEREVIDENCE_COPILOT_RUNTIME")
    if configured:
        runtime = Path(configured).expanduser().resolve()
    else:
        local_data = os.environ.get("LOCALAPPDATA")
        if os.name != "nt" or local_data is None:
            raise RuntimeError(
                "Set AFTEREVIDENCE_COPILOT_RUNTIME to the verified matching SDK runtime."
            )
        runtime = (
            Path(local_data)
            / "github-copilot-sdk"
            / "cli"
            / "1.0.111-0"
            / "prebuilds"
            / "win32-x64"
            / "copilot-runtime.exe"
        )
    if not runtime.is_file():
        raise RuntimeError(
            "The pinned, checksum-verified Copilot 1.0.111-0 runtime is not installed."
        )
    base = Path(__file__).parent / "cache" / "copilot-isolated"
    base.mkdir(parents=True, exist_ok=True)
    return CopilotClient(
        connection=RuntimeConnection.for_stdio(path=str(runtime)),
        working_directory=str(base),
        use_logged_in_user=True,
        log_level="error",
        mode="copilot-cli",
    )


async def quota_snapshot(client: CopilotClient):
    return await client.rpc.account.get_quota(AccountGetQuotaRequest())


# Owner rule (2026-11-17): research usage must stay inside the included allowance, never overage.
QUOTA_FLOOR_PERCENT = 50.0


def quota_problem(snapshot: Any) -> str | None:
    """Why no inference may start, or None: premium quota unknown, any overage, or under the floor."""
    quota = snapshot.quota_snapshots.get("premium_interactions")
    if quota is None:
        return "Premium quota unavailable; no inference permitted."
    if (getattr(quota, "overage", 0) or 0) > 0:
        return "Premium usage is already in overage; no inference permitted."
    if quota.remaining_percentage < QUOTA_FLOOR_PERCENT:
        return f"Premium quota below {QUOTA_FLOOR_PERCENT:.0f}% remaining; no inference permitted."
    return None


class CopilotBackend:
    max_request_limit = 30

    def __init__(
        self,
        client: CopilotClient,
        model: str,
        working_directory: Path,
        journal: TextIO,
        request_limit: int = 3,
    ):
        if not 1 <= request_limit <= self.max_request_limit:
            raise ValueError(
                f"This backend allows 1-{self.max_request_limit} model requests per instance."
            )
        self.client = client
        self.model = model
        self.directory = working_directory.resolve()
        self.journal = journal
        self.limit = request_limit
        self.calls = 0
        self.last_metrics: object = None
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: object) -> None:
        self.journal.write(
            json.dumps({"event": event, **fields}, sort_keys=True, default=str) + "\n"
        )
        self.journal.flush()

    async def complete(
        self,
        system: str,
        prompt: str,
        response_schema: type[BaseModel] | dict[str, Any] | None = None,
    ) -> str:
        if self.calls >= self.limit:
            raise PilotRequestLimit(f"Pilot stopped at its explicit {self.limit}-request cap.")
        self.calls += 1
        call_id = self.calls
        schema = (
            response_schema.model_json_schema()
            if isinstance(response_schema, type)
            else response_schema
        )
        self.write(
            "copilot-request-started",
            call_id=call_id,
            model=self.model,
            system=system,
            prompt=prompt,
            response_schema=schema,
        )

        def deny_permission(
            _request: PermissionRequest, _invocation: PermissionInvocation
        ) -> PermissionDecisionReject:
            return PermissionDecisionReject(
                feedback="This benchmark adapter permits no host or built-in tool actions."
            )

        session = await self.client.create_session(
            on_permission_request=deny_permission,
            client_name="afterevidence-research",
            model=self.model,
            system_message={"mode": "replace", "content": system},
            available_tools=[],
            mcp_servers={},
            custom_agents=[],
            skill_directories=[],
            disabled_skills=["*"],
            working_directory=str(self.directory),
            enable_config_discovery=False,
            infinite_sessions={"enabled": False},
            streaming=False,
            memory={"enabled": False},
            session_limits={"max_ai_credits": 30},
            skip_custom_instructions=True,
            enable_session_store=False,
            enable_skills=False,
            enable_file_hooks=False,
            enable_host_git_operations=False,
            skip_embedding_retrieval=True,
        )
        usage: list[object] = []

        def event_handler(event):
            if event.type.value in {"assistant.usage", "session.usage_info"}:
                usage.append(data_value(event.data))

        session.on(event_handler)
        try:
            response = await session.send_and_wait(
                prompt, timeout=120, response_schema=response_schema
            )
            if response is None or not isinstance(response.data, AssistantMessageData):
                raise RuntimeError("Copilot did not return a final assistant message.")
            text = response.data.content
            self.write("copilot-response-received", call_id=call_id, response=text, usage=usage)
            metrics = await session.rpc.usage.get_metrics()
            self.last_metrics = data_value(metrics)
            self.write("copilot-request-completed", call_id=call_id, metrics=self.last_metrics)
            return text
        except (TimeoutError, asyncio.CancelledError):
            await session.abort()
            self.write(
                "copilot-request-aborted",
                call_id=call_id,
                billing="usage may be incomplete; do not assume zero",
            )
            raise
        finally:
            await session.disconnect()


class PilotRequestLimit(RuntimeError):
    """The explicitly authorized number of inference requests was reached."""


async def quota_and_models() -> None:
    client = isolated_client()
    try:
        await asyncio.wait_for(client.start(), timeout=45)
        quota = await asyncio.wait_for(quota_snapshot(client), timeout=20)
        models = await asyncio.wait_for(client.list_models(), timeout=20)
        summaries = []
        for model in models:
            value = data_value(model)
            if not isinstance(value, dict):
                raise RuntimeError("Model list has an unsupported shape.")
            summaries.append(
                {
                    key: value[key]
                    for key in ("id", "name", "billing", "capabilities")
                    if key in value
                }
            )
        print(
            json.dumps(
                {"quota": data_value(quota), "models": summaries, "model_prompts_sent": 0},
                indent=2,
                default=str,
            )
        )
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(quota_and_models())
