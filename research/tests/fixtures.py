"""Fixtures built on the pinned benchmark: a prepared setup, a scripted fake actor, and actions."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from research.harness.commitment_pilot import (
    EVAL_STAGE,
    OPENING,
    RUNS,
    prepare,
    run_session,
)
from research.harness.copilot_backend import PilotRequestLimit
from research.tests.support import BENCHMARK, billed, require

require(*BENCHMARK)

SETUP = prepare()
FAMILY = SETUP["families"]["C2"]
TARGET = next(v for v in FAMILY["alternatives"] if v["item_id"] == FAMILY["target_id"])
OTHER = next(v for v in FAMILY["alternatives"] if v["item_id"] != FAMILY["target_id"])


def act(name: str | None = None, text: str = "", **arguments: Any) -> str:
    if name is None:
        return json.dumps({"kind": "message", "value": text, "arguments_json": "{}"})
    return json.dumps({"kind": "tool", "value": name, "arguments_json": json.dumps(arguments)})


class FakeBackend:
    """Scripted actor with CopilotBackend's request cap and journal events."""

    def __init__(self, replies: list[str], limit: int = 12) -> None:
        self.replies, self.limit, self.calls, self.systems = list(replies), limit, 0, []

    def write(self, event: str, **fields: object) -> None:
        pass

    async def complete(self, system: str, prompt: str, response_schema: Any = None) -> str:
        if self.calls >= self.limit:
            raise PilotRequestLimit("cap")
        self.calls += 1
        self.systems.append(system + prompt)
        return (
            self.replies.pop(0)
            if self.replies
            else act("get_user_details", user_id=FAMILY["user_id"])
        )


def proposal(variant: dict[str, Any]) -> str:
    return act(text=f"I can exchange it for item {variant['item_id']}. Shall I proceed (yes/no)?")


def exchange(item_id: str) -> str:
    return act(
        "exchange_delivered_order_items",
        order_id=FAMILY["order_id"],
        item_ids=[FAMILY["current"]["item_id"]],
        new_item_ids=[item_id],
        payment_method_id=FAMILY["payment_id"],
    )


def session(
    arm: str, replies: list[str], limit: int = 12, history: str | None = None
) -> tuple[dict, FakeBackend]:
    job = {"session": 2, "family": "C2", "arm": arm}
    backend = FakeBackend(replies, limit)
    return asyncio.run(run_session(backend, SETUP, job, history)), backend


class SdkTransportError(Exception):
    """Stands in for copilot._jsonrpc.JsonRpcError (same module root, plain Exception base)."""


SdkTransportError.__module__ = "copilot._jsonrpc"


class JournalingBackend(FakeBackend):
    """Fake actor that journals like CopilotBackend: TIMEOUT aborts; TRANSPORT leaves no record."""

    def __init__(self, replies: list[str], journal: Any) -> None:
        super().__init__(replies)
        self.journal = journal

    def write(self, event: str, **fields: object) -> None:
        self.journal.write(json.dumps({"event": event, **fields}) + "\n")
        self.journal.flush()

    async def complete(self, system: str, prompt: str, response_schema: Any = None) -> str:
        if self.calls >= self.limit:
            raise PilotRequestLimit("cap")
        self.calls += 1
        self.write("copilot-request-started", call_id=self.calls)
        reply = self.replies.pop(0) if self.replies else act(text="Anything else?")
        if reply == "TIMEOUT":
            self.write("copilot-request-aborted", call_id=self.calls)
            raise TimeoutError("Copilot response exceeded 150 seconds.")
        if reply == "TRANSPORT":
            raise ConnectionError("transport closed")
        if reply == "CREDENTIAL":  # the SDK's JSON-RPC error type is not an OSError or ValueError
            raise SdkTransportError("GitHub CLI token lookup timed out after 5 seconds")
        self.write("copilot-response-received", call_id=self.calls)
        self.journal.write(json.dumps(billed(self.calls)) + "\n")
        return reply


REAL_EVAL = RUNS / EVAL_STAGE


