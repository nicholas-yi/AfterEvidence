from __future__ import annotations

import unittest
from pathlib import Path

from research.honcho_features_analysis import read_csv
from research.honcho_stage3_analysis import FIELDS, analyse

CSV = Path(__file__).resolve().parent / "data" / "honcho-stage3-eval-v1-episodes.csv"
# Published in research/RESULTS.md "Honcho Stage 3 evaluation":
# (successes, n, Wilson 95%, stale, declined, infra-failed, tool sessions, credits per session).
ARMS = {
    "Hod": (8, 30, (0.142, 0.444), 0, 22, 0, 0, 1.252),
    "Hdr": (12, 30, (0.246, 0.577), 0, 18, 0, 0, 1.164),
    "Ht": (1, 30, (0.006, 0.167), 0, 29, 0, 5, 1.509),
    "Hw": (26, 30, (0.703, 0.947), 0, 4, 1, 0, 0.882),
    "Fd": (29, 30, (0.833, 0.994), 0, 1, 0, 0, 0.865),
}
# (arm-only, reference-only) discordant families and unadjusted exact p.
PRIMARY = {
    "Hdr vs Hod (success)": (8, 4, 0.387695),
    "Ht vs Hod (success)": (1, 8, 0.039062),
    "Hw vs Hod (success)": (18, 0, 8e-06),
}
FACTS = {"Hw vs Fd (success)": (1, 4, 0.375), "Fd vs Hod (success)": (21, 0, 1e-06)}


class PublishedStage3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse(cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 214)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (30, ["L03", "L04"], [], 0),
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
        for block, expected in (("primary_success", PRIMARY), ("secondary_facts", FACTS)):
            for name, (arm_only, reference_only, p) in expected.items():
                got = r[block]["tests"][name]
                self.assertEqual(
                    (got["arm_only"], got["reference_only"]), (arm_only, reference_only), name
                )
                self.assertAlmostEqual(got["p"], p, places=6, msg=name)
        self.assertAlmostEqual(
            r["primary_success"]["tests"]["Ht vs Hod (success)"]["p_holm"], 0.0781, places=4
        )
        self.assertEqual(
            [r["secondary_stale"]["tests"][t]["arm_only"] for t in r["secondary_stale"]["tests"]],
            [0, 0, 0],
        )


if __name__ == "__main__":
    unittest.main()
