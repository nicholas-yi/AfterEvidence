"""One entry point to the public benchmark: list the studies and re-verify every published table.

`python -m research.benchmark list` prints each study's question, its public per-session CSV and the
command that recomputes its table. `python -m research.benchmark verify` checks every published
number against the CSVs (research/published.py) and the figures, with no model calls, no network and
no private run data. Standard library only.
"""

from __future__ import annotations

import argparse
import unittest

from research.published import TABLES

VERIFY = "research.tests.test_published_tables"


def listing() -> str:
    lines = []
    for table in TABLES:
        lines += [
            f"Study {table.study}: {table.question}",
            f"  data: research/data/{table.csv} ({table.rows} rows)",
            f"  table: python -m {table.command} --csv research/data/{table.csv}",
        ]
    lines.append("Study 3 (deletion) is a per-system probe; see research/RESULTS.md.")
    return "\n".join(lines)


def verify() -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromName(VERIFY)
    return unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List the benchmark studies or re-verify their tables."
    )
    parser.add_argument("command", choices=["list", "verify"])
    args = parser.parse_args()
    if args.command == "list":
        print(listing())
        return 0
    return 0 if verify() else 1


if __name__ == "__main__":
    raise SystemExit(main())
