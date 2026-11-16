from __future__ import annotations

import unittest
from pathlib import Path

from research.changed_mind_dated_analysis import FIELDS, analyse, read_csv

CSV = Path(__file__).resolve().parent / "data" / "changed-mind-dated-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Dated changed-mind evaluation":
# (successes, n, Wilson 95%, stale, declined, credits per session).
ARMS = {
    "Hn": (29, 31, (0.793, 0.982), 0, 2, 0.91),
    "M": (17, 31, (0.378, 0.708), 9, 5, 0.969),
    "Mi": (17, 31, (0.378, 0.708), 5, 9, 1.002),
    "Ho": (3, 31, (0.033, 0.249), 0, 28, 1.468),
    "Hod": (8, 31, (0.137, 0.432), 0, 22, 1.294),
}
# (arm-only, reference-only) discordant families.
PRIMARY = {"Mi vs M": (9, 9), "Hod vs Ho": (7, 2)}
SECONDARY = {"Mi vs M": (4, 8), "Hod vs Ho": (0, 0)}
VERSUS_HN = {"M": (1, 13), "Mi": (0, 12), "Ho": (0, 26), "Hod": (1, 22)}


class PublishedDatedChangedMindEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse(cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 219)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["complete"], r["leakage_sessions"]),
            (31, ["G03"], True, 0),
        )
        for arm, (k, n, ci, stale, declined, credits) in ARMS.items():
            cell = r["arms"][arm]
            self.assertEqual((cell["successes"], cell["n"], tuple(cell["wilson95"]), cell["stale"], cell["declined"]),
                             (k, n, ci, stale, declined), arm)  # fmt: skip
            self.assertAlmostEqual(cell["credits_per_session"], credits, delta=0.0011, msg=arm)
        for block, expected in (("primary_success", PRIMARY), ("secondary_stale", SECONDARY)):
            for name, pair in expected.items():
                got = r[block][name]
                self.assertEqual((got["arm_only"], got["reference_only"]), pair, (block, name))
        self.assertEqual(r["primary_success"]["Mi vs M"]["p_holm"], 1.0)
        self.assertAlmostEqual(r["primary_success"]["Hod vs Ho"]["p_holm"], 0.3594, places=4)
        self.assertAlmostEqual(r["secondary_stale"]["Mi vs M"]["p_holm"], 0.7754, places=4)
        for arm, pair in VERSUS_HN.items():
            got = r["descriptive_vs_hn"][f"{arm} vs Hn"]["success"]
            self.assertEqual((got["arm_only"], got["reference_only"]), pair, arm)
        memory = {a: (v["has_Y"], v["has_X"], v["date_correct"], v["deferral_present"])
                  for a, v in r["provider_memory"].items()}  # fmt: skip
        self.assertEqual(memory, {"M": (31, 29, 0, 9), "Mi": (31, 28, 28, 0),
                                  "Ho": (18, 19, 0, 10), "Hod": (18, 21, 31, 3)})  # fmt: skip


if __name__ == "__main__":
    unittest.main()
