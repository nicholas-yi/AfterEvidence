from __future__ import annotations

import unittest
from pathlib import Path

from research.gaps_analysis import FIELDS, analyse
from research.honcho_features_analysis import read_csv

CSV = Path(__file__).resolve().parent / "data" / "address-change-eval-v1-episodes.csv"
# Published in research/RESULTS.md (Study 18). Per arm: (successes, n, stale, superseded, injected, foreign, declined, infra_failed, tool_sessions), Wilson 95%, credits/session.
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
    "Hn": ((27, 32, 0, 0, 0, 0, 5, 0, 0), (0.682, 0.931), 0.866),
    "Mi": ((17, 32, 3, 3, 0, 0, 12, 0, 0), (0.364, 0.691), 0.919),
    "Hod": ((4, 32, 0, 0, 0, 0, 27, 0, 0), (0.05, 0.281), 1.211),
    "Fd": ((25, 32, 0, 0, 0, 0, 7, 0, 0), (0.612, 0.89), 0.783),
}
# Per block: test -> (arm-only, reference-only discordant families, Holm-adjusted p).
BLOCKS = {
    "primary_success": {
        "Mi vs Hn (success)": (1, 11, 0.0127),
        "Hod vs Hn (success)": (3, 26, 0.0),
        "Fd vs Hn (success)": (3, 5, 0.7266),
    },
    "secondary_stale": {
        "Mi vs Hn (stale)": (3, 0, 0.75),
        "Hod vs Hn (stale)": (0, 0, 1.0),
        "Fd vs Hn (stale)": (0, 0, 1.0),
    },
}


class PublishedACTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse("ac", cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 192)

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
