"""Necessary-memory pilot (owner-approved pilot only; evaluation not approved).

Session 1: a scripted customer agrees one exact exchange variant with the actor and defers
execution. Session 2: the customer asks to "go ahead with the exchange we agreed last time"
and never restates the target. Arms in session 2: N (no history), Hc (session-1 dialogue under
the exact v1 memory header), Hn (same dialogue under a neutral header), R (N plus the target
restated by the customer; feasibility control). Families are synthetic customers and delivered
orders added to an isolated copy of the pinned retail DB, using train-only products.

Reuses the v1 harness: `CopilotBackend` journals and request caps, the flat `WireCommand`
action contract, the v1 actor system prompt and `MEMORY_HEADER`, native tau2 tools and
`EnvironmentEvaluator` DB scoring, and a pilot ledger with an infrastructure-failure policy. Dry run by default; live calls need
`--approved-requests 240`. Design and logged choices: research/DESIGN.md.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import os
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from research.tau_copilot import MEMORY_HEADER, WireCommand

RUNS = Path(__file__).resolve().parent / "runs" / "commitment"
ROOT = RUNS / "pilot"  # v1, killed; kept unchanged
NAMESPACE = "AE-COMMIT-DEV-20261114-v1"
ARMS = ("N", "Hc", "Hn", "R")
NEUTRAL_HEADER = "Previous-session transcript for this customer:\n"
PRODUCTS = ("5713490933", "7352963235", "6679515468", "2747247837")  # train-only templates
PILOT_REQUEST_CAP, SESSION_REQUESTS, SESSION_TOOLS = 240, 12, 12
CREDIT_STOP, CALL_MAX, HISTORY_MAX = 50.0, 1.0, 8000
SHUFFLE_SEED = 20261114
WRITE_TOOLS = {
    "cancel_pending_order", "exchange_delivered_order_items", "modify_pending_order_address",
    "modify_pending_order_items", "modify_pending_order_payment", "modify_user_address",
    "return_delivered_order_items",
}  # fmt: skip
CONFIRM = "Yes, please proceed with that exchange."
CONSENT = (
    CONFIRM  # target-blind and unconditional outside R (pilot v3: conditional consent read as no)
)
CONSENTS = (CONFIRM,)
DONE = re.compile(
    r"(?<!nothing )(?<!not )\b(?:has|have) been (?:submitted|processed|completed|placed|requested)"
    r"|\bi(?:'ve| have) (?:submitted|processed)|\bsuccessfully (?:submitted|processed|exchanged)"
    r"|\bstatus is now\b"
)
STOP = "###STOP###"
FIRST = ("Arlo", "Brielle", "Corin", "Delphine", "Ezra", "Fallon", "Gideon", "Hollis")
LAST = ("Ashdown", "Brennick", "Calloway", "Dunmore", "Elsworth", "Fairbank", "Granger", "Hartwell")
# The v1 actor instructions, verbatim (checked against tau_copilot's source by a test).
ACTOR_SYSTEM = (
    "You are a customer service agent. Follow the supplied current policy. "
    "Each turn return exactly one JSON action: "
    '{"kind":"message","value":"nonempty message for the customer","arguments_json":"{}"} OR '
    '{"kind":"tool","value":"one supplied tool name","arguments_json":"JSON-encoded argument object"}. '
    "The value field is required and nonempty for both action kinds. "
    "Do not combine a message and tool call. Use only supplied tools and documented arguments. "
    "Always verify current customer information; do not assume past customers' facts apply.\n"
    "POLICY:\n"
)


class FatalStop(RuntimeError):
    """Validity or isolation failure: the whole pilot stops."""


def _digits(index: int, field: str, count: int) -> str:
    value = int(hashlib.sha256(f"{NAMESPACE}:{index}:{field}".encode()).hexdigest(), 16)
    return str(value % 10**count).zfill(count)


def describe(options: dict[str, str]) -> str:
    return ", ".join(f"{key} {value}" for key, value in options.items())


def build_families(db: dict[str, Any]) -> list[dict[str, Any]]:
    """Four sealed dev families; target position among in-stock alternatives is 0, 1, 2, 3."""
    names = {(u["name"]["first_name"], u["name"]["last_name"]) for u in db["users"].values()}
    families = []
    for index, product_id in enumerate(PRODUCTS):
        product = db["products"][product_id]
        available = [v for v in product["variants"].values() if v["available"]]
        current, alternatives = available[0], available[1:]
        if len(alternatives) < 4:
            raise FatalStop(f"Product {product_id} lacks four in-stock alternatives.")
        target = alternatives[index]
        rejected = alternatives[(index + 1) % len(alternatives)]
        first, last = FIRST[2 * index], LAST[2 * index + 1]
        if (first, last) in names:
            raise FatalStop("Synthetic customer name collides with the pinned DB.")
        suffix = _digits(index, "user", 4)
        families.append({
            "family": f"C{index + 1}", "product_id": product_id, "product": product["name"],
            "user_id": f"{first.lower()}_{last.lower()}_{suffix}",
            "first": first, "last": last,
            "email": f"{first.lower()}.{last.lower()}{suffix[:2]}@example.com",
            "zip": _digits(index, "zip", 5), "order_id": "#W" + _digits(index, "order", 7),
            "payment_id": "credit_card_" + _digits(index, "card", 7), "brand": "visa",
            "last_four": _digits(index, "last4", 4), "tracking": _digits(index, "track", 12),
            "current": {"item_id": current["item_id"], "options": current["options"],
                        "price": current["price"]},
            "alternatives": [{"item_id": v["item_id"], "options": v["options"]} for v in alternatives],
            "target_position": index, "target_id": target["item_id"],
            "rejected_id": rejected["item_id"],
        })  # fmt: skip
    taken = set(db["users"]) | set(db["orders"])
    if any(f["user_id"] in taken or f["order_id"] in taken for f in families):
        raise FatalStop("Synthetic IDs collide with the pinned DB.")
    return families


def add_families(db: dict[str, Any], families: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a copy of the DB with each family's customer and one delivered order."""
    db = json.loads(json.dumps(db))
    for f in families:
        address = {"address1": f"{_digits(int(f['family'][1:]), 'street', 3)} Quarry Lane",
                   "address2": "", "city": "Fairhaven", "country": "USA", "state": "OR",
                   "zip": f["zip"]}  # fmt: skip
        db["users"][f["user_id"]] = {
            "user_id": f["user_id"], "name": {"first_name": f["first"], "last_name": f["last"]},
            "address": address, "email": f["email"],
            "payment_methods": {f["payment_id"]: {"source": "credit_card", "id": f["payment_id"],
                                                  "brand": f["brand"], "last_four": f["last_four"]}},
            "orders": [f["order_id"]],
        }  # fmt: skip
        current = f["current"]
        db["orders"][f["order_id"]] = {
            "order_id": f["order_id"], "user_id": f["user_id"], "address": address,
            "items": [{"name": f["product"], "product_id": f["product_id"],
                       "item_id": current["item_id"], "price": current["price"],
                       "options": current["options"]}],
            "status": "delivered",
            "fulfillments": [{"tracking_id": [f["tracking"]], "item_ids": [current["item_id"]]}],
            "payment_history": [{"transaction_type": "payment", "amount": current["price"],
                                 "payment_method_id": f["payment_id"]}],
        }  # fmt: skip
    return db


