"""Study 4: the necessary-memory harness, provider arms and evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from research.harness.commitment_pilot import (
    AMEND_HASHES,
    BUDGETS,
    CONFIRM,
    EVAL_ARMS,
    EVAL_STAGE,
    HISTORY_MAX,
    HONCHO_WORKSPACE,
    NEUTRAL_HEADER,
    OPENING,
    PHASE1,
    PROVIDER_ARMS,
    PROVIDER_STAGES,
    STAGE_BUDGET,
    STOP,
    FatalStop,
    ScriptedCustomer,
    artifact_problems,
    eval_seed,
    final_reports,
    first_message,
    frozen_inputs,
    identified,
    journal_rows,
    leaks,
    oracle,
    pilot_ledger,
    plan,
    prepare,
    provider_gates,
    provider_phase,
    provider_scope,
    retrieve_memories,
    run_jobs,
    select_jobs,
    session_one_artifacts,
    session_system,
    smoke_passed,
    start_refusals,
    tag_state,
    template_pool,
    transcript,
)
from research.harness.tau_copilot import MEMORY_HEADER
from research.tests.fixtures import (
    FAMILY,
    OTHER,
    REAL_EVAL,
    SETUP,
    TARGET,
    FakeBackend,
    JournalingBackend,
    act,
    exchange,
    proposal,
    session,
)
from research.tests.support import billed, shim_journal, slow


class CommitmentPilotTests(unittest.TestCase):
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
        flow = [
            lookup,
            proposal(TARGET),
            act(text="Which card should I use for the payment?"),
            act(text=f"To confirm: item {TARGET['item_id']}, Visa card. Please reply yes."),
            exchange(TARGET["item_id"]),
            act(text="Your exchange has been submitted."),
        ]
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
                [
                    f"Item {item}. Reply yes?",
                    f"I still need an explicit yes for item {item}.",
                    "The exchange has been processed.",
                ],
                [
                    f"Item {item}. Which card should I use for the payment?",
                    f"Final check: item {item} on your Visa card. Please reply yes.",
                    done,
                ],
                [
                    f"Before I submit the exchange to item {item}, please confirm; once submitted it is final.",
                    "I have submitted the exchange.",
                ],
                [
                    f"Summary: the {options} option. Shall I proceed?",
                    f"That is item {item}. Reply yes.",
                    done,
                ],
                [
                    f"Which would you like? {listing}",
                    f"Proceeding with item {item}? Reply yes.",
                    done,
                ],
            ]

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
        message = (
            f"Item to exchange: {current}. New item: "
            f"{', '.join(TARGET['options'].values())} (item ID {TARGET['item_id']}). Proceed?"
        )
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
            call = {
                "name": "exchange_delivered_order_items",
                "arguments": {
                    "item_ids": [FAMILY["current"]["item_id"]],
                    "new_item_ids": [item_id],
                },
            }
            messages = [
                {"role": "user", "content": CONFIRM if confirm else "ok"},
                {"role": "assistant", "tool_calls": [call]},
            ]
            return oracle(FAMILY, messages, True, item_id == FAMILY["target_id"])

        self.assertTrue(run(FAMILY["target_id"], True)["success"])
        wrong = run(OTHER["item_id"], True)
        self.assertEqual((wrong["success"], wrong["wrong_variant_attempts"]), (False, 1))
        unconfirmed = run(FAMILY["target_id"], False)
        self.assertEqual((unconfirmed["success"], unconfirmed["unauthorized_attempts"]), (False, 1))

    def test_transcript_keeps_dialogue_only(self) -> None:
        messages = [
            {"role": "user", "content": f"Hi {STOP}"},
            {"role": "assistant", "content": None, "tool_calls": [{"name": "x"}]},
            {"role": "tool", "content": "{payload}"},
            {"role": "assistant", "content": "Done."},
        ]
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
            # The un-journaled call never settles; skip the settle wait a live run allows.
            with mock.patch("research.harness.commitment_pilot.SETTLE_SECONDS", 0):
                refusals = start_refusals([Path(tmp)])
            self.assertTrue(any(r.startswith("un-journaled") for r in refusals))

    def test_v4_budget_is_separate_and_phase_two_needs_smoke(self) -> None:
        self.assertEqual(BUDGETS[STAGE_BUDGET["pilot-v4"]]["stages"], ("pilot-v4",))
        self.assertEqual(plan("n", "pilot-v4")["request_cap"], 264)
        self.assertEqual(plan("n", "pilot-v4")["credit_stop"], 40.0)
        self.assertEqual(
            {(j["family"], j["arm"]) for j in PHASE1},
            {("C1", "S1"), ("C2", "S1"), ("C1", "R"), ("C2", "R")},
        )
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


class InfrastructurePolicyTests(unittest.TestCase):
    S1: ClassVar[dict[str, Any]] = {"session": 1, "family": "C2", "arm": "S1"}
    AGREE: ClassVar[list[str]] = [
        act(text="Several options are in stock."),
        act(text=f"Confirming item {TARGET['item_id']}."),
    ]

    def run_jobs(self, scripts: list[list[str]], jobs: list[dict], directory: Path) -> dict:
        queue = list(scripts)
        return asyncio.run(
            run_jobs(
                SETUP,
                directory,
                jobs,
                lambda journal: JournalingBackend(queue.pop(0), journal),
                [directory],
            )
        )

    def test_timeout_and_transport_errors_get_one_fresh_reattempt(self) -> None:
        for failure in ("TIMEOUT", "TRANSPORT", "CREDENTIAL"):
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


class ProviderPilotTests(unittest.TestCase):
    """Pilot v5 (Mem0 / Honcho arms) with fake gateways and a scripted fake actor."""

    def test_fresh_scopes_and_gateway_isolation_settings(self) -> None:
        from research.harness import memory_gateway as gateway

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
                messages = [
                    {"role": "assistant", "content": OPENING},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"name": "get_user_details"}],
                    },
                    {"role": "tool", "content": "payload"},
                    {"role": "user", "content": f"agreed {name} ###STOP###"},
                ]
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
            self.assertEqual(
                [(r["provider"], r["scope"], r["text"]) for r in failed],
                [("honcho", provider_scope("C2"), "")],
            )
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
            with mock.patch("research.harness.provider_ingest.post", return_value=v1) as post:
                result = provider_phase(SETUP, Path(tmp), {})
            self.assertEqual(len(result["refused"]), 2)
            self.assertEqual(post.call_count, 1)

    def test_integration_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                {
                    "provider": p,
                    "scope": provider_scope(f),
                    "episode": f"cmp-p5-{f}-s1",
                    "status": "ok",
                }
                for p in PROVIDER_ARMS.values()
                for f in SETUP["families"]
            ]
            (root / "ingest.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
            )
            (root / "honcho-queue.json").write_text(
                json.dumps({"total": 8, "completed": 8, "pending": 0, "in_progress": 0}),
                encoding="utf-8",
            )
            failing = {"C2"}
            retrieve_memories(
                SETUP,
                root,
                lambda p, s, q: (
                    (_ for _ in ()).throw(OSError("x"))
                    if p == "honcho" and s[-2:] in failing
                    else ["memo"]
                ),
            )
            reports = [
                {"arm": a, "family": f, "leakage": [], "success": False}
                for a in PROVIDER_ARMS
                for f in SETUP["families"]
            ]
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
        self.assertEqual(
            (provider_scope("E01", cfg["prefix"]), cfg["workspace"]),
            ("customer:cmp-eval-E01", "commitment-eval-v1"),
        )
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
            outcome = asyncio.run(
                run_jobs(
                    self.eval_setup,
                    Path(tmp),
                    jobs,
                    silent,
                    [Path(tmp)],
                    2816,
                    310.0,
                    2304,
                    exclude_uncommitted=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(
                [r["family"] for r in final_reports(Path(tmp))], [family]
            )  # E-family found
            self.assertEqual(frozen_inputs(Path(tmp), "cmp-eval-", exclude=True), {})
            report = {
                "session": 1,
                "family": "E02",
                "arm": "S1",
                "commitment": True,
                "messages": [{"role": "user", "content": "agreed"}],
            }
            Path(tmp, "E02-s1-S1-a1.json").write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(list(frozen_inputs(Path(tmp), "cmp-eval-", exclude=True)), ["E02"])
            with self.assertRaises(FatalStop):
                frozen_inputs(Path(tmp), "cmp-eval-", [family])
            shim_journal(
                Path(tmp),
                "honcho",
                400,
                *[
                    e
                    for i in range(1, 21)
                    for e in ({"event": "copilot-request-started", "call_id": i}, billed(i))
                ],
            )
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
        from research.analysis.commitment_analysis import analyse

        def row(family: str, arm: str, ok: bool, **memory: Any) -> dict[str, Any]:
            return {
                "family": family,
                "session": 2,
                "arm": arm,
                "success": ok,
                "commitment": "",
                "credits": 0.5,
                "requests": 6,
                "lookups": 3,
                "proposals_before_consent": 1,
                "wrong_variant_attempts": 0,
                "unauthorized_attempts": 0,
                "leakage": False,
                "memory_error": memory.get("error", ""),
                "memory_has_target_id": memory.get("has_id", ""),
                "memory_has_target_options": "",
            }

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
            rows += [
                row(f, "N", i == 0),
                row(f, "Hn", True),
                row(f, "Hc", i != 1),
                row(f, "M", i != 2, has_id=i != 3),
                row(f, "Ho", i < 6, error=i == 8, has_id=i < 4),
            ]
        result = analyse(rows, planned_families=10)
        self.assertEqual(
            (result["included"], result["excluded"], result["complete"]), (9, ["E09"], True)
        )
        self.assertEqual(result["arms"]["N"]["successes"], 1)
        self.assertEqual(
            {k: result["primary"][k] for k in ("wins", "losses", "p")},
            {"wins": 8, "losses": 0, "p": round(2 / 2**8, 4)},
        )
        sec = result["secondaries"]
        self.assertEqual((sec["Ho vs Hn"]["losses"], sec["Ho vs Hn"]["p"]), (3, 0.25))
        self.assertEqual(sec["Ho vs Hn"]["p_holm"], 0.75)
        self.assertEqual(result["provider_memory"]["M"]["lacking_id_recovered"], [1, 1])
        self.assertEqual(result["provider_memory"]["Ho"]["lacking_id_recovered"], [2, 4])
        self.assertEqual(result["provider_memory"]["Ho"]["retrieval_errors"], 1)


@unittest.skipUnless((REAL_EVAL / "plan.json").exists(), "private eval-v1 run not present")
class EvalResumeDryPassTests(unittest.TestCase):
    """Amendment 1: the whole resume path over a copy of the real eval-v1 run, zero model calls.
    Fails on a2a2c1d, whose report discovery ignored E-prefixed families."""

    @slow
    def test_end_to_end_over_a_copy_of_the_real_run(self) -> None:
        from unittest import mock

        from research.analysis.commitment_analysis import analyse, rows_from_runs

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
                    return {
                        "state": str((run / "mem0").resolve()),
                        "honcho_workspace": "commitment-eval-v1",
                        "honcho_reasoning_level": None,
                        "queue": {"total": 32, "completed": 32, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    ingested[(body["provider"], body["scope"])] = body["episode"]
                    return {"result": {"events": 1}}
                lines = ingested[(body["provider"], body["scope"])]["lines"]
                return {"results": [t for speaker, t in lines if speaker == "agent"][-2:]}

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(setup, run, inputs, EVAL_STAGE)
            self.assertEqual(providers["refused"], [])
            self.assertEqual(
                sorted(ingested),
                sorted(
                    (p, provider_scope(f, "cmp-eval-"))
                    for p in PROVIDER_ARMS.values()
                    for f in inputs
                ),
            )
            self.assertTrue(
                all(
                    e["id"] == f"{s.removeprefix('customer:')}-s1" and "outcome" not in e
                    for (_, s), e in ingested.items()
                )
            )
            self.assertEqual(len(providers["retrievals"]), 64)

            jobs = select_jobs(stored["jobs"], "sessions", inputs)
            self.assertEqual(jobs, [j for j in stored["jobs"] if j["session"] == 2])
            self.assertEqual(len(jobs), 160)
            seen: list[tuple[dict[str, Any], FakeBackend]] = []

            class Capture(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event == "commitment-session-started":
                        seen.append(({k: fields[k] for k in ("session", "family", "arm")}, self))

            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    jobs,
                    lambda _: Capture([act(text="How can I help?")] * 12),
                    [run],
                    2816,
                    310.0,
                    2304,
                    exclude_uncommitted=True,
                )
            )
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


if __name__ == "__main__":
    unittest.main()
