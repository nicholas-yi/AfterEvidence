from __future__ import annotations

import csv
import unittest
from pathlib import Path

from research.memory_analysis import EPISODE_FIELDS, tables_from_csv

CSV = Path(__file__).resolve().parent / "data" / "memory-study-v1-episodes.csv"
# Published in research/RESULTS.md "Memory study v1": successes, wins/losses, credits/episode.
STUDY1 = {
    "none": (39, None, 2.02), "raw": (41, (6, 4), 2.25), "consolidated": (41, (7, 5), 2.27),
    "sleep": (42, (7, 4), 2.11), "workflows": (43, (8, 4), 1.97), "mem0": (43, (9, 5), 2.05),
    "graphiti": (42, (7, 4), 2.17), "hindsight": (38, (6, 7), 2.13), "honcho": (41, (7, 5), 2.08),
}  # fmt: skip
STUDY2 = {"none": (20, None), "session": (19, (1, 2)), "mem0": (18, (0, 2)), "honcho": (17, (1, 4))}
# Post-hoc (not preregistered) paired differences and cluster-bootstrap 95% CIs.
POST_HOC = {
    ("study1", "raw"): (0.0385, (-0.0577, 0.1346)),
    ("study1", "hindsight"): (-0.0192, (-0.1538, 0.1154)),
    ("study2", "honcho"): (-0.1364, (-0.3333, 0.0476)),
}


class PublishedMemoryStudyTests(unittest.TestCase):
    def test_csv_has_only_public_columns(self) -> None:
        with CSV.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(tuple(reader.fieldnames or ()), EPISODE_FIELDS)
            rows = list(reader)
        self.assertEqual(len(rows), 572)
        self.assertTrue(all(r["family"] == "" or r["family"].startswith("F") for r in rows))

    def test_published_headline_numbers_match_the_csv(self) -> None:
        tables = tables_from_csv(CSV)
        for name, (successes, record, credits) in STUDY1.items():
            row = tables["study1"][name]
            self.assertEqual((row["episodes"], row["successes"]), (52, successes), name)
            self.assertEqual(round(row["mean_episode_credits"], 2), credits, name)
            if record:
                self.assertEqual((row["wins"], row["losses"], row["holm_p"]), (*record, 1.0), name)
        self.assertEqual(
            round(tables["study1"]["hindsight"]["provider_credits_per_episode"], 2), 0.31
        )
        self.assertEqual(round(tables["study1"]["honcho"]["provider_credits_per_episode"], 2), 0.17)
        for name, (successes, record) in STUDY2.items():
            row = tables["study2"][name]
            self.assertEqual((row["episodes"], row["successes"]), (22, successes), name)
            if record:
                self.assertEqual((row["wins"], row["losses"], row["holm_p"]), (*record, 1.0), name)
        self.assertEqual(tables["study2"]["honcho"]["failures"]["contract"], 2)
        for (study, name), (difference, ci95) in POST_HOC.items():
            post_hoc = tables[study][name]["post_hoc"]
            self.assertEqual((post_hoc["difference"], post_hoc["ci95"]), (difference, ci95))


if __name__ == "__main__":
    unittest.main()