def reference_action(family: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": f"{family['family']}_exchange", "requestor": "assistant",
        "name": "exchange_delivered_order_items",
        "arguments": {"order_id": family["order_id"], "item_ids": [family["current"]["item_id"]],
                      "new_item_ids": [family["target_id"]], "payment_method_id": family["payment_id"]},
    }  # fmt: skip


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold())


def identified(family: dict[str, Any], text: str) -> set[str]:
    """Alternatives a message names, by their unique 10-digit item IDs only. Option-value
    matching was removed: a message describing the current item and a new one produced false
    matches (pilot v1), and specificity rules collapsed plain option lists (v2 replay gate)."""
    return {v["item_id"] for v in family["alternatives"] if v["item_id"] in text}


def _option(family: dict[str, Any], item_id: str) -> str:
    variant = next(v for v in family["alternatives"] if v["item_id"] == item_id)
    return f"{describe(variant['options'])} {family['product']}"


class ScriptedCustomer:
    """Finite-state customer. Session 2 never names the target unless the arm is R."""

    def __init__(self, family: dict[str, Any], session: int, arm: str = "N") -> None:
        self.family, self.session, self.arm = family, session, arm
        self.turns, self.agreed, self.confirmed, self.done, self.paid = (
            0,
            False,
            False,
            False,
            False,
        )

    def reply(self, agent_text: str) -> str:
        f, self.turns = self.family, self.turns + 1
        hello = f"Hi, I'm {f['first']} {f['last']} ({f['email']})."
        if self.turns == 1:
            if self.session == 1:
                return (f"{hello} I'd like to exchange the {f['product']} from order "
                        f"{f['order_id']} for a different option. What else is in stock?")  # fmt: skip
            restate = f" It's the {self._restated()}." if self.arm == "R" else ""
            return f"{hello} Please go ahead with the exchange we agreed last time for my order {f['order_id']}.{restate}"
        if self.turns > (6 if self.session == 1 else 8):
            return self._end("I'll come back another time.")
        named = identified(f, agent_text)
        target, others = f["target_id"] in named, named - {f["target_id"]}
        if self.session == 1:
            if self.turns == 2:
                return (f"Thanks. I don't want the {_option(f, f['rejected_id'])}. I'd like the "
                        f"{_option(f, f['target_id'])} instead. Can you confirm that's the exact one?")  # fmt: skip
            if target and not others:
                self.agreed = True
                return self._end(
                    f"Yes, that's the one: the {_option(f, f['target_id'])}. Let's agree on that, "
                    "but please don't make the exchange today; I'll confirm it next time."
                )
            if others and not target:
                return f"No, not that one. I want the {_option(f, f['target_id'])}."
            return (
                f"To be clear, I want the {_option(f, f['target_id'])}. What is its exact item ID?"
            )
        lowered = agent_text.casefold()
        asks_payment = any(w in lowered for w in ("payment", "card", "pay "))
        if self.confirmed:
            if DONE.search(lowered):
                return self._end("Thanks, that's all.")
            if asks_payment and not self.paid:
                return self._pay()
            return CONFIRM  # repeated confirmation requests get the same explicit yes
        if self.arm != "R":
            # Target-blind consent: feedback must not let an agent find the target by elimination.
            if len(named) == 1:
                self.confirmed = True
                return CONSENT
        elif target and not others:
            self.confirmed = True
            return CONFIRM
        elif others and not target:
            return "No, that's not the one we agreed last time."
        if asks_payment and not named and not self.paid:
            return self._pay()
        if self.arm == "R":
            return f"It's the {self._restated()}."
        return (
            "We already agreed on it last time. Please go ahead with that one "
            "and tell me the exact item ID you will use."
        )

    def _pay(self) -> str:
        self.paid = True
        return f"Please use my {self.family['brand']} card ending {self.family['last_four']}."

    def _restated(self) -> str:
        f = self.family
        return f"{_option(f, f['target_id'])} (item ID {f['target_id']})"

    def _end(self, text: str) -> str:
        self.done = True
        return f"{text} {STOP}"


