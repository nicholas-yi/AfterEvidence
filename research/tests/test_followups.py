"""Studies 9 to 12: second and third models, write it down, memory poisoning."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from research.harness.commitment_pilot import (
    BUDGETS,
    NEUTRAL_HEADER,
    PROVIDER_STAGES,
    STAGE_BUDGET,
    eval_seed,
    run_jobs,
)
from research.tests.fixtures import (
    FakeBackend,
    _features_policy,
    _first_session_source,
    act,
    stage3_policy,
)
from research.tests.support import shim_journal, slow


class SecondModelTests(unittest.TestCase):
    """Second-model replication (gpt-6-luna): generation, Mi record, dry pass and analysis."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research.studies import second_model

        cls.m2, cls.today = second_model, dt.date(2026, 11, 17)

    @slow
    def test_eval_families_are_fresh(self) -> None:
        m2 = self.m2
        families = list(m2.prepare(eval_seed("3" * 40))["families"].values())
        self.assertEqual(sorted(f["family"] for f in families), [f"P{i:02d}" for i in range(1, 33)])
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        others = [
            *m2.hf.prepare(m2.HF_SEED)["families"].values(),
            *m2.cm.prepare(m2.hf.DE_SEED, dated=True)["families"].values(),
        ]
        keys = {x for f in others for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        self.assertFalse(
            keys
            & {x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        )

    @slow
    def test_eval_dry_pass(self) -> None:
        from unittest import mock

        from research.analysis.common import read_csv
        from research.analysis.honcho_features_analysis import write_csv
        from research.analysis.second_model_analysis import analyse, rows_from_runs

        m2, today = self.m2, self.today
        self.assertIsNone(m2.tag_state("no-such-tag-for-tests"))
        tag = {"tag": m2.TAG, "commit": "3" * 40, "seed": eval_seed("3" * 40)}
        setup = {**m2.prepare(tag["seed"]), "today": m2.cm.today_sentence(today)}
        families, cfg = setup["families"], PROVIDER_STAGES[m2.EVAL_STAGE]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            public = m2.eval_plan(setup, "dry", tag, today)
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}
            Policy = _features_policy(
                families, seen, systems, {"Hn": "Y", "Mi": "X", "Hod": "decline", "Hs": "Y"}
            )
            options = {
                "exclude_uncommitted": True,
                "history_fn": m2.hf.history(today, run),
                "infra_continue": True,
            }
            first = m2.cm.select(public["jobs"], "session1", [])
            outcome = asyncio.run(
                run_jobs(
                    setup, run, first, lambda _: Policy([]), [run], 1880, 230.0, 1544, **options
                )
            )
            self.assertEqual((outcome["refused"], len(first)), ([], 64))
            included = m2.cm.committed(run)
            shim_journal(run, "mem0", 96)
            shim_journal(run, "honcho", 240)

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {
                        "state": str((run / "mem0").resolve()),
                        "honcho_workspace": cfg["workspace"],
                        "honcho_workspace_by_prefix": {},
                        "honcho_reasoning_level": None,
                        "queue": {"total": 1, "completed": 1, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    return {"result": {}}
                f = families[body["scope"][-3:]]
                return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = m2.hf.providers(setup, run, run, today, m2.EVAL_STAGE)
            m2.mem0_record(run, included)
            self.assertEqual(result["refused"], [])
            second = m2.cm.select(public["jobs"], "sessions", included)
            self.assertEqual(len(second), 128)
            seen.clear()
            outcome = asyncio.run(
                run_jobs(
                    setup, run, second, lambda _: Policy([]), [run], 1880, 230.0, 1544, **options
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(
                [seen[i * 32]["arm"] for i in range(4)], list(m2.ARMS)
            )  # arm blocks in priority order
            rows = rows_from_runs(run)
            analysis = analyse(rows)
            self.assertEqual(
                (analysis["included"], analysis["not_run_arms"], analysis["leakage_sessions"]),
                (32, [], 0),
            )
            arms = {
                a: (v["successes"], v["stale"], v["declined"]) for a, v in analysis["arms"].items()
            }
            self.assertEqual(
                arms, {"Hn": (32, 0, 0), "Mi": (0, 32, 0), "Hod": (0, 0, 32), "Hs": (32, 0, 0)}
            )
            self.assertEqual(
                analysis["primary_success"]["tests"]["Hod vs Hn (success)"]["reference_only"], 32
            )
            self.assertEqual(
                analysis["secondary_stale"]["tests"]["Mi vs Hn (stale)"]["arm_only"], 32
            )
            self.assertEqual(analysis["arms"]["Mi"]["memory_has_Y"], 32)
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), analysis)

    def test_dev_dry_pass_and_analysis(self) -> None:
        from unittest import mock

        from research.analysis.second_model_analysis import ARMS, analyse

        m2, today = self.m2, self.today
        setup = {**m2.prepare(), "today": m2.cm.today_sentence(today)}
        families = setup["families"]
        cfg = PROVIDER_STAGES[m2.DEV_STAGE]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            source, run = _first_session_source(Path(tmp) / "src", families), Path(tmp) / "run"
            run.mkdir()
            shim_journal(run, "mem0", 12)
            shim_journal(run, "honcho", 45)

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {
                        "state": str((run / "mem0").resolve()),
                        "honcho_workspace": cfg["workspace"],
                        "honcho_workspace_by_prefix": {},
                        "honcho_reasoning_level": None,
                        "queue": {"total": 1, "completed": 1, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    return {"result": {}}
                f = families[body["scope"][-2:]]
                return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = m2.hf.providers(setup, run, source, today, m2.DEV_STAGE)
            m2.mem0_record(run, sorted(families))
            self.assertEqual(result["refused"], [])
            mi = json.loads((run / "memory" / "D1-Mi.json").read_text(encoding="utf-8"))
            mir = json.loads((run / "memory" / "D1-Mir.json").read_text(encoding="utf-8"))
            self.assertEqual((mi["text"], mi["shared_from"]), (mir["text"], "Mir"))
            public = m2.plan(setup, "dry", today, m2.DEV_STAGE, m2.hf.DEV_SEED, {})
            self.assertEqual(
                (public["model"], [j["arm"] for j in public["jobs"][::4]]),
                ("gpt-6-luna", list(m2.ARMS)),
            )
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}
            Policy = _features_policy(
                families, seen, systems, {"Hn": "Y", "Mi": "X", "Hod": "decline", "Hs": "Y"}
            )
            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    public["jobs"],
                    lambda _: Policy([]),
                    [run],
                    260,
                    35.0,
                    192,
                    exclude_uncommitted=True,
                    history_fn=m2.hf.history(today, source),
                    infra_continue=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            summary = m2.summary(run, setup, outcome)
            self.assertEqual(summary["verdict"], "PASS", summary["gates"])
            rows = [
                {"family": f, "session": 1, "arm": a, "commitment": True}
                for f in families
                for a in ("S1a", "S1b")
            ]
            rows += [
                {
                    "family": r["family"],
                    "session": 2,
                    "arm": r["arm"],
                    "success": r["success"],
                    "stale_commitment": r["stale_commitment"],
                    "declined": r["declined"],
                }
                for r in summary["rows"]
            ]
            result = analyse(rows, planned_families=4)
            self.assertEqual(result["complete_arms"], list(ARMS))
            self.assertEqual(
                result["primary_success"]["tests"]["Hod vs Hn (success)"]["reference_only"], 4
            )
            self.assertEqual(result["secondary_stale"]["tests"]["Mi vs Hn (stale)"]["arm_only"], 4)


class FollowupsTests(unittest.TestCase):
    """Studies 10 (write it down, transcript tool) and 11 (third model): providers, dry passes."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research.studies import followups

        cls.fu, cls.today = followups, dt.date(2026, 11, 19)

    @staticmethod
    def _gateway(
        run: Path, families: dict[str, Any], calls: dict[str, list[Any]], workspace: str
    ) -> Any:
        ids = iter(range(10**6))

        def gateway(
            path: str, body: dict[str, Any], url: str = "", timeout: int = 0
        ) -> dict[str, Any]:
            calls.setdefault(path, []).append(body)
            if path == "/status":
                return {
                    "state": str((run / "mem0").resolve()),
                    "honcho_workspace": workspace,
                    "honcho_workspace_by_prefix": {},
                    "honcho_reasoning_level": None,
                    "queue": {"total": 1, "completed": 1, "pending": 0, "in_progress": 0},
                }
            if path == "/ingest":
                return {"result": {}}
            if path == "/mem0/facts":
                return {
                    "result": {
                        "created": [f"m{next(ids)}" for _ in body["facts"]],
                        "deleted": body["delete"],
                        "missing": [],
                    }
                }
            f = next(v for k, v in families.items() if body["scope"].endswith(k))
            return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

        return gateway

    def _sessions(
        self, spec: Any, setup: dict[str, Any], run: Path, source: Path, plan_for: dict[str, str]
    ) -> Any:
        seen: list[Any] = []
        prompts: dict[str, list[str]] = {}
        Policy = stage3_policy(setup["families"], plan_for, seen, prompts)
        public = self.fu.plan(spec, setup, "dry", self.today, spec.dev_stage, 7, {})
        budget = BUDGETS[STAGE_BUDGET[spec.dev_stage]]
        outcome = asyncio.run(
            run_jobs(
                setup,
                run,
                public["jobs"],
                lambda _: Policy([]),
                [run],
                budget["cap"],
                budget["credit_stop"],
                PROVIDER_STAGES[spec.dev_stage]["episode_cap"],
                history_fn=self.fu.hf.history(self.today, source),
                infra_continue=True,
            )
        )
        return outcome, prompts

    def test_write_it_down_dev_dry_pass(self) -> None:
        from unittest import mock

        fu, today, spec = self.fu, self.today, self.fu.WD
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            run = Path(tmp) / "run"
            run.mkdir()
            families = fu.prepare(spec)["families"]
            source = _first_session_source(Path(tmp) / "src", families)
            setup = fu.setup_for(spec, source, today)
            shim_journal(run, "mem0", 24)
            shim_journal(run, "app", 10)
            calls: dict[str, list[Any]] = {}
            texts: list[str] = []

            def summarizer(text: str) -> list[str]:
                texts.append(text)
                return [f"Summary {len(texts)}.", "Current agreement: the latest item."]

            gateway = self._gateway(run, families, calls, "unused")
            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = fu.providers(
                    spec, setup, run, source, today, spec.dev_stage, summarizer=summarizer
                )
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            ingested = Counter(b["scope"].removeprefix("customer:")[:-2] for b in calls["/ingest"])
            self.assertEqual(
                ingested, {"cmp-wd-d1-": 8, "cmp-wd-d1-w-": 8}
            )  # Mi and Mw scopes only
            self.assertTrue(all(b["provider"] == "mem0" for b in calls["/ingest"]))
            facts = calls["/mem0/facts"]
            self.assertEqual(len(facts), 8)
            self.assertTrue(
                all(b["delete"] == [] for b in facts[0::2])
                and all(len(b["delete"]) == 2 for b in facts[1::2])
            )  # replaces its own facts
            self.assertTrue(all(b["scope"].startswith("customer:cmp-wd-d1-w-") for b in facts))
            self.assertEqual(
                texts[:2], [fu.s3.summarizer_input(source, "D1", today, o) for o in "ab"]
            )
            self.assertEqual(
                {(b["provider"], b["scope"][9:-2]) for b in calls["/search"]},
                {("mem0", "cmp-wd-d1-"), ("mem0", "cmp-wd-d1-w-")},
            )
            names = sorted(p.stem.split("-")[1] for p in (run / "memory").glob("D1-*.json"))
            self.assertEqual(names, ["Fd", "Mi", "Mw"])
            self.assertIn(
                "Current agreement",
                json.loads((run / "memory" / "D1-Fd.json").read_text(encoding="utf-8"))["text"],
            )
            self.assertEqual(
                setup["memory_tool"]("D1", "anything"),
                fu.cm.dated_history_text(source, "D1", today),
            )
            outcome, prompts = self._sessions(
                spec,
                setup,
                run,
                source,
                {"Mi": "decline", "Mw": "Y", "Hn": "Y", "Tn": "recall", "Fd": "Y"},
            )
            self.assertEqual(outcome["refused"], [])
            label = fu.cm.session_label(today, "a")
            self.assertNotIn(label, prompts["D1-Tn"][0])  # no memory block up front
            self.assertIn(label, prompts["D1-Tn"][1])  # the tool's answer: the dated transcripts
            self.assertIn(NEUTRAL_HEADER + label, prompts["D1-Hn"][0])
            self.assertIn("Current agreement", prompts["D1-Fd"][0])
            self.assertFalse(any(fu.cp.MEMORY_TOOL in p for p in prompts["D1-Hn"]))
            summary = fu.dev_summary(spec, run, setup, source, today, outcome)
            self.assertEqual(summary["verdict"], "PASS", summary["gates"])
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            self.assertTrue(all(rows[(f, "Tn")]["tool_calls"] == 1 for f in families))
            self.assertFalse(any(rows[(f, "Mi")]["success"] for f in families))

    def test_third_model_dev_dry_pass(self) -> None:
        from unittest import mock

        fu, today, spec = self.fu, self.today, self.fu.M3
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            run = Path(tmp) / "run"
            run.mkdir()
            families = fu.prepare(spec)["families"]
            source = _first_session_source(Path(tmp) / "src", families)
            setup = fu.setup_for(spec, source, today)
            self.assertNotIn("memory_tool", setup)
            for label, cap in PROVIDER_STAGES[spec.dev_stage]["shim_caps"].items():
                shim_journal(run, label, cap)
            calls: dict[str, list[Any]] = {}
            texts: list[str] = []
            workspace = PROVIDER_STAGES[spec.dev_stage]["workspace"]
            with mock.patch(
                "research.harness.provider_ingest.post",
                side_effect=self._gateway(run, families, calls, "wrong-workspace"),
            ):
                refused = fu.providers(
                    spec, setup, run, source, today, spec.dev_stage, summarizer=texts.append
                )
            self.assertTrue(refused["refused"])  # another Honcho workspace: nothing is ingested
            self.assertNotIn("/ingest", calls)
            with mock.patch(
                "research.harness.provider_ingest.post",
                side_effect=self._gateway(run, families, calls, workspace),
            ):
                result = fu.providers(
                    spec,
                    setup,
                    run,
                    source,
                    today,
                    spec.dev_stage,
                    summarizer=lambda text: texts.append(text) or ["Current agreement: Y."],
                )
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            self.assertEqual(
                Counter(b["provider"] for b in calls["/ingest"]), {"mem0": 8, "honcho": 8}
            )
            self.assertEqual(len(texts), 4)  # Fd only: one summary per family, over 1a and 1b
            self.assertNotIn("/mem0/facts", calls)
            outcome, _ = self._sessions(
                spec, setup, run, source, {"Hn": "Y", "Mi": "Y", "Hod": "decline", "Fd": "Y"}
            )
            self.assertEqual(outcome["refused"], [])
            summary = fu.dev_summary(spec, run, setup, source, today, outcome)
            self.assertEqual(summary["verdict"], "PASS", summary["gates"])

    def test_poisoned_memory_dev_dry_pass(self) -> None:
        from unittest import mock

        fu, today, spec = self.fu, self.today, self.fu.PZ
        setup = fu.setup_for(spec, Path("unused"), today)
        families = setup["families"]
        self.assertEqual(sorted(families), ["T01", "T02", "T03", "T04"])
        self.assertIs(setup["customer"], fu.PoisonCustomer)
        budget = BUDGETS[STAGE_BUDGET[spec.dev_stage]]
        cap = PROVIDER_STAGES[spec.dev_stage]["episode_cap"]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for label, limit in PROVIDER_STAGES[spec.dev_stage]["shim_caps"].items():
                shim_journal(run, label, limit)
            first = [
                {"session": 1, "family": f, "arm": a}
                for f in sorted(families)
                for a in ("S1a", "S1b")
            ]
            public = fu.plan(
                spec, setup, "dry", today, spec.dev_stage, fu.dev_seed(spec), {}, first
            )

            class SessionOne(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    f = families[str(fields["family"])]
                    agree = [
                        act(text="Several options are in stock."),
                        act(text=f"Confirming item {f['target_id']}."),
                    ]
                    self.replies = (
                        agree
                        if fields["arm"] == "S1a"
                        else [act(text="Noted; nothing will change.")]
                    )

            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    fu.cm.select(public["jobs"], "session1", []),
                    lambda _: SessionOne([]),
                    [run],
                    budget["cap"],
                    budget["credit_stop"],
                    cap,
                    infra_continue=True,
                    exclude_uncommitted=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(fu.cm.committed(run), sorted(families))
            calls: dict[str, list[Any]] = {}
            workspace = PROVIDER_STAGES[spec.dev_stage]["workspace"]
            with mock.patch(
                "research.harness.provider_ingest.post",
                side_effect=self._gateway(run, families, calls, workspace),
            ):
                result = fu.providers(
                    spec,
                    setup,
                    run,
                    run,
                    today,
                    spec.dev_stage,
                    summarizer=lambda text: ["The customer kept the exchange agreed first."],
                )
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            mem0 = [b for b in calls["/ingest"] if b["provider"] == "mem0"]
            self.assertTrue(
                all(families[b["scope"][-3:]]["stale_id"] in json.dumps(b) for b in mem0[1::2])
            )
            prompts: dict[str, list[str]] = {}
            Policy = stage3_policy(
                families, {"Hn": "Y", "Mi": "Y", "Hod": "decline", "Fd": "Y"}, [], prompts
            )
            jobs = fu.cm.select(public["jobs"], "sessions", fu.cm.committed(run))
            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    jobs,
                    lambda _: Policy([]),
                    [run],
                    budget["cap"],
                    budget["credit_stop"],
                    cap,
                    history_fn=fu.hf.history(today, run),
                    infra_continue=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            f = families["T01"]
            self.assertIn(
                f["stale_id"], prompts["T01-Hn"][0]
            )  # the quoted message is in the transcript
            summary = fu.dev_summary(spec, run, setup, run, today, outcome)
            self.assertEqual(summary["verdict"], "PASS", summary["gates"])
            self.assertEqual(
                summary["session1"],
                {"included": sorted(families), "excluded": [], "1b_wrote_to_db": 0},
            )
            self.assertTrue(all(r["stale_commitment"] == 0 for r in summary["rows"]))

    @slow
    def test_evaluation_families_are_fresh_and_studies_differ(self) -> None:
        from itertools import combinations

        from research.studies import second_model as m2

        fu, commit = self.fu, "4" * 40
        specs = (fu.WD, fu.M3, fu.PZ)
        seeds = {s.key: fu.eval_seed(commit, s.tag) for s in specs}
        self.assertEqual(len(set(seeds.values())), 3)

        def keys(families: Any) -> set[Any]:
            return {
                x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))
            }

        built = {}
        for spec in specs:
            families = list(fu.prepare(spec, seeds[spec.key])["families"].values())
            self.assertEqual(
                sorted(f["family"] for f in families),
                [f"{spec.letter}{i:02d}" for i in range(1, 33)],
            )
            self.assertEqual(
                Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8}
            )
            built[spec.key] = keys(families)
        built["pz-dev"] = keys(fu.prepare(fu.PZ)["families"].values())
        others = keys(
            [
                *fu.s3.prepare_eval(fu.STAGE3_SEED)["families"].values(),
                *m2.prepare(fu.s3.M2_SEED)["families"].values(),
                *fu.hf.prepare(m2.HF_SEED)["families"].values(),
            ]
        )
        for name, found in built.items():
            self.assertFalse(others & found, name)
        self.assertFalse(built["pz"] & built["pz-dev"])
        for a, b in combinations(("wd", "m3", "pz"), 2):
            self.assertFalse(built[a] & built[b], (a, b))


if __name__ == "__main__":
    unittest.main()
