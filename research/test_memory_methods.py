from __future__ import annotations

import unittest

from research.memory_methods import Condition, Experience, Lesson, retrieve, validate_lessons


class MemoryMethodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.experiences = (
            Experience(
                "e1",
                "train-a",
                "policy-a",
                ("Inspect the current order status.",),
                "environment-goal-success",
            ),
            Experience(
                "e2",
                "train-b",
                "policy-a",
                ("Confirm item choices before updating an order.",),
                "environment-goal-failure",
            ),
        )
        self.lessons = (
            Lesson(
                "q",
                "Inspect status and confirm the user's choices before a change.",
                (("e1", "e2"),),
                "policy-a",
            ),
        )

    def test_static_conditions_and_matched_budget(self) -> None:
        for condition in Condition:
            text, ids = retrieve(
                condition,
                "order status",
                self.experiences,
                self.lessons,
                frozenset({"e1", "e2"}),
                "policy-a",
                120,
            )
            self.assertLessEqual(len(text), 120)
            self.assertEqual(bool(ids), condition != Condition.NONE)

    def test_joint_premise_withdrawal_only_blocks_revision_condition(self) -> None:
        for condition in (Condition.CONSOLIDATED, Condition.REVISED):
            text, _ = retrieve(
                condition, "status", self.experiences, self.lessons, frozenset({"e1"}), "policy-a"
            )
            self.assertEqual(bool(text), condition == Condition.CONSOLIDATED)

    def test_independent_support_preserves_revised_lesson(self) -> None:
        lesson = Lesson("q", "Inspect order status.", (("e1",), ("e2",)), "policy-a")
        text, ids = retrieve(
            Condition.REVISED, "status", self.experiences, (lesson,), frozenset({"e2"}), "policy-a"
        )
        self.assertEqual(ids, ("q",))
        self.assertIn("Inspect", text)

    def test_policy_change_invalidates_only_revision_condition(self) -> None:
        for condition in (Condition.CONSOLIDATED, Condition.REVISED):
            text, _ = retrieve(
                condition,
                "status",
                self.experiences,
                self.lessons,
                frozenset({"e1", "e2"}),
                "policy-b",
            )
            self.assertEqual(bool(text), condition == Condition.CONSOLIDATED)

    def test_raw_condition_does_not_retrieve_withdrawn_sources(self) -> None:
        text, ids = retrieve(
            Condition.RAW, "status", self.experiences, self.lessons, frozenset({"e2"}), "policy-a"
        )
        self.assertTrue(ids)
        self.assertTrue(all(identifier.startswith("e2/") for identifier in ids))
        self.assertNotIn("Inspect the current", text)

    def test_model_citations_cannot_reduce_actual_input_dependencies(self) -> None:
        lessons = validate_lessons(
            {"lessons": [{"text": "Inspect status.", "support_sets": [["e1"]]}]},
            self.experiences,
            "policy-a",
        )
        self.assertEqual(lessons[0].support_sets, (("e1", "e2"),))
        with self.assertRaises(ValueError):
            validate_lessons(
                {"lessons": [{"text": "Invented", "support_sets": [["test-answer"]]}]},
                self.experiences,
                "policy-a",
            )

    def test_long_raw_evidence_is_excerpted_and_separator_counts_toward_budget(self) -> None:
        experiences = (
            Experience("e1", "train", "p", ("order " * 1000, "another observation"), "failed"),
        )
        for budget in (0, 10, 20, 40, 100):
            text, _ = retrieve(
                Condition.RAW, "order", experiences, (), frozenset({"e1"}), "p", budget
            )
            self.assertLessEqual(len(text), budget)
            if budget >= 40:
                self.assertIn("order", text)

    def test_only_observable_experience_fields_exist(self) -> None:
        fields = self.experiences[0].public()
        self.assertNotIn("evaluation_criteria", fields)
        self.assertNotIn("reference_actions", fields)
        self.assertNotIn("gold_answer", fields)
        self.assertNotIn("test_outcome", fields)


if __name__ == "__main__":
    unittest.main()
