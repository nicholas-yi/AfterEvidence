from __future__ import annotations

import unittest
from pathlib import Path

from research.gaps_analysis import FIELDS, analyse
from research.honcho_features_analysis import read_csv

CSV = Path(__file__).resolve().parent / "data" / "long-history-eval-v1-episodes.csv"
# Published in research/RESULTS.md (Study 14). Per arm: (successes, n, stale, superseded, injected, foreign, declined, infra_failed, tool_sessions), Wilson 95%, credits/session.
KEYS = (
    "successes",
    "n",
    "stale",
    "superseded",
    "injected",
    "foreign",
    "declined",
    "infra_failed",
    "tool_sessions",
)
ARMS = {
    "Hn": ((32, 32, 0, 0, 0, 0, 0, 0, 0), (0.893, 1.0), 0.831),
    "Mi": ((4, 32, 4, 5, 0, 0, 23, 0, 0), (0.05, 0.281), 1.326),
    "Hod": ((2, 32, 0, 0, 0, 0, 30, 0, 0), (0.017, 0.201), 1.399),
    "Fd": ((32, 32, 0, 0, 0, 0, 0, 0, 0), (0.893, 1.0), 0.795),
}
# Per block: test -> (arm-only, reference-only discordant families, Holm-adjusted p).
BLOCKS = {
    "primary_success": {
        "Mi vs Hn (success)": (0, 28, 0.0),
        "Hod vs Hn (success)": (0, 30, 0.0),
        "Fd vs Hn (success)": (0, 0, 1.0),
    },
    "secondary_superseded": {
        "Mi vs Hn (superseded)": (5, 0, 0.1875),
        "Hod vs Hn (superseded)": (0, 0, 1.0),
        "Fd vs Hn (superseded)": (0, 0, 1.0),
    },
}


class PublishedLHTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse("lh", cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 288)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (32, [], [], 0),
        )
        for arm, (counts, ci, credits) in ARMS.items():
            cell = r["arms"][arm]
            self.assertEqual(tuple(cell[k] for k in KEYS), counts, arm)
            self.assertEqual(tuple(cell["wilson95"]), ci, arm)
            self.assertAlmostEqual(cell["credits_per_session"], credits, delta=0.0011, msg=arm)
        for block, tests in BLOCKS.items():
            self.assertEqual(sorted(r[block]["tests"]), sorted(tests), block)
            for name, (arm_only, reference_only, p_holm) in tests.items():
                got = r[block]["tests"][name]
                self.assertEqual(
                    (got["arm_only"], got["reference_only"]), (arm_only, reference_only), name
                )
                self.assertAlmostEqual(got["p_holm"], p_holm, places=4, msg=name)


if __name__ == "__main__":
    unittest.main()
