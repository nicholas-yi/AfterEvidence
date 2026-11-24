from __future__ import annotations

import unittest

from research.figures import render_all
from research.published import TABLES, Approx, Exactly, arms, discordant, mismatches, read_rows


class PublishedTableTests(unittest.TestCase):
    def test_every_published_number_matches_its_csv(self) -> None:
        for table in TABLES:
            with self.subTest(study=table.study):
                fields, rows = read_rows(table.path)
                self.assertEqual(fields, table.fields)
                self.assertEqual(len(rows), table.rows)
                self.assertEqual(mismatches(table.expected, table.analyse(table.path)), [])

    def test_memory_study_families_are_public_ids(self) -> None:
        (memory,) = [t for t in TABLES if t.key == "memory"]
        _, rows = read_rows(memory.path)
        self.assertTrue(all(r["family"] == "" or r["family"].startswith("F") for r in rows))

    def test_readme_figures_match_the_csv(self) -> None:
        for path, svg in render_all().items():
            self.assertTrue(path.exists(), path.name)
            self.assertEqual(path.read_text(encoding="utf-8"), svg, f"{path.name} is stale")

    def test_mismatches_catch_changed_missing_and_extra_values(self) -> None:
        actual = {
            "arms": {"A": {"successes": 3, "wilson95": [0.1, 0.2], "credits_per_session": 1.0}},
            "tests": {"A vs B": {"arm_only": 2, "reference_only": 0, "p_holm": 0.5}},
        }
        expected = {
            "arms": arms("successes wilson95 credits_per_session", {"A": (3, (0.1, 0.2), 1.001)}),
            "tests": Exactly(discordant({"A vs B": (2, 0, 0.5)})),
        }
        self.assertEqual(mismatches(expected, actual), [])
        self.assertEqual(
            mismatches({"arms": {"A": {"successes": 4}}}, actual), ["arms.A.successes: 3 != 4"]
        )
        self.assertEqual(mismatches({"arms": {"B": {}}}, actual), ["arms.B: missing"])
        self.assertTrue(mismatches({"tests": Exactly({})}, actual))
        self.assertTrue(mismatches({"arms": {"A": {"wilson95": (0.1, 0.21)}}}, actual))
        self.assertTrue(mismatches({"arms": {"A": {"credits_per_session": 1.002}}}, actual))
        self.assertTrue(mismatches({"tests": {"A vs B": {"p_holm": 0.5001}}}, actual))
        self.assertEqual(
            mismatches({"tests": {"A vs B": {"p_holm": Approx(0.6, 0.2)}}}, actual), []
        )


if __name__ == "__main__":
    unittest.main()
