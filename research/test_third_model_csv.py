from __future__ import annotations

import unittest
from pathlib import Path

from research.followups_analysis import FIELDS, analyse
from research.honcho_features_analysis import read_csv

CSV = Path(__file__).resolve().parent / "data" / "third-model-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Third-model replication":
# (successes, n, Wilson 95%, stale, declined, infra-failed, tool sessions, credits per session).
ARMS = {
    "Hn": (30, 31, (0.838, 0.994), 0, 0, 0, 0, 1.236),
    "Mi": (10, 31, (0.186, 0.499), 20, 1, 0, 0, 1.244),
    "Hod": (19, 31, (0.438, 0.763), 0, 11, 0, 0, 1.577),
    "Fd": (31, 31, (0.89, 1.0), 0, 0, 0, 0, 1.035),
}
# (arm-only, reference-only) discordant families and Holm-adjusted p.
PRIMARY = {
    "Mi vs Hn (success)": (0, 20, 0.0),
    "Hod vs Hn (success)": (1, 12, 0.0068),
    "Fd vs Hn (success)": (1, 0, 1.0),
}
SECONDARY = {
    "Mi vs Hn (stale)": (20, 0, 0.0),
    "Hod vs Hn (stale)": (0, 0, 1.0),
    "Fd vs Hn (stale)": (0, 0, 1.0),
}


class PublishedThirdModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse("m3", cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 64 + 31 * 4)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (31, ["R28"], [], 0),
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
        for block, expected in (("primary_success", PRIMARY), ("secondary_stale", SECONDARY)):
            for name, (arm_only, reference_only, p_holm) in expected.items():
                got = r[block]["tests"][name]
                self.assertEqual(
                    (got["arm_only"], got["reference_only"]), (arm_only, reference_only), name
                )
                self.assertAlmostEqual(got["p_holm"], p_holm, places=4, msg=name)


if __name__ == "__main__":
    unittest.main()
