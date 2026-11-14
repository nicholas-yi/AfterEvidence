from __future__ import annotations

import unittest
from pathlib import Path

from research.commitment_analysis import FIELDS, analyse, read_csv

CSV = Path(__file__).resolve().parent / "data" / "commitment-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Necessary-memory evaluation": successes, n, Wilson 95%,
# credits per session (episodes only).
ARMS = {
    "N": (0, 28, (0.0, 0.121), 1.38),
    "Hc": (23, 24, (0.798, 0.993), 0.832),
    "Hn": (26, 26, (0.871, 1.0), 0.835),
    "M": (24, 24, (0.862, 1.0), 0.859),
    "Ho": (19, 23, (0.629, 0.93), 0.934),
}
# (pairs, wins, losses, p, Holm p)
SECONDARIES = {"M vs Hn": (20, 0, 0, 1.0, 1.0), "Ho vs Hn": (18, 0, 3, 0.25, 0.75),
               "Hc vs Hn": (18, 0, 1, 1.0, 1.0)}  # fmt: skip


class PublishedCommitmentEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse(cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 157)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual((r["included"], r["excluded"], r["complete"]), (32, [], False))
        for arm, (k, n, ci, credits) in ARMS.items():
            cell = r["arms"][arm]
            self.assertEqual(
                (cell["successes"], cell["n"], tuple(cell["wilson95"])), (k, n, ci), arm
            )
            # Python 3.12's compensated sum() can move a value sitting on a rounding boundary.
            self.assertAlmostEqual(cell["credits_per_session"], credits, delta=0.0011, msg=arm)
        primary = r["primary"]
        self.assertEqual((primary["pairs"], primary["wins"], primary["losses"]), (22, 22, 0))
        self.assertTrue(primary["significant"])
        for name, (pairs, wins, losses, p, p_holm) in SECONDARIES.items():
            s = r["secondaries"][name]
            self.assertEqual((s["pairs"], s["wins"], s["losses"], s["p"], s["p_holm"]),
                             (pairs, wins, losses, p, p_holm), name)  # fmt: skip
        memory = r["provider_memory"]
        self.assertEqual(
            (memory["M"]["has_target_id"], memory["M"]["lacking_id_recovered"]), (20, [4, 4])
        )
        self.assertEqual(
            (memory["Ho"]["has_target_id"], memory["Ho"]["lacking_id_recovered"]), (11, [9, 12])
        )
        self.assertEqual(r["leakage_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
