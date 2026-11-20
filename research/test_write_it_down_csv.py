from __future__ import annotations

import unittest
from pathlib import Path

from research.followups_analysis import FIELDS, analyse
from research.honcho_features_analysis import read_csv

CSV = Path(__file__).resolve().parent / "data" / "write-it-down-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Write it down evaluation":
# (successes, n, Wilson 95%, stale, declined, infra-failed, tool sessions, credits per session).
ARMS = {
    "Mi": (14, 31, (0.292, 0.622), 8, 9, 2, 0, 0.979),
    "Mw": (28, 31, (0.751, 0.967), 1, 2, 0, 0, 0.864),
    "Hn": (30, 31, (0.838, 0.994), 0, 1, 1, 0, 0.866),
    "Tn": (5, 31, (0.071, 0.326), 0, 26, 2, 9, 1.432),
    "Fd": (28, 31, (0.751, 0.967), 0, 3, 0, 0, 0.907),
}
# (arm-only, reference-only) discordant families and Holm-adjusted p.
PRIMARY = {"Mw vs Mi (success)": (15, 1, 0.0005), "Tn vs Hn (success)": (1, 26, 0.0)}
SECONDARY = {"Mw vs Fd (success)": (2, 2, 1.0), "Mw vs Mi (stale)": (1, 8, 0.0781)}


class PublishedWriteItDownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse("wd", cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 64 + 31 * 5)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (31, ["Q30"], [], 0),
        )
        for arm, (k, n, ci, stale, declined, infra, tools, credits) in ARMS.items():
            cell = r["arms"][arm]
            got = (
                cell["successes"],
                cell["n"],
                tuple(cell["wilson95"]),
                cell["stale"],
                cell["declined"],
                cell["infra_failed"],
                cell["tool_sessions"],
            )
            self.assertEqual(got, (k, n, ci, stale, declined, infra, tools), arm)
            self.assertAlmostEqual(cell["credits_per_session"], credits, delta=0.0011, msg=arm)
        for block, expected in (("primary_success", PRIMARY), ("secondary", SECONDARY)):
            for name, (arm_only, reference_only, p_holm) in expected.items():
                got = r[block]["tests"][name]
                self.assertEqual(
                    (got["arm_only"], got["reference_only"]), (arm_only, reference_only), name
                )
                self.assertAlmostEqual(got["p_holm"], p_holm, places=4, msg=name)


if __name__ == "__main__":
    unittest.main()
