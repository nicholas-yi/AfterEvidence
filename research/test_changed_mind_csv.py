from __future__ import annotations

import unittest
from pathlib import Path

from research.changed_mind_analysis import FIELDS, analyse, read_csv

CSV = Path(__file__).resolve().parent / "data" / "changed-mind-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Changed-mind evaluation":
# (successes, n, Wilson 95%, stale, declined, credits per session).
ARMS = {
    "N": (0, 31, (0.0, 0.11), 0, 31, 1.34),
    "Hn": (30, 31, (0.838, 0.994), 0, 0, 0.901),
    "M": (13, 31, (0.264, 0.592), 13, 5, 0.927),
    "Ho": (3, 31, (0.033, 0.249), 0, 28, 1.433),
    "Hoh": (2, 31, (0.018, 0.207), 0, 29, 1.389),
}
# (arm-only, reference-only) discordant families against Hn.
PRIMARY = {"M vs Hn": (0, 17), "Ho vs Hn": (1, 28), "Hoh vs Hn": (0, 28)}
SECONDARY = {"M vs Hn": (13, 0), "Ho vs Hn": (0, 0), "Hoh vs Hn": (0, 0)}


class PublishedChangedMindEvaluationTests(unittest.TestCase):
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
            (31, ["F02"], True, 0),
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
        self.assertTrue(all(v["p_holm"] < 0.0001 for v in r["primary_success"].values()))
        self.assertLess(r["secondary_stale"]["M vs Hn"]["p_holm"], 0.001)
        self.assertEqual(r["secondary_stale"]["Ho vs Hn"]["p_holm"], 1.0)
        self.assertEqual(
            (r["hoh_vs_ho_success"]["arm_only"], r["hoh_vs_ho_success"]["reference_only"]), (1, 2)
        )
        self.assertEqual(r["hoh_vs_ho_success"]["p"], 1.0)
        self.assertEqual(r["manipulation_hn_vs_n"]["arm_only"], 30)
        memory = r["provider_memory"]
        self.assertEqual({a: (v["has_Y"], v["has_X"], v["has_both"]) for a, v in memory.items()},
                         {"M": (31, 29, 29), "Ho": (26, 16, 13), "Hoh": (24, 15, 12)})  # fmt: skip


if __name__ == "__main__":
    unittest.main()
