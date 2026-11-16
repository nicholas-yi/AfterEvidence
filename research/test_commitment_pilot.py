from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research.commitment_pilot import (
    ACTOR_SYSTEM,
    AMEND_HASHES,
    RUNS,
    artifact_problems,
    select_jobs,
    session_one_artifacts,
    EVAL_ARMS,
    EVAL_STAGE,
    PROVIDER_STAGES,
    eval_seed,
    tag_state,
    template_pool,
    HONCHO_WORKSPACE,
    OPENING,
    PROVIDER_ARMS,
    final_reports,
    first_message,
    frozen_inputs,
    provider_gates,
    provider_phase,
    provider_scope,
    retrieve_memories,
    shim_problems,
    BUDGETS,
    PHASE1,
    STAGE_BUDGET,
    CONFIRM,
    CONSENT,
    HISTORY_MAX,
    NEUTRAL_HEADER,
    STOP,
    FatalStop,
    ScriptedCustomer,
    identified,
    journal_rows,
    leaks,
    oracle,
    pilot_ledger,
    plan,
    prepare,
    run_jobs,
    run_session,
    session_system,
    smoke_passed,
    start_refusals,
    transcript,
)
from research.copilot_backend import PilotRequestLimit
from research.tau_copilot import MEMORY_HEADER

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
    return act("exchange_delivered_order_items", order_id=FAMILY["order_id"],
               item_ids=[FAMILY["current"]["item_id"]], new_item_ids=[item_id],
               payment_method_id=FAMILY["payment_id"])  # fmt: skip


def session(
    arm: str, replies: list[str], limit: int = 12, history: str | None = None
) -> tuple[dict, FakeBackend]:
    job = {"session": 2, "family": "C2", "arm": arm}
    backend = FakeBackend(replies, limit)
    return asyncio.run(run_session(backend, SETUP, job, history)), backend


class CommitmentPilotTests(unittest.TestCase):
    def test_headers_history_limit_and_isolation(self) -> None:
        policy = SETUP["policy"]
        self.assertIn("\n\n" + MEMORY_HEADER + "dialogue", session_system(policy, "Hc", "dialogue"))
        self.assertIn(
            "\n\n" + NEUTRAL_HEADER + "dialogue", session_system(policy, "Hn", "dialogue")
        )
        self.assertNotIn("dialogue", session_system(policy, "N", "dialogue"))
        with self.assertRaises(FatalStop):
            session_system(policy, "Hn", "x" * (HISTORY_MAX + 1))

    def test_customer_never_restates_target_except_in_r(self) -> None:
        for arm in ("N", "Hc", "Hn", "R"):
            customer = ScriptedCustomer(FAMILY, 2, arm)
            opening = customer.reply("Hi! How can I help you today?")
            clarify = customer.reply("Which option would you like?")
            named = bool(leaks(FAMILY, "N", "", None, [opening + clarify]))
            self.assertEqual(named, arm == "R", arm)
        customer = ScriptedCustomer(FAMILY, 2, "N")
        customer.reply("hello")
        self.assertEqual(customer.reply(f"Item {OTHER['item_id']}, proceed?"), CONSENT)
        self.assertIn(STOP, customer.reply("The exchange has been processed."))
        restating = ScriptedCustomer(FAMILY, 2, "R")
        restating.reply("hello")
        self.assertIn("not the one", restating.reply(f"Item {OTHER['item_id']}, proceed?"))
        self.assertEqual(restating.reply(f"Item {TARGET['item_id']}, proceed?"), CONFIRM)

    def test_session_two_feedback_is_target_blind_outside_r(self) -> None:
        # Elimination leak: target-dependent consent would let an N agent search IDs one by one.
        for family in SETUP["families"].values():
            ids = [v["item_id"] for v in family["alternatives"]]
            for arm in ("N", "Hc", "Hn"):
                single, multiple = set(), set()
                for item in ids:
                    customer = ScriptedCustomer(family, 2, arm)
                    customer.reply("hello")
                    single.add(customer.reply(f"Shall I exchange it for item {item}?"))
                    self.assertTrue(customer.confirmed)
                    pair = ScriptedCustomer(family, 2, arm)
                    pair.reply("hello")
                    other = ids[(ids.index(item) + 1) % len(ids)]
                    multiple.add(pair.reply(f"Options: item {item} or item {other}?"))
                    self.assertFalse(pair.confirmed)
                self.assertEqual(single, {CONSENT}, (family["family"], arm))
                self.assertEqual(len(multiple), 1, (family["family"], arm))

    def test_session_two_reconfirmation_payment_and_completion(self) -> None:
        # Pilot v3 defects: conditional consent, unanswered re-confirmation, payment loop,
        # future-tense "submitted" read as done, and an R restatement without an item ID.
        customer = ScriptedCustomer(FAMILY, 2, "Hn")
        customer.reply("hello")
        self.assertEqual(
            customer.reply(f"Exchange for item {OTHER['item_id']}? Reply yes."), CONFIRM
        )
        self.assertIn("card ending", customer.reply("Which payment method should I use?"))
        self.assertEqual(
            customer.reply("Once submitted, the status changes. Please reply yes."), CONFIRM
        )
        self.assertEqual(
            customer.reply(
                "I still need an explicit yes; nothing has been submitted. Visa card noted."
            ),
            CONFIRM,
        )
        self.assertFalse(customer.done)
        self.assertIn(STOP, customer.reply("Your exchange has been submitted."))
        self.assertIn(TARGET["item_id"], ScriptedCustomer(FAMILY, 2, "R").reply("hello"))
        lookup = act("find_user_id_by_email", email=FAMILY["email"])
        flow = [lookup, proposal(TARGET), act(text="Which card should I use for the payment?"),
                act(text=f"To confirm: item {TARGET['item_id']}, Visa card. Please reply yes."),
                exchange(TARGET["item_id"]), act(text="Your exchange has been submitted.")]  # fmt: skip
        report, _ = session("Hn", flow, history="Customer: earlier\nAgent: noted")
        self.assertTrue(report["success"] and report["confirmation_first"])

    def test_robustness_sweep_of_agent_confirmation_styles(self) -> None:
        def styles(family: dict, item: str) -> list[list[str]]:
            alt = next(v for v in family["alternatives"] if v["item_id"] == item)
            options = ", ".join(alt["options"].values())
            listing = " ".join(
                f"{v['item_id']}: {', '.join(v['options'].values())}"
                for v in family["alternatives"]
            )
            done = "Your exchange has been submitted."
            return [
                [f"I can exchange it for item {item}. Please reply yes to confirm.", done],
                [f"Item {item}. Reply yes?", f"I still need an explicit yes for item {item}.",
                 "The exchange has been processed."],
                [f"Item {item}. Which card should I use for the payment?",
                 f"Final check: item {item} on your Visa card. Please reply yes.", done],
                [f"Before I submit the exchange to item {item}, please confirm; once submitted it is final.",
                 "I have submitted the exchange."],
                [f"Summary: the {options} option. Shall I proceed?", f"That is item {item}. Reply yes.", done],
                [f"Which would you like? {listing}", f"Proceeding with item {item}? Reply yes.", done],
            ]  # fmt: skip

        for family in SETUP["families"].values():
            ids = [v["item_id"] for v in family["alternatives"]]
            for arm in ("N", "Hc", "Hn", "R"):
                for index in range(6):
                    runs = {}
                    for item in ids:
                        customer = ScriptedCustomer(family, 2, arm)
                        customer.reply("hello")
                        replies = [
                            customer.reply(t)
                            for t in styles(family, item)[index]
                            if not customer.done
                        ]
                        runs[item] = (replies, customer.confirmed, customer.done)
                    key = (family["family"], arm, index)
                    replies, confirmed, done = runs[family["target_id"]]
                    self.assertTrue(confirmed and done and STOP in replies[-1], key)
                    if arm != "R":
                        self.assertEqual(len({json.dumps(r) for r in runs.values()}), 1, key)

    def test_confirmation_listing_the_current_item_is_not_ambiguous(self) -> None:
        # Pilot v1 C2 defect: describing the current item made another alternative match by
        # option values. Matching is now by item ID only; ID-less proposals get an ID request.
        current = ", ".join(FAMILY["current"]["options"].values())
        message = (f"Item to exchange: {current}. New item: "
                   f"{', '.join(TARGET['options'].values())} (item ID {TARGET['item_id']}). Proceed?")  # fmt: skip
        self.assertEqual(identified(FAMILY, message), {TARGET["item_id"]})
        without_id = message.replace(f" (item ID {TARGET['item_id']})", "")
        self.assertEqual(identified(FAMILY, without_id), set())
        listing = " ".join(
            f"{v['item_id']}: {', '.join(v['options'].values())}" for v in FAMILY["alternatives"]
        )
        self.assertEqual(
            identified(FAMILY, listing), {v["item_id"] for v in FAMILY["alternatives"]}
        )
        asking = ScriptedCustomer(FAMILY, 2, "N")
        asking.reply("hello")
        reply = asking.reply(without_id)
        self.assertIn("exact item ID", reply)
        self.assertFalse(leaks(FAMILY, "N", "", None, [reply]))
        customer = ScriptedCustomer(FAMILY, 1)
        customer.reply("hello")
        customer.reply("options")
        self.assertIn("exact item ID", customer.reply(without_id))
        customer.reply(message)
        self.assertTrue(customer.agreed)

    def test_session_one_agreement_and_refusal_branches(self) -> None:
        customer = ScriptedCustomer(FAMILY, 1)
        self.assertIn(FAMILY["order_id"], customer.reply("hello"))
        self.assertIn("I'd like the", customer.reply("Here are the options."))
        self.assertIn("not that one", customer.reply(f"So item {OTHER['item_id']}?"))
        self.assertIn("To be clear", customer.reply("Could you clarify?"))
        self.assertFalse(customer.agreed)
        agreed = customer.reply(f"Confirming item {TARGET['item_id']}.")
        self.assertTrue(customer.agreed and STOP in agreed and "don't make the exchange" in agreed)
        silent = ScriptedCustomer(FAMILY, 1)
        replies = [silent.reply("Could you clarify?") for _ in range(7)]
        self.assertTrue(STOP in replies[-1] and not silent.agreed)

    def test_oracle_cases(self) -> None:
        def run(item_id: str, confirm: bool) -> dict:
            call = {"name": "exchange_delivered_order_items",
                    "arguments": {"item_ids": [FAMILY["current"]["item_id"]], "new_item_ids": [item_id]}}  # fmt: skip
            messages = [{"role": "user", "content": CONFIRM if confirm else "ok"},
                        {"role": "assistant", "tool_calls": [call]}]  # fmt: skip
            return oracle(FAMILY, messages, True, item_id == FAMILY["target_id"])

        self.assertTrue(run(FAMILY["target_id"], True)["success"])
        wrong = run(OTHER["item_id"], True)
        self.assertEqual((wrong["success"], wrong["wrong_variant_attempts"]), (False, 1))
        unconfirmed = run(FAMILY["target_id"], False)
        self.assertEqual((unconfirmed["success"], unconfirmed["unauthorized_attempts"]), (False, 1))

    def test_transcript_keeps_dialogue_only(self) -> None:
        messages = [{"role": "user", "content": f"Hi {STOP}"},
                    {"role": "assistant", "content": None, "tool_calls": [{"name": "x"}]},
                    {"role": "tool", "content": "{payload}"}, {"role": "assistant", "content": "Done."}]  # fmt: skip
        self.assertEqual(transcript(messages), "Customer: Hi\nAgent: Done.")

    def test_orchestrated_sessions_with_fake_actor(self) -> None:
        lookup = act("find_user_id_by_email", email=FAMILY["email"])
        done = act(text="The exchange has been processed.")
        good, _ = session("R", [lookup, proposal(TARGET), exchange(TARGET["item_id"]), done])
        self.assertTrue(good["success"] and good["db_match"] and good["confirmation_first"])
        self.assertEqual(good["leakage"], [])
        wrong, _ = session("N", [lookup, proposal(OTHER), exchange(OTHER["item_id"]), done])
        self.assertFalse(wrong["success"] or wrong["db_match"])
        self.assertEqual(
            (
                wrong["unauthorized_attempts"],
                wrong["wrong_variant_attempts"],
                wrong["proposals_before_consent"],
            ),
            (0, 1, 1),
        )
        rushed, _ = session("N", [lookup, exchange(TARGET["item_id"]), done])
        self.assertEqual((rushed["success"], rushed["unauthorized_attempts"]), (False, 1))
        history = "Customer: earlier\nAgent: noted"
        guarded, backend = session(
            "Hc",
            ["not json", lookup, proposal(TARGET), exchange(TARGET["item_id"]), done],
            history=history,
        )
        self.assertEqual((guarded["reasks"], guarded["success"]), (1, True))
        self.assertIn(MEMORY_HEADER + history, backend.systems[0])
        self.assertNotIn(FAMILY["target_id"], backend.systems[0])
        capped, _ = session("N", [], limit=3)
        self.assertEqual((capped["status"], capped["success"]), ("budget-capped", False))

    def test_leak_detection_and_ledger_refusal(self) -> None:
        system = session_system(SETUP["policy"], "N", None)
        self.assertEqual(leaks(FAMILY, "N", system, None, ["We agreed last time."]), [])
        self.assertTrue(leaks(FAMILY, "N", system, None, [f"Item {TARGET['item_id']} please"]))
        self.assertTrue(leaks(FAMILY, "N", system + TARGET["item_id"], None, []))
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "x.calls.jsonl").write_text(
                '{"event": "copilot-request-started", "call_id": 1}\n', encoding="utf-8"
            )
            self.assertTrue(any(r.startswith("un-journaled") for r in start_refusals([Path(tmp)])))

    def test_v4_budget_is_separate_and_phase_two_needs_smoke(self) -> None:
        self.assertEqual(BUDGETS[STAGE_BUDGET["pilot-v4"]]["stages"], ("pilot-v4",))
        self.assertEqual(plan("n", "pilot-v4")["request_cap"], 264)
        self.assertEqual(plan("n", "pilot-v4")["credit_stop"], 40.0)
        self.assertEqual({(j["family"], j["arm"]) for j in PHASE1},
                         {("C1", "S1"), ("C2", "S1"), ("C1", "R"), ("C2", "R")})  # fmt: skip
        with tempfile.TemporaryDirectory() as tmp:
            for family, ok in (("C1", True), ("C2", False)):
                report = {"session": 2, "family": family, "arm": "R", "success": ok, "attempt": 1}
                Path(tmp, f"{family}-s2-R-a1.json").write_text(json.dumps(report), encoding="utf-8")
            self.assertFalse(smoke_passed(Path(tmp)))
            Path(tmp, "C2-s2-R-a1.json").write_text(
                json.dumps(
                    {"session": 2, "family": "C2", "arm": "R", "success": True, "attempt": 1}
                ),
                encoding="utf-8",
            )
            self.assertTrue(smoke_passed(Path(tmp)))


