from __future__ import annotations

import unittest
from pathlib import Path

from research.gaps_analysis import FIELDS, analyse
from research.honcho_features_analysis import read_csv

CSV = Path(__file__).resolve().parent / "data" / "second-model-gaps-eval-v1-episodes.csv"
# Published in research/RESULTS.md (Study 19). Per arm: (successes, n, stale, superseded, injected, foreign, declined, infra_failed, tool_sessions), Wilson 95%, credits/session.
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
    "Hn": ((32, 32, 0, 0, 0, 0, 0, 0, 0), (0.893, 1.0), 0.492),
    "Fd": ((31, 32, 0, 0, 0, 0, 0, 0, 0), (0.843, 0.994), 0.492),
    "Fs": ((0, 32, 31, 31, 0, 0, 1, 0, 0), (0.0, 0.107), 0.507),
    "Fsh": ((32, 32, 0, 0, 0, 0, 0, 0, 0), (0.893, 1.0), 0.554),
    "Tn": ((32, 32, 0, 0, 0, 0, 0, 0, 32), (0.893, 1.0), 0.632),
    "Tp": ((32, 32, 0, 0, 0, 0, 0, 0, 32), (0.893, 1.0), 0.562),
    "Mi": ((22, 32, 9, 9, 0, 0, 0, 0, 0), (0.514, 0.82), 0.51),
    "Mz": ((3, 32, 3, 3, 26, 15, 0, 0, 0), (0.032, 0.242), 0.495),
    "Fz": ((0, 32, 0, 0, 32, 18, 0, 0, 0), (0.0, 0.107), 0.496),
    "Hod": ((31, 32, 0, 0, 0, 0, 0, 0, 0), (0.843, 0.994), 0.491),
    "Hz": ((0, 32, 0, 0, 32, 18, 0, 0, 0), (0.0, 0.107), 0.483),
}
# Per block: test -> (arm-only, reference-only discordant families, Holm-adjusted p).
BLOCKS = {
    "study13_primary": {"Fsh vs Fs (success)": (32, 0, 0.0), "Tp vs Tn (success)": (0, 0, 1.0)},
    "study13_secondary": {
        "Fs vs Fd (success)": (0, 31, 0.0),
        "Fsh vs Hn (success)": (0, 0, 1.0),
        "Fs vs Fd (stale)": (31, 0, 0.0),
    },
    "study15_primary": {
        "Mz vs Mi (injected)": (26, 0, 0.0),
        "Hz vs Hod (injected)": (32, 0, 0.0),
        "Fz vs Fd (injected)": (32, 0, 0.0),
    },
    "study15_secondary": {
        "Mz vs Mi (success)": (1, 20, 0.0),
        "Hz vs Hod (success)": (0, 31, 0.0),
        "Fz vs Fd (success)": (0, 31, 0.0),
    },
}


class PublishedGMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse("gm", cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 416)

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
