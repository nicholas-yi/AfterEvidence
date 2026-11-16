from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from research.run_status import budget_snapshot, instant, snapshot


class RunStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.start = instant("2026-01-01T10:00:00Z")
        self.now = self.start + timedelta(hours=2)
        self.jobs = [
            {"family": family, "session": 2, "arm": arm}
            for family in ("C1", "E01", "Z9")
            for arm in ("N", "Ho")
        ]
        self.plan()

    def plan(self) -> None:
        (self.root / "plan.json").write_text(
            json.dumps(
                {
                    "jobs": self.jobs,
                    "request_cap": 20,
                    "credit_stop": 10,
                }
            ),
            encoding="utf-8",
        )

    def report(self, name: str, minutes_ago: int = 1) -> None:
        path = self.root / name
        # A monitor must not parse result bodies, even malformed ones.
        path.write_text("NOT JSON: private outcome must never be opened", encoding="utf-8")
        stamp = (self.now - timedelta(minutes=minutes_ago)).timestamp()
        os.utime(path, (stamp, stamp))

    def test_plan_driven_ids_numeric_attempts_and_no_outcome_read(self) -> None:
        for name in ("C1-s2-N-a1.json", "E01-s2-Ho-a2.json", "E01-s2-Ho-a10.json"):
            self.report(name)
        self.report("Z9-s2-N.json")
        result = snapshot(self.root, now=self.now)
        self.assertEqual(result["job_ids_with_reports"], 3)
        self.assertEqual(result["attempt_report_files"], 4)
        self.assertEqual(result["multiple_attempt_job_ids"], ["E01-s2-Ho"])
        self.assertEqual(result["by_arm"]["N"]["job_ids_with_reports"], 2)
        self.assertNotIn("private outcome", json.dumps(result))

    def test_sleep_union_active_time_and_conditional_rate(self) -> None:
        self.report("E01-s2-N-a1.json")
        sleeps = [
            (self.start, self.start + timedelta(minutes=45)),
            (self.start + timedelta(minutes=30), self.start + timedelta(hours=1)),
        ]
        result = snapshot(self.root, now=self.now, started_at=self.start, sleeps=sleeps)
        timing = result["timing"]
        self.assertEqual(timing["wall_seconds"], 7200)
        self.assertEqual(timing["reported_sleep_seconds"], 3600)
        self.assertEqual(timing["awake_wall_seconds"], 3600)
        self.assertIsNone(timing["CPU_seconds"])
        self.assertEqual(timing["report_presence_per_hour"], 1)
        self.assertEqual(timing["conditional_seconds_to_remaining_report_presence"], 18000)

    def test_stale_snapshot_does_not_extrapolate_or_retry(self) -> None:
        self.report("E01-s2-N-a1.json", minutes_ago=20)
        before = set(self.root.iterdir())
        result = snapshot(self.root, now=self.now, started_at=self.start)
        self.assertIsNone(result["timing"]["conditional_seconds_to_remaining_report_presence"])
        self.assertTrue(result["warnings"])
        self.assertEqual(before, set(self.root.iterdir()))

    def test_exclusions_and_unknown_report_are_explicit(self) -> None:
        (self.root / "exclusions.json").write_text('{"excluded":["C1"]}', encoding="utf-8")
        self.report("Q4-s2-N-a1.json")
        result = snapshot(self.root, now=self.now)
        self.assertEqual(result["planned_jobs"], 4)
        self.assertEqual(result["unexpected_job_ids"], ["Q4-s2-N"])
        self.assertTrue(result["warnings"])

    def test_changed_mind_session_one_arms(self) -> None:
        self.jobs = [{"family": "D1", "session": 1, "arm": a} for a in ("S1a", "S1b")] + self.jobs
        self.plan()
        self.report("D1-s1-S1b-a1.json")
        result = snapshot(self.root, session=1, now=self.now)
        self.assertEqual((result["planned_jobs"], result["job_ids_with_reports"]), (2, 1))
        self.assertEqual(result["missing_job_ids"], ["D1-s1-S1a"])

    def test_invalid_times_and_duplicate_plan_fail(self) -> None:
        with self.assertRaises(ValueError):
            instant("2026-01-01T10:00:00")
        with self.assertRaises(ValueError):
            snapshot(self.root, now=self.now, started_at=self.now + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            snapshot(self.root, now=self.now, sleeps=[(self.start, self.now)])
        self.jobs.append(self.jobs[0])
        self.plan()
        with self.assertRaises(ValueError):
            snapshot(self.root, now=self.now)

    def test_budget_delegates_accounting_without_returning_private_rows(self) -> None:
        rows = [{"prompt": "PRIVATE"}]
        read = Mock(return_value=rows)
        ledger = Mock(
            return_value={
                "started": 2,
                "charged_credits": 1.5,
                "reasons": [],
            }
        )
        fake = SimpleNamespace(journal_rows=read, pilot_ledger=ledger)
        with patch.dict(
            "sys.modules",
            {"research.commitment_pilot": fake},
        ):
            result = budget_snapshot(self.root)
        read.assert_called_once_with(self.root)
        ledger.assert_called_once_with(rows, 20, 10)
        self.assertEqual(result["started"], 2)
        self.assertEqual(result["charged_credits"], 1.5)
        self.assertEqual(result["request_headroom"], 18)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_invalid_budget_metadata_fails_before_loading_research_dependencies(self) -> None:
        for cap, stop in ((True, 10), (20, 0), (20, "unknown")):
            (self.root / "plan.json").write_text(
                json.dumps({"request_cap": cap, "credit_stop": stop}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                budget_snapshot(self.root)

    def test_dated_plan_nested_budget(self) -> None:
        (self.root / "plan.json").write_text(
            json.dumps({"budget": {"hard_cap": 3408, "credit_stop": 400.0}}), encoding="utf-8"
        )
        ledger = Mock(return_value={"started": 8, "charged_credits": 1.0, "reasons": []})
        fake = SimpleNamespace(journal_rows=Mock(return_value=[]), pilot_ledger=ledger)
        with patch.dict("sys.modules", {"research.commitment_pilot": fake}):
            result = budget_snapshot(self.root)
        ledger.assert_called_once_with([], 3408, 400.0)
        self.assertEqual(result["request_headroom"], 3400)


if __name__ == "__main__":
    unittest.main()
