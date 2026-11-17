from __future__ import annotations

import importlib
import unittest

from research.benchmark import DATA, STUDIES, listing


class BenchmarkTests(unittest.TestCase):
    def test_every_public_csv_is_listed_with_its_checks(self) -> None:
        self.assertEqual({s[2] for s in STUDIES}, {p.name for p in DATA.glob("*.csv")})
        for _, _, csv, analysis, test in STUDIES:
            importlib.import_module(analysis)
            importlib.import_module(test)
            self.assertIn(f"python -m {analysis} --csv research/data/{csv}", listing())


if __name__ == "__main__":
    unittest.main()
