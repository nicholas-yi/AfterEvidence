from __future__ import annotations

import unittest
from pathlib import Path

from research.honcho_features_analysis import FIELDS, analyse, read_csv

CSV = Path(__file__).resolve().parent / "data" / "honcho-features-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Honcho features evaluation":
# (successes, n, Wilson 95%, stale, declined, restated sessions, credits per session).
ARMS = {
    "Hs": (14, 32, (0.282, 0.607), 0, 18, 0, 1.24),
    "Hod": (8, 32, (0.133, 0.421), 0, 24, 0, 1.305),
    "Nr": (32, 32, (0.893, 1.0), 0, 0, 32, 1.1),
    "Hodr": (27, 32, (0.682, 0.931), 0, 4, 21, 1.049),
    "Mir": (30, 32, (0.799, 0.983), 2, 0, 9, 0.861),
    "Hnr": (32, 32, (0.893, 1.0), 0, 0, 1, 0.863),
}
# (arm-only, reference-only) discordant families and Holm-adjusted p.
FAMILY_1 = {"Hs vs Hod (success)": (11, 5, 0.2101)}
FAMILY_2 = {
    "Hodr vs Nr (stale)": (0, 0, 1.0),
    "Mir vs Nr (stale)": (2, 0, 1.0),
    "Hodr vs Nr (success)": (0, 5, 0.25),
    "Mir vs Nr (success)": (0, 2, 1.0),
}


class PublishedHonchoFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse(cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 256)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (32, [], [], 0),
        )
        for arm, (k, n, ci, stale, declined, restated, credits) in ARMS.items():
            cell = r["arms"][arm]
            got = (cell["successes"], cell["n"], tuple(cell["wilson95"]), cell["stale"],
                   cell["declined"], cell["restated_sessions"])  # fmt: skip
            self.assertEqual(got, (k, n, ci, stale, declined, restated), arm)
            self.assertAlmostEqual(cell["credits_per_session"], credits, delta=0.0011, msg=arm)
        for block, expected in (("family_1", FAMILY_1), ("family_2", FAMILY_2)):
            for name, (arm_only, reference_only, p_holm) in expected.items():
                got = r[block]["tests"][name]
                self.assertEqual(
                    (got["arm_only"], got["reference_only"]), (arm_only, reference_only), name
                )
                self.assertAlmostEqual(got["p_holm"], p_holm, places=4, msg=name)
        memory = {
            a: (r["arms"][a]["memory_has_Y"], r["arms"][a]["memory_has_X"])
            for a in ("Hs", "Hod", "Mir")
        }
        self.assertEqual(memory, {"Hs": (32, 32), "Hod": (21, 17), "Mir": (32, 31)})


if __name__ == "__main__":
    unittest.main()