def billed(call_id: int) -> dict[str, Any]:
    usage = {"usage": {"input_tokens": 1, "output_tokens": 1}, "requests": {"count": 1}}
    return {"event": "copilot-request-completed", "call_id": call_id,
            "metrics": {"ai_credits_status": "complete", "total_nano_aiu": 1e8,
                        "model_metrics": {"m": usage}}}  # fmt: skip


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
        self.write("copilot-response-received", call_id=self.calls)
        self.journal.write(json.dumps(billed(self.calls)) + "\n")
        return reply


class InfrastructurePolicyTests(unittest.TestCase):
    S1 = {"session": 1, "family": "C2", "arm": "S1"}
    AGREE = [
        act(text="Several options are in stock."),
        act(text=f"Confirming item {TARGET['item_id']}."),
    ]

    def run_jobs(self, scripts: list[list[str]], jobs: list[dict], directory: Path) -> dict:
        queue = list(scripts)
        return asyncio.run(run_jobs(SETUP, directory, jobs,
                                    lambda journal: JournalingBackend(queue.pop(0), journal), [directory]))  # fmt: skip

    def test_timeout_and_transport_errors_get_one_fresh_reattempt(self) -> None:
        for failure in ("TIMEOUT", "TRANSPORT"):
            with tempfile.TemporaryDirectory() as tmp:
                result = self.run_jobs([[failure], list(self.AGREE)], [self.S1], Path(tmp))
                self.assertEqual(result["refused"], [], failure)
                self.assertEqual([e["attempt"] for e in result["infra_events"]], [1])
                self.assertTrue(result["results"][0]["commitment"])
                first = json.loads(Path(tmp, "C2-s1-S1-a1.json").read_text(encoding="utf-8"))
                self.assertTrue(first["infra_failure"])
                ledger = pilot_ledger(journal_rows(Path(tmp)))
                self.assertEqual((ledger["aborted"], ledger["reasons"]), (1, []))
                self.assertAlmostEqual(ledger["charged_credits"], ledger["recorded_credits"] + 1.0)

    def test_second_infrastructure_failure_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_jobs([["TIMEOUT"], ["TIMEOUT"]], [self.S1], Path(tmp))
            self.assertIn("second infrastructure failure", result["refused"][0])

    def test_agent_failures_are_never_reattempted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_jobs([["bad", "still bad"], list(self.AGREE)], [self.S1], Path(tmp))
            self.assertIn("no explicit session-1 commitment", result["refused"][0])
            self.assertFalse(Path(tmp, "C2-s1-S1-a2.json").exists())
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_jobs(
                [[act(text="Options?")] * 8, list(self.AGREE)], [self.S1], Path(tmp)
            )
            self.assertIn("no explicit session-1 commitment", result["refused"][0])
            self.assertFalse(Path(tmp, "C2-s1-S1-a2.json").exists())
        with tempfile.TemporaryDirectory() as tmp:
            lookup = act("find_user_id_by_email", email=FAMILY["email"])
            wrong = [
                lookup,
                proposal(OTHER),
                exchange(OTHER["item_id"]),
                act(text="Done, it has been processed."),
            ]
            s2 = {"session": 2, "family": "C2", "arm": "N"}
            result = self.run_jobs([list(self.AGREE), wrong, wrong], [self.S1, s2], Path(tmp))
            self.assertEqual(result["refused"], [])
            self.assertEqual([r["attempt"] for r in result["results"]], [1, 1])
            self.assertFalse(result["results"][1]["success"])

    def test_aborted_is_charged_and_unjournaled_mismatch_stops(self) -> None:
        aborted = [{"event": "copilot-request-started", "call_id": 1, "_journal": "a"},
                   {"event": "copilot-request-aborted", "call_id": 1, "_journal": "a"}]  # fmt: skip
        self.assertEqual(pilot_ledger(aborted)["reasons"], [])
        self.assertEqual(pilot_ledger(aborted)["charged_credits"], 1.0)
        self.assertTrue(pilot_ledger(aborted, credit_stop=0.5)["reasons"])
        silent = [{"event": "copilot-request-started", "call_id": 1, "_journal": "b"}]
        self.assertTrue(pilot_ledger(silent)["reasons"][0].startswith("un-journaled"))


