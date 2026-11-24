"""Studies 13 to 20: dry passes of every design."""

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
    PROVIDER_STAGES,
    STAGE_BUDGET,
    run_jobs,
)
from research.tests.fixtures import (
    FakeBackend,
    _first_session_source,
    act,
)
from research.tests.support import shim_journal, slow


class GapsDryPassTests(unittest.TestCase):
    """Studies 13-18 (research/gaps.py): session 1, providers, sessions and dev summaries, without
    inference. Policy choices: Y target, S stale_id, Z injected_id, F first_id, recallY, decline."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research.studies import gaps

        cls.g, cls.today = gaps, dt.date(2026, 11, 20)

    def _gateway(
        self, run: Path, families: dict[str, Any], calls: dict[str, list[Any]], design: Any
    ) -> Any:
        g, ids = self.g, iter(range(10**6))
        cfg = PROVIDER_STAGES[design.dev_stage]

        def gateway(
            path: str, body: dict[str, Any], url: str = "", timeout: int = 0
        ) -> dict[str, Any]:
            calls.setdefault(path, []).append(body)
            if path == "/status":
                return {
                    "state": str((run / "mem0").resolve()),
                    "honcho_workspace": cfg["workspace"],
                    "honcho_workspace_by_prefix": g.workspace_map(design, design.dev_stage),
                    "honcho_reasoning_level": None,
                    "queue": {"total": 1, "completed": 1, "pending": 0, "in_progress": 0},
                }
            if path == "/ingest":
                return {"result": {}}
            if path in ("/mem0/facts", "/honcho/facts"):
                return {"result": {"created": [f"c{next(ids)}" for _ in body["facts"]]}}
            if body["provider"] == "hindsight":
                raise OSError("hindsight unavailable")  # integration failure: Hi is dropped
            if body["scope"].endswith("shared"):
                return {
                    "results": [
                        f"{v['first']} {v['last']} agreed item {v['target_id']}."
                        for v in families.values()
                    ]
                }
            f = next(v for k, v in families.items() if body["scope"].endswith(k))
            return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

        return gateway

    def _policy(
        self, families: dict[str, Any], plan_for: dict[str, str], prompts: dict[str, list[str]]
    ) -> Any:
        from research.harness.commitment_pilot import MEMORY_TOOL

        g = self.g

        def first(f: dict[str, Any], arm: str) -> list[str]:
            if f.get("kind") == "address":
                item = f["stale_id"] if arm == "S1a" else f["target_id"]
                return [act(text=f"Noted: {g.address_text(f, item)}.")]
            if arm == "S1a":
                item = f.get("first_id") or f["stale_id"]
                return [
                    act(text="Several options are in stock."),
                    act(text=f"Confirming item {item}."),
                ]
            if arm in ("S1b", "S1d") and "first_id" in f:
                return [act(text="It was delivered on Monday; you paid by card.")]
            item = f["stale_id"] if arm == "S1c" else f["target_id"]
            return [act(text=f"Confirming item {item}.")]

        class Policy(FakeBackend):
            def write(self, event: str, **fields: object) -> None:
                if event != "commitment-session-started":
                    return
                f, arm = families[str(fields["family"])], str(fields["arm"])
                self.key = f"{fields['family']}-{arm}"
                if fields["session"] == 1:
                    self.replies = first(f, arm)
                    return
                choice = plan_for[arm]
                if choice == "decline":
                    self.replies = [act(text="I can't act without the exact item.")] * 12
                    return
                key = {"Y": "target_id", "S": "stale_id", "Z": "injected_id", "F": "first_id"}
                item = f[key[choice[-1]]]
                if f.get("kind") == "address":
                    address = g.alternative(f, item)["options"]
                    run = [
                        act(text=f"I'll change the address to {address['address1']}. Proceed?"),
                        act("modify_pending_order_address", order_id=f["order_id"], **address),
                        act(text="The address change has been completed."),
                    ]
                else:
                    run = [
                        act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                        act(
                            "exchange_delivered_order_items",
                            order_id=f["order_id"],
                            item_ids=[f["current"]["item_id"]],
                            new_item_ids=[item],
                            payment_method_id=f["payment_id"],
                        ),
                        act(text="The exchange has been processed."),
                    ]
                recall = [act(MEMORY_TOOL, question="What did we agree?")]
                self.replies = (recall if choice.startswith("recall") else []) + run

            async def complete(self, system: str, prompt: str, response_schema: Any = None) -> str:
                prompts.setdefault(getattr(self, "key", ""), []).append(system + prompt)
                return await super().complete(system, prompt, response_schema)

        return Policy

    def _run(
        self, design: Any, setup: dict[str, Any], run: Path, jobs: list, policy: Any, source: Path
    ) -> dict[str, Any]:
        budget = BUDGETS[STAGE_BUDGET[design.dev_stage]]
        return asyncio.run(
            run_jobs(
                setup,
                run,
                jobs,
                lambda _: policy([]),
                [run],
                budget["cap"],
                budget["credit_stop"],
                PROVIDER_STAGES[design.dev_stage]["episode_cap"],
                history_fn=self.g.history(design, self.today, source),
                infra_continue=True,
                exclude_uncommitted=True,
            )
        )

    @slow
    def test_gaps_dev_dry_pass(self) -> None:
        from unittest import mock

        g, today, design = self.g, self.today, self.g.GX
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            run = Path(tmp) / "run"
            run.mkdir()
            families = g.prepare(design)["families"]
            self.assertTrue(
                all(
                    f["injected_id"] not in (f["target_id"], f["stale_id"], f["rejected_id"])
                    for f in families.values()
                )
            )
            source = _first_session_source(Path(tmp) / "src", families)
            setup = g.setup_for(design, source, today)
            self.assertEqual(setup["memory_tool_arms"], ("Tn", "Tp"))
            for label, cap in PROVIDER_STAGES[design.dev_stage]["shim_caps"].items():
                shim_journal(run, label, cap)
            calls: dict[str, list[Any]] = {}
            texts: list[str] = []

            def summarizer(text: str) -> list[str]:
                texts.append(text)
                return [f"Summary {len(texts)}."]

            gateway = self._gateway(run, families, calls, design)

            import urllib.error

            def failing(path: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
                if path == "/ingest" and body["provider"] == "honcho" and "D2" in body["scope"]:
                    raise urllib.error.URLError("Honcho unavailable")  # e.g. Docker stopped
                return gateway(path, body, **kwargs)

            with mock.patch("research.harness.provider_ingest.post", side_effect=failing):
                stopped = g.providers(
                    design,
                    setup,
                    run,
                    source,
                    today,
                    design.dev_stage,
                    sorted(families),
                    summarizer=summarizer,
                )
            self.assertTrue(stopped["refused"] and stopped["ingestion_errors"])
            self.assertFalse(list((run / "memory").glob("*.json")))  # no retrieval written
            done = json.loads((run / "ingested.json").read_text(encoding="utf-8"))
            self.assertNotIn("Hod:D2", done)
            self.assertIn("Hod:D1", done)
            first_pass = len(calls["/ingest"])  # failed writes never reached the store
            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = g.providers(
                    design,
                    setup,
                    run,
                    source,
                    today,
                    design.dev_stage,
                    sorted(families),
                    summarizer=summarizer,
                )
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            # the retry re-ingests only the failed episodes; every other write already succeeded
            self.assertEqual(
                sorted(b["scope"] for b in calls["/ingest"][first_pass:]),
                ["customer:cmp-gx-d2-D2"] * 2 + ["customer:cmp-gx-d2-z-D2"] * 2,
            )

            def stem(scope: str) -> str:
                scope = scope.removeprefix("customer:")
                return scope if scope.endswith("shared") else scope[:-2]

            self.assertEqual(
                Counter((b["provider"], stem(b["scope"])) for b in calls["/ingest"]),
                {
                    ("mem0", "cmp-gx-d2-"): 8,
                    ("mem0", "cmp-gx-d2-z-"): 8,
                    ("mem0", "cmp-gx-d2-s-shared"): 8,
                    ("honcho", "cmp-gx-d2-"): 8,
                    ("honcho", "cmp-gx-d2-z-"): 8,
                    ("graphiti", "cmp-gx-d2-"): 8,
                    ("hindsight", "cmp-gx-d2-"): 8,
                },
            )
            graph = [b["episode"] for b in calls["/ingest"] if b["provider"] == "graphiti"]
            self.assertTrue(all(e["time"] and "UTC:" in e["lines"][0][1] for e in graph))
            self.assertEqual(len(texts), 8)  # after 1a and after 1b, per family
            self.assertEqual(texts[0], g.history_text(source, "D1", today, g.TWO, "a"))
            for path, prefix in (
                ("/mem0/facts", "cmp-gx-d2-z-"),
                ("/honcho/facts", "cmp-gx-d2-z-"),
            ):
                self.assertEqual(len(calls[path]), 4)
                for body in calls[path]:
                    f = families[body["scope"][-2:]]
                    self.assertTrue(body["scope"].startswith("customer:" + prefix))
                    self.assertIn(f["injected_id"], body["facts"][0])
            records = sorted(p.stem.split("-", 1)[1] for p in (run / "memory").glob("D1-*.json"))
            self.assertEqual(records, sorted(set(design.arms) - {"Hn", "Tn", "Tp"}))
            plan_for = {
                **dict.fromkeys(design.arms, "Y"),
                "Fs": "S",
                "Mz": "Z",
                "Fz": "Z",
                "Tn": "decline",
                "Tp": "recallY",
                "Hz": "decline",
            }
            prompts: dict[str, list[str]] = {}
            public = g.plan(design, setup, "dry", today, design.dev_stage, 7, {})
            outcome = self._run(
                design,
                setup,
                run,
                public["jobs"],
                self._policy(families, plan_for, prompts),
                source,
            )
            self.assertEqual(outcome["refused"], [])
            instruction = g.cp.ARM_INSTRUCTIONS["Tp"]
            self.assertIn(instruction, prompts["D1-Tp"][0])
            self.assertNotIn(instruction, prompts["D1-Tn"][0])
            self.assertIn("Summary 1.", prompts["D1-Fs"][0])
            self.assertNotIn("Summary 2.", prompts["D1-Fs"][0])
            self.assertIn("Summary 2.", prompts["D1-Fd"][0])
            self.assertIn(families["D1"]["injected_id"], prompts["D1-Fz"][0])
            summary = g.dev_summary(design, run, setup, source, today, outcome)
            self.assertEqual(summary["verdict"], "PASS", summary["gates"])
            self.assertEqual(summary["dropped_arms"], ["Hi"])
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            for f in families:
                self.assertEqual(rows[(f, "Mz")]["injected"], 1)
                self.assertEqual(rows[(f, "Fs")]["stale"], 1)
                self.assertEqual(rows[(f, "Tp")]["tool_calls"], 1)
                self.assertTrue(rows[(f, "Ms")]["success"] and rows[(f, "Hn")]["success"])

    @slow
    def test_long_history_dev_dry_pass(self) -> None:
        from unittest import mock

        g, today, design = self.g, self.today, self.g.LH
        setup = g.setup_for(design, Path("unused"), today)
        families = setup["families"]
        self.assertEqual(sorted(families), ["W01", "W02", "W03", "W04"])
        self.assertTrue(
            all(
                len({f["first_id"], f["stale_id"], f["target_id"], f["rejected_id"]}) == 4
                for f in families.values()
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            setup = g.setup_for(design, run, today)
            for label, cap in PROVIDER_STAGES[design.dev_stage]["shim_caps"].items():
                shim_journal(run, label, cap)
            first = [
                {"session": 1, "family": f, "arm": f"S1{o}"}
                for f in sorted(families)
                for o in g.FIVE
            ]
            public = g.plan(
                design, setup, "dry", today, design.dev_stage, g.dev_seed(design), {}, first
            )
            prompts: dict[str, list[str]] = {}
            plan_for = {"Hn": "Y", "Mi": "F", "Hod": "S", "Fd": "decline"}
            policy = self._policy(families, plan_for, prompts)
            outcome = self._run(
                design, setup, run, [j for j in public["jobs"] if j["session"] == 1], policy, run
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(g.committed(run, g.FIVE), sorted(families))
            calls: dict[str, list[Any]] = {}
            texts: list[str] = []
            with mock.patch(
                "research.harness.provider_ingest.post",
                side_effect=self._gateway(run, families, calls, design),
            ):
                result = g.providers(
                    design,
                    setup,
                    run,
                    run,
                    today,
                    design.dev_stage,
                    sorted(families),
                    summarizer=lambda text: texts.append(text) or ["The latest agreement."],
                )
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            self.assertEqual(
                Counter(b["provider"] for b in calls["/ingest"]), {"mem0": 20, "honcho": 20}
            )
            self.assertEqual(len(texts), 4)
            self.assertTrue(all(g.label(today, g.FIVE, o) in texts[0] for o in g.FIVE))
            jobs = [j for j in public["jobs"] if j["session"] == 2]
            outcome = self._run(design, setup, run, jobs, policy, run)
            self.assertEqual(outcome["refused"], [])
            self.assertTrue(all(g.label(today, g.FIVE, o) in prompts["W01-Hn"][0] for o in g.FIVE))
            summary = g.dev_summary(design, run, setup, run, today, outcome)
            self.assertEqual((summary["verdict"], summary["dropped_arms"]), ("PASS", []), summary)
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            for f in families:
                self.assertTrue(rows[(f, "Hn")]["success"])
                self.assertEqual((rows[(f, "Mi")]["superseded"], rows[(f, "Mi")]["stale"]), (1, 0))
                self.assertEqual(
                    (rows[(f, "Hod")]["superseded"], rows[(f, "Hod")]["stale"]), (1, 1)
                )

    def test_address_change_dev_dry_pass(self) -> None:
        from unittest import mock

        g, today, design = self.g, self.today, self.g.AC
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            setup = g.setup_for(design, run, today)
            families = setup["families"]
            self.assertEqual(sorted(families), ["B01", "B02", "B03", "B04"])
            self.assertIs(setup["oracle"], g.address_oracle)
            self.assertEqual(
                setup["tasks"]["B01"].evaluation_criteria.actions[0].name,
                "modify_pending_order_address",
            )
            for label, cap in PROVIDER_STAGES[design.dev_stage]["shim_caps"].items():
                shim_journal(run, label, cap)
            first = [
                {"session": 1, "family": f, "arm": f"S1{o}"} for f in sorted(families) for o in "ab"
            ]
            public = g.plan(
                design, setup, "dry", today, design.dev_stage, g.dev_seed(design), {}, first
            )
            prompts: dict[str, list[str]] = {}
            policy = self._policy(
                families, {"Hn": "Y", "Mi": "S", "Hod": "decline", "Fd": "Y"}, prompts
            )
            outcome = self._run(
                design, setup, run, [j for j in public["jobs"] if j["session"] == 1], policy, run
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(g.committed(run, g.TWO), sorted(families))
            calls: dict[str, list[Any]] = {}
            with mock.patch(
                "research.harness.provider_ingest.post",
                side_effect=self._gateway(run, families, calls, design),
            ):
                result = g.providers(
                    design,
                    setup,
                    run,
                    run,
                    today,
                    design.dev_stage,
                    sorted(families),
                    summarizer=lambda text: ["The current shipping address change."],
                )
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            self.assertIn("address change", g.first_message(setup, families["B01"]))
            jobs = [j for j in public["jobs"] if j["session"] == 2]
            outcome = self._run(design, setup, run, jobs, policy, run)
            self.assertEqual(outcome["refused"], [])
            summary = g.dev_summary(design, run, setup, run, today, outcome)
            self.assertEqual((summary["verdict"], summary["dropped_arms"]), ("PASS", []), summary)
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            for f in families:
                self.assertTrue(rows[(f, "Hn")]["success"] and rows[(f, "Fd")]["success"])
                self.assertEqual((rows[(f, "Mi")]["success"], rows[(f, "Mi")]["stale"]), (False, 1))
                self.assertTrue(rows[(f, "Hod")]["declined"])

    @slow
    def test_gap_evaluation_families_are_fresh(self) -> None:
        from itertools import combinations

        g, commit = self.g, "5" * 40
        designs = (g.GX, g.LH, g.AC)

        def keys(families: Any) -> set[Any]:
            return {
                x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))
            }

        built = {}
        for design in designs:
            families = list(g.prepare(design, g.eval_seed(commit, design.tag))["families"].values())
            self.assertEqual(
                sorted(f["family"] for f in families),
                [f"{design.letter}{i:02d}" for i in range(1, 33)],
            )
            self.assertEqual(
                Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8}
            )
            built[design.key] = keys(families)
            if design.dev_letter:
                built[design.key + "-dev"] = keys(g.prepare(design)["families"].values())
        from research.harness import commitment_pilot as cp

        base, pool = cp._vendor_env()[1][1], g.hf.prepare()["pool"]
        earlier = keys(g.avoid_families(base, pool))
        for name, found in built.items():
            self.assertFalse(earlier & found, name)
        for a, b in combinations(sorted(built), 2):
            self.assertFalse(built[a] & built[b], (a, b))

    @slow
    def test_second_model_designs_dry_pass(self) -> None:
        """Studies 19-20: gpt-6-luna replications of gx (frozen D1-D4) and lh (live session 1)."""
        from unittest import mock

        g, today = self.g, self.today
        for design in (g.GM, g.LM):
            with self.subTest(design=design.key), tempfile.TemporaryDirectory() as tmp:
                run = Path(tmp) / "run"
                run.mkdir()
                if design.dev_letter:
                    setup = g.setup_for(design, run, today)
                    families, source = setup["families"], run
                else:
                    (Path(tmp) / "src").mkdir()
                    families = g.prepare(design)["families"]
                    source = _first_session_source(Path(tmp) / "src", families)
                    setup = g.setup_for(design, source, today)
                self.assertEqual(design.model, "gpt-6-luna")
                for label, cap in PROVIDER_STAGES[design.dev_stage]["shim_caps"].items():
                    shim_journal(run, label, cap)
                plan_for = dict.fromkeys(design.arms, "Y") | {"Tn": "decline", "Tp": "recallY"}
                prompts: dict[str, list[str]] = {}
                policy = self._policy(families, plan_for, prompts)
                first = [
                    {"session": 1, "family": f, "arm": f"S1{o}"}
                    for f in sorted(families)
                    for o in design.phases
                ]
                public = g.plan(
                    design,
                    setup,
                    "dry",
                    today,
                    design.dev_stage,
                    7,
                    {},
                    first if design.dev_letter else None,
                )
                self.assertEqual(public["model"], "gpt-6-luna")
                self.assertEqual(public["completion"], "COMPLETED (Studies 19-20)")
                if design.dev_letter:
                    jobs = [j for j in public["jobs"] if j["session"] == 1]
                    self.assertEqual(
                        self._run(design, setup, run, jobs, policy, run)["refused"], []
                    )
                calls: dict[str, list[Any]] = {}
                with mock.patch(
                    "research.harness.provider_ingest.post",
                    side_effect=self._gateway(run, families, calls, design),
                ):
                    result = g.providers(
                        design,
                        setup,
                        run,
                        source,
                        today,
                        design.dev_stage,
                        g.committed(source, design.phases),
                        summarizer=lambda text: ["The current agreement."],
                    )
                self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
                self.assertNotIn("graphiti", {b["provider"] for b in calls["/ingest"]})
                jobs = [j for j in public["jobs"] if j["session"] == 2]
                outcome = self._run(design, setup, run, jobs, policy, source)
                self.assertEqual(outcome["refused"], [])
                summary = g.dev_summary(design, run, setup, source, today, outcome)
                self.assertEqual((summary["verdict"], summary["dropped_arms"]), ("PASS", []))
                rows = [r for r in summary["rows"] if r["arm"] not in ("Tn",)]
                self.assertTrue(all(r["success"] for r in rows), rows)

    @slow
    def test_second_model_families_avoid_studies_13_to_18(self) -> None:
        g, commit = self.g, "6" * 40

        def keys(families: Any) -> set[Any]:
            return {
                x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))
            }

        from research.harness import commitment_pilot as cp

        base, pool = cp._vendor_env()[1][1], g.hf.prepare()["pool"]
        earlier = keys(g.avoid_families(base, pool, later=True))
        built = {}
        for design in (g.GM, g.LM):
            families = list(g.prepare(design, g.eval_seed(commit, design.tag))["families"].values())
            self.assertEqual(
                sorted(f["family"] for f in families),
                [f"{design.letter}{i:02d}" for i in range(1, 33)],
            )
            built[design.key] = keys(families)
            self.assertFalse(earlier & built[design.key], design.key)
        built["lm-dev"] = keys(g.prepare(g.LM)["families"].values())
        self.assertFalse(earlier & built["lm-dev"])
        self.assertFalse(built["gm"] & built["lm"] or built["lm"] & built["lm-dev"])


if __name__ == "__main__":
    unittest.main()