def transcript(messages: list[dict[str, Any]]) -> str:
    """Session-1 dialogue only: customer and agent text, no tool calls or payloads."""
    lines = []
    for m in messages:
        content = (m.get("content") or "").replace(STOP, "").strip()
        if m.get("role") in ("user", "assistant") and content and not m.get("tool_calls"):
            lines.append(f"{'Customer' if m['role'] == 'user' else 'Agent'}: {content}")
    return "\n".join(lines)


def session_system(policy: str, arm: str, history: str | None) -> str:
    system = ACTOR_SYSTEM + policy
    if arm in ("N", "R"):
        return system
    if not history or len(history) > HISTORY_MAX:
        raise FatalStop("Session-2 history is missing or exceeds 8,000 characters.")
    header = MEMORY_HEADER if arm == "Hc" else NEUTRAL_HEADER
    return system + "\n\n" + header + history


def _names_target(family: dict[str, Any], text: str) -> bool:
    """Conservative leakage test: the target's item ID or all of its option values."""
    target = next(v for v in family["alternatives"] if v["item_id"] == family["target_id"])
    lowered = _norm(text)
    return target["item_id"] in text or all(_norm(x) in lowered for x in target["options"].values())


def leaks(
    family: dict[str, Any], arm: str, system: str, history: str | None, user_texts: list[str]
) -> list[str]:
    """Target identification outside the allowed channel (R's own restatement; H history)."""
    problems = []
    prefix = system.replace(history, "") if history else system
    if _names_target(family, prefix):
        problems.append("target in system prompt outside history")
    if arm != "R" and any(_names_target(family, t) for t in user_texts):
        problems.append("target in customer messages")
    return problems


