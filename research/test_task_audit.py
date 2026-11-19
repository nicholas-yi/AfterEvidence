from __future__ import annotations

import unittest
from typing import Any

from research.task_audit import audit, invalid_references, write_tools

WRITES = frozenset({"return_delivered_order_items"})


def act(name: str, **arguments: object) -> dict[str, object]:
    return {"name": name, "arguments": arguments}


def task(
    task_id: str, *actions: dict[str, object], nl: int = 0, scenario: str = ""
) -> dict[str, Any]:
    return {
        "id": task_id,
        "user_scenario": {"instructions": {"reason_for_call": scenario}},
        "evaluation_criteria": {
            "actions": list(actions),
            "reward_basis": ["DB", "NL_ASSERTION"],
            "nl_assertions": ["hidden"] * nl,
        },
    }


def user(first: str, zip_code: str, email: str) -> dict[str, object]:
    return {
        "name": {"first_name": first, "last_name": "X"},
        "address": {"zip": zip_code},
        "email": email,
    }


DB: dict[str, Any] = {
    "users": {
        "alice": user("Alice", "1", "a@x"),
        "bob": user("Bob", "2", "b@x"),
        "carol": user("Carol", "3", "c@x"),
        "dave": user("Dave", "4", "d@x"),
    },
    "orders": {
        f"#W{i}": {"user_id": u} for i, u in enumerate(["alice", "bob", "carol", "dave"], 1)
    },
    "products": {"P1": {"variants": {"I1": {}}}},
}

RETURN = "return_delivered_order_items"
TASKS = [
    task(
        "0",
        act("find_user_id_by_name_zip", first_name="Alice", last_name="X", zip="1"),
        act(RETURN, order_id="#W1", item_ids=["I1"]),
    ),
    task(
        "1", act("find_user_id_by_email", email="a@x"), act("get_product_details", product_id="P9")
    ),
    task("2", act(RETURN, order_id="#W3", item_ids=["I1"]), nl=1),
    task("3", act(RETURN, order_id="#W2", item_ids=["I1"])),
    task("4", act(RETURN, order_id="#W4", item_ids=["I1"])),
    task(
        "5", act("get_order_details", order_id="#W2"), act(RETURN, order_id="#W2", item_ids=["I1"])
    ),
    task("9", act("get_user_details", user_id="dave")),
]
SPLIT = {"train": ["0", "1", "2", "3", "4", "5"], "test": ["9"]}


class TaskAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = audit(TASKS, SPLIT, DB, WRITES, exposed=("0",))
        self.rows = {row["task_id"]: row for row in self.report["rows"]}

    def test_families_join_lookup_customers_and_order_owners(self) -> None:
        self.assertEqual(self.rows["1"]["family"], "0")
        self.assertEqual(self.rows["5"]["family"], "3")
        self.assertEqual(self.rows["5"]["customers"], ["bob"])
        self.assertEqual(self.report["exposed_family_members"], ["0", "1"])
        self.assertTrue(self.rows["4"]["shares_customer_with_test"])

    def test_exclusions_are_recorded_and_one_task_proposed_per_family(self) -> None:
        self.assertIn("invalid_reference", self.rows["1"]["exclusion_reasons"])
        self.assertIn("exposed_family", self.rows["1"]["exclusion_reasons"])
        self.assertEqual(self.rows["2"]["exclusion_reasons"], ["needs_nl_judge"])
        self.assertEqual(self.rows["4"]["exclusion_reasons"], ["shares_customer_with_test"])
        self.assertEqual(self.report["eligible_train_tasks"], ["3", "5"])
        self.assertEqual(self.report["proposed_one_per_family"], ["3"])

    def test_invalid_references_distinguish_scripted_wrong_ids(self) -> None:
        unscripted = invalid_references(TASKS[1], DB)
        self.assertEqual(unscripted[0]["action"], 2)
        self.assertFalse(unscripted[0]["scripted_in_user_instructions"])
        scripted = task("7", act("get_order_details", order_id="#999"), scenario="say 999 first")
        self.assertTrue(invalid_references(scripted, DB)[0]["scripted_in_user_instructions"])

    def test_failed_customer_lookups_are_invalid_references(self) -> None:
        wrong = task("8", act("find_user_id_by_email", email="z@x"), scenario="first say z@x")
        [problem] = invalid_references(wrong, DB)
        self.assertEqual(problem["field"], "customer_lookup")
        self.assertTrue(problem["scripted_in_user_instructions"])
        self.assertEqual(invalid_references(TASKS[0], DB), [])
        wrong_zip = task(
            "9",
            act("find_user_id_by_name_zip", first_name="Alice", last_name="X", zip="7"),
            scenario="say zip 7 first",
        )
        [zip_problem] = invalid_references(wrong_zip, DB)
        self.assertEqual(zip_problem["value"], "7")
        self.assertTrue(zip_problem["scripted_in_user_instructions"])
        lookup_task = task(
            "6",
            act("find_user_id_by_email", email="z@x"),
            act(RETURN, order_id="#W3", item_ids=["I1"]),
            scenario="first say z@x",
        )
        report = audit(
            TASKS[:6] + [lookup_task], {"train": ["2", "6"], "test": []}, DB, WRITES, exposed=()
        )
        self.assertEqual(report["rows"][1]["exclusion_reasons"], [])

    def test_write_tools_require_the_pinned_decorator_layout(self) -> None:
        source = "@is_tool(ToolType.WRITE)\n    def cancel_pending_order(self):"
        self.assertEqual(write_tools(source), frozenset({"cancel_pending_order"}))
        with self.assertRaises(ValueError):
            write_tools("def cancel_pending_order(self):")


if __name__ == "__main__":
    unittest.main()
