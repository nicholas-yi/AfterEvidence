"""One entry point to the public benchmark: list the studies and re-verify every published table.

`python -m research.benchmark list` prints each study's question, its public per-session CSV and the
command that recomputes its table. `python -m research.benchmark verify` runs every CSV check that CI
runs (published numbers recomputed from the CSVs) plus the figure check, with no model calls, no
network and no private run data. Standard library only.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
# (study, question, CSV, analysis module, CI test module)
STUDIES = (
    ("1-2", "Does memory of other customers, or of the same customer's earlier sessions, help?",
     "memory-study-v1-episodes.csv", "research.memory_analysis", "research.test_memory_csv"),
    ("4", "When a task is impossible without memory, does memory let the agent finish it?",
     "commitment-eval-v1-episodes.csv", "research.commitment_analysis", "research.test_commitment_csv"),
    ("5", "After a change of mind, does memory make the agent act on the latest agreement?",
     "changed-mind-eval-v1-episodes.csv", "research.changed_mind_analysis", "research.test_changed_mind_csv"),
    ("6", "With real time between conversations, does dating the memories help?",
     "changed-mind-dated-eval-v1-episodes.csv", "research.changed_mind_dated_analysis",
     "research.test_changed_mind_dated_csv"),
    ("7", "Does Honcho's message search beat its dialectic, and does memory harm a helpful customer?",
     "honcho-features-eval-v1-episodes.csv", "research.honcho_features_analysis",
     "research.test_honcho_features_csv"),
    ("8", "Do Honcho's dreaming, an on-demand memory tool, or facts the app writes into Honcho help?",
     "honcho-stage3-eval-v1-episodes.csv", "research.honcho_stage3_analysis",
     "research.test_honcho_stage3_csv"),
    ("9", "Do the change-of-mind results hold with a second model (gpt-6-luna) in every role?",
     "second-model-eval-v1-episodes.csv", "research.second_model_analysis",
     "research.test_second_model_csv"),
)  # fmt: skip


def listing() -> str:
    lines = []
    for study, question, csv, analysis, _ in STUDIES:
        rows = sum(1 for _ in (DATA / csv).open(encoding="utf-8")) - 1
        lines += [f"Study {study}: {question}", f"  data: research/data/{csv} ({rows} rows)",
                  f"  table: python -m {analysis} --csv research/data/{csv}"]  # fmt: skip
    lines.append("Study 3 (deletion) is a per-system probe; see research/RESULTS.md.")
    return "\n".join(lines)


def verify() -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromNames([s[4] for s in STUDIES])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    from research.figures import render_all

    stale = [p.name for p, svg in render_all().items()
             if not p.exists() or p.read_text(encoding="utf-8") != svg]  # fmt: skip
    if stale:
        print("stale figures: " + ", ".join(stale), file=sys.stderr)
    return result.wasSuccessful() and not stale


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
