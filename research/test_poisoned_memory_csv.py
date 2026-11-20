from __future__ import annotations

import unittest
from pathlib import Path

from research.followups_analysis import FIELDS, analyse
from research.honcho_features_analysis import read_csv

CSV = Path(__file__).resolve().parent / "data" / "poisoned-memory-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Memory poisoning evaluation":
# (successes, n, Wilson 95%, stale, declined, infra-failed, tool sessions, credits per session).
ARMS = {
    "Hn": (23, 27, (0.675, 0.941), 0, 4, 0, 0, 0.979),
    "Mi": (20, 27, (0.553, 0.868), 0, 7, 0, 0, 0.996),
    "Hod": (14, 27, (0.34, 0.693), 0, 12, 0, 0, 1.114),
    "Fd": (26, 27, (0.817, 0.993), 0, 1, 0, 0, 0.795),
}
# (arm-only, reference-only) discordant families and Holm-adjusted p; "stale" = executed Z.
PRIMARY = {
    "Mi vs Hn (stale)": (0, 0, 1.0),
    "Hod vs Hn (stale)": (0, 0, 1.0),
    "Fd vs Hn (stale)": (0, 0, 1.0),
}
SECONDARY = {
    "Mi vs Hn (success)": (2, 5, 0.75),
    "Hod vs Hn (success)": (4, 13, 0.1471),
    "Fd vs Hn (success)": (4, 1, 0.75),
}


class PublishedPoisonedMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse("pz", cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 64 + 27 * 4)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (27, ["S21", "S22", "S23", "S24", "S32"], [], 0),
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
        for block, expected in (("primary_harm", PRIMARY), ("secondary_success", SECONDARY)):
            for name, (arm_only, reference_only, p_holm) in expected.items():
                got = r[block]["tests"][name]
                self.assertEqual(
                    (got["arm_only"], got["reference_only"]), (arm_only, reference_only), name
                )
                self.assertAlmostEqual(got["p_holm"], p_holm, places=4, msg=name)


if __name__ == "__main__":
    unittest.main()
