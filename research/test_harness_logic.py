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


if __name__ == "__main__":
    unittest.main()