def _first_session_source(root: Path, families: dict[str, Any]) -> Path:
    """Synthetic frozen 1a/1b reports (agreements on X then Y) for dry passes."""
    for name, f in families.items():
        for arm, item in (("S1a", f["stale_id"]), ("S1b", f["target_id"])):
            messages = [
                {"role": "assistant", "content": OPENING},
                {"role": "user", "content": "Please don't make the exchange today."},
                {"role": "assistant", "content": f"Agreed item {item}."},
            ]
            report = {
                "session": 1,
                "family": name,
                "arm": arm,
                "commitment": True,
                "messages": messages,
            }
            (root / f"{name}-s1-{arm}-a1.json").write_text(json.dumps(report), encoding="utf-8")
    return root


def _features_policy(
    families: dict[str, Any],
    seen: list[dict[str, Any]],
    systems: dict[str, str],
    plan_for: dict[str, str],
) -> Any:
    """Actor per arm: 'Y' executes Y, 'X' executes X, 'ask' asks which item then executes Y,
    'decline' never acts."""

    class Policy(FakeBackend):
        def write(self, event: str, **fields: object) -> None:
            if event != "commitment-session-started":
                return
            job = {k: fields[k] for k in ("session", "family", "arm")}
            seen.append(job)
            self.key = f"{job['family']}-{job['arm']}"
            f = families[str(job["family"])]
            x, y = f["stale_id"], f["target_id"]

            def execute(item: str) -> list[str]:
                return [
                    act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                    act(
                        "exchange_delivered_order_items",
                        order_id=f["order_id"],
                        item_ids=[f["current"]["item_id"]],
                        new_item_ids=[item],
                        payment_method_id=f["payment_id"],
                    ),
                    act(text="The exchange has been processed."),
                ]

            if job["session"] == 1:
                self.replies = (
                    [act(text="Options."), act(text=f"Item {x}: is that the one?")]
                    if job["arm"] == "S1a"
                    else [act(text=f"Item {y}: is that the one?")]
                )
                return
            kind = plan_for[str(job["arm"])]
            self.replies = {
                "Y": execute(y),
                "X": execute(x),
                "ask": [act(text="Which item did we agree on last time?"), *execute(y)],
                "decline": [act(text="I can't act on that without the exact item.")] * 12,
            }[kind]

        async def complete(self, system: str, prompt: str, response_schema: Any = None) -> str:
            systems.setdefault(getattr(self, "key", ""), system)
            return await super().complete(system, prompt, response_schema)

    return Policy


def stage3_policy(
    families: dict[str, Any],
    plan_for: dict[str, str],
    seen: list[Any],
    prompts: dict[str, list[str]],
) -> Any:
    """A fake actor per (family, arm) plan: execute Y, decline, or ask the memory tool first."""
    from research.harness.commitment_pilot import MEMORY_TOOL

    class Policy(FakeBackend):
        def write(self, event: str, **fields: object) -> None:
            if event != "commitment-session-started":
                return
            self.key = f"{fields['family']}-{fields['arm']}"
            seen.append(self.key)
            f = families[str(fields["family"])]
            y = f["target_id"]
            execute = [
                act(text=f"I can exchange it for item {y}. Shall I proceed?"),
                act(
                    "exchange_delivered_order_items",
                    order_id=f["order_id"],
                    item_ids=[f["current"]["item_id"]],
                    new_item_ids=[y],
                    payment_method_id=f["payment_id"],
                ),
                act(text="The exchange has been processed."),
            ]
            recall = act(MEMORY_TOOL, question="Which exchange did this customer agree last?")
            self.replies = {
                "Y": execute,
                "decline": [act(text="I can't act without the exact item.")] * 12,
                "recall": [recall, *execute],
                "recall3": [recall, recall, recall, *execute],
            }[plan_for[str(fields["arm"])]]

        async def complete(self, system: str, prompt: str, response_schema: Any = None) -> str:
            prompts.setdefault(getattr(self, "key", ""), []).append(system + prompt)
            return await super().complete(system, prompt, response_schema)

    return Policy
