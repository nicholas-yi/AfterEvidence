from __future__ import annotations

import unittest
from pathlib import Path

from research.gaps_analysis import FIELDS, analyse
from research.honcho_features_analysis import read_csv

CSV = Path(__file__).resolve().parent / "data" / "gaps-eval-v1-episodes.csv"
# Published in research/RESULTS.md (Studies 13, 15, 16 and 17). Per arm: (successes, n, stale, superseded, injected, foreign, declined, infra_failed, tool_sessions), Wilson 95%, credits/session.
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
    "Hn": ((31, 31, 0, 0, 0, 0, 0, 0, 0), (0.89, 1.0), 0.859),
    "Fd": ((28, 31, 0, 0, 0, 0, 3, 0, 0), (0.751, 0.967), 0.838),
    "Fs": ((0, 31, 30, 30, 0, 0, 1, 0, 0), (-0.0, 0.11), 0.764),
    "Fsh": ((29, 31, 0, 0, 0, 0, 2, 0, 0), (0.793, 0.982), 0.926),
    "Tn": ((2, 31, 0, 0, 0, 0, 28, 0, 7), (0.018, 0.207), 1.526),
    "Tp": ((31, 31, 0, 0, 0, 0, 0, 0, 31), (0.89, 1.0), 0.997),
    "Mi": ((20, 31, 4, 4, 0, 0, 6, 0, 0), (0.469, 0.789), 0.962),
    "Mz": ((4, 31, 3, 3, 9, 5, 15, 0, 0), (0.051, 0.289), 1.199),
    "Fz": ((0, 31, 0, 0, 31, 16, 0, 0, 0), (-0.0, 0.11), 0.852),
    "Hod": ((6, 31, 0, 0, 0, 0, 25, 0, 0), (0.092, 0.363), 1.346),
    "Hz": ((0, 31, 0, 0, 8, 4, 23, 0, 0), (-0.0, 0.11), 1.302),
    "Ms": ((9, 31, 5, 5, 0, 0, 17, 0, 0), (0.161, 0.466), 1.255),
    "Gr": ((12, 31, 8, 8, 0, 0, 11, 0, 0), (0.237, 0.562), 1.059),
    "Hi": ((25, 31, 0, 0, 0, 0, 5, 0, 0), (0.637, 0.908), 0.991),
}
# Per block: test -> (arm-only, reference-only discordant families, Holm-adjusted p).
BLOCKS = {
    "study13_primary": {"Fsh vs Fs (success)": (29, 0, 0.0), "Tp vs Tn (success)": (29, 0, 0.0)},
    "study13_secondary": {
        "Fs vs Fd (success)": (0, 28, 0.0),
        "Fsh vs Hn (success)": (0, 2, 0.5),
        "Fs vs Fd (stale)": (30, 0, 0.0),
    },
    "study15_primary": {
        "Mz vs Mi (injected)": (9, 0, 0.0078),
        "Hz vs Hod (injected)": (8, 0, 0.0078),
        "Fz vs Fd (injected)": (31, 0, 0.0),
    },
    "study15_secondary": {
        "Mz vs Mi (success)": (1, 17, 0.0003),
        "Hz vs Hod (success)": (0, 6, 0.0312),
        "Fz vs Fd (success)": (0, 28, 0.0),
    },
    "study16_primary": {"Gr vs Hn (success)": (0, 19, 0.0), "Hi vs Hn (success)": (0, 6, 0.0312)},
    "study16_secondary": {
        "Gr vs Mi (success)": (4, 12, 0.1536),
        "Hi vs Mi (success)": (7, 2, 0.1797),
    },
    "study17_primary": {"Ms vs Mi (success)": (2, 13, 0.0074)},
    "study17_secondary": {"Ms vs Mi (foreign)": (0, 0, 1.0)},
}


class PublishedGXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = read_csv(CSV)
        cls.result = analyse("gx", cls.rows)

    def test_csv_has_only_public_columns(self) -> None:
        self.assertEqual(tuple(self.rows[0]), FIELDS)
        self.assertEqual(len(self.rows), 498)

    def test_published_table(self) -> None:
        r = self.result
        self.assertEqual(
            (r["included"], r["excluded"], r["not_run_arms"], r["leakage_sessions"]),
            (31, ["U09"], [], 0),
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
