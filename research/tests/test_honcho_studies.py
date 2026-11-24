"""Studies 7 and 8: Honcho features and Honcho Stage 3."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from research.harness.commitment_pilot import (
    ACTOR_SYSTEM,
    NEUTRAL_HEADER,
    PROVIDER_STAGES,
    RUNS,
    FatalStop,
    eval_seed,
    final_reports,
    first_message,
    run_jobs,
)
from research.tests.fixtures import (
    SETUP,
    FakeBackend,
    _features_policy,
    _first_session_source,
    act,
    stage3_policy,
)
from research.tests.support import shim_journal, slow


class HonchoFeaturesTests(unittest.TestCase):
    """Honcho features: restating customer, message search, schedule, dry passes."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research.studies import honcho_features

        cls.hf, cls.today = honcho_features, dt.date(2026, 11, 16)
        cls.dev = honcho_features.prepare()

    def test_stage_one_b_reuses_retrievals_and_gates_stage_two(self) -> None:
        from unittest import mock

        hf = self.hf
        with tempfile.TemporaryDirectory() as tmp:
            first, rerun = Path(tmp) / "v1", Path(tmp) / "v2"
            (first / "memory").mkdir(parents=True)
            for name in ("D1-Hod", "D1-Hodr", "D1-Mir", "D1-Hs"):
                (first / "memory" / f"{name}.json").write_text(
                    json.dumps({"text": name}), encoding="utf-8"
                )
            with (
                mock.patch.object(hf, "DEV_DIRECTORY", first),
                mock.patch.object(hf, "DEV2_DIRECTORY", rerun),
            ):
                copied = hf.reuse_retrievals(rerun)
                self.assertEqual(hf.shim_problems(rerun, hf.DEV2_STAGE), [])  # no shims in Stage 1b
                (rerun / "shims").mkdir()
                (rerun / "shims" / "mem0.calls.jsonl").write_text("", encoding="utf-8")
                self.assertTrue(hf.shim_problems(rerun, hf.DEV2_STAGE))
                self.assertEqual(sorted(copied), ["D1-Hod.json", "D1-Hodr.json", "D1-Mir.json"])
                self.assertFalse((rerun / "memory" / "D1-Hs.json").exists())
                self.assertFalse(hf.stage_one_passed())
                gates = {
                    "Hs_retrieval_3of4": True,
                    "zero_leakage": True,
                    "no_harness_defect": True,
                    "restating_customer_answered_every_which": False,
                }
                (first / "summary-audited.json").write_text(
                    json.dumps({"gates": gates}), encoding="utf-8"
                )
                (rerun / "summary.json").write_text(
                    json.dumps({"verdict": "PASS"}), encoding="utf-8"
                )
                self.assertTrue(
                    hf.stage_one_passed()
                )  # the restating gate is superseded by Stage 1b
                (first / "summary-audited.json").write_text(
                    json.dumps({"gates": {**gates, "zero_leakage": False}}), encoding="utf-8"
                )
                self.assertFalse(hf.stage_one_passed())
                (first / "summary-audited.json").write_text(
                    json.dumps({"gates": gates}), encoding="utf-8"
                )
                (rerun / "summary.json").write_text(
                    json.dumps({"verdict": "FAIL"}), encoding="utf-8"
                )
                self.assertFalse(hf.stage_one_passed())

    def test_message_search_rendering_and_scope(self) -> None:
        import datetime as dt
        from types import SimpleNamespace

        from research.harness import memory_gateway as gateway

        calls: list[Any] = []
        when = dt.datetime(2026, 11, 13, 14, 20, tzinfo=dt.UTC)

        class Workspace:
            def peer(self, name: str) -> Any:
                return SimpleNamespace(
                    sessions=lambda: [SimpleNamespace(id="s1a"), SimpleNamespace(id="s1b")]
                )

            def search(self, query: str, filters: Any = None, limit: int = 10) -> list[Any]:
                calls.append((query, filters, limit))
                return [
                    SimpleNamespace(
                        created_at=when, peer_id="agent", content="Item 123: is that the one?"
                    ),
                    SimpleNamespace(
                        created_at=when, peer_id="cmp-x-D1", content="Yes, that's the one."
                    ),
                ]

        store = object.__new__(gateway.HonchoStore)
        store.clients, store.factory = {}, lambda workspace: Workspace()
        lines = store.messages("customer:cmp-x-D1", "go ahead")
        self.assertEqual(
            lines,
            [
                "[2026-11-13 14:20 UTC] Agent: Item 123: is that the one?",
                "[2026-11-13 14:20 UTC] Customer: Yes, that's the one.",
            ],
        )
        self.assertEqual(calls, [("go ahead", {"session_id": {"in": ["s1a", "s1b"]}}, 10)])

    @slow
    def test_schedule_caps_and_eval_generation(self) -> None:
        hf = self.hf
        jobs = hf.schedule([f"K{i:02d}" for i in range(1, 33)], hf.EVAL_ARMS, 7)
        blocks = [jobs[i * 32 : (i + 1) * 32] for i in range(len(hf.EVAL_ARMS))]
        self.assertEqual([b[0]["arm"] for b in blocks], list(hf.EVAL_ARMS))  # priority order
        self.assertTrue(
            all(
                len({j["family"] for j in b}) == 32 and len({j["arm"] for j in b}) == 1
                for b in blocks
            )
        )
        for stage, (cap, stop) in (
            (hf.DEV_STAGE, (350, 40.0)),
            (hf.DEV2_STAGE, (200, 25.0)),
            (hf.EVAL_STAGE, (3000, 400.0)),
        ):
            budget = hf.caps(stage)
            self.assertEqual((budget["hard_cap"], budget["credit_stop"]), (cap, stop))
            self.assertLessEqual(sum(budget["caps"].values()), cap)
            self.assertLessEqual(budget["conservative_at_caps"], stop)
        self.assertIsNone(hf.tag_state("no-such-tag-for-tests"))
        setup = hf.prepare(eval_seed("2" * 40))
        families = list(setup["families"].values())
        self.assertEqual(sorted(f["family"] for f in families), [f"K{i:02d}" for i in range(1, 33)])
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        cm = hf.cm
        others = [
            *SETUP["families"].values(),
            *cm.prepare()["families"].values(),
            *cm.prepare(cm.CM_EVAL_SEED)["families"].values(),
            *cm.prepare(hf.DE_SEED, dated=True)["families"].values(),
        ]
        keys = {x for f in others for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        self.assertFalse(
            keys
            & {x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        )

    def _gateway(
        self,
        run: Path,
        families: dict[str, Any],
        workspace: str,
        prefix: str,
        searched: list[dict[str, Any]],
        ingested: dict[Any, list[Any]],
    ) -> Any:
        def gateway(
            path: str, body: dict[str, Any], url: str = "", timeout: int = 0
        ) -> dict[str, Any]:
            if path == "/status":
                return {
                    "state": str((run / "mem0").resolve()),
                    "honcho_workspace": workspace,
                    "honcho_workspace_by_prefix": {},
                    "honcho_reasoning_level": None,
                    "queue": {"total": 8, "completed": 8, "pending": 0, "in_progress": 0},
                }
            if path == "/ingest":
                ingested.setdefault((body["provider"], body["scope"]), []).append(body["episode"])
                return {"result": {}}
            searched.append(body)
            name = body["scope"].removeprefix(f"customer:{prefix}")
            f = families[name]
            if body["provider"] == "mem0" and name in ("D4", "K32"):
                raise TimeoutError("down")
            if body.get("mode") == "messages":
                return {
                    "results": [
                        f"[2026-11-15 16:05 UTC] Agent: Item {f['target_id']}: is that the one?"
                    ]
                }
            return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

        return gateway

    def test_dev_dry_pass(self) -> None:
        from unittest import mock

        hf, today = self.hf, self.today
        setup = {**self.dev, "today": hf.cm.today_sentence(today)}
        families = setup["families"]
        cfg = PROVIDER_STAGES[hf.DEV_STAGE]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            source, run = _first_session_source(Path(tmp) / "src", families), Path(tmp) / "run"
            run.mkdir()
            shim_journal(run, "mem0", 12)
            shim_journal(run, "honcho", 40)
            searched: list[dict[str, Any]] = []
            ingested: dict[Any, list[Any]] = {}
            gateway = self._gateway(
                run, families, cfg["workspace"], cfg["prefix"], searched, ingested
            )
            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = hf.providers(setup, run, source, today, hf.DEV_STAGE)
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            self.assertEqual(len(ingested), 8)
            self.assertTrue(
                all("times" in e for (p, _), eps in ingested.items() if p == "honcho" for e in eps)
            )
            self.assertEqual(
                Counter((b["provider"], b.get("mode")) for b in searched),
                {("honcho", None): 4, ("honcho", "messages"): 4, ("mem0", None): 4},
            )
            query = first_message(families["D1"], "Hod")
            self.assertTrue(
                all(b["query"] == first_message(families[b["scope"][-2:]], "Hod") for b in searched)
            )
            self.assertIn("go ahead", query.casefold())
            for f in families:  # Hodr is Hod's retrieval, identical text
                hod, hodr = (
                    json.loads((run / "memory" / f"{f}-{a}.json").read_text(encoding="utf-8"))
                    for a in ("Hod", "Hodr")
                )
                self.assertEqual((hodr["text"], hodr["shared_from"]), (hod["text"], "Hod"))
            public = hf.dev_plan(setup, "dry", today, source)
            stored = run / "plan-check"
            stored.mkdir()
            hf._plan_file(stored, public, None)  # type: ignore[arg-type]
            hf._plan_file(stored, public, None)  # type: ignore[arg-type]  # resume: JSON round trip is equal
            self.assertEqual(
                [j["arm"] for j in public["jobs"]], [a for a in hf.DEV_ARMS for _ in range(4)]
            )
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}
            plan_for = {"Hs": "Y", "Nr": "ask", "Hnr": "Y", "Hodr": "ask", "Mir": "X"}
            Policy = _features_policy(families, seen, systems, plan_for)
            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    public["jobs"],
                    lambda _: Policy([]),
                    [run],
                    350,
                    40.0,
                    240,
                    exclude_uncommitted=True,
                    history_fn=hf.history(today, source),
                    infra_continue=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, public["jobs"])
            today_line = setup["policy"] + "\n\n" + hf.cm.today_sentence(today)
            for key, system in systems.items():
                self.assertTrue(system.startswith(ACTOR_SYSTEM + today_line), key)
            self.assertNotIn(NEUTRAL_HEADER, systems["D1-Nr"])
            self.assertNotIn(NEUTRAL_HEADER, systems["D4-Mir"])  # retrieval error: no memory block
            self.assertIn(hf.cm.session_label(today, "b"), systems["D1-Hnr"])
            self.assertIn("UTC] Agent:", systems["D1-Hs"])
            summary = hf.dev_summary(run, setup, outcome)
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            self.assertEqual(len(rows), 20)
            self.assertTrue(
                all(
                    rows[(f, "Nr")]["success"] and rows[(f, "Nr")]["restated"] == 1
                    for f in families
                )
            )
            self.assertTrue(all(rows[(f, "Hodr")]["restated"] == 1 for f in families))
            self.assertTrue(
                all(
                    rows[(f, "Hnr")]["restated"] == 0 and rows[(f, "Hs")]["success"]
                    for f in families
                )
            )
            self.assertTrue(all(rows[(f, "Mir")]["stale_commitment"] == 1 for f in families))
            self.assertEqual(summary["retrievals_ok"], {"Hod": 4, "Hs": 4, "Mir": 3})
            self.assertEqual(summary["verdict"], "PASS")

    @slow
    def test_eval_dry_pass_and_incomplete_arms(self) -> None:
        from unittest import mock

        from research.analysis.common import read_csv
        from research.analysis.honcho_features_analysis import (
            analyse,
            rows_from_runs,
            write_csv,
        )

        hf, today = self.hf, self.today
        tag = {
            "tag": hf.TAG,
            "commit": "2" * 40,
            "seed": eval_seed("2" * 40),
            "dev_check": "0" * 64,
        }
        setup = {**hf.prepare(tag["seed"]), "today": hf.cm.today_sentence(today)}
        families = setup["families"]
        cfg = PROVIDER_STAGES[hf.EVAL_STAGE]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            public = hf.eval_plan(setup, "dry", tag, today)
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}
            plan_for = {
                "Hs": "Y",
                "Hod": "decline",
                "Nr": "ask",
                "Hodr": "ask",
                "Mir": "X",
                "Hnr": "Y",
            }
            Policy = _features_policy(families, seen, systems, plan_for)
            options = {
                "exclude_uncommitted": True,
                "history_fn": hf.history(today, run),
                "infra_continue": True,
            }
            first = hf.cm.select(public["jobs"], "session1", [])
            outcome = asyncio.run(
                run_jobs(
                    setup, run, first, lambda _: Policy([]), [run], 3000, 400.0, 2600, **options
                )
            )
            self.assertEqual((outcome["refused"], len(first)), ([], 64))
            included = hf.cm.committed(run)
            self.assertEqual(len(included), 32)
            shim_journal(run, "mem0", 96)
            shim_journal(run, "honcho", 300)
            searched: list[dict[str, Any]] = []
            ingested: dict[Any, list[Any]] = {}
            gateway = self._gateway(
                run, families, cfg["workspace"], cfg["prefix"], searched, ingested
            )
            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = hf.providers(setup, run, run, today, hf.EVAL_STAGE)
            self.assertEqual(result["refused"], [])
            self.assertEqual((len(ingested), len(searched)), (64, 96))
            second = hf.cm.select(public["jobs"], "sessions", included)
            self.assertEqual(len(second), 192)
            seen.clear()
            outcome = asyncio.run(
                run_jobs(
                    setup, run, second, lambda _: Policy([]), [run], 3000, 400.0, 2600, **options
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, second)  # arm blocks in priority order
            self.assertEqual([seen[i * 32]["arm"] for i in range(6)], list(hf.EVAL_ARMS))
            rows = rows_from_runs(run)
            result = analyse(rows)
            self.assertEqual(
                (result["included"], result["leakage_sessions"], result["not_run_arms"]),
                (32, 0, []),
            )
            arms = {
                a: (v["successes"], v["stale"], v["declined"], v["restated_sessions"])
                for a, v in result["arms"].items()
            }
            self.assertEqual(
                arms,
                {
                    "Hs": (32, 0, 0, 0),
                    "Hod": (0, 0, 32, 0),
                    "Nr": (32, 0, 0, 32),
                    "Hodr": (32, 0, 0, 32),
                    "Mir": (0, 32, 0, 0),
                    "Hnr": (32, 0, 0, 0),
                },
            )
            one, two = result["family_1"]["tests"], result["family_2"]["tests"]
            self.assertEqual(one["Hs vs Hod (success)"]["arm_only"], 32)
            self.assertEqual(two["Mir vs Nr (stale)"]["arm_only"], 32)
            self.assertEqual(two["Mir vs Nr (success)"]["reference_only"], 32)
            self.assertEqual(two["Hodr vs Nr (stale)"]["p_holm"], 1.0)
            self.assertEqual(
                result["arms"]["Mir"]["memory_error"], 1
            )  # K32's Mem0 retrieval failed
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), result)
            partial = [
                r
                for r in rows
                if not (r["arm"] == "Mir" and r["family"] == "K05") and r["arm"] != "Hnr"
            ]
            cut = analyse(partial)
            self.assertEqual(cut["not_run_arms"], ["Mir", "Hnr"])
            self.assertEqual(cut["arms"]["Hnr"], {"status": "not run"})
            self.assertEqual(
                cut["family_2"]["not_run"], ["Mir vs Nr (stale)", "Mir vs Nr (success)"]
            )
            self.assertEqual(
                set(cut["family_2"]["tests"]), {"Hodr vs Nr (stale)", "Hodr vs Nr (success)"}
            )


