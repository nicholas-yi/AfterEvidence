from __future__ import annotations

import unittest
from pathlib import Path

from scripts.audit_release import path_errors, text_errors


class PublicationTests(unittest.TestCase):
    def test_private_artifacts_are_excluded_even_if_staged(self) -> None:
        for path in (
            "research/runs/usage.json",
            "research/vendor/tau2-bench/LICENSE",
            "data/memory.sqlite3",
            "results/report.json",
            ".env",
            "research/cache/account.json",
        ):
            self.assertTrue(path_errors(path), path)

    def test_intended_public_source_is_allowed(self) -> None:
        for path in (
            "README.md",
            "afterevidence/static/style.css",
            "research/COSTS.md",
            "scripts/keep-awake.ps1",
        ):
            self.assertEqual(path_errors(path), [], path)

    def test_tokens_and_machine_paths_are_reported_without_echoing_values(self) -> None:
        self.assertIn("credential-token", text_errors("ghp_" + "x" * 36))
        self.assertIn("local-home-path", text_errors(str(Path.home()) + "\\private"))
        self.assertEqual(text_errors("Read the public project documentation."), [])

    def test_raw_account_snapshots_are_not_public_source(self) -> None:
        key = "quota_" + "snapshots"
        self.assertIn("raw-account-quota", text_errors('{"' + key + '": {}}'))


if __name__ == "__main__":
    unittest.main()
