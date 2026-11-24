from __future__ import annotations

import importlib
import unittest

from research.benchmark import listing
from research.published import DATA, TABLES


class BenchmarkTests(unittest.TestCase):
    def test_every_public_csv_is_listed_with_its_analysis(self) -> None:
        self.assertEqual({t.csv for t in TABLES}, {p.name for p in DATA.glob("*.csv")})
        self.assertEqual(len({t.key for t in TABLES}), len(TABLES))
        for table in TABLES:
            importlib.import_module(table.command.split()[0])  # the module; any arguments follow it
            self.assertIn(f"python -m {table.command} --csv research/data/{table.csv}", listing())


if __name__ == "__main__":
    unittest.main()