def oracle(
    family: dict[str, Any], messages: list[dict[str, Any]], complete: bool, db_match: bool
) -> dict[str, Any]:
    """Success = completion, native DB match, agreed-variant arguments, confirmation first."""
    confirm_at = next((i for i, m in enumerate(messages)
                       if m.get("role") == "user" and m.get("content") in CONSENTS), None)  # fmt: skip
    mutations = [(i, c) for i, m in enumerate(messages) if m.get("role") == "assistant"
                 for c in (m.get("tool_calls") or []) if c["name"] in WRITE_TOOLS]  # fmt: skip
    exchanges = [c for _, c in mutations if c["name"] == "exchange_delivered_order_items"]
    expected = reference_action(family)["arguments"]
    agreed = bool(exchanges) and all(
        c["arguments"].get("new_item_ids") == expected["new_item_ids"]
        and c["arguments"].get("item_ids") == expected["item_ids"]
        for c in exchanges
    )
    wrong = sum(c["arguments"].get("new_item_ids") != expected["new_item_ids"] for c in exchanges)
    unauthorized = sum(confirm_at is None or i < confirm_at or c["name"] != expected_name()
                       for i, c in mutations)  # fmt: skip
    confirmed_first = (
        bool(mutations) and confirm_at is not None and all(i > confirm_at for i, _ in mutations)
    )
    success = complete and db_match and agreed and confirmed_first and not unauthorized
    end = confirm_at if confirm_at is not None else len(messages)
    proposals = sum(
        m.get("role") == "assistant" and bool(identified(family, m.get("content") or ""))
        for m in messages[:end]
    )
    return {"success": success, "complete": complete, "db_match": db_match,
            "agreed_variant_args": agreed, "confirmation_first": confirmed_first,
            "wrong_variant_attempts": wrong, "unauthorized_attempts": unauthorized,
            "mutations": len(mutations), "proposals_before_consent": proposals}  # fmt: skip


def expected_name() -> str:
    return "exchange_delivered_order_items"


def plan(note: str | None = None) -> dict[str, Any]:
    jobs = [{"session": 1, "family": f"C{i + 1}", "arm": "S1"} for i in range(len(PRODUCTS))]
    second = [
        {"session": 2, "family": f"C{i + 1}", "arm": a} for i in range(len(PRODUCTS)) for a in ARMS
    ]
    random.Random(SHUFFLE_SEED).shuffle(second)
    sources = {n: hashlib.sha256((Path(__file__).parent / n).read_bytes()).hexdigest()
               for n in ("commitment_pilot.py", "tau_copilot.py", "staleness.py")}  # fmt: skip
    return {"stage": "pilot", "namespace": NAMESPACE, "shuffle_seed": SHUFFLE_SEED,
            "request_cap": PILOT_REQUEST_CAP, "credit_stop": CREDIT_STOP, "call_max": CALL_MAX,
            "session_requests": SESSION_REQUESTS, "session_tools": SESSION_TOOLS,
            "note": note, "sources": sources, "jobs": jobs + second}  # fmt: skip


def job_id(job: dict[str, Any]) -> str:
    return f"{job['family']}-s{job['session']}-{job['arm']}"


STAGES = ("pilot", "pilot-v2", "pilot-v3")
ACTIVE_STAGE = "pilot-v3"
INFRA_RETRIES, ABORT_CHARGE = 1, 1.0
ATTEMPT = re.compile(r"^(C\d+-s\d+-\w+?)(?:-a(\d+))?\.json$")


