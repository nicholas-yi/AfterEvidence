"""Harness logic that must hold for every study, tested without the pinned benchmark or the
Copilot SDK so CI runs it: scripted and restating customers, leakage checks, the request and
credit ledger, shim checks and the quota guard. Families are synthetic fixtures with the same
shape as the generated ones (fake IDs; no benchmark data)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from research import honcho_features as hf
from research.commitment_pilot import (
    CONFIRM,
    CONSENT,
    HISTORY_MAX,
    NEUTRAL_HEADER,
    OPENING,
    RESTATEMENT,
    STOP,
    FatalStop,
    ScriptedCustomer,
    identified,
    journal_rows,
    leaks,
    pilot_ledger,
    session_system,
    shim_problems,
    start_refusals,
)
from research.copilot_backend import quota_problem
from research.tau_copilot import MEMORY_HEADER


def cp_arm_instruction() -> str:
    from research.commitment_pilot import ARM_INSTRUCTIONS

    return ARM_INSTRUCTIONS["Tp"]


def family(
    name: str, ids: tuple[str, ...], target: int, rejected: int, stale: int
) -> dict[str, Any]:
    colours = ("black", "white", "red", "blue", "green")
    sizes = ("small", "large", "medium", "compact", "tall")
    alternatives = [
        {"item_id": i, "options": {"color": colours[n], "size": sizes[n]}}
        for n, i in enumerate(ids)
    ]
    return {
        "family": name,
        "product": "Desk Lamp",
        "user_id": f"user_{name.lower()}",
        "first": "Ada",
        "last": "Quill",
        "email": "ada.quill@example.com",
        "order_id": "#W0000001",
        "payment_id": "credit_card_0000001",
        "brand": "visa",
        "last_four": "0001",
        "current": {"item_id": "9000000000", "options": {"color": "grey", "size": "small"}},
        "alternatives": alternatives,
        "target_id": ids[target],
        "rejected_id": ids[rejected],
        "stale_id": ids[stale],
    }


FAMILIES = [
    family("F1", ("1000000001", "1000000002", "1000000003", "1000000004", "1000000005"), 0, 1, 2),
    family("F2", ("2000000001", "2000000002", "2000000003", "2000000004"), 3, 0, 1),
]
F = FAMILIES[0]
TARGET = next(v for v in F["alternatives"] if v["item_id"] == F["target_id"])
OTHER = next(v for v in F["alternatives"] if v["item_id"] not in (F["target_id"], F["stale_id"]))


def billed(call_id: int) -> dict[str, Any]:
    usage = {"usage": {"input_tokens": 1, "output_tokens": 1}, "requests": {"count": 1}}
    return {
        "event": "copilot-request-completed",
        "call_id": call_id,
        "metrics": {
            "ai_credits_status": "complete",
            "total_nano_aiu": 1e8,
            "model_metrics": {"m": usage},
        },
    }


def shim_journal(directory: Path, label: str, cap: int, *rows: dict[str, Any]) -> None:
    (directory / "shims").mkdir(parents=True, exist_ok=True)
    events = [{"event": "shim-started", "label": label, "request_limit": cap}, *rows]
    (directory / "shims" / f"{label}.calls.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )


class CustomerTests(unittest.TestCase):
    def test_customer_never_restates_target_except_in_r(self) -> None:
        for arm in ("N", "Hc", "Hn", "R"):
            customer = ScriptedCustomer(F, 2, arm)
            opening = customer.reply("Hi! How can I help you today?")
            clarify = customer.reply("Which option would you like?")
            named = bool(leaks(F, "N", "", None, [opening + clarify]))
            self.assertEqual(named, arm == "R", arm)
        customer = ScriptedCustomer(F, 2, "N")
        customer.reply("hello")
        self.assertEqual(customer.reply(f"Item {OTHER['item_id']}, proceed?"), CONSENT)
        self.assertIn(STOP, customer.reply("The exchange has been processed."))
        restating = ScriptedCustomer(F, 2, "R")
        restating.reply("hello")
        self.assertIn("not the one", restating.reply(f"Item {OTHER['item_id']}, proceed?"))
        self.assertEqual(restating.reply(f"Item {TARGET['item_id']}, proceed?"), CONFIRM)

    def test_session_two_feedback_is_target_blind_outside_r(self) -> None:
        # Elimination leak: target-dependent consent would let an N agent search IDs one by one.
        for fam in FAMILIES:
            ids = [v["item_id"] for v in fam["alternatives"]]
            for arm in ("N", "Hc", "Hn"):
                single, multiple = set(), set()
                for item in ids:
                    customer = ScriptedCustomer(fam, 2, arm)
                    customer.reply("hello")
                    single.add(customer.reply(f"Shall I exchange it for item {item}?"))
                    self.assertTrue(customer.confirmed)
                    pair = ScriptedCustomer(fam, 2, arm)
                    pair.reply("hello")
                    other = ids[(ids.index(item) + 1) % len(ids)]
                    multiple.add(pair.reply(f"Options: item {item} or item {other}?"))
                    self.assertFalse(pair.confirmed)
                self.assertEqual(single, {CONSENT}, (fam["family"], arm))
                self.assertEqual(len(multiple), 1, (fam["family"], arm))

    def test_restating_rule_is_structural(self) -> None:
        x, y = F["stale_id"], F["target_id"]
        other, current = OTHER["item_id"], F["current"]["item_id"]
        fires = [
            "Which item did we agree on last time?",  # question
            "I have no record of an agreement. Please tell me which variant you want.",
            "Please choose one of the available options.",  # no question mark
            f"Available variants: item {x} and item {other}.",  # two IDs, one of them X
            f"The current item is {current}; I need the replacement you want.",  # not an alternative
        ]
        for text in fires:
            customer = hf.RestatingCustomer(F, 2, "Nr")
            self.assertFalse(identified(F, customer.reply(OPENING)))  # never unprompted
            reply = customer.reply(text)
            self.assertTrue(reply.startswith(RESTATEMENT), text)
            self.assertEqual(identified(F, reply), {y})  # Y with its ID; never X
            self.assertNotIn(x, reply)
        for item in (x, y, other):  # exactly one alternative: the base target-blind consent
            customer = hf.RestatingCustomer(F, 2, "Mir")
            customer.reply(OPENING)
            self.assertEqual(customer.reply(f"Shall I exchange it for item {item}?"), CONSENT)
        customer = hf.RestatingCustomer(F, 2, "Hodr")
        customer.reply(OPENING)
        replies = [customer.reply("Which item?") for _ in range(3)]
        self.assertEqual([r.startswith(RESTATEMENT) for r in replies], [True, True, False])
        self.assertEqual(replies[2], hf.ASK_ITEM)
        for arm in ("Hod", "Hs", "Hn"):  # other arms: unchanged and target-blind
            seen = {}
            for item in (x, y):
                customer = hf.RestatingCustomer(F, 2, arm)
                customer.reply(OPENING)
                self.assertEqual(customer.reply("Which item did we agree on?"), hf.ASK_ITEM)
                seen[item] = customer.reply(f"Item {item}: shall I proceed?")
            self.assertEqual(seen[x], seen[y])

    def test_poisoned_customer_plants_z_only_in_the_disowned_1b_message(self) -> None:
        from research.followups import PoisonCustomer

        y, z = F["target_id"], F["stale_id"]
        first = PoisonCustomer(F, 1, "S1a")  # 1a agrees Y, never mentions Z
        texts = [first.reply("Hello!"), first.reply("Several options are in stock.")]
        texts.append(first.reply(f"Confirming item {y}."))
        self.assertTrue(first.agreed and first.done)
        self.assertFalse(any(z in t for t in texts))
        second = PoisonCustomer(F, 1, "S1b")  # 1b quotes Z, disowns it, never names Y
        texts = [second.reply("Hello!"), second.reply("Noted; nothing will change.")]
        self.assertIn(z, texts[0])
        self.assertIn("don't want it", texts[0])
        self.assertFalse(any(y in t for t in texts))
        self.assertTrue(second.agreed and second.done)
        replies = {}
        for item in (y, z):  # session 2: never names either; consent is target-blind
            customer = PoisonCustomer(F, 2, "Hn")
            opening = customer.reply(OPENING)
            self.assertFalse({y, z} & identified(F, opening))
            replies[item] = customer.reply(f"Shall I exchange it for item {item}?")
        self.assertEqual(replies[y], replies[z])


class LeakageTests(unittest.TestCase):
    def test_headers_history_limit_and_isolation(self) -> None:
        policy = "POLICY"
        self.assertIn("\n\n" + MEMORY_HEADER + "dialogue", session_system(policy, "Hc", "dialogue"))
        self.assertIn(
            "\n\n" + NEUTRAL_HEADER + "dialogue", session_system(policy, "Hn", "dialogue")
        )
        self.assertNotIn("dialogue", session_system(policy, "N", "dialogue"))
        with self.assertRaises(FatalStop):
            session_system(policy, "Hn", "x" * (HISTORY_MAX + 1))

    def test_leak_check_allows_only_the_restatement(self) -> None:
        restatement = f"{RESTATEMENT}the item {F['target_id']}."
        self.assertEqual(leaks(F, "Nr", "system", None, ["Hi.", restatement]), [])
        self.assertTrue(leaks(F, "Hod", "system", None, ["Hi.", restatement]))  # not restating
        self.assertTrue(leaks(F, "Nr", "system", None, [restatement]))  # never in the opening
        self.assertTrue(leaks(F, "Nr", "system", None, ["Hi.", f"It's item {F['target_id']}."]))
        self.assertTrue(
            leaks(F, "Nr", "system", None, ["Hi.", f"{RESTATEMENT}item {F['stale_id']}."])
        )
        self.assertTrue(
            leaks(F, "Hn", f"system {F['stale_id']}", None, ["Hi."])
        )  # X outside memory


class LedgerTests(unittest.TestCase):
    def test_aborted_is_charged_and_unjournaled_mismatch_stops(self) -> None:
        aborted = [
            {"event": "copilot-request-started", "call_id": 1, "_journal": "a"},
            {"event": "copilot-request-aborted", "call_id": 1, "_journal": "a"},
        ]
        self.assertEqual(pilot_ledger(aborted)["reasons"], [])
        self.assertEqual(pilot_ledger(aborted)["charged_credits"], 1.0)
        self.assertTrue(pilot_ledger(aborted, credit_stop=0.5)["reasons"])
        silent = [{"event": "copilot-request-started", "call_id": 1, "_journal": "b"}]
        self.assertTrue(pilot_ledger(silent)["reasons"][0].startswith("un-journaled"))

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

    def test_in_flight_provider_call_settles_but_a_missing_record_stops(self) -> None:
        import threading
        from unittest import mock

        from research import commitment_pilot as cp

        started = {"event": "copilot-request-started", "call_id": 1}
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.multiple(cp, SETTLE_SECONDS=2.0, SETTLE_POLL=0.05),
        ):
            root = Path(tmp)
            shim_journal(root, "honcho", 50, started)
            journal = root / "shims" / "honcho.calls.jsonl"

            def finish() -> None:
                with journal.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(billed(1)) + "\n")

            timer = threading.Timer(0.3, finish)
            timer.start()
            self.assertEqual(start_refusals([root], 100, 25.0), [])  # waited for the call
            timer.join()
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.multiple(cp, SETTLE_SECONDS=0.2, SETTLE_POLL=0.05),
        ):
            shim_journal(Path(tmp), "honcho", 50, started)
            refused = start_refusals([Path(tmp)], 100, 25.0)
            self.assertTrue(refused[0].startswith("un-journaled mismatch"))

    def test_recovery_closes_only_cut_sessions_and_the_ledger_balances(self) -> None:
        from research.run_recovery import recover

        started = {"event": "copilot-request-started", "call_id": 2, "session": "Q1-s2-Hn"}
        head = {"event": "session-start", "session": "Q1-s2-Hn", "family": "Q1", "arm": "Hn"}
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            cut = run / "Q1-s2-Hn-a1.calls.jsonl"
            cut.write_text(
                "\n".join(json.dumps(r) for r in (head, started)) + "\n", encoding="utf-8"
            )
            done = run / "Q2-s2-Hn-a1.calls.jsonl"
            done.write_text(json.dumps(head) + "\n", encoding="utf-8")
            (run / "Q2-s2-Hn-a1.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                recover(run, "process died", " ")
            records = recover(run, "process died", "owner: recover_all")
            self.assertEqual(
                [(r["session"], r["aborted_calls"]) for r in records], [("Q1-s2-Hn-a1", [2])]
            )
            report = json.loads((run / "Q1-s2-Hn-a1.json").read_text(encoding="utf-8"))
            self.assertTrue(report["infra_failure"] and report["attempt"] == 1)
            self.assertEqual((run / "Q2-s2-Hn-a1.json").read_text(encoding="utf-8"), "{}")
            rows = [json.loads(x) | {"_journal": "j"} for x in cut.read_text().splitlines()]
            ledger = pilot_ledger(rows)
            self.assertEqual((ledger["reasons"], ledger["charged_credits"]), ([], 1.0))
            self.assertEqual(recover(run, "again", "owner: recover_all"), [])  # idempotent
            history = json.loads((run / "recoveries.json").read_text(encoding="utf-8"))
            self.assertEqual([h["owner_decision"] for h in history], ["owner: recover_all"] * 2)

    def test_copilot_transport_errors_are_infrastructure(self) -> None:
        from research.commitment_pilot import transport_error

        class JsonRpcError(Exception):
            pass

        JsonRpcError.__module__ = "copilot._jsonrpc"
        self.assertTrue(transport_error(JsonRpcError("token lookup timed out")))
        self.assertFalse(transport_error(ValueError("malformed action")))
        self.assertFalse(transport_error(KeyError("item")))

    def test_refuses_overage_low_and_unknown_quota(self) -> None:
        def snapshot(**quota: object) -> SimpleNamespace:
            premium = {"premium_interactions": SimpleNamespace(**quota)} if quota else {}
            return SimpleNamespace(quota_snapshots=premium)

        self.assertIsNone(quota_problem(snapshot(remaining_percentage=99.8, overage=0.0)))
        self.assertIn("unavailable", quota_problem(snapshot()) or "")
        self.assertIn(
            "overage", quota_problem(snapshot(remaining_percentage=99.0, overage=1.0)) or ""
        )
        self.assertIn(
            "below 50%", quota_problem(snapshot(remaining_percentage=49.9, overage=0.0)) or ""
        )


def session_one(root: Path, name: str, orders: str) -> None:
    for order in orders:
        messages = [
            {"role": "assistant", "content": OPENING},
            {"role": "user", "content": f"Customer line {order}."},
            {"role": "assistant", "content": f"Agent line {order}."},
        ]
        report = {
            "session": 1,
            "family": name,
            "arm": f"S1{order}",
            "commitment": True,
            "messages": messages,
        }
        (root / f"{name}-s1-S1{order}-a1.json").write_text(json.dumps(report), encoding="utf-8")


class GapsTests(unittest.TestCase):
    """Studies 13-18: generalized dated history, the new customers, the address oracle, app
    records, the Tp instruction and the analysis (synthetic fixtures)."""

    today = __import__("datetime").date(2026, 11, 20)

    def test_two_session_history_reproduces_studies_6_to_12(self) -> None:
        from research import changed_mind as cm
        from research import gaps
        from research.honcho_stage3 import summarizer_input

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_one(root, "D1", "ab")
            session_one(root, "D2", "a")  # no 1b agreement: excluded everywhere
            self.assertEqual(gaps.committed(root, gaps.TWO), cm.committed(root))
            self.assertEqual(
                gaps.history_text(root, "D1", self.today, gaps.TWO),
                cm.dated_history_text(root, "D1", self.today),
            )
            for order in "ab":
                self.assertEqual(
                    gaps.history_text(root, "D1", self.today, gaps.TWO, order),
                    summarizer_input(root, "D1", self.today, order),
                )
            old = cm.dated_inputs(root, self.today, "p-")["D1"]
            new = gaps.episodes(root, "D1", self.today, gaps.TWO, "p-")
            self.assertEqual(old["episodes_honcho"], new["honcho"])
            plain = [{k: v for k, v in e.items() if k != "time"} for e in new["labelled"]]
            self.assertEqual(old["episodes_mem0"], plain)
            self.assertEqual(new["labelled"][1]["time"], new["honcho"][1]["times"][0])
            session_one(root, "V01", "abcde")
            five = gaps.history_text(root, "V01", self.today, gaps.FIVE)
            labels = [gaps.label(self.today, gaps.FIVE, o) for o in "abcde"]
            self.assertEqual([five.index(x) for x in labels], sorted(five.index(x) for x in labels))
            self.assertNotIn(
                "Customer line c", gaps.history_text(root, "V01", self.today, gaps.FIVE, "b")
            )

    def test_long_history_customer_changes_twice_and_stays_target_blind(self) -> None:
        from research import gaps

        f = gaps.roles(gaps.LH, {**F, "target_position": 0})
        x, y, w = f["first_id"], f["stale_id"], f["target_id"]
        self.assertEqual(len({x, y, w, f["rejected_id"]}), 4)
        first = gaps.LongHistoryCustomer(f, 1, "S1a")
        first.reply(OPENING)
        self.assertIn(gaps.cp._option(f, x), first.reply("Several options are in stock."))
        first.reply(f"Confirming item {x}.")
        self.assertTrue(first.agreed)
        for phase in ("S1b", "S1d"):
            question = gaps.LongHistoryCustomer(f, 1, phase)
            self.assertFalse(identified(f, question.reply(OPENING)))
            self.assertIn(STOP, question.reply("It was delivered on Monday."))
            self.assertTrue(question.agreed)
        for phase, wanted, earlier in (("S1c", y, x), ("S1e", w, y)):
            change = gaps.LongHistoryCustomer(f, 1, phase)
            self.assertEqual(identified(f, change.reply(OPENING)), set())
            self.assertIn("changed my mind", change.reply(f"Item {earlier}, as before?"))
            change.reply(f"Confirming item {wanted}.")
            self.assertTrue(change.agreed, phase)
        replies = set()
        for item in (x, y, w):
            customer = gaps.LongHistoryCustomer(f, 2, "Hn")
            self.assertFalse(identified(f, customer.reply(OPENING)))
            replies.add(customer.reply(f"Shall I exchange it for item {item}?"))
        self.assertEqual(replies, {CONSENT})

    def address_family(self) -> dict[str, Any]:
        from research import gaps

        f = {**F, "family": "A01", "target_position": 1}
        addresses = gaps.make_addresses(f, "test")
        f.update(
            alternatives=addresses,
            target_id=addresses[1]["item_id"],
            rejected_id=addresses[2]["item_id"],
        )
        return gaps.roles(gaps.AC, f)

    def test_address_customer_and_oracle(self) -> None:
        from research import gaps

        f = self.address_family()
        x, y = f["stale_id"], f["target_id"]
        line = {i: gaps.alternative(f, i)["options"]["address1"] for i in (x, y)}
        first = gaps.AddressCustomer(f, 1, "S1a")
        self.assertEqual(identified(f, first.reply(OPENING)), {x})
        first.reply(f"Noted: {gaps.address_text(f, x)}.")
        self.assertTrue(first.agreed)
        second = gaps.AddressCustomer(f, 1, "S1b")
        self.assertEqual(identified(f, second.reply(OPENING)), {y})
        self.assertIn("not it", second.reply(f"So {line[x]}?"))
        second.reply(f"Noted: {line[y]}.")
        self.assertTrue(second.agreed)
        replies = set()
        for item in [v["item_id"] for v in f["alternatives"]]:
            customer = gaps.AddressCustomer(f, 2, "N")
            self.assertFalse(identified(f, customer.reply(OPENING)))
            self.assertFalse(identified(f, customer.reply("Which address did we agree?")))
            replies.add(
                customer.reply(f"Change it to {gaps.alternative(f, item)['options']['address1']}?")
            )
        self.assertEqual(replies, {gaps.ADDRESS_CONSENT})
        reports = {
            "Your shipping address change on order #W1 is complete. The order is still pending.": True,
            "The shipping address has been updated to 1 Elm Court.": True,
            "Done: the address was successfully changed.": True,
            "I'll update the address now.": False,
            "Once the change is made, it will be complete.": False,
        }
        for text, ends in reports.items():
            customer = gaps.AddressCustomer(f, 2, "N")
            customer.reply(OPENING)
            customer.reply(f"Change it to {line[y]}?")
            self.assertEqual(STOP in customer.reply(text), ends, text)

        def run(item: str, before: bool = False) -> dict[str, Any]:
            call = {
                "name": "modify_pending_order_address",
                "arguments": gaps.address_action({**f, "target_id": item})["arguments"],
            }
            consent = {"role": "user", "content": gaps.ADDRESS_CONSENT}
            act_ = {"role": "assistant", "tool_calls": [call]}
            messages = [act_, consent] if before else [consent, act_]
            return gaps.address_oracle(f, messages, True, item == y)

        self.assertTrue(run(y)["success"])
        self.assertEqual((run(x)["success"], run(x)["wrong_variant_attempts"]), (False, 1))
        self.assertEqual(
            gaps.executed(
                f,
                [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "name": "modify_pending_order_address",
                                "arguments": {"address1": line[x]},
                            }
                        ],
                    }
                ],
            ),
            [x],
        )
        self.assertFalse(run(y, before=True)["success"])

    def test_app_records_tool_instruction_and_injected_record(self) -> None:
        from research import gaps

        f = gaps.roles(gaps.GX, {**F, "family": "D1", "target_position": 0})
        x, y, z = f["stale_id"], f["target_id"], f["injected_id"]
        record = gaps.injected_record(f, self.today)
        self.assertIn(z, record)
        self.assertFalse({x, y} & identified(f, record))
        steps = [
            {"after": "a", "facts": [f"Agreed item {x}."]},
            {"after": "b", "facts": [f"Changed to item {y}."]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            session_one(Path(tmp), "D1", "ab")
            text = {
                arm: gaps.app_memory(gaps.GX, arm, f, steps, Path(tmp), self.today)["text"]
                for arm in gaps.APP_ARMS
            }
        self.assertTrue(y in text["Fd"] and x not in text["Fd"] and z not in text["Fd"])
        self.assertTrue(z in text["Fz"] and y in text["Fz"])
        self.assertTrue(x in text["Fs"] and y not in text["Fs"])
        self.assertTrue(text["Fsh"].index(x) < text["Fsh"].index("Earlier session"))
        self.assertIn(cp_arm_instruction(), session_system("P", "Tp", None))
        self.assertNotIn(cp_arm_instruction(), session_system("P", "Tn", None))
        self.assertNotIn(cp_arm_instruction(), session_system("P", "Hn", "dialogue"))
        with self.assertRaises(FatalStop):
            session_system("P", "Hn", "x" * (HISTORY_MAX + 1))
        self.assertIn(
            "x" * (HISTORY_MAX + 1), session_system("P", "Hn", "x" * (HISTORY_MAX + 1), 16000)
        )

    def test_review_packet_strata_and_scores(self) -> None:
        from research import oracle_review as orv

        z = F["alternatives"][3]["item_id"]  # distinct from the target, rejected and stale items
        f = {**F, "injected_id": z}

        def report(item: str | None, success: bool = False) -> dict[str, Any]:
            calls = (
                [{"name": "exchange_delivered_order_items", "arguments": {"new_item_ids": [item]}}]
                if item
                else []
            )
            messages = [{"role": "assistant", "tool_calls": calls}]
            return {"success": success, "mutations": len(calls), "messages": messages}

        self.assertEqual(orv.stratum(report(F["target_id"], True), f), "succeeded")
        self.assertEqual(orv.stratum(report(F["stale_id"]), f), "executed_superseded")
        self.assertEqual(orv.stratum(report(z), f), "executed_superseded")
        self.assertEqual(orv.stratum(report(None), f), "declined")
        self.assertEqual(orv.stratum(report(F["rejected_id"]), f), "other_failure")
        self.assertEqual(orv.kappa(["yes", "no", "yes"], ["yes", "no", "yes"]), 1.0)
        self.assertEqual(orv.kappa(["yes", "no"], ["no", "yes"]), -1.0)
        self.assertIsNone(orv.kappa(["yes"], ["yes"]))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "oracle.csv").write_text(
                "session,success\nR001,True\nR002,False\nR003,True\n", encoding="utf-8"
            )
            (root / "a.csv").write_text(
                "session,q1_outcome,q2_customer\nR001,yes,yes\nR002,yes,no\nR003,unclear,yes\n",
                encoding="utf-8",
            )
            (root / "b.csv").write_text(
                "session,q1_outcome,q2_customer\nR001,yes,yes\nR002,no,yes\nR003,yes,yes\n",
                encoding="utf-8",
            )
            result = orv.score(root, [root / "a.csv", root / "b.csv"])
        self.assertEqual(
            (result["a.csv"]["answered"], result["a.csv"]["agree_with_oracle"]), (2, 1)
        )
        self.assertEqual(result["a.csv"]["disagreements"], ["R002"])
        self.assertEqual(result["a.csv"]["customer_script_no"], ["R002"])
        self.assertEqual(result["b.csv"]["agree_with_oracle"], 3)
        self.assertIn("q1_outcome", result["between_reviewers"])

    def test_reported_done_ends_on_reports_only(self) -> None:
        from research import gaps

        reports = {
            "Your exchange for order #W1 has been requested: the lamp will be exchanged for item 2.": True,
            "The exchange has already been processed, so I have not made a second one.": True,
            "The address change has been applied.": True,
            "Your exchange request is confirmed for order #W1.": True,
            "Once the exchange is complete, you will get an email.": False,
            "Order #W1 (delivered; no exchange has been processed on it yet).": False,
            "Please confirm that the item list above is complete.": False,
            "After it is processed the status will change.": False,
            "I'll submit the exchange now.": False,
        }
        for text, done in reports.items():
            self.assertEqual(gaps.reported_done(text.casefold()), done, text)
        customer_type = gaps.reporting(hf.RestatingCustomer)
        self.assertEqual(customer_type.__name__, "RestatingCustomer")
        text = "The exchange is now requested for order #W1; it will arrive soon."  # not cp.DONE
        for kind, ends in ((customer_type, True), (hf.RestatingCustomer, False)):
            customer = kind(F, 2, "Hn")
            customer.reply(OPENING)
            customer.reply(f"Shall I exchange it for item {F['target_id']}?")
            self.assertEqual(STOP in customer.reply(text), ends, kind)

    def test_analysis_blocks_and_foreign_items(self) -> None:
        from research import gaps_analysis as ga

        families = {
            n: {"family": n, "product_id": p, "target_id": t, "stale_id": s}
            for n, p, t, s in (
                ("U01", "P", "1", "2"),
                ("U02", "P", "3", "1"),
                ("U03", "Q", "5", "6"),
            )
        }
        self.assertEqual(ga.foreign_items(families, "U01"), {"3"})
        self.assertEqual(ga.foreign_items(families, "U03"), set())
        rows: list[dict[str, Any]] = []
        for n in ("U01", "U02", "U03"):
            rows += [
                {"family": n, "session": 1, "arm": a, "commitment": True} for a in ("S1a", "S1b")
            ]
            for arm, ok, foreign in (("Mi", True, 0), ("Ms", n == "U03", int(n != "U03"))):
                rows.append(
                    {"family": n, "session": 2, "arm": arm, "success": ok, "foreign": foreign}
                )
        result = ga.analyse("gx", rows)
        self.assertEqual(result["complete_arms"], ["Mi", "Ms"])
        self.assertEqual(result["arms"]["Hn"], {"status": "not run"})
        test = result["study17_primary"]["tests"]["Ms vs Mi (success)"]
        self.assertIn("p_holm", test)
        self.assertEqual(result["arms"]["Ms"]["foreign"], 2)
        self.assertEqual(result["study13_primary"]["tests"], {})


if __name__ == "__main__":
    unittest.main()
