from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research.commitment_pilot import (
    CONFIRM,
    CONSENT,
    HISTORY_MAX,
    NEUTRAL_HEADER,
    STOP,
    FatalStop,
    ScriptedCustomer,
    identified,
    leaks,
    oracle,
    prepare,
    run_session,
    session_system,
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
                '{"event": "copilot-request-started"}\n', encoding="utf-8"
            )
            self.assertTrue(any(r.startswith("count mismatch") for r in start_refusals(Path(tmp))))


if __name__ == "__main__":
    unittest.main()
