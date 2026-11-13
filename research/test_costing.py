from __future__ import annotations

import unittest
from copy import deepcopy

from research.costing import summarize_micro


class CostingTests(unittest.TestCase):
    def row(self) -> dict[str, object]:
        return {
            "event": "copilot-request-completed",
            "call_id": 1,
            "metrics": {
                "ai_credits_status": "AiCreditsStatus.COMPLETE",
                "total_nano_aiu": 100_000_000,
                "model_metrics": {
                    "model": {
                        "requests": {"count": 1, "cost": 1.0},
                        "total_nano_aiu": 100_000_000,
                        "usage": {"input_tokens": 100, "output_tokens": 20},
                    }
                },
            },
        }

    def test_counts_only_root_cost_not_duplicate_nested_cost(self) -> None:
        result = summarize_micro([self.row()])
        self.assertEqual(result["ai_credits"], 0.1)
        self.assertEqual(result["input_tokens"], 100)
        self.assertEqual(result["usd_equivalent_at_0_01_per_ai_credit"], 0.001)

    def test_missing_and_partial_costs_are_errors_not_free_usage(self) -> None:
        for status in ("pending", None):
            row = self.row()
            metrics = row["metrics"]
            self.assertIsInstance(metrics, dict)
            if not isinstance(metrics, dict):
                self.fail("Fixture metrics shape changed.")
            metrics["ai_credits_status"] = status
            with self.assertRaises(ValueError):
                summarize_micro([row])

    def test_duplicate_snapshots_are_not_summed_twice(self) -> None:
        row = self.row()
        with self.assertRaises(ValueError):
            summarize_micro([row, deepcopy(row)])

    def test_unfinished_requests_do_not_count_as_completed(self) -> None:
        rows = [self.row(), {"event": "copilot-request-started", "call_id": 2}]
        self.assertEqual(summarize_micro(rows)["completed_session_requests"], 1)


if __name__ == "__main__":
    unittest.main()