def shim_journal(directory: Path, label: str, cap: int, *rows: dict[str, Any]) -> None:
    (directory / "shims").mkdir(parents=True, exist_ok=True)
    events = [{"event": "shim-started", "label": label, "request_limit": cap}, *rows]
    (directory / "shims" / f"{label}.calls.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )


class ProviderPilotTests(unittest.TestCase):
    """Pilot v5 (Mem0 / Honcho arms) with fake gateways and a scripted fake actor."""

    def test_fresh_scopes_and_gateway_isolation_settings(self) -> None:
        from research import memory_gateway as gateway

        self.assertEqual(provider_scope("C1"), "customer:cmp-p5-C1")
        saved = dict(gateway.CONFIG)
        try:
            gateway.CONFIG.clear()
            gateway.CONFIG.update(honcho_workspace=HONCHO_WORKSPACE, state="fresh")
            self.assertEqual(
                gateway.Mem0Store.owner(provider_scope("C1")), {"user_id": "cmp-p5-C1"}
            )
            honcho = object.__new__(gateway.HonchoStore)
            honcho.clients, honcho.factory = {}, lambda workspace: workspace
            self.assertEqual(honcho.workspace(provider_scope("C1")), HONCHO_WORKSPACE)
            self.assertEqual(gateway.state(), Path("fresh"))
            lines = gateway.turns({"id": "x", "lines": [("customer", "hi")]})
            self.assertEqual(lines, [("customer", "hi")])  # no outcome line for v5 episodes
            gateway.CONFIG.clear()  # absent keys keep the v1 stores
            self.assertEqual(honcho.workspace("customer:z"), "ae-customer")
            self.assertEqual(gateway.state(), gateway.STATE)
        finally:
            gateway.CONFIG.clear()
            gateway.CONFIG.update(saved)

    def test_frozen_inputs_are_the_h_arm_dialogue(self) -> None:
        messages: list[dict[str, Any]] = []
        report: dict[str, Any] = {}
        with tempfile.TemporaryDirectory() as tmp:
            for name in SETUP["families"]:
                messages = [{"role": "assistant", "content": OPENING},
                            {"role": "assistant", "content": None, "tool_calls": [{"name": "get_user_details"}]},
                            {"role": "tool", "content": "payload"},
                            {"role": "user", "content": f"agreed {name} ###STOP###"}]  # fmt: skip
                report = {
                    "session": 1,
                    "family": name,
                    "arm": "S1",
                    "commitment": True,
                    "messages": messages,
                }
                Path(tmp, f"{name}-s1-S1-a1.json").write_text(json.dumps(report), encoding="utf-8")
            inputs = frozen_inputs(Path(tmp))
            text = transcript(messages)
            self.assertEqual(inputs["C4"]["sha256"], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(
                inputs["C4"]["episode"]["lines"], [("agent", OPENING), ("customer", "agreed C4")]
            )
            self.assertNotIn("payload", json.dumps(inputs))
            report["commitment"] = False
            Path(tmp, "C4-s1-S1-a1.json").write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(FatalStop):
                frozen_inputs(Path(tmp))

    def test_query_cap_errors_header_and_sessions(self) -> None:
        policy = SETUP["policy"]
        self.assertTrue(session_system(policy, "M", "memo").endswith(NEUTRAL_HEADER + "memo"))
        self.assertNotIn(MEMORY_HEADER, session_system(policy, "Ho", "memo"))
        self.assertEqual(session_system(policy, "Ho", None), session_system(policy, "N", None))
        with self.assertRaises(FatalStop):
            session_system(policy, "M", "x" * (HISTORY_MAX + 1))
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[tuple[str, str, str]] = []

            def search(provider: str, scope: str, query: str) -> list[str]:
                calls.append((provider, scope, query))
                if provider == "honcho" and scope.endswith("C2"):
                    raise TimeoutError("down")
                return [
                    "x" * 5000,
                    f"item {TARGET['item_id']}" if scope.endswith("C2") else "y" * 5000,
                ]

            records = retrieve_memories(SETUP, Path(tmp), search)
            self.assertEqual(len(calls), 8)
            for name, family in SETUP["families"].items():
                queries = {q for _, scope, q in calls if scope == provider_scope(name)}
                self.assertEqual(queries, {first_message(family, "N")})
            self.assertTrue(all(r["chars"] <= HISTORY_MAX for r in records))
            failed = [r for r in records if r["error"]]
            self.assertEqual([(r["provider"], r["scope"], r["text"]) for r in failed],
                             [("honcho", provider_scope("C2"), "")])  # fmt: skip
            m2 = next(
                r for r in records if r["scope"] == provider_scope("C2") and r["provider"] == "mem0"
            )
            self.assertEqual((m2["has_target_id"], m2["has_target_options"]), (True, False))
            retrieve_memories(SETUP, Path(tmp), lambda *_: self.fail("retrieval repeated"))

            backends: list[FakeBackend] = []

            def make_backend(journal: Any) -> FakeBackend:
                backends.append(FakeBackend([act(text="How can I help?")]))
                return backends[-1]

            jobs = [{"session": 2, "family": "C2", "arm": a} for a in PROVIDER_ARMS]
            outcome = asyncio.run(
                run_jobs(SETUP, Path(tmp), jobs, make_backend, [Path(tmp)], 160, 25.0)
            )
            self.assertEqual(outcome["refused"], [])
            reports = {r["arm"]: r for r in final_reports(Path(tmp))}
            self.assertIn(NEUTRAL_HEADER + "[mem0-1]", backends[0].systems[0])
            self.assertNotIn(NEUTRAL_HEADER, backends[1].systems[0])
            self.assertTrue(reports["Ho"]["memory"]["error"])
            self.assertEqual(reports["Ho"]["history_chars"], 0)
            self.assertNotIn("text", reports["M"]["memory"])
            first_user = next(m["content"] for m in reports["M"]["messages"] if m["role"] == "user")
            self.assertEqual(first_user, m2["query"])
            self.assertEqual((reports["M"]["leakage"], reports["Ho"]["leakage"]), ([], []))

    def test_leakage_outside_memory_block(self) -> None:
        memory = f"The customer agreed item {TARGET['item_id']}."
        system = session_system(SETUP["policy"], "M", memory)
        self.assertEqual(leaks(FAMILY, "M", system, memory, ["We agreed last time."]), [])
        self.assertTrue(leaks(FAMILY, "M", system + TARGET["item_id"], memory, []))
        self.assertTrue(leaks(FAMILY, "Ho", system, memory, [f"Item {TARGET['item_id']}"]))

    def test_ledger_counts_shims_and_shim_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shim_journal(
                root, "mem0", 14, {"event": "copilot-request-started", "call_id": 1}, billed(1)
            )
            shim_journal(root, "honcho", 50)
            self.assertEqual(shim_problems(root), [])
            ledger = pilot_ledger(journal_rows(root), 160, 25.0)
            self.assertEqual((ledger["started"], ledger["recorded_credits"]), (1, 0.1))
            self.assertTrue(start_refusals([root], 12, 25.0))  # 1 shim request + 12 > 12
            shim_journal(root, "honcho", 60)
            self.assertTrue(shim_problems(root))
            shim_journal(
                root, "honcho", 50, {"event": "shim-error", "error": "PilotRequestLimit: cap"}
            )
            self.assertTrue(any("reached" in p for p in shim_problems(root)))

    def test_preflight_refuses_v1_stores_before_any_ingestion(self) -> None:
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            shim_journal(Path(tmp), "mem0", 14)
            shim_journal(Path(tmp), "honcho", 50)
            v1 = {
                "state": "elsewhere",
                "honcho_workspace": "ae-customer",
                "honcho_reasoning_level": "low",
            }
            with mock.patch("research.provider_ingest.post", return_value=v1) as post:
                result = provider_phase(SETUP, Path(tmp), {})
            self.assertEqual(len(result["refused"]), 2)
            self.assertEqual(post.call_count, 1)

    def test_integration_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{"provider": p, "scope": provider_scope(f), "episode": f"cmp-p5-{f}-s1", "status": "ok"}
                    for p in PROVIDER_ARMS.values() for f in SETUP["families"]]  # fmt: skip
            (root / "ingest.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
            )
            (root / "honcho-queue.json").write_text(
                json.dumps({"total": 8, "completed": 8, "pending": 0, "in_progress": 0}),
                encoding="utf-8",
            )
            failing = {"C2"}
            retrieve_memories(SETUP, root, lambda p, s, q: (_ for _ in ()).throw(OSError("x"))
                              if p == "honcho" and s[-2:] in failing else ["memo"])  # fmt: skip
            reports = [{"arm": a, "family": f, "leakage": [], "success": False}
                       for a in PROVIDER_ARMS for f in SETUP["families"]]  # fmt: skip
            self.assertEqual(provider_gates(root, reports)["verdict"], "PASS")
            (root / "memory" / "C3-Ho.json").write_text(
                json.dumps({"provider": "honcho", "error": "OSError: x"}), encoding="utf-8"
            )
            self.assertEqual(provider_gates(root, reports)["verdict"], "FAIL")


class EvaluationTests(unittest.TestCase):
    """Evaluation stage (tag commitment-eval-v1): generation, exclusion, caps, analysis."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.eval_setup = prepare(seed=eval_seed("0" * 40))

    def test_seed_rule_pool_and_fresh_scopes(self) -> None:
        self.assertEqual(eval_seed("abc"), int(hashlib.sha256(b"abc").hexdigest()[:8], 16))
        self.assertIsNone(tag_state("no-such-tag-for-tests"))

        def product(name: str, base: int, available: int = 5) -> dict[str, Any]:
            return {
                "name": name,
                "variants": {str(base + i): {"available": i < available} for i in range(5)},
            }

        db = {
            "products": {
                "1000000001": product("Lamp", 1100000000),
                "1000000002": product("Desk", 1200000000),
                "1000000003": product("Rug", 1300000000, 3),
                "1000000004": product("Pet Bed", 1400000000),
            }
        }
        tasks = {
            "a": "train 1100000000 1200000000 1300000000 1400000000",
            "b": "test 1200000001",
            "c": "test mentions a pet bed",
        }
        self.assertEqual(
            template_pool(db, tasks, {"train": ["a"], "test": ["b", "c"]}), ["1000000001"]
        )
        cfg = PROVIDER_STAGES[EVAL_STAGE]
        self.assertEqual((provider_scope("E01", cfg["prefix"]), cfg["workspace"]),
                         ("customer:cmp-eval-E01", "commitment-eval-v1"))  # fmt: skip
        self.assertEqual(sum(cfg["shim_caps"].values()) + cfg["episode_cap"], 2816)

    def test_thirty_two_balanced_fresh_families(self) -> None:
        families = list(self.eval_setup["families"].values())
        self.assertEqual(len(families), 32)
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        self.assertTrue({f["product_id"] for f in families} <= set(self.eval_setup["pool"]))
        self.assertNotIn(
            "2747247837", self.eval_setup["pool"]
        )  # Pet Bed's name appears in test tasks
        dev = {
            x
            for f in SETUP["families"].values()
            for x in (f["user_id"], f["order_id"], f["payment_id"])
        }
        self.assertFalse(
            dev & {x for f in families for x in (f["user_id"], f["order_id"], f["payment_id"])}
        )
        self.assertEqual(len(self.eval_setup["tasks"]), 32)  # every reference exchange validated
        self.assertEqual(
            prepare(seed=eval_seed("0" * 40))["manifest_sha256"], self.eval_setup["manifest_sha256"]
        )

    def test_exclusion_rule_and_episode_cap(self) -> None:
        family = sorted(self.eval_setup["families"])[0]
        with tempfile.TemporaryDirectory() as tmp:
            jobs = [{"session": 1, "family": family, "arm": "S1"}]
            silent = lambda journal: FakeBackend([act(text="Hello.")] * 12)  # noqa: E731
            outcome = asyncio.run(run_jobs(self.eval_setup, Path(tmp), jobs, silent, [Path(tmp)],
                                           2816, 310.0, 2304, exclude_uncommitted=True))  # fmt: skip
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(
                [r["family"] for r in final_reports(Path(tmp))], [family]
            )  # E-family found
            self.assertEqual(frozen_inputs(Path(tmp), "cmp-eval-", exclude=True), {})
            report = {"session": 1, "family": "E02", "arm": "S1", "commitment": True,
                      "messages": [{"role": "user", "content": "agreed"}]}  # fmt: skip
            Path(tmp, "E02-s1-S1-a1.json").write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(list(frozen_inputs(Path(tmp), "cmp-eval-", exclude=True)), ["E02"])
            with self.assertRaises(FatalStop):
                frozen_inputs(Path(tmp), "cmp-eval-", [family])
            shim_journal(Path(tmp), "honcho", 400, *[e for i in range(1, 21) for e in
                         ({"event": "copilot-request-started", "call_id": i}, billed(i))])  # fmt: skip
            self.assertEqual(
                start_refusals([Path(tmp)], 2816, 310.0, 24), []
            )  # shims not in episode cap
            self.assertTrue(
                start_refusals([Path(tmp)], 2816, 310.0, 11)
            )  # 0 episode requests + 12 > 11
            self.assertTrue(
                start_refusals([Path(tmp)], 31, 310.0, 2304)
            )  # 20 shim requests + 12 > 31

    def test_prespecified_analysis(self) -> None:
        from research.commitment_analysis import analyse

        def row(family: str, arm: str, ok: bool, **memory: Any) -> dict[str, Any]:
            return {"family": family, "session": 2, "arm": arm, "success": ok, "commitment": "",
                    "credits": 0.5, "requests": 6, "lookups": 3, "proposals_before_consent": 1,
                    "wrong_variant_attempts": 0, "unauthorized_attempts": 0, "leakage": False,
                    "memory_error": memory.get("error", ""), "memory_has_target_id": memory.get("has_id", ""),
                    "memory_has_target_options": ""}  # fmt: skip

        rows: list[dict[str, Any]] = []
        for i in range(10):
            f = f"E{i:02d}"
            rows.append(
                {
                    "family": f,
                    "session": 1,
                    "arm": "S1",
                    "commitment": i < 9,
                    "credits": 0.6,
                    "requests": 6,
                }
            )
            rows += [row(f, "N", i == 0), row(f, "Hn", True), row(f, "Hc", i != 1),
                     row(f, "M", i != 2, has_id=i != 3), row(f, "Ho", i < 6, error=i == 8, has_id=i < 4)]  # fmt: skip
        result = analyse(rows, planned_families=10)
        self.assertEqual(
            (result["included"], result["excluded"], result["complete"]), (9, ["E09"], True)
        )
        self.assertEqual(result["arms"]["N"]["successes"], 1)
        self.assertEqual({k: result["primary"][k] for k in ("wins", "losses", "p")},
                         {"wins": 8, "losses": 0, "p": round(2 / 2**8, 4)})  # fmt: skip
        sec = result["secondaries"]
        self.assertEqual((sec["Ho vs Hn"]["losses"], sec["Ho vs Hn"]["p"]), (3, 0.25))
        self.assertEqual(sec["Ho vs Hn"]["p_holm"], 0.75)
        self.assertEqual(result["provider_memory"]["M"]["lacking_id_recovered"], [1, 1])
        self.assertEqual(result["provider_memory"]["Ho"]["lacking_id_recovered"], [2, 4])
        self.assertEqual(result["provider_memory"]["Ho"]["retrieval_errors"], 1)


REAL_EVAL = RUNS / EVAL_STAGE


@unittest.skipUnless((REAL_EVAL / "plan.json").exists(), "private eval-v1 run not present")
class EvalResumeDryPassTests(unittest.TestCase):
    """Amendment 1: the whole resume path over a copy of the real eval-v1 run, zero model calls.
    Fails on a2a2c1d, whose report discovery ignored E-prefixed families."""

    def test_end_to_end_over_a_copy_of_the_real_run(self) -> None:
        from unittest import mock

        from research.commitment_analysis import analyse, rows_from_runs

        before = session_one_artifacts(REAL_EVAL)
        record = json.loads(AMEND_HASHES.read_text(encoding="utf-8"))
        self.assertEqual(artifact_problems(REAL_EVAL, record["artifacts"]), [])
        stored = json.loads((REAL_EVAL / "plan.json").read_text(encoding="utf-8"))
        setup = prepare(seed=stored["seed"])
        self.assertEqual(setup["manifest_sha256"], stored["manifest_sha256"])
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / EVAL_STAGE
            run.mkdir()
            for name in record["artifacts"]:  # exactly the recorded pre-resume state
                shutil.copy2(REAL_EVAL / name, run / name)
            inputs = frozen_inputs(run, "cmp-eval-", exclude=True)
            self.assertEqual(len(inputs), 32)  # exclusion: every family committed

            shim_journal(run, "mem0", 112)
            shim_journal(run, "honcho", 400)
            ingested: dict[tuple[str, str], dict[str, Any]] = {}

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {"state": str((run / "mem0").resolve()), "honcho_workspace": "commitment-eval-v1",
                            "honcho_reasoning_level": None,
                            "queue": {"total": 32, "completed": 32, "pending": 0, "in_progress": 0}}  # fmt: skip
                if path == "/ingest":
                    ingested[(body["provider"], body["scope"])] = body["episode"]
                    return {"result": {"events": 1}}
                lines = ingested[(body["provider"], body["scope"])]["lines"]
                return {"results": [t for speaker, t in lines if speaker == "agent"][-2:]}

            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(setup, run, inputs, EVAL_STAGE)
            self.assertEqual(providers["refused"], [])
            self.assertEqual(sorted(ingested), sorted((p, provider_scope(f, "cmp-eval-"))
                                                      for p in PROVIDER_ARMS.values() for f in inputs))  # fmt: skip
            self.assertTrue(all(e["id"] == f"{s.removeprefix('customer:')}-s1" and "outcome" not in e
                                for (_, s), e in ingested.items()))  # fmt: skip
            self.assertEqual(len(providers["retrievals"]), 64)

            jobs = select_jobs(stored["jobs"], "sessions", inputs)
            self.assertEqual(jobs, [j for j in stored["jobs"] if j["session"] == 2])
            self.assertEqual(len(jobs), 160)
            seen: list[tuple[dict[str, Any], FakeBackend]] = []

            class Capture(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event == "commitment-session-started":
                        seen.append(({k: fields[k] for k in ("session", "family", "arm")}, self))

            outcome = asyncio.run(run_jobs(setup, run, jobs, lambda _: Capture([act(text="How can I help?")] * 12),
                                           [run], 2816, 310.0, 2304, exclude_uncommitted=True))  # fmt: skip
            self.assertEqual((outcome["refused"], outcome["infra_events"]), ([], []))
            self.assertEqual([job for job, _ in seen], jobs)  # the plan's seeded order
            for job, backend in seen:
                system = backend.systems[0]
                if job["arm"] in ("Hc", "Hn"):
                    first = json.loads(
                        (run / f"{job['family']}-s1-S1-a1.json").read_text(encoding="utf-8")
                    )
                    text = transcript(first["messages"])
                    self.assertEqual(
                        hashlib.sha256(text.encode()).hexdigest(), inputs[job["family"]]["sha256"]
                    )
                    self.assertIn(
                        (MEMORY_HEADER if job["arm"] == "Hc" else NEUTRAL_HEADER) + text, system
                    )
                elif job["arm"] in PROVIDER_ARMS:
                    self.assertIn(NEUTRAL_HEADER + f"[{PROVIDER_ARMS[job['arm']]}-1]", system)
                else:
                    self.assertNotIn(NEUTRAL_HEADER, system)
                    self.assertNotIn(MEMORY_HEADER, system)
            self.assertEqual(pilot_ledger(journal_rows(run), 2816, 310.0)["started"], 186)
            result = analyse(rows_from_runs(run))
            self.assertEqual(
                (result["included"], result["excluded"], result["complete"]), (32, [], True)
            )
            self.assertEqual(
                {a: v["n"] for a, v in result["arms"].items()}, dict.fromkeys(EVAL_ARMS, 32)
            )
            self.assertEqual(result["leakage_sessions"], 0)
            self.assertEqual(
                artifact_problems(run, record["artifacts"]), []
            )  # session 1, plan, manifest intact
            (run / "E01-s1-S1-a1.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                artifact_problems(run, record["artifacts"]), ["E01-s1-S1-a1.json: hash differs"]
            )
        self.assertEqual(session_one_artifacts(REAL_EVAL), before)  # the real run is untouched


class ChangedMindTests(unittest.TestCase):
    """Changed-mind pilot: customer branches, X/Y target-blindness, end-to-end dry pass."""

    @classmethod
    def setUpClass(cls) -> None:
        from research import changed_mind

        cls.cm = changed_mind
        cls.setup = changed_mind.prepare()

    def x_view(self, family: dict[str, Any]) -> dict[str, Any]:
        return {**family, "target_id": family["stale_id"]}

    def test_sessions_1a_and_1b_branches(self) -> None:
        from research.commitment_pilot import _names_target

        customer_cls = self.cm.ChangedMindCustomer
        for family in self.setup["families"].values():
            x, y = family["stale_id"], family["target_id"]
            first = customer_cls(family, 1, "S1a")
            first.reply(OPENING)
            first.reply("Here are the options.")
            first.reply(f"Item {x} is in stock. Is that the one?")
            self.assertTrue(first.agreed and first.done)
            before = json.dumps(family, sort_keys=True)
            change = customer_cls(family, 1, "S1b")
            self.assertEqual(json.dumps(family, sort_keys=True), before)  # never mutates the family
            opening = change.reply(OPENING)
            self.assertIn("changed my mind", opening)
            self.assertFalse(_names_target(self.x_view(family), opening) or y in opening)
            ids = [v["item_id"] for v in family["alternatives"]]
            replies = [change.reply(t) for t in (
                f"Is it item {x}?", f"Options: {', '.join(ids)}.", "Which item did we agree earlier?",
                f"Instead of item {x}, item {y}?")]  # fmt: skip
            self.assertIn("I changed my mind", replies[0])
            target = next(v for v in family["alternatives"] if v["item_id"] == y)
            probe = customer_cls(family, 1, "S1b")
            probe.reply(OPENING)
            options_only = probe.reply(f"The {', '.join(target['options'].values())} one?")
            self.assertFalse(probe.agreed)
            self.assertIn("exact item ID", options_only)  # options without the ID are not agreement
            self.assertIn("the one we agreed last time", replies[2])
            self.assertFalse(change.agreed)
            self.assertFalse(
                any(_names_target(self.x_view(family), r) for r in [opening, *replies])
            )
            agreed = change.reply(f"Item {y} it is. Confirm?")
            self.assertTrue(change.agreed and change.done and STOP in agreed)
            slow, last = customer_cls(family, 1, "S1b"), ""
            for _ in range(7):
                last = slow.reply("Let me check.")
            self.assertTrue(slow.done and not slow.agreed and STOP in last)

    def test_session_two_is_target_blind_over_x_and_y(self) -> None:
        customer_cls = self.cm.ChangedMindCustomer
        for family in self.setup["families"].values():
            ids = [v["item_id"] for v in family["alternatives"]]
            for arm in ("N", "Hc", "Hn", "M", "Ho"):
                single, multi = set(), set()
                for item in ids:
                    customer = customer_cls(family, 2, arm)
                    opening = customer.reply(OPENING)
                    single.add(
                        customer.reply(f"I can exchange it for item {item}. Shall I proceed?")
                    )
                    other = customer_cls(family, 2, arm)
                    other.reply(OPENING)
                    multi.add(
                        other.reply(f"Item {item} or item {ids[0] if item != ids[0] else ids[1]}?")
                    )
                    self.assertEqual(leaks(family, arm, "", None, [opening]), [])
                self.assertEqual(
                    single, {CONSENT}, (family["family"], arm)
                )  # X, Y and others alike
                self.assertEqual(len(multi), 1, (family["family"], arm))
            control = customer_cls(family, 2, "R")
            restated = control.reply(OPENING)
            self.assertIn(family["target_id"], restated)
            self.assertEqual(leaks(family, "R", "", None, [restated]), [])  # X never restated
            self.assertTrue(leaks(family, "Hn", "", None, [f"item {family['stale_id']}"]))

    def test_end_to_end_dry_pass(self) -> None:
        from unittest import mock

        cm, setup = self.cm, self.setup
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            public = cm.plan(setup, "dry pass")
            first_jobs = cm.select(public["jobs"], "session1", [])
            self.assertEqual(len(first_jobs), 8)
            seen: list[tuple[dict[str, Any], FakeBackend]] = []

            class Scripted(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    job = {k: fields[k] for k in ("session", "family", "arm")}
                    seen.append((job, self))
                    f = families[str(job["family"])]
                    x, y = f["stale_id"], f["target_id"]
                    done = act(text="The exchange has been processed.")

                    def run_exchange(item: str) -> list[str]:
                        return [act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                                act("exchange_delivered_order_items", order_id=f["order_id"],
                                    item_ids=[f["current"]["item_id"]], new_item_ids=[item],
                                    payment_method_id=f["payment_id"]), done]  # fmt: skip

                    self.replies = {
                        "S1a": [
                            act(text="Here are the options."),
                            act(text=f"Item {x}: is that the one?"),
                        ],
                        "S1b": [act(text=f"Item {y}: is that the one?")],
                        "Hn": run_exchange(y),
                        "R": run_exchange(y),
                        "M": run_exchange(x),
                        "Ho": [act(text="Which item would you like?")] * 12,
                    }[str(job["arm"])]

            def backend(_: Any) -> Scripted:
                return Scripted([])

            outcome = asyncio.run(run_jobs(setup, run, first_jobs, backend, [run], 240, 30.0, 188,
                                           exclude_uncommitted=True, infra_continue=True))  # fmt: skip
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(cm.committed(run), sorted(families))

            shim_journal(run, "mem0", 12)
            shim_journal(run, "honcho", 40)
            ingested: dict[tuple[str, str], list[str]] = {}

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {"state": str((run / "mem0").resolve()), "honcho_workspace": "changed-mind-pilot-v1",
                            "honcho_reasoning_level": None,
                            "queue": {"total": 8, "completed": 8, "pending": 0, "in_progress": 0}}  # fmt: skip
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]["id"]
                    )
                    return {"result": {}}
                f = families[body["scope"].removeprefix("customer:cmp-cm-p1-")]
                return {
                    "results": [
                        f"Agreed item {f['stale_id']}, then changed to item {f['target_id']}."
                    ]
                }

            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(setup, run, cm.provider_inputs(run), "cm-pilot-v1")
            self.assertEqual(providers["refused"], [])
            self.assertEqual(len(ingested), 8)
            for (_, scope), episodes in ingested.items():
                prefix = scope.removeprefix("customer:")
                self.assertEqual(
                    episodes, [f"{prefix}-s1a", f"{prefix}-s1b"]
                )  # same customer, in order

            second = cm.select(public["jobs"], "sessions", cm.committed(run))
            self.assertEqual(len(second), 16)
            seen.clear()
            outcome = asyncio.run(run_jobs(setup, run, second, backend, [run], 240, 30.0, 188,
                                           exclude_uncommitted=True, history_fn=cm.history,
                                           infra_continue=True))  # fmt: skip
            self.assertEqual(outcome["refused"], [])
            self.assertEqual([j for j, _ in seen], second)
            for job, used in seen:
                system = used.systems[0]
                if job["arm"] == "Hn":
                    self.assertIn(NEUTRAL_HEADER + "Earlier session (1 of 2):", system)
                    self.assertIn("Most recent session (2 of 2):", system)
                elif job["arm"] == "R":
                    self.assertNotIn(NEUTRAL_HEADER, system)
            summary = cm.summarize(run, setup)
            arms = summary["arms"]
            self.assertEqual({a: (v["successes"], v["n"], v["stale_commitment"]) for a, v in arms.items()},
                             {"Hn": (4, 4, 0), "M": (0, 4, 4), "Ho": (0, 4, 0), "R": (4, 4, 0)})  # fmt: skip
            m_rows = [r for r in summary["rows"] if r["arm"] == "M"]
            self.assertTrue(all(r["memory_has_X"] and r["memory_has_Y"] and r["wrong_variant_other"] == 0
                                for r in m_rows))  # fmt: skip
            self.assertEqual(summary["verdict"], "PASS")
            self.assertEqual(len(summary["rows"]), 24)


class HonchoHighTests(unittest.TestCase):
    """Hoh dev check: Honcho at its highest level, retrieval only, per-call shim accounting."""

    @classmethod
    def setUpClass(cls) -> None:
        from research import changed_mind

        cls.cm = changed_mind
        cls.setup = changed_mind.prepare()

    def test_gateway_uses_the_per_request_level(self) -> None:
        from research import memory_gateway as gateway

        asked: list[Any] = []

        class Peer:
            def chat(self, question: str, reasoning_level: str | None = None) -> str:
                asked.append(reasoning_level)
                return "memo"

        class Workspace:
            def peer(self, name: str) -> Peer:
                return Peer()

        honcho = object.__new__(gateway.HonchoStore)
        honcho.clients, honcho.factory = {}, lambda workspace: Workspace()
        saved = dict(gateway.CONFIG)
        try:
            gateway.CONFIG.clear()
            gateway.CONFIG.update(honcho_workspace="w", honcho_reasoning_level=None)
            honcho.search("customer:x", "q")
            honcho.search("customer:x", "q", "max")
        finally:
            gateway.CONFIG.clear()
            gateway.CONFIG.update(saved)
        self.assertEqual(asked, [None, "max"])  # null config: level omitted, server default (low)

    def test_retrieval_only_with_level_and_per_call_cost(self) -> None:
        from unittest import mock

        cm, setup = self.cm, self.setup
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            shim_journal(run, "honcho", 52)
            journal = run / "shims" / "honcho.calls.jsonl"
            posts: list[tuple[str, dict[str, Any]]] = []
            calls = iter(range(1, 100))

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                posts.append((path, body))
                if path == "/status":
                    return {"state": "x", "honcho_workspace": "changed-mind-pilot-v1", "honcho_reasoning_level": None,
                            "queue": {"total": 42, "completed": 42, "pending": 0, "in_progress": 0}}  # fmt: skip
                with journal.open("a", encoding="utf-8") as handle:
                    for _ in range(3):
                        i = next(calls)
                        handle.write(
                            json.dumps({"event": "copilot-request-started", "call_id": i}) + "\n"
                        )
                        handle.write(json.dumps(billed(i)) + "\n")
                family = setup["families"][body["scope"].removeprefix("customer:cmp-cm-p1-")]
                return {"results": [f"Latest agreement: item {family['target_id']}."]}

            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                result = cm.hoh_retrieve(setup, run)
            self.assertEqual(result["refused"], [])
            searches = [b for path, b in posts if path == "/search"]
            self.assertEqual(len(searches), 4)
            self.assertFalse(any(path == "/ingest" for path, _ in posts))
            self.assertTrue(
                all(b["reasoning_level"] == "max" and b["provider"] == "honcho" for b in searches)
            )
            self.assertEqual(
                {(r["shim_requests"], r["shim_credits"]) for r in result["retrievals"]}, {(3, 0.3)}
            )
            job = {"session": 2, "family": "D1", "arm": "Hoh"}
            text, meta = cm.history(run, job)
            self.assertIn(setup["families"]["D1"]["target_id"], text or "")
            self.assertEqual((meta or {}).get("provider"), "honcho")
            with mock.patch("research.provider_ingest.post", return_value={
                    "state": "x", "honcho_workspace": "ae-customer", "honcho_reasoning_level": None}):  # fmt: skip
                self.assertTrue(cm.hoh_retrieve(setup, run)["refused"])


class ChangedMindEvaluationTests(unittest.TestCase):
    """Changed-mind evaluation (tag changed-mind-eval-v1): generation and a full dry pass."""

    @classmethod
    def setUpClass(cls) -> None:
        from research import changed_mind

        cls.cm = changed_mind
        cls.tag = {"tag": "changed-mind-eval-v1", "commit": "0" * 40, "seed": eval_seed("0" * 40)}
        cls.setup = changed_mind.prepare(cls.tag["seed"])

    def test_generation_and_tag_check(self) -> None:
        self.assertIsNone(self.cm.eval_tag_state("no-such-tag-for-tests"))
        families = list(self.setup["families"].values())
        self.assertEqual(sorted(f["family"] for f in families), [f"F{i:02d}" for i in range(1, 33)])
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        self.assertTrue(all((f["first"], f["last"]) in {(a, b) for a in self.cm.EVAL_FIRST for b in self.cm.EVAL_LAST}
                            for f in families))  # fmt: skip
        pilot = self.cm.prepare()["families"].values()
        others = {
            x for f in [*pilot, *SETUP["families"].values()] for x in (f["user_id"], f["order_id"])
        }
        self.assertFalse(others & {x for f in families for x in (f["user_id"], f["order_id"])})
        self.assertTrue(
            all(len({f["stale_id"], f["target_id"], f["rejected_id"]}) == 3 for f in families)
        )

    def test_end_to_end_dry_pass(self) -> None:
        from unittest import mock

        from research.changed_mind_analysis import analyse, read_csv, rows_from_runs, write_csv

        cm, setup = self.cm, self.setup
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            public = cm.eval_plan(setup, "dry pass", self.tag)
            seen: list[dict[str, Any]] = []

            class Policy(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    job = {k: fields[k] for k in ("session", "family", "arm")}
                    seen.append(job)
                    f = families[str(job["family"])]
                    x, y = f["stale_id"], f["target_id"]

                    def execute(item: str) -> list[str]:
                        return [act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                                act("exchange_delivered_order_items", order_id=f["order_id"],
                                    item_ids=[f["current"]["item_id"]], new_item_ids=[item],
                                    payment_method_id=f["payment_id"]),
                                act(text="The exchange has been processed.")]  # fmt: skip

                    decline = [act(text="I can't act on that without the exact item.")] * 12
                    self.replies = {"S1a": [act(text="Options."), act(text=f"Item {x}: is that the one?")],
                                    "S1b": [act(text=f"Item {y}: is that the one?")],
                                    "Hn": execute(y), "Hoh": execute(y), "M": execute(x),
                                    "Ho": decline, "N": decline}[str(job["arm"])]  # fmt: skip

            def backend(_: Any) -> Policy:
                return Policy([])

            options = {
                "exclude_uncommitted": True,
                "history_fn": cm.history,
                "infra_continue": True,
            }
            first = cm.select(public["jobs"], "session1", [])
            outcome = asyncio.run(
                run_jobs(setup, run, first, backend, [run], 3120, 360.0, 2688, **options)
            )
            self.assertEqual((outcome["refused"], len(first)), ([], 64))
            included = cm.committed(run)
            self.assertEqual(len(included), 32)

            shim_journal(run, "mem0", 96)
            shim_journal(run, "honcho", 336)
            ingested: dict[tuple[str, str], list[str]] = {}
            levels: dict[str, set[Any]] = {}

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {"state": str((run / "mem0").resolve()), "honcho_workspace": "changed-mind-eval-v1",
                            "honcho_reasoning_level": None,
                            "queue": {"total": 64, "completed": 64, "pending": 0, "in_progress": 0}}  # fmt: skip
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]["id"]
                    )
                    return {"result": {}}
                levels.setdefault(body["provider"], set()).add(body.get("reasoning_level"))
                f = families[body["scope"].removeprefix("customer:cmp-cm-e1-")]
                return {"results": [f"Item {f['stale_id']}, later item {f['target_id']}."]}

            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(setup, run, cm.provider_inputs(run, "cmp-cm-e1-"), "cm-eval-v1",
                                           ("M", "Ho", "Hoh"))  # fmt: skip
            self.assertEqual(providers["refused"], [])
            self.assertEqual(len(ingested), 64)  # Hoh reuses Honcho's ingestion
            self.assertTrue(
                all(
                    ids[0].endswith("-s1a") and ids[1].endswith("-s1b") for ids in ingested.values()
                )
            )
            self.assertEqual(levels, {"mem0": {None}, "honcho": {None, "max"}})
            self.assertEqual(len(providers["retrievals"]), 96)

            second = cm.select(public["jobs"], "sessions", included)
            self.assertEqual(len(second), 160)
            seen.clear()
            outcome = asyncio.run(
                run_jobs(setup, run, second, backend, [run], 3120, 360.0, 2688, **options)
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, second)  # the plan's seeded order

            rows = rows_from_runs(run)
            result = analyse(rows)
            self.assertEqual(
                (result["included"], result["complete"], result["leakage_sessions"]), (32, True, 0)
            )
            arms = {
                a: (v["successes"], v["n"], v["stale"], v["declined"])
                for a, v in result["arms"].items()
            }
            self.assertEqual(arms, {"N": (0, 32, 0, 32), "Hn": (32, 32, 0, 0), "M": (0, 32, 32, 0),
                                    "Ho": (0, 32, 0, 32), "Hoh": (32, 32, 0, 0)})  # fmt: skip
            primary, secondary = result["primary_success"], result["secondary_stale"]
            self.assertEqual(
                (primary["M vs Hn"]["reference_only"], primary["Hoh vs Hn"]["p_holm"]), (32, 1.0)
            )
            self.assertEqual(secondary["M vs Hn"]["arm_only"], 32)
            self.assertEqual(result["hoh_vs_ho_success"]["arm_only"], 32)
            self.assertEqual(result["manipulation_hn_vs_n"]["arm_only"], 32)
            self.assertEqual(result["provider_memory"]["Hoh"]["has_both"], 32)
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), result)


class DatedCheckTests(unittest.TestCase):
    """Dated dev check: backdated sessions, identical date labels and "Today is" sentence."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research import changed_mind

        cls.cm, cls.today = changed_mind, dt.date(2026, 11, 15)
        cls.setup = changed_mind.prepare()

    def source(self, root: Path) -> Path:
        for name, f in self.setup["families"].items():
            for arm, item in (("S1a", f["stale_id"]), ("S1b", f["target_id"])):
                messages = [{"role": "assistant", "content": OPENING},
                            {"role": "user", "content": "Please don't make the exchange today."},
                            {"role": "assistant", "content": f"Agreed item {item}."}]  # fmt: skip
                report = {
                    "session": 1,
                    "family": name,
                    "arm": arm,
                    "commitment": True,
                    "messages": messages,
                }
                (root / f"{name}-s1-{arm}-a1.json").write_text(json.dumps(report), encoding="utf-8")
        return root

    def test_dates_inputs_and_gateway_created_at(self) -> None:
        from research import memory_gateway as gateway

        cm, today = self.cm, self.today
        self.assertEqual(
            cm.session_label(today, "a"),
            "Earlier session (1 of 2), Thursday 12 November 2026, 14:20 UTC:",
        )
        self.assertEqual(cm.today_sentence(today), "Today is Sunday 15 November 2026 (UTC).")
        with tempfile.TemporaryDirectory() as tmp:
            source = self.source(Path(tmp))
            inputs = cm.dated_inputs(source, today)["D1"]
            history = cm.dated_history_text(source, "D1", today)
            for order, mem0, honcho in zip(
                "ab", inputs["episodes_mem0"], inputs["episodes_honcho"]
            ):
                label = cm.session_label(today, order)
                self.assertTrue(mem0["lines"][0][1].startswith(label + "\n"))  # Mem0 in-band header
                self.assertIn(label + "\n", history)  # identical label in Hn
                self.assertNotIn(
                    "session (", json.dumps(honcho["lines"])
                )  # Honcho: dates via created_at only
                self.assertEqual(honcho["times"][0], cm.session_start(today, order).isoformat())
                self.assertEqual(len(honcho["times"]), len(honcho["lines"]))
            self.assertEqual(inputs["episodes_honcho"][0]["times"][0][:10], "2026-11-12")
            self.assertEqual(inputs["episodes_honcho"][1]["times"][0][:10], "2026-11-14")
        sent: list[Any] = []

        class Peer:
            def message(self, content: str, **kwargs: Any) -> dict[str, Any]:
                sent.append(kwargs.get("created_at"))
                return {}

        class Session:
            id = "s"

            def add_messages(self, messages: list[Any]) -> None:
                pass

        class Workspace:
            def peer(self, name: str) -> Peer:
                return Peer()

            def session(self, name: str, peers: list[Any]) -> Session:
                return Session()

        honcho = object.__new__(gateway.HonchoStore)
        honcho.clients, honcho.factory = {}, lambda workspace: Workspace()
        honcho.wait = lambda honcho, limit=900: {}
        honcho.ingest(
            "customer:x",
            {"id": "e", "lines": [("customer", "a"), ("agent", "b")], "times": ["t1", "t2"]},
        )
        honcho.ingest("customer:x", {"id": "f", "lines": [("customer", "a")]})
        self.assertEqual(sent, ["t1", "t2", None])

    def test_dry_pass_today_sentence_summary_and_gates(self) -> None:
        from unittest import mock

        cm, today = self.cm, self.today
        setup = {**self.setup, "today": cm.today_sentence(today)}
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            source, run = self.source(Path(tmp) / "src"), Path(tmp) / "run"
            run.mkdir()
            shim_journal(run, "mem0", 12)
            shim_journal(run, "honcho", 45)
            ingested: dict[tuple[str, str], list[dict[str, Any]]] = {}

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {"state": str((run / "mem0").resolve()), "honcho_workspace": "changed-mind-dated-v1",
                            "honcho_reasoning_level": None,
                            "queue": {"total": 8, "completed": 8, "pending": 0, "in_progress": 0}}  # fmt: skip
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]
                    )
                    return {"result": {}}
                f = families[body["scope"].removeprefix("customer:cmp-cm-t1-")]
                if body["provider"] == "mem0" and f["family"] == "D4":
                    raise TimeoutError("down")
                return {
                    "results": [
                        f"On 2026-11-12 item {f['stale_id']}; on 2026-11-14 changed to item {f['target_id']}."
                    ]
                }

            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(
                    setup, run, cm.dated_inputs(source, today), "cm-dated-v1"
                )
            self.assertEqual(providers["refused"], [])
            self.assertTrue(
                all("times" in e for (p, _), eps in ingested.items() if p == "honcho" for e in eps)
            )
            self.assertFalse(
                any("times" in e for (p, _), eps in ingested.items() if p == "mem0" for e in eps)
            )
            public = cm.dated_plan(setup, "dry", today, source)
            self.assertEqual(len(public["jobs"]), 12)
            systems: dict[str, str] = {}

            class Policy(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    f = families[str(fields["family"])]
                    arm = str(fields["arm"])
                    self.key = f"{fields['family']}-{arm}"
                    item = {"Hn": f["target_id"], "M": f["stale_id"]}.get(arm)
                    self.replies = [act(text="I can't act on that.")] * 12 if item is None else [
                        act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                        act("exchange_delivered_order_items", order_id=f["order_id"], item_ids=[f["current"]["item_id"]],
                            new_item_ids=[item], payment_method_id=f["payment_id"]),
                        act(text="The exchange has been processed.")]  # fmt: skip

                async def complete(
                    self, system: str, prompt: str, response_schema: Any = None
                ) -> str:
                    systems.setdefault(self.key, system)
                    return await super().complete(system, prompt, response_schema)

            outcome = asyncio.run(run_jobs(setup, run, public["jobs"], lambda _: Policy([]), [run], 200, 25.0, 144,
                                           exclude_uncommitted=True, history_fn=cm.dated_history(today, source),
                                           infra_continue=True))  # fmt: skip
            self.assertEqual(outcome["refused"], [])
            policy_today = setup["policy"] + "\n\n" + cm.today_sentence(today)
            self.assertEqual(len(systems), 12)
            for key, system in systems.items():
                self.assertTrue(
                    system.startswith(ACTOR_SYSTEM + policy_today), key
                )  # same sentence, same place
                self.assertEqual(system.count("Today is"), 1, key)
            self.assertNotIn(
                NEUTRAL_HEADER, systems["D4-M"]
            )  # retrieval error: no memory, still dated
            summary = cm.dated_summary(run, setup, today, source)
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            self.assertEqual(len(rows), 12)
            self.assertTrue(
                all(
                    rows[(f, "Hn")]["success"] and rows[(f, "Hn")]["date_correct"] for f in families
                )
            )
            self.assertEqual(
                sum(rows[(f, "M")]["stale_commitment"] > 0 for f in families), 4
            )  # policy ignores memory
            self.assertTrue(
                all(
                    rows[(f, "Ho")]["declined"] and rows[(f, "Ho")]["shows_backdated_date"]
                    for f in families
                )
            )
            self.assertTrue(rows[("D1", "Ho")]["date_correct"] and rows[("D1", "Ho")]["has_X"])
            self.assertEqual(summary["verdict"], "PASS")
            self.assertEqual(summary["retrievals_ok"], {"mem0": 3, "honcho": 4})


class DatedEvaluationTests(unittest.TestCase):
    """Dated changed-mind evaluation (tag changed-mind-dated-eval-v1): generation, scopes, dry pass."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research import changed_mind

        cls.cm, cls.today = changed_mind, dt.date(2026, 11, 16)
        seed = eval_seed("1" * 40)
        cls.tag = {"tag": changed_mind.DE_TAG, "commit": "1" * 40, "seed": seed,
                   "sources": (*changed_mind.EVAL_SOURCES, "changed_mind_dated_analysis.py")}  # fmt: skip
        cls.setup = changed_mind.prepare(seed, dated=True)

    def test_generation_caps_and_workspace_map(self) -> None:
        from unittest import mock

        from research import memory_gateway as gateway

        cm = self.cm
        self.assertIsNone(cm.de_tag_state("no-such-tag-for-tests"))
        families = list(self.setup["families"].values())
        self.assertEqual(sorted(f["family"] for f in families), [f"G{i:02d}" for i in range(1, 33)])
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        self.assertTrue(all((f["first"], f["last"]) in {(a, b) for a in cm.DE_FIRST for b in cm.DE_LAST}
                            for f in families))  # fmt: skip
        others = [*SETUP["families"].values(), *cm.prepare()["families"].values(),
                  *cm.prepare(cm.CM_EVAL_SEED)["families"].values()]  # fmt: skip
        keys = {x for f in others for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        self.assertFalse(
            keys
            & {x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        )
        self.assertTrue(
            all(len({f["stale_id"], f["target_id"], f["rejected_id"]}) == 3 for f in families)
        )
        caps = cm.de_caps()
        self.assertEqual((caps["hard_cap"], caps["credit_stop"]), (3408, 400.0))
        self.assertEqual(sum(caps["caps"].values()), 3408)
        self.assertLessEqual(caps["conservative_at_caps"], 400.0)
        self.assertEqual(len(set(cm.DE_PREFIXES.values())), 3)
        self.assertEqual(cm.DE_PREFIXES["M"], cm.DE_CFG["prefix"])
        store = object.__new__(gateway.HonchoStore)
        store.clients, store.factory = {}, lambda workspace: workspace
        config = {
            "honcho_workspace": cm.DE_CFG["workspace"],
            "honcho_workspace_by_prefix": cm.DE_WORKSPACES,
        }
        with mock.patch.dict(gateway.CONFIG, config, clear=True):
            self.assertEqual(
                store.workspace("customer:cmp-cm-d2d-G01"), "changed-mind-dated-eval-v1-dated"
            )
            self.assertEqual(
                store.workspace("customer:cmp-cm-d2u-G01"), "changed-mind-dated-eval-v1-undated"
            )
            self.assertEqual(store.workspace("customer:"), "changed-mind-dated-eval-v1-undated")

    def test_end_to_end_dry_pass(self) -> None:
        from unittest import mock

        from research.changed_mind_dated_analysis import (
            analyse,
            read_csv,
            rows_from_runs,
            write_csv,
        )

        cm, today = self.cm, self.today
        setup = {**self.setup, "today": cm.today_sentence(today)}
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            public = cm.de_plan(setup, "dry pass", self.tag, today)
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            (run / "plan.json").write_text(json.dumps(public), encoding="utf-8")
            self.assertEqual(public["today_sentence"], "Today is Monday 16 November 2026 (UTC).")
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}

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
                        return [act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                                act("exchange_delivered_order_items", order_id=f["order_id"],
                                    item_ids=[f["current"]["item_id"]], new_item_ids=[item],
                                    payment_method_id=f["payment_id"]),
                                act(text="The exchange has been processed.")]  # fmt: skip

                    decline = [act(text="I can't act on that without the exact item.")] * 12
                    self.replies = {"S1a": [act(text="Options."), act(text=f"Item {x}: is that the one?")],
                                    "S1b": [act(text=f"Item {y}: is that the one?")],
                                    "Hn": execute(y), "M": execute(x), "Mi": execute(y),
                                    "Ho": decline, "Hod": execute(y)}[str(job["arm"])]  # fmt: skip

                async def complete(
                    self, system: str, prompt: str, response_schema: Any = None
                ) -> str:
                    systems.setdefault(self.key, system)
                    return await super().complete(system, prompt, response_schema)

            options = {"exclude_uncommitted": True, "history_fn": cm.dated_history(today, run),
                       "infra_continue": True}  # fmt: skip
            first = cm.select(public["jobs"], "session1", [])
            outcome = asyncio.run(run_jobs(setup, run, first, lambda _: Policy([]), [run], 3408, 400.0, 2688,
                                           **options))  # fmt: skip
            self.assertEqual((outcome["refused"], len(first)), ([], 64))
            included = cm.committed(run)
            self.assertEqual(len(included), 32)

            shim_journal(run, "mem0", 192)
            shim_journal(run, "honcho", 528)
            ingested: dict[tuple[str, str], list[dict[str, Any]]] = {}
            searched: dict[tuple[str, str], int] = {}
            drained: list[str] = []

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    drained.append(body.get("scope", ""))
                    return {"state": str((run / "mem0").resolve()), "honcho_workspace": cm.DE_CFG["workspace"],
                            "honcho_workspace_by_prefix": cm.DE_WORKSPACES, "honcho_reasoning_level": None,
                            "queue": {"total": 64, "completed": 64, "pending": 0, "in_progress": 0}}  # fmt: skip
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]
                    )
                    return {"result": {}}
                key = (body["provider"], body["scope"])
                searched[key] = searched.get(key, 0) + 1
                prefix, name = body["scope"].removeprefix("customer:")[:11], body["scope"][-3:]
                f = families[name]
                dated = (
                    "On 13 November item {x}; on 15 November changed to item {y}."
                    if prefix != "cmp-cm-d2u-"
                    else "Item {x}, later item {y}. Do not process today."
                )
                return {"results": [dated.format(x=f["stale_id"], y=f["target_id"])]}

            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                providers = cm.de_providers(setup, run, today)
            self.assertEqual((providers["refused"], providers["ingestion_errors"]), ([], []))
            self.assertEqual(drained.count("customer:cmp-cm-d2u-"), 1)
            self.assertEqual(drained.count("customer:cmp-cm-d2d-"), 1)
            self.assertEqual(len(ingested), 128)  # four separate scopes per family
            for f in included:
                streams = {(p, prefix): ingested[(p, f"customer:{prefix}{f}")]
                           for p, prefix in (("mem0", "cmp-cm-d2u-"), ("mem0", "cmp-cm-d2i-"),
                                             ("honcho", "cmp-cm-d2u-"), ("honcho", "cmp-cm-d2d-"))}  # fmt: skip
                for (provider, prefix), episodes in streams.items():
                    self.assertEqual([e["id"][-4:] for e in episodes], ["-s1a", "-s1b"])
                    dated_text = provider == "mem0" and prefix == "cmp-cm-d2i-"
                    for order, episode in zip("ab", episodes):
                        label = cm.session_label(today, order)
                        self.assertEqual(
                            episode["lines"][0][1].startswith(label + "\n"), dated_text
                        )
                        self.assertEqual("times" in episode, prefix == "cmp-cm-d2d-")
                    if prefix == "cmp-cm-d2d-":
                        self.assertEqual(
                            [e["times"][0][:10] for e in episodes], ["2026-11-13", "2026-11-15"]
                        )
                undated = [
                    [line for _, line in e["lines"]] for e in streams[("mem0", "cmp-cm-d2u-")]
                ]
                self.assertEqual(
                    undated,
                    [[line for _, line in e["lines"]] for e in streams[("honcho", "cmp-cm-d2u-")]],
                )
            self.assertEqual(len(providers["retrievals"]), 128)
            self.assertEqual(len(searched), 128)
            self.assertEqual(
                {k[1][9:20] for k in searched if k[0] == "mem0"}, {"cmp-cm-d2u-", "cmp-cm-d2i-"}
            )
            self.assertEqual(
                {k[1][9:20] for k in searched if k[0] == "honcho"}, {"cmp-cm-d2u-", "cmp-cm-d2d-"}
            )

            second = cm.select(public["jobs"], "sessions", included)
            self.assertEqual(len(second), 160)
            seen.clear()
            systems.clear()
            outcome = asyncio.run(run_jobs(setup, run, second, lambda _: Policy([]), [run], 3408, 400.0, 2688,
                                           **options))  # fmt: skip
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, second)  # the plan's seeded order
            policy_today = setup["policy"] + "\n\n" + cm.today_sentence(today)
            self.assertEqual(len(systems), 160)
            for key, system in systems.items():
                self.assertTrue(
                    system.startswith(ACTOR_SYSTEM + policy_today), key
                )  # same sentence, same place
                self.assertEqual(system.count("Today is"), 1, key)
                self.assertIn(NEUTRAL_HEADER, system, key)
            self.assertIn(cm.session_label(today, "b"), systems["G01-Hn"])

            rows = rows_from_runs(run)
            result = analyse(rows)
            self.assertEqual(
                (result["included"], result["complete"], result["leakage_sessions"]), (32, True, 0)
            )
            arms = {
                a: (v["successes"], v["n"], v["stale"], v["declined"])
                for a, v in result["arms"].items()
            }
            self.assertEqual(arms, {"Hn": (32, 32, 0, 0), "M": (0, 32, 32, 0), "Mi": (32, 32, 0, 0),
                                    "Ho": (0, 32, 0, 32), "Hod": (32, 32, 0, 0)})  # fmt: skip
            primary, secondary = result["primary_success"], result["secondary_stale"]
            self.assertEqual(set(primary), {"Mi vs M", "Hod vs Ho"})
            self.assertEqual(
                (primary["Mi vs M"]["arm_only"], primary["Hod vs Ho"]["arm_only"]), (32, 32)
            )
            self.assertEqual(secondary["Mi vs M"]["reference_only"], 32)
            self.assertEqual(
                result["descriptive_vs_hn"]["Ho vs Hn"]["success"]["reference_only"], 32
            )
            memory = result["provider_memory"]
            self.assertEqual((memory["Hod"]["date_correct"], memory["M"]["date_correct"]), (32, 0))
            self.assertEqual(
                (memory["M"]["deferral_present"], memory["Mi"]["deferral_present"]), (32, 0)
            )
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), result)


def _first_session_source(root: Path, families: dict[str, Any]) -> Path:
    """Synthetic frozen 1a/1b reports (agreements on X then Y) for dry passes."""
    for name, f in families.items():
        for arm, item in (("S1a", f["stale_id"]), ("S1b", f["target_id"])):
            messages = [{"role": "assistant", "content": OPENING},
                        {"role": "user", "content": "Please don't make the exchange today."},
                        {"role": "assistant", "content": f"Agreed item {item}."}]  # fmt: skip
            report = {
                "session": 1,
                "family": name,
                "arm": arm,
                "commitment": True,
                "messages": messages,
            }
            (root / f"{name}-s1-{arm}-a1.json").write_text(json.dumps(report), encoding="utf-8")
    return root


def _features_policy(families: dict[str, Any], seen: list[dict[str, Any]], systems: dict[str, str],
                     plan_for: dict[str, str]) -> Any:  # fmt: skip
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
                return [act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                        act("exchange_delivered_order_items", order_id=f["order_id"],
                            item_ids=[f["current"]["item_id"]], new_item_ids=[item], payment_method_id=f["payment_id"]),
                        act(text="The exchange has been processed.")]  # fmt: skip

            if job["session"] == 1:
                self.replies = ([act(text="Options."), act(text=f"Item {x}: is that the one?")] if job["arm"] == "S1a"
                                else [act(text=f"Item {y}: is that the one?")])  # fmt: skip
                return
            kind = plan_for[str(job["arm"])]
            self.replies = {"Y": execute(y), "X": execute(x),
                            "ask": [act(text="Which item did we agree on last time?"), *execute(y)],
                            "decline": [act(text="I can't act on that without the exact item.")] * 12}[kind]  # fmt: skip

        async def complete(self, system: str, prompt: str, response_schema: Any = None) -> str:
            systems.setdefault(getattr(self, "key", ""), system)
            return await super().complete(system, prompt, response_schema)

    return Policy


class HonchoFeaturesTests(unittest.TestCase):
    """Honcho features (staged_auto): restating customer, message search, schedule, dry passes."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research import honcho_features

        cls.hf, cls.today = honcho_features, dt.date(2026, 11, 16)
        cls.dev = honcho_features.prepare()

    def test_restating_branch_names_y_only_after_a_which_item_question(self) -> None:
        from research.commitment_pilot import RESTATEMENT

        hf = self.hf
        f = self.dev["families"]["D1"]
        x, y = f["stale_id"], f["target_id"]
        prompts = ["Which item did we agree on last time?", "Could you confirm which option you chose?",
                   "What variant would you like?", "Can you tell me the item you agreed?",
                   # Stage 1 phrasings that the first detector missed (no question mark):
                   "I have no record of an agreement. Please tell me which item you want instead.",
                   "For the Makeup Kit, please choose one of the available options.",
                   "To proceed, please tell me which Espresso Machine variant you want."]  # fmt: skip
        for prompt in prompts:
            customer = hf.RestatingCustomer(f, 2, "Nr")
            opening = customer.reply(OPENING)
            self.assertFalse(identified(f, opening))  # never unprompted
            reply = customer.reply(prompt)
            self.assertTrue(reply.startswith(RESTATEMENT), prompt)
            self.assertIn(y, reply)
            self.assertNotIn(x, reply)  # never X
            self.assertEqual(identified(f, reply), {y})
        for arm in ("Nr", "Hnr", "Hodr", "Mir"):
            customer = hf.RestatingCustomer(f, 2, arm)
            customer.reply(OPENING)
            self.assertEqual(
                customer.reply("Let me look up your order."), hf.ASK_ITEM
            )  # no question
            self.assertEqual(customer.reply("I'll process it now."), hf.ASK_ITEM)
            self.assertEqual(customer.reply(f"Item {x}: shall I proceed?"), CONSENT)  # target-blind
        for arm in ("Hod", "Hs", "Hn"):  # other arms keep the base script
            customer = hf.RestatingCustomer(f, 2, arm)
            customer.reply(OPENING)
            self.assertEqual(customer.reply("Which item did we agree on last time?"), hf.ASK_ITEM)
        base = hf.cm.ChangedMindCustomer(f, 2, "Hod")
        base.reply(OPENING)
        self.assertEqual(
            base.reply("Which item?"), hf.ASK_ITEM
        )  # the constant is the base script's reply

    def test_leak_check_allows_only_the_restatement(self) -> None:
        from research.commitment_pilot import RESTATEMENT

        f = self.dev["families"]["D1"]
        restatement = f"{RESTATEMENT}the item {f['target_id']}."
        self.assertEqual(leaks(f, "Nr", "system", None, ["Hi.", restatement]), [])
        self.assertTrue(
            leaks(f, "Hod", "system", None, ["Hi.", restatement])
        )  # not a restating arm
        self.assertTrue(leaks(f, "Nr", "system", None, [restatement]))  # never in the opening
        self.assertTrue(leaks(f, "Nr", "system", None, ["Hi.", f"It's item {f['target_id']}."]))
        self.assertTrue(
            leaks(f, "Nr", "system", None, ["Hi.", f"{RESTATEMENT}item {f['stale_id']}."])
        )

    def test_message_search_rendering_and_scope(self) -> None:
        import datetime as dt
        from types import SimpleNamespace

        from research import memory_gateway as gateway

        calls: list[Any] = []
        when = dt.datetime(2026, 11, 13, 14, 20, tzinfo=dt.timezone.utc)

        class Workspace:
            def peer(self, name: str) -> Any:
                return SimpleNamespace(
                    sessions=lambda: [SimpleNamespace(id="s1a"), SimpleNamespace(id="s1b")]
                )

            def search(self, query: str, filters: Any = None, limit: int = 10) -> list[Any]:
                calls.append((query, filters, limit))
                return [SimpleNamespace(created_at=when, peer_id="agent", content="Item 123: is that the one?"),
                        SimpleNamespace(created_at=when, peer_id="cmp-x-D1", content="Yes, that's the one.")]  # fmt: skip

        store = object.__new__(gateway.HonchoStore)
        store.clients, store.factory = {}, lambda workspace: Workspace()
        lines = store.messages("customer:cmp-x-D1", "go ahead")
        self.assertEqual(lines, ["[2026-11-13 14:20 UTC] Agent: Item 123: is that the one?",
                                 "[2026-11-13 14:20 UTC] Customer: Yes, that's the one."])  # fmt: skip
        self.assertEqual(calls, [("go ahead", {"session_id": {"in": ["s1a", "s1b"]}}, 10)])

    def test_schedule_caps_and_eval_generation(self) -> None:
        hf = self.hf
        jobs = hf.schedule([f"K{i:02d}" for i in range(1, 33)], hf.EVAL_ARMS, 7)
        blocks = [jobs[i * 32 : (i + 1) * 32] for i in range(len(hf.EVAL_ARMS))]
        self.assertEqual([b[0]["arm"] for b in blocks], list(hf.EVAL_ARMS))  # priority order
        self.assertTrue(
            all(
                len({j["family"] for j in b}) == 32 and len({j["arm"] for j in b}) == 1
                for b in blocks
            )
        )
        for stage, (cap, stop) in ((hf.DEV_STAGE, (350, 40.0)), (hf.EVAL_STAGE, (3000, 400.0))):
            budget = hf.caps(stage)
            self.assertEqual((budget["hard_cap"], budget["credit_stop"]), (cap, stop))
            self.assertLessEqual(sum(budget["caps"].values()), cap)
            self.assertLessEqual(budget["conservative_at_caps"], stop)
        self.assertIsNone(hf.tag_state("no-such-tag-for-tests"))
        setup = hf.prepare(eval_seed("2" * 40))
        families = list(setup["families"].values())
        self.assertEqual(sorted(f["family"] for f in families), [f"K{i:02d}" for i in range(1, 33)])
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        cm = hf.cm
        others = [*SETUP["families"].values(), *cm.prepare()["families"].values(),
                  *cm.prepare(cm.CM_EVAL_SEED)["families"].values(),
                  *cm.prepare(hf.DE_SEED, dated=True)["families"].values()]  # fmt: skip
        keys = {x for f in others for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        self.assertFalse(
            keys
            & {x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        )

    def _gateway(self, run: Path, families: dict[str, Any], workspace: str, prefix: str,
                 searched: list[dict[str, Any]], ingested: dict[Any, list[Any]]) -> Any:  # fmt: skip
        def gateway(
            path: str, body: dict[str, Any], url: str = "", timeout: int = 0
        ) -> dict[str, Any]:
            if path == "/status":
                return {"state": str((run / "mem0").resolve()), "honcho_workspace": workspace,
                        "honcho_workspace_by_prefix": {}, "honcho_reasoning_level": None,
                        "queue": {"total": 8, "completed": 8, "pending": 0, "in_progress": 0}}  # fmt: skip
            if path == "/ingest":
                ingested.setdefault((body["provider"], body["scope"]), []).append(body["episode"])
                return {"result": {}}
            searched.append(body)
            name = body["scope"].removeprefix(f"customer:{prefix}")
            f = families[name]
            if body["provider"] == "mem0" and name in ("D4", "K32"):
                raise TimeoutError("down")
            if body.get("mode") == "messages":
                return {
                    "results": [
                        f"[2026-11-15 16:05 UTC] Agent: Item {f['target_id']}: is that the one?"
                    ]
                }
            return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

        return gateway

    def test_dev_dry_pass(self) -> None:
        from unittest import mock

        hf, today = self.hf, self.today
        setup = {**self.dev, "today": hf.cm.today_sentence(today)}
        families = setup["families"]
        cfg = PROVIDER_STAGES[hf.DEV_STAGE]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            source, run = _first_session_source(Path(tmp) / "src", families), Path(tmp) / "run"
            run.mkdir()
            shim_journal(run, "mem0", 12)
            shim_journal(run, "honcho", 40)
            searched: list[dict[str, Any]] = []
            ingested: dict[Any, list[Any]] = {}
            gateway = self._gateway(
                run, families, cfg["workspace"], cfg["prefix"], searched, ingested
            )
            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                result = hf.providers(setup, run, source, today, hf.DEV_STAGE)
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            self.assertEqual(len(ingested), 8)
            self.assertTrue(
                all("times" in e for (p, _), eps in ingested.items() if p == "honcho" for e in eps)
            )
            self.assertEqual(Counter((b["provider"], b.get("mode")) for b in searched),
                             {("honcho", None): 4, ("honcho", "messages"): 4, ("mem0", None): 4})  # fmt: skip
            query = first_message(families["D1"], "Hod")
            self.assertTrue(
                all(b["query"] == first_message(families[b["scope"][-2:]], "Hod") for b in searched)
            )
            self.assertIn("go ahead", query.casefold())
            for f in families:  # Hodr is Hod's retrieval, identical text
                hod, hodr = (
                    json.loads((run / "memory" / f"{f}-{a}.json").read_text(encoding="utf-8"))
                    for a in ("Hod", "Hodr")
                )
                self.assertEqual((hodr["text"], hodr["shared_from"]), (hod["text"], "Hod"))
            public = hf.dev_plan(setup, "dry", today, source)
            stored = run / "plan-check"
            stored.mkdir()
            hf._plan_file(stored, public, None)  # type: ignore[arg-type]
            hf._plan_file(stored, public, None)  # type: ignore[arg-type]  # resume: JSON round trip is equal
            self.assertEqual(
                [j["arm"] for j in public["jobs"]], [a for a in hf.DEV_ARMS for _ in range(4)]
            )
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}
            plan_for = {"Hs": "Y", "Nr": "ask", "Hnr": "Y", "Hodr": "ask", "Mir": "X"}
            Policy = _features_policy(families, seen, systems, plan_for)
            outcome = asyncio.run(run_jobs(setup, run, public["jobs"], lambda _: Policy([]), [run], 350, 40.0, 240,
                                           exclude_uncommitted=True, history_fn=hf.history(today, source),
                                           infra_continue=True))  # fmt: skip
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, public["jobs"])
            today_line = setup["policy"] + "\n\n" + hf.cm.today_sentence(today)
            for key, system in systems.items():
                self.assertTrue(system.startswith(ACTOR_SYSTEM + today_line), key)
            self.assertNotIn(NEUTRAL_HEADER, systems["D1-Nr"])
            self.assertNotIn(NEUTRAL_HEADER, systems["D4-Mir"])  # retrieval error: no memory block
            self.assertIn(hf.cm.session_label(today, "b"), systems["D1-Hnr"])
            self.assertIn("UTC] Agent:", systems["D1-Hs"])
            summary = hf.dev_summary(run, setup, outcome)
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            self.assertEqual(len(rows), 20)
            self.assertTrue(
                all(
                    rows[(f, "Nr")]["success"] and rows[(f, "Nr")]["restated"] == 1
                    for f in families
                )
            )
            self.assertTrue(all(rows[(f, "Hodr")]["restated"] == 1 for f in families))
            self.assertTrue(
                all(
                    rows[(f, "Hnr")]["restated"] == 0 and rows[(f, "Hs")]["success"]
                    for f in families
                )
            )
            self.assertTrue(all(rows[(f, "Mir")]["stale_commitment"] == 1 for f in families))
            self.assertEqual(summary["retrievals_ok"], {"Hod": 4, "Hs": 4, "Mir": 3})
            self.assertEqual(summary["verdict"], "PASS")

    def test_eval_dry_pass_and_incomplete_arms(self) -> None:
        from unittest import mock

        from research.honcho_features_analysis import analyse, read_csv, rows_from_runs, write_csv

        hf, today = self.hf, self.today
        tag = {
            "tag": hf.TAG,
            "commit": "2" * 40,
            "seed": eval_seed("2" * 40),
            "dev_check": "0" * 64,
        }
        setup = {**hf.prepare(tag["seed"]), "today": hf.cm.today_sentence(today)}
        families = setup["families"]
        cfg = PROVIDER_STAGES[hf.EVAL_STAGE]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            public = hf.eval_plan(setup, "dry", tag, today)
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}
            plan_for = {
                "Hs": "Y",
                "Hod": "decline",
                "Nr": "ask",
                "Hodr": "ask",
                "Mir": "X",
                "Hnr": "Y",
            }
            Policy = _features_policy(families, seen, systems, plan_for)
            options = {
                "exclude_uncommitted": True,
                "history_fn": hf.history(today, run),
                "infra_continue": True,
            }
            first = hf.cm.select(public["jobs"], "session1", [])
            outcome = asyncio.run(
                run_jobs(
                    setup, run, first, lambda _: Policy([]), [run], 3000, 400.0, 2600, **options
                )
            )
            self.assertEqual((outcome["refused"], len(first)), ([], 64))
            included = hf.cm.committed(run)
            self.assertEqual(len(included), 32)
            shim_journal(run, "mem0", 96)
            shim_journal(run, "honcho", 300)
            searched: list[dict[str, Any]] = []
            ingested: dict[Any, list[Any]] = {}
            gateway = self._gateway(
                run, families, cfg["workspace"], cfg["prefix"], searched, ingested
            )
            with mock.patch("research.provider_ingest.post", side_effect=gateway):
                result = hf.providers(setup, run, run, today, hf.EVAL_STAGE)
            self.assertEqual(result["refused"], [])
            self.assertEqual((len(ingested), len(searched)), (64, 96))
            second = hf.cm.select(public["jobs"], "sessions", included)
            self.assertEqual(len(second), 192)
            seen.clear()
            outcome = asyncio.run(
                run_jobs(
                    setup, run, second, lambda _: Policy([]), [run], 3000, 400.0, 2600, **options
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, second)  # arm blocks in priority order
            self.assertEqual([seen[i * 32]["arm"] for i in range(6)], list(hf.EVAL_ARMS))
            rows = rows_from_runs(run)
            result = analyse(rows)
            self.assertEqual(
                (result["included"], result["leakage_sessions"], result["not_run_arms"]),
                (32, 0, []),
            )
            arms = {
                a: (v["successes"], v["stale"], v["declined"], v["restated_sessions"])
                for a, v in result["arms"].items()
            }
            self.assertEqual(arms, {"Hs": (32, 0, 0, 0), "Hod": (0, 0, 32, 0), "Nr": (32, 0, 0, 32),
                                    "Hodr": (32, 0, 0, 32), "Mir": (0, 32, 0, 0), "Hnr": (32, 0, 0, 0)})  # fmt: skip
            one, two = result["family_1"]["tests"], result["family_2"]["tests"]
            self.assertEqual(one["Hs vs Hod (success)"]["arm_only"], 32)
            self.assertEqual(two["Mir vs Nr (stale)"]["arm_only"], 32)
            self.assertEqual(two["Mir vs Nr (success)"]["reference_only"], 32)
            self.assertEqual(two["Hodr vs Nr (stale)"]["p_holm"], 1.0)
            self.assertEqual(
                result["arms"]["Mir"]["memory_error"], 1
            )  # K32's Mem0 retrieval failed
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), result)
            partial = [
                r
                for r in rows
                if not (r["arm"] == "Mir" and r["family"] == "K05") and r["arm"] != "Hnr"
            ]
            cut = analyse(partial)
            self.assertEqual(cut["not_run_arms"], ["Mir", "Hnr"])
            self.assertEqual(cut["arms"]["Hnr"], {"status": "not run"})
            self.assertEqual(
                cut["family_2"]["not_run"], ["Mir vs Nr (stale)", "Mir vs Nr (success)"]
            )
            self.assertEqual(
                set(cut["family_2"]["tests"]), {"Hodr vs Nr (stale)", "Hodr vs Nr (success)"}
            )


if __name__ == "__main__":
    unittest.main()