class Stage3Tests(unittest.TestCase):
    """Honcho Stage 3: summarizer input, memory tool hook, facts/dream providers phase, dry pass."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research.studies import honcho_stage3

        cls.s3, cls.today = honcho_stage3, dt.date(2026, 11, 17)

    def test_token_file_is_the_shared_shim_token(self) -> None:
        self.assertEqual(self.s3.TOKEN_FILE, RUNS.parent.parent / "providers" / "shim-token.txt")

    def test_summarizer_sees_only_dated_transcripts(self) -> None:
        from unittest import mock

        s3, today = self.s3, self.today
        families = s3.hf.prepare()["families"]
        with tempfile.TemporaryDirectory() as tmp:
            source = _first_session_source(Path(tmp), families)
            first = s3.summarizer_input(source, "D1", today, "a")
            both = s3.summarizer_input(source, "D1", today, "b")
            self.assertEqual(both, s3.cm.dated_history_text(source, "D1", today))
            self.assertTrue(
                both.startswith(first) and first.startswith(s3.cm.session_label(today, "a"))
            )
            f = families["D1"]
            self.assertNotIn(f["target_id"], first)  # 1a's transcript never mentions Y
            for key in ("stale_id", "target_id", "rejected_id", "target_position"):
                self.assertNotIn(key, both)
            sent: list[Any] = []

            class Reply:
                def __enter__(self) -> Any:
                    return self

                def __exit__(self, *args: Any) -> None:
                    pass

                def read(self) -> bytes:
                    content = (
                        "Notes:\n- Current agreement: item 1.\n- Replaced: item 2.\nignored line"
                    )
                    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

            def urlopen(request: Any, timeout: int = 0) -> Reply:
                sent.append(json.loads(request.data))
                return Reply()

            with mock.patch("urllib.request.urlopen", side_effect=urlopen):
                facts = s3.summarize(both, "token")
            self.assertEqual(facts, ["Current agreement: item 1.", "Replaced: item 2."])
            self.assertEqual(
                [m["content"] for m in sent[0]["messages"]], [s3.SUMMARIZER_PROMPT, both]
            )

    def test_memory_tool_hook_counts_caps_and_stops(self) -> None:
        from research.harness.commitment_pilot import MEMORY_TOOL

        s3 = self.s3
        setup = {**s3.hf.prepare(), "today": s3.cm.today_sentence(self.today)}
        families, asked = setup["families"], []

        def recall(family: str, question: str) -> str:
            asked.append((family, question))
            return f"The customer changed to item {families[family]['target_id']}."

        setup.update(memory_tool=recall, memory_tool_arms=("Ht",), memory_tool_cap=2)
        jobs = [
            {"session": 2, "family": "D1", "arm": "Ht"},
            {"session": 2, "family": "D2", "arm": "Hod"},
        ]
        seen: list[Any] = []
        prompts: dict[str, list[str]] = {}
        Policy = stage3_policy(families, {"Ht": "recall3", "Hod": "decline"}, seen, prompts)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "memory").mkdir()
            (run / "memory" / "D2-Hod.json").write_text(
                json.dumps({"text": "", "error": "x"}), encoding="utf-8"
            )
            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    jobs,
                    lambda _: Policy([]),
                    [run],
                    400,
                    50.0,
                    210,
                    history_fn=s3.history(),
                    infra_continue=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            report = next(r for r in final_reports(run) if r["arm"] == "Ht")
            calls = report["memory_tool_calls"]
            self.assertEqual(
                [c["error"] for c in calls], [None, None, "cap"]
            )  # third call over the cap
            self.assertEqual(len(asked), 2)
            self.assertTrue(report["success"] and report["tools"] >= 3)
            self.assertIn(
                "changed to item", prompts["D1-Ht"][1]
            )  # the answer is in the next prompt
            self.assertTrue(all(MEMORY_TOOL in p for p in prompts["D1-Ht"]))
            self.assertFalse(
                any(MEMORY_TOOL in p for p in prompts["D2-Hod"])
            )  # other arms: no tool
            self.assertNotIn(
                "memory_tool_calls", next(r for r in final_reports(run) if r["arm"] == "Hod")
            )

            def broken(family: str, question: str) -> str:
                raise FatalStop("shim cap")

            setup["memory_tool"] = broken
            stop = Path(tmp) / "stop"
            stop.mkdir()
            outcome = asyncio.run(
                run_jobs(
                    setup,
                    stop,
                    jobs[:1],
                    lambda _: Policy([]),
                    [stop],
                    400,
                    50.0,
                    210,
                    history_fn=s3.history(),
                    infra_continue=True,
                )
            )
            self.assertTrue(outcome["refused"])  # a shim stop is never swallowed as "no memory"

    def test_dev_dry_pass(self) -> None:
        from unittest import mock

        s3, today = self.s3, self.today
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            run = Path(tmp) / "run"
            run.mkdir()
            setup = {**s3.setup_for(s3.DEV_STAGE, run), "today": s3.cm.today_sentence(today)}
            families = setup["families"]
            source = _first_session_source(Path(tmp) / "src", families)
            shim_journal(run, "honcho", 180)
            shim_journal(run, "app", 10)
            calls: dict[str, list[dict[str, Any]]] = {}
            ids = iter(range(10**6))

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                calls.setdefault(
                    path + (":" + body["mode"] if body.get("mode") else ""), []
                ).append(body)
                if path == "/status":
                    return {
                        "state": "x",
                        "honcho_workspace": "honcho-stage3-dev-v1",
                        "honcho_reasoning_level": None,
                        "honcho_workspace_by_prefix": s3.workspaces(s3.DEV_STAGE),
                        "queue": {"total": 1, "completed": 1, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    return {"result": {}}
                if path == "/honcho/facts":
                    return {
                        "result": {
                            "created": [f"c{next(ids)}" for _ in body["facts"]],
                            "deleted": body["delete"],
                        }
                    }
                if path == "/honcho/dream":
                    return {"result": {"queue": {}, "dream_runs_before": 0, "dream_runs_after": 1}}
                f = families[body["scope"][-2:]]
                return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

            def summarizer(text: str) -> list[str]:
                return [
                    f"Summary of {len(text)} characters.",
                    "Current agreement: the latest item.",
                ]

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = s3.providers(
                    setup, run, source, today, s3.DEV_STAGE, summarizer=summarizer
                )
            self.assertEqual((result["refused"], result["ingestion_errors"]), ([], []))
            scopes = {b["scope"].removeprefix("customer:")[:8] for b in calls["/ingest"]}
            self.assertEqual(scopes, {"cmp-h3d-", "cmp-h3r-", "cmp-h3w-"})
            facts = calls["/honcho/facts"]
            self.assertEqual(len(facts), 8)
            self.assertTrue(
                all(b["delete"] == [] for b in facts[0::2])
                and all(len(b["delete"]) == 2 for b in facts[1::2])
            )
            self.assertEqual({b["scope"][-2:] for b in calls["/honcho/dream"]}, set(families))
            fd = json.loads((run / "memory" / "D1-Fd.json").read_text(encoding="utf-8"))
            expected = (
                f"- Summary of {len(s3.summarizer_input(source, 'D1', today, 'b'))} characters.\n"
                "- Current agreement: the latest item."
            )
            self.assertIn(expected, fd["text"])  # Fd = the final (after 1b) summarizer facts
            public = s3.plan(setup, "dry", today, source, s3.DEV_STAGE, s3.ARMS, s3.hf.DEV_SEED, {})
            seen: list[Any] = []
            prompts: dict[str, list[str]] = {}
            Policy = stage3_policy(
                families,
                {"Hod": "decline", "Hdr": "Y", "Ht": "recall", "Hw": "Y", "Fd": "Y"},
                seen,
                prompts,
            )
            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                outcome = asyncio.run(
                    run_jobs(
                        setup,
                        run,
                        public["jobs"],
                        lambda _: Policy([]),
                        [run],
                        400,
                        50.0,
                        210,
                        history_fn=s3.history(),
                        infra_continue=True,
                    )
                )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(len(calls["/search:ask"]), 4)  # one memory-tool call per Ht session
            self.assertTrue(
                all(b["scope"].startswith("customer:cmp-h3d-") for b in calls["/search:ask"])
            )
            self.assertIn("Current agreement", prompts["D1-Fd"][0])
            self.assertNotIn(NEUTRAL_HEADER, prompts.get("D1-Ht", [""])[0] + "")
            summary = s3.dev_summary(run, setup, outcome)
            self.assertEqual(summary["verdict"], "PASS", summary["gates"])
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            self.assertTrue(
                all(
                    rows[(f, "Ht")]["tool_calls"] == 1 and rows[(f, "Ht")]["tool_has_Y"]
                    for f in families
                )
            )


class Stage3EvaluationTests(unittest.TestCase):
    """Honcho Stage 3 evaluation: L families, call-notes gate, 32-family dry pass and analysis."""

    @slow
    def test_eval_dry_pass_and_analysis(self) -> None:
        import datetime as dt
        from unittest import mock

        from research.analysis.common import read_csv
        from research.analysis.honcho_stage3_analysis import analyse, rows_from_runs, write_csv
        from research.studies import honcho_stage3 as s3

        today = dt.date(2026, 11, 17)
        self.assertTrue(s3.CALL_NOTES)  # recorded before the tag
        self.assertIsNone(s3.tag_state("no-such-tag-for-tests"))
        tag = {"tag": s3.TAG, "commit": "4" * 40, "seed": eval_seed("4" * 40)}
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            setup = {
                **s3.setup_for(s3.EVAL_STAGE, run, tag["seed"]),
                "today": s3.cm.today_sentence(today),
            }
            families = setup["families"]
            self.assertEqual(sorted(families), [f"L{i:02d}" for i in range(1, 33)])
            self.assertEqual(
                Counter(f["target_position"] for f in families.values()), {0: 8, 1: 8, 2: 8, 3: 8}
            )
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            public = s3.eval_plan(setup, "dry", tag, today)
            self.assertEqual(public["call_notes"], s3.CALL_NOTES)
            budget = public["budget"]
            self.assertLessEqual(budget["conservative_at_caps"], 450.0)
            self.assertLessEqual(sum(budget["caps"].values()), budget["hard_cap"])
            seen: list[Any] = []
            prompts: dict[str, list[str]] = {}
            Policy = stage3_policy(
                families,
                {
                    "Hod": "decline",
                    "Hdr": "Y",
                    "Ht": "recall",
                    "Hw": "Y",
                    "Fd": "Y",
                    "S1a": "s1",
                    "S1b": "s1",
                },
                seen,
                prompts,
            )
            first = s3.cm.select(public["jobs"], "session1", [])

            class Session1(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event == "commitment-session-started":
                        f = families[str(fields["family"])]
                        item = f["stale_id"] if fields["arm"] == "S1a" else f["target_id"]
                        self.replies = (
                            [act(text="Options.")] if fields["arm"] == "S1a" else []
                        ) + [act(text=f"Item {item}: is that the one?")]

            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    first,
                    lambda _: Session1([]),
                    [run],
                    3742,
                    450.0,
                    2374,
                    infra_continue=True,
                    exclude_uncommitted=True,
                )
            )
            self.assertEqual((outcome["refused"], len(s3.cm.committed(run))), ([], 32))
            stage = PROVIDER_STAGES[s3.EVAL_STAGE]
            shim_journal(run, "honcho", stage["shim_caps"]["honcho"])
            shim_journal(run, "app", stage["shim_caps"]["app"])
            ids = iter(range(10**6))

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {
                        "state": "x",
                        "honcho_workspace": stage["workspace"],
                        "honcho_reasoning_level": None,
                        "honcho_workspace_by_prefix": s3.workspaces(s3.EVAL_STAGE),
                        "queue": {"total": 1, "completed": 1, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    return {"result": {}}
                if path == "/honcho/facts":
                    return {
                        "result": {
                            "created": [f"c{next(ids)}" for _ in body["facts"]],
                            "deleted": body["delete"],
                        }
                    }
                if path == "/honcho/dream":
                    return {"result": {"queue": {}, "dream_runs_before": 0, "dream_runs_after": 1}}
                f = families[body["scope"][-3:]]
                return {"results": [f"Agreed {f['stale_id']}, then changed to {f['target_id']}."]}

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = s3.providers(
                    setup,
                    run,
                    run,
                    today,
                    s3.EVAL_STAGE,
                    summarizer=lambda text: ["Current agreement."],
                )
                self.assertEqual(result["refused"], [])
                second = s3.cm.select(public["jobs"], "sessions", s3.cm.committed(run))
                self.assertEqual(len(second), 160)
                outcome = asyncio.run(
                    run_jobs(
                        setup,
                        run,
                        second,
                        lambda _: Policy([]),
                        [run],
                        3742,
                        450.0,
                        2374,
                        history_fn=s3.history(),
                        infra_continue=True,
                    )
                )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(
                [seen[i * 32].split("-")[1] for i in range(5)], list(s3.ARMS)
            )  # arm blocks in priority order
            rows = rows_from_runs(run)
            analysis = analyse(rows)
            self.assertEqual(
                (analysis["included"], analysis["not_run_arms"], analysis["leakage_sessions"]),
                (32, [], 0),
            )
            arms = {
                a: (v["successes"], v["declined"], v["tool_sessions"])
                for a, v in analysis["arms"].items()
            }
            self.assertEqual(
                arms,
                {
                    "Hod": (0, 32, 0),
                    "Hdr": (32, 0, 0),
                    "Ht": (32, 0, 32),
                    "Hw": (32, 0, 0),
                    "Fd": (32, 0, 0),
                },
            )
            self.assertEqual(
                analysis["primary_success"]["tests"]["Hw vs Hod (success)"]["arm_only"], 32
            )
            self.assertEqual(
                analysis["secondary_facts"]["tests"]["Hw vs Fd (success)"]["arm_only"], 0
            )
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), analysis)


if __name__ == "__main__":
    unittest.main()