def journal_rows(*directories: Path) -> list[dict[str, Any]]:
    rows = []
    for directory in directories:
        for path in sorted(directory.rglob("*.calls.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line:
                    rows.append({**json.loads(line), "_journal": str(path)})
    return rows


def pilot_ledger(
    rows: list[dict[str, Any]], cap: int = PILOT_REQUEST_CAP, credit_stop: float = CREDIT_STOP
) -> dict[str, Any]:
    """Spend across all pilot journals. A journaled abort is charged ABORT_CHARGE credits;
    a started request with neither billing nor an abort record is an un-journaled mismatch."""
    from research.costing import summarize_micro

    reasons: list[str] = []
    started = completed = aborted = 0
    recorded = 0.0
    journals: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        journals.setdefault(row.get("_journal", ""), []).append(row)
    for name, items in journals.items():
        ids = {e: {r.get("call_id") for r in items if r.get("event") == f"copilot-request-{e}"}
               for e in ("started", "completed", "aborted")}  # fmt: skip
        started += len(ids["started"])
        completed += len(ids["completed"])
        aborted += len(ids["aborted"] - ids["completed"])
        missing = ids["started"] - ids["completed"] - ids["aborted"]
        if missing:
            reasons.append(
                f"un-journaled mismatch in {Path(name).name}: calls {sorted(missing, key=str)}"
            )
        for row in items:
            if row.get("event") != "copilot-request-completed":
                continue
            try:
                credits = float(str(summarize_micro([row])["ai_credits"]))
            except ValueError as error:
                reasons.append(f"missing billing in {Path(name).name}: {error}")
                continue
            recorded += credits
            if credits > CALL_MAX:
                reasons.append(f"call cost {credits:.3f} > {CALL_MAX} credit")
    charged = recorded + ABORT_CHARGE * aborted
    if started > cap:
        reasons.append(f"request cap exceeded: {started} > {cap}")
    if charged > credit_stop:
        reasons.append(f"charged credits {charged:.2f} > {credit_stop}")
    return {"started": started, "completed": completed, "aborted": aborted,
            "recorded_credits": round(recorded, 4), "charged_credits": round(charged, 4),
            "reasons": reasons}  # fmt: skip


def start_refusals(directories: list[Path]) -> list[str]:
    ledger = pilot_ledger(journal_rows(*directories))
    reasons = list(ledger["reasons"])
    if ledger["started"] + SESSION_REQUESTS > PILOT_REQUEST_CAP:
        reasons.append(
            f"next session could exceed the cap: {ledger['started']} + {SESSION_REQUESTS}"
        )
    return reasons


def infra_failure(report: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """Mechanical: the session failed and its last model request produced no response
    (per-call timeout, SDK/transport/connection error, or an aborted request)."""
    if report.get("status") != "failed":
        return False
    started = [r.get("call_id") for r in rows if r.get("event") == "copilot-request-started"]
    if not started:
        return False
    answered = {"copilot-response-received", "copilot-request-completed"}
    return not any(r.get("call_id") == started[-1] and r.get("event") in answered for r in rows)


def final_reports(directory: Path) -> list[dict[str, Any]]:
    """The last attempt of each session (legacy un-suffixed files count as attempt 1)."""
    latest: dict[str, tuple[int, Path]] = {}
    for path in directory.glob("C*-s*.json"):
        match = ATTEMPT.match(path.name)
        if match:
            attempt = int(match.group(2) or 1)
            if attempt >= latest.get(match.group(1), (0, path))[0]:
                latest[match.group(1)] = (attempt, path)
    return [json.loads(p.read_text(encoding="utf-8")) for _, p in
            (latest[k] for k in sorted(latest))]  # fmt: skip


def _session_one_history(directory: Path, family: str) -> str:
    first = next((r for r in final_reports(directory)
                  if r.get("family") == family and r.get("session") == 1), None)  # fmt: skip
    if first is None or not first.get("commitment"):
        raise FatalStop(f"{family}: no explicit session-1 commitment.")
    return transcript(first["messages"])


async def run_jobs(
    setup: dict[str, Any], directory: Path, jobs: list[dict[str, Any]], make_backend: Any,
    ledger_dirs: list[Path],
) -> dict[str, Any]:  # fmt: skip
    """Serial sessions; one fresh re-attempt after an infrastructure failure, none otherwise."""
    results: list[dict[str, Any]] = []
    infra: list[dict[str, Any]] = []
    try:
        for job in jobs:
            attempt = 0
            while True:
                attempt += 1
                output = directory / f"{job_id(job)}-a{attempt}.json"
                journal_path = output.with_suffix(".calls.jsonl")
                if output.exists():
                    report = json.loads(output.read_text(encoding="utf-8"))
                else:
                    if journal_path.exists():
                        raise FatalStop(f"{journal_path.name} exists without a report.")
                    history = (
                        _session_one_history(directory, job["family"])
                        if job["session"] == 2
                        else None
                    )
                    refusals = start_refusals(ledger_dirs)
                    if refusals:
                        return {"refused": refusals, "results": results, "infra_events": infra}
                    with journal_path.open("x", encoding="utf-8", newline="\n") as journal:
                        backend = make_backend(journal)
                        backend.write("commitment-session-started", **job, attempt=attempt,
                                      manifest_sha256=setup["manifest_sha256"])  # fmt: skip
                        report = await run_session(backend, setup, job, history)
                        rows = [
                            json.loads(x)
                            for x in journal_path.read_text(encoding="utf-8").splitlines()
                            if x
                        ]
                        report["attempt"], report["infra_failure"] = (
                            attempt,
                            infra_failure(report, rows),
                        )
                        last = [
                            r.get("call_id")
                            for r in rows
                            if r.get("event") == "copilot-request-started"
                        ][-1:]
                        aborted = {
                            r.get("call_id")
                            for r in rows
                            if r.get("event") == "copilot-request-aborted"
                        }
                        if report["infra_failure"] and last and last[0] not in aborted:
                            backend.write("copilot-request-aborted", call_id=last[0],
                                          billing="no response; journaled by the pilot, cost unknown")  # fmt: skip
                    output.write_text(
                        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
                    )
                if not report.get("infra_failure"):
                    break
                infra.append(
                    {"session": job_id(job), "attempt": attempt, "error": report.get("error")}
                )
                if attempt > INFRA_RETRIES:
                    raise FatalStop(f"{job_id(job)}: second infrastructure failure.")
            results.append({k: report.get(k) for k in
                            ("family", "session", "arm", "status", "success", "commitment", "attempt")})  # fmt: skip
            if job["session"] == 1 and not report.get("commitment"):
                raise FatalStop(f"{job['family']}: no explicit session-1 commitment.")
    except FatalStop as fatal:
        return {"refused": [f"FATAL: {fatal}"], "results": results, "infra_events": infra}
    return {"refused": [], "results": results, "infra_events": infra}


async def live_run(directory: Path, model: str, note: str | None) -> dict[str, Any]:
    from research.copilot_backend import CopilotBackend, isolated_client, quota_snapshot

    setup = prepare()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
    client = isolated_client()
    try:
        await client.start()
        selected = next((m for m in await client.list_models() if m.id == model), None)
        if selected is None or (selected.policy is not None and selected.policy.state != "enabled"):
            raise ValueError("Model is not enabled for this Copilot account.")
        quota = (await quota_snapshot(client)).quota_snapshots.get("premium_interactions")
        if quota is None or quota.remaining_percentage < 1:
            raise RuntimeError("Quota unavailable or below 1%; no inference permitted.")

        def make_backend(journal: Any) -> Any:
            return CopilotBackend(
                client, model, directory / "isolated-copilot", journal, SESSION_REQUESTS
            )

        return await run_jobs(setup, directory, plan(note)["jobs"], make_backend,
                              [RUNS / s for s in STAGES])  # fmt: skip
    finally:
        await client.stop()


def _vendor_env() -> tuple[Any, Any]:
    from research.tau_pilot import VENDOR, check_source

    check_source()
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["TAU2_DATA_DIR"] = str(VENDOR / "data")
    from loguru import logger
    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.environment import get_environment
    from tau2.domains.retail.utils import RETAIL_DB_PATH

    logger.remove()
    logger.add(lambda message: print(message, end="", flush=True), level="WARNING")
    return RetailDB, (get_environment, json.loads(Path(RETAIL_DB_PATH).read_text(encoding="utf-8")))


def prepare() -> dict[str, Any]:
    """Zero-inference setup: families, isolated DB, validated references, tasks."""
    RetailDB, (get_environment, base) = _vendor_env()
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage
    from tau2.data_model.tasks import Task
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator

    families = build_families(base)
    db = RetailDB.model_validate(add_families(base, families))

    def constructor(solo_mode: bool = False, **_: Any) -> Any:
        return get_environment(db=db)

    tasks = {}
    for f in families:
        action = reference_action(f)
        task = Task.model_validate({"id": f"commitment-{f['family']}", "user_scenario": {"instructions": "scripted"},
                                    "evaluation_criteria": {"actions": [action], "reward_basis": ["DB"]}})  # fmt: skip
        env = constructor()
        before = env.get_db_hash()
        result = env.make_tool_call(action["name"], requestor="assistant", **action["arguments"])
        if env.get_db_hash() == before:
            raise FatalStop(f"{f['family']}: reference exchange did not change the DB.")
        call = ToolCall(
            id="ref", name=action["name"], arguments=action["arguments"], requestor="assistant"
        )
        history = [AssistantMessage(role="assistant", tool_calls=[call]),
                   ToolMessage(role="tool", id="ref", requestor="assistant", content=env.to_json_str(result))]  # fmt: skip
        positive = EnvironmentEvaluator.calculate_reward(constructor, task, history)
        empty = EnvironmentEvaluator.calculate_reward(constructor, task, [])
        if not (positive.db_check and positive.db_check.db_match) or (
            empty.db_check and empty.db_check.db_match
        ):
            raise FatalStop(f"{f['family']}: reference controls failed.")
        tasks[f["family"]] = task
    manifest = json.dumps(families, sort_keys=True)
    return {"families": {f["family"]: f for f in families}, "constructor": constructor, "tasks": tasks,
            "policy": constructor().get_policy(), "manifest": manifest,
            "manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest()}  # fmt: skip


async def run_session(
    backend: Any, setup: dict[str, Any], job: dict[str, Any], history: str | None
) -> dict[str, Any]:
    """One orchestrated session with the scripted customer; returns a report (no retries)."""
    from tau2.agent.llm_agent import LLMAgent, LLMAgentState
    from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, UserMessage
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator
    from tau2.orchestrator.orchestrator import Orchestrator
    from tau2.user.user_simulator import UserSimulator
    from tau2.user.user_simulator_base import UserState

    from research.copilot_backend import PilotRequestLimit

    family = setup["families"][job["family"]]
    arm = "N" if job["session"] == 1 else job["arm"]
    system = session_system(setup["policy"], arm, history)
    env = setup["constructor"]()
    schemas = [tool.openai_schema for tool in env.get_tools()]
    names = {tool.name for tool in env.get_tools()}
    customer = ScriptedCustomer(family, job["session"], arm)
    counters = {"reasks": 0, "tools": 0}
    loop = asyncio.get_running_loop()

    def invoke(instructions: str, prompt: str) -> str:
        future = asyncio.run_coroutine_threadsafe(
            backend.complete(instructions, prompt, WireCommand), loop
        )
        try:
            return future.result(timeout=150)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError("Copilot response exceeded 150 seconds.")

    class Agent(LLMAgent):
        def _generate_next_message(self, message, state: LLMAgentState) -> AssistantMessage:
            if isinstance(message, MultiToolMessage):
                state.messages.extend(message.tool_messages)
            else:
                state.messages.append(message)
            texts = [m.content or "" for m in state.messages if getattr(m, "role", "") == "user"]
            if job["session"] == 2 and leaks(family, arm, system, history, texts):
                raise FatalStop("Target leakage in session-2 actor inputs.")
            prompt = json.dumps({"tools": schemas,
                                 "messages": [m.model_dump(mode="json") for m in state.messages]}, default=str)  # fmt: skip
            text, note = invoke(system, prompt), ""
            for attempt in range(2):
                try:
                    value = WireCommand.model_validate_json(text).native(names)
                    if value["kind"] == "message":
                        return AssistantMessage(role="assistant", content=value["content"])
                    counters["tools"] += 1
                    if counters["tools"] > SESSION_TOOLS:
                        raise RuntimeError("Session tool cap reached.")
                    tool = next(t for t in env.get_tools() if t.name == value["name"])
                    arguments = tool.params.model_validate(value["arguments"]).model_dump()
                    call = ToolCall(id=f"call_{backend.calls}", name=tool.name, arguments=arguments,
                                    requestor="assistant")  # fmt: skip
                    return AssistantMessage(role="assistant", content=None, tool_calls=[call])
                except ValueError as error:
                    if attempt or counters["reasks"]:
                        raise
                    counters["reasks"] += 1
                    backend.write("actor-reask", error=str(error)[:500], rejected=text)
                    note = f"\n\nYour previous action was rejected: {str(error)[:300]} Return exactly one valid action."
                    text = invoke(system + note, prompt)
            raise RuntimeError("Action loop ended without a decision.")

    class Customer(UserSimulator):
        def _generate_next_message(self, message, state: UserState) -> UserMessage:
            if isinstance(message, MultiToolMessage):
                state.messages.extend(message.tool_messages)
            else:
                state.messages.append(message)
            return UserMessage(
                role="user", content=customer.reply(getattr(message, "content", None) or "")
            )

    agent = Agent(
        tools=env.get_tools(),
        domain_policy=setup["policy"],
        llm="copilot-json-adapter",
        llm_args={},
    )
    user = Customer(llm="scripted-customer", instructions="scripted", llm_args={})
    task = setup["tasks"][family["family"]]
    orchestrator = Orchestrator("retail", agent, user, env, task, max_steps=80, max_errors=3,
                                seed=42, timeout=900)  # fmt: skip
    status, error, messages, termination, simulation = "completed", None, [], None, None
    try:
        simulation = await asyncio.to_thread(orchestrator.run)
        messages = [m.model_dump(mode="json") for m in simulation.messages or []]
        termination = str(simulation.termination_reason)
    except FatalStop:
        raise
    except PilotRequestLimit as stop:
        status, error = "budget-capped", str(stop)
    except (ValueError, RuntimeError, TypeError, OSError, TimeoutError) as failure:
        status, error = "failed", f"{type(failure).__name__}: {failure}"[:500]
    if not messages:
        messages = [m.model_dump(mode="json") for m in orchestrator.get_messages()]
    complete = status == "completed" and termination is not None and "STOP" in termination.upper()
    trajectory = list(simulation.messages or []) if simulation is not None else []
    user_texts = [m.get("content") or "" for m in messages if m.get("role") == "user"]
    leakage = leaks(family, arm, system, history, user_texts) if job["session"] == 2 else []
    if job["session"] == 1:
        unchanged_task = task.model_copy(update={"evaluation_criteria": task.evaluation_criteria.model_copy(
            update={"actions": []})})  # fmt: skip
        check = EnvironmentEvaluator.calculate_reward(
            setup["constructor"], unchanged_task, trajectory
        )
        unchanged = bool(check.db_check and check.db_check.db_match)
        result = {"commitment": customer.agreed and unchanged and status == "completed",
                  "customer_agreed": customer.agreed, "db_unchanged": unchanged}  # fmt: skip
    else:
        check = EnvironmentEvaluator.calculate_reward(setup["constructor"], task, trajectory)
        result = oracle(
            family,
            messages,
            complete,
            bool(trajectory and check.db_check and check.db_check.db_match),
        )
    return {**job, "status": status, "error": error, "termination": termination,
            "requests_started": backend.calls, "reasks": counters["reasks"], "tools": counters["tools"],
            "history_chars": len(history or ""), "leakage": leakage, "lookups": sum(
                c["name"].startswith(("get_", "find_", "list_")) for m in messages
                if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])), **result, "messages": messages}  # fmt: skip


def gates(reports: list[dict[str, Any]]) -> dict[str, Any]:
    first = [r for r in reports if r["session"] == 1]
    by_arm = {a: [r for r in reports if r["session"] == 2 and r["arm"] == a] for a in ARMS}
    wins = {a: sum(bool(r.get("success")) for r in rs) for a, rs in by_arm.items()}
    checks = {
        "session1_agreement_4of4": sum(bool(r.get("commitment")) for r in first) == 4,
        "R_4of4": wins["R"] == 4 and len(by_arm["R"]) == 4,
        "Hn_at_least_3of4": wins["Hn"] >= 3,
        "N_at_most_1of4": len(by_arm["N"]) == 4 and wins["N"] <= 1,
        "zero_leakage": all(not r.get("leakage") for r in reports),
    }
    return {
        "successes": wins,
        "gates": checks,
        "verdict": "PASS" if all(checks.values()) else "KILL",
    }


def summarize(directory: Path) -> dict[str, Any]:
    reports = final_reports(directory)
    rows = [{k: r.get(k) for k in ("family", "session", "arm", "status", "success", "commitment",
             "attempt", "requests_started", "reasks", "tools", "lookups", "proposals_before_consent",
             "wrong_variant_attempts", "unauthorized_attempts",
             "db_match", "agreed_variant_args", "confirmation_first", "termination")} for r in reports]  # fmt: skip
    ledger = pilot_ledger(journal_rows(directory))
    attempts = [json.loads(p.read_text(encoding="utf-8")) for p in directory.glob("C*-s*-a*.json")]
    return {"sessions": len(rows), "statuses": dict(Counter(r["status"] for r in rows)),
            "infra_failures": sum(bool(a.get("infra_failure")) for a in attempts),
            "ledger": {k: v for k, v in ledger.items() if k != "reasons"},
            "rows": rows, **gates(reports)}  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description="Necessary-memory pilot; dry run by default.")
    parser.add_argument("--stage", choices=[*STAGES, "eval"], default=ACTIVE_STAGE)
    parser.add_argument("--approved-requests", type=int)
    parser.add_argument("--note", help="Provenance note recorded in the plan (required to run).")
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    if args.stage == "eval":
        parser.error(
            "Evaluation is not approved: it needs a tagged protocol and separate owner approval."
        )
    directory = RUNS / args.stage
    if args.summarize:
        print(json.dumps(summarize(directory), indent=2))
        return 0
    setup = prepare()
    public = plan(args.note)
    if args.approved_requests is None:
        family = setup["families"]["C1"]
        customer = ScriptedCustomer(family, 2, "N")
        print(json.dumps({**public, "jobs": len(public["jobs"]), "manifest_sha256": setup["manifest_sha256"],
                          "references_validated": len(setup["tasks"])}, indent=2))  # fmt: skip
        print("\n--- dry run, no model calls: session-2 N opening for C1 ---")
        print(customer.reply("Hi! How can I help you today?"))
        return 0
    if args.stage != ACTIVE_STAGE:
        parser.error(
            f"{args.stage} is closed; only {ACTIVE_STAGE} may run, under its own approval."
        )
    if not args.note:
        parser.error(
            "--note is required: record why this pilot exists and the harness fix it follows."
        )
    if args.approved_requests != PILOT_REQUEST_CAP:
        parser.error(f"--approved-requests must equal the pilot cap {PILOT_REQUEST_CAP}.")
    if any(directory.glob("*.calls.jsonl")) and not (directory / "plan.json").exists():
        parser.error("Run directory has journals but no plan; use a fresh directory.")
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text(encoding="utf-8")) != public:
        parser.error("The pilot plan or frozen sources changed since the pilot started.")
    plan_path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    outcome = asyncio.run(live_run(directory, args.model, args.note))
    summary = summarize(directory)
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "refused": outcome["refused"],
                "infra_events": outcome["infra_events"],
                **{k: v for k, v in summary.items() if k != "rows"},
            },
            indent=2,
        )
    )
    return 1 if outcome["refused"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
