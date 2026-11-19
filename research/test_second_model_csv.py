from __future__ import annotations

import unittest
from pathlib import Path

from research.honcho_features_analysis import read_csv
from research.second_model_analysis import FIELDS, analyse

CSV = Path(__file__).resolve().parent / "data" / "second-model-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Second-model replication":
# (successes, n, Wilson 95%, stale, declined, credits per session).
ARMS = {
    "Hn": (30, 32, (0.799, 0.983), 0, 0, 0.562),
    "Mi": (20, 32, (0.453, 0.771), 10, 1, 0.537),
    "Hod": (27, 32, (0.682, 0.931), 0, 2, 0.56),
    "Hs": (28, 32, (0.719, 0.95), 0, 0, 0.582),
}
# (arm-only, reference-only) discordant families and Holm-adjusted p.
PRIMARY = {
    "Mi vs Hn (success)": (2, 12, 0.0388),
    "Hod vs Hn (success)": (2, 5, 0.9062),
    "Hs vs Hn (success)": (1, 3, 0.9062),
}
SECONDARY = {
    "Mi vs Hn (stale)": (10, 0, 0.0059),
    "Hod vs Hn (stale)": (0, 0, 1.0),
    "Hs vs Hn (stale)": (0, 0, 1.0),
}


class PublishedSecondModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse(cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 192)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (32, [], [], 0),
        )
        for arm, (k, n, ci, stale, declined, credits) in ARMS.items():
            cell = r["arms"][arm]
            got = (
                cell["successes"],
                cell["n"],
                tuple(cell["wilson95"]),
                cell["stale"],
                cell["declined"],
            )
            self.assertEqual(got, (k, n, ci, stale, declined), arm)
            self.assertAlmostEqual(cell["credits_per_session"], credits, delta=0.0011, msg=arm)
        for block, expected in (("primary_success", PRIMARY), ("secondary_stale", SECONDARY)):
            for name, (arm_only, reference_only, p_holm) in expected.items():
                got = r[block]["tests"][name]
                self.assertEqual(
                    (got["arm_only"], got["reference_only"]), (arm_only, reference_only), name
                )
                self.assertAlmostEqual(got["p_holm"], p_holm, places=4, msg=name)
        memory = {
            a: (r["arms"][a]["memory_has_Y"], r["arms"][a]["memory_has_X"])
            for a in ("Mi", "Hod", "Hs")
        }
        self.assertEqual(memory, {"Mi": (32, 32), "Hod": (24, 1), "Hs": (32, 32)})


if __name__ == "__main__":
    unittest.main()
