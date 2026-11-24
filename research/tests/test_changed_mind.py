"""Studies 5 and 6: the changed-mind task, undated and dated."""

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
    CONSENT,
    NEUTRAL_HEADER,
    OPENING,
    STOP,
    eval_seed,
    leaks,
    provider_phase,
    run_jobs,
)
from research.tests.fixtures import (
    SETUP,
    FakeBackend,
    act,
)
from research.tests.support import billed, shim_journal, slow


class ChangedMindTests(unittest.TestCase):
    """Changed-mind pilot: customer branches, X/Y target-blindness, end-to-end dry pass."""

    @classmethod
    def setUpClass(cls) -> None:
        from research.studies import changed_mind

        cls.cm = changed_mind
        cls.setup = changed_mind.prepare()

    def x_view(self, family: dict[str, Any]) -> dict[str, Any]:
        return {**family, "target_id": family["stale_id"]}

    def test_sessions_1a_and_1b_branches(self) -> None:
        from research.harness.commitment_pilot import _names_target

        customer_cls = self.cm.ChangedMindCustomer
        for family in self.setup["families"].values():
            x, y = family["stale_id"], family["target_id"]
            first = customer_cls(family, 1, "S1a")
            first.reply(OPENING)
            first.reply("Here are the options.")
            first.reply(f"Item {x} is in stock. Is that the one?")
            self.assertTrue(first.agreed and first.done)
            before = json.dumps(family, sort_keys=True)
            change = customer_cls(family, 1, "S1b")
            self.assertEqual(json.dumps(family, sort_keys=True), before)  # never mutates the family
            opening = change.reply(OPENING)
            self.assertIn("changed my mind", opening)
            self.assertFalse(_names_target(self.x_view(family), opening) or y in opening)
            ids = [v["item_id"] for v in family["alternatives"]]
            replies = [
                change.reply(t)
                for t in (
                    f"Is it item {x}?",
                    f"Options: {', '.join(ids)}.",
                    "Which item did we agree earlier?",
                    f"Instead of item {x}, item {y}?",
                )
            ]
            self.assertIn("I changed my mind", replies[0])
            target = next(v for v in family["alternatives"] if v["item_id"] == y)
            probe = customer_cls(family, 1, "S1b")
            probe.reply(OPENING)
            options_only = probe.reply(f"The {', '.join(target['options'].values())} one?")
            self.assertFalse(probe.agreed)
            self.assertIn("exact item ID", options_only)  # options without the ID are not agreement
            self.assertIn("the one we agreed last time", replies[2])
            self.assertFalse(change.agreed)
            self.assertFalse(
                any(_names_target(self.x_view(family), r) for r in [opening, *replies])
            )
            agreed = change.reply(f"Item {y} it is. Confirm?")
            self.assertTrue(change.agreed and change.done and STOP in agreed)
            slow, last = customer_cls(family, 1, "S1b"), ""
            for _ in range(7):
                last = slow.reply("Let me check.")
            self.assertTrue(slow.done and not slow.agreed and STOP in last)

    def test_session_two_is_target_blind_over_x_and_y(self) -> None:
        customer_cls = self.cm.ChangedMindCustomer
        for family in self.setup["families"].values():
            ids = [v["item_id"] for v in family["alternatives"]]
            for arm in ("N", "Hc", "Hn", "M", "Ho"):
                single, multi = set(), set()
                for item in ids:
                    customer = customer_cls(family, 2, arm)
                    opening = customer.reply(OPENING)
                    single.add(
                        customer.reply(f"I can exchange it for item {item}. Shall I proceed?")
                    )
                    other = customer_cls(family, 2, arm)
                    other.reply(OPENING)
                    multi.add(
                        other.reply(f"Item {item} or item {ids[0] if item != ids[0] else ids[1]}?")
                    )
                    self.assertEqual(leaks(family, arm, "", None, [opening]), [])
                self.assertEqual(
                    single, {CONSENT}, (family["family"], arm)
                )  # X, Y and others alike
                self.assertEqual(len(multi), 1, (family["family"], arm))
            control = customer_cls(family, 2, "R")
            restated = control.reply(OPENING)
            self.assertIn(family["target_id"], restated)
            self.assertEqual(leaks(family, "R", "", None, [restated]), [])  # X never restated
            self.assertTrue(leaks(family, "Hn", "", None, [f"item {family['stale_id']}"]))

    def test_end_to_end_dry_pass(self) -> None:
        from unittest import mock

        cm, setup = self.cm, self.setup
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            public = cm.plan(setup, "dry pass")
            first_jobs = cm.select(public["jobs"], "session1", [])
            self.assertEqual(len(first_jobs), 8)
            seen: list[tuple[dict[str, Any], FakeBackend]] = []

            class Scripted(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    job = {k: fields[k] for k in ("session", "family", "arm")}
                    seen.append((job, self))
                    f = families[str(job["family"])]
                    x, y = f["stale_id"], f["target_id"]
                    done = act(text="The exchange has been processed.")

                    def run_exchange(item: str) -> list[str]:
                        return [
                            act(text=f"I can exchange it for item {item}. Shall I proceed?"),
                            act(
                                "exchange_delivered_order_items",
                                order_id=f["order_id"],
                                item_ids=[f["current"]["item_id"]],
                                new_item_ids=[item],
                                payment_method_id=f["payment_id"],
                            ),
                            done,
                        ]

                    self.replies = {
                        "S1a": [
                            act(text="Here are the options."),
                            act(text=f"Item {x}: is that the one?"),
                        ],
                        "S1b": [act(text=f"Item {y}: is that the one?")],
                        "Hn": run_exchange(y),
                        "R": run_exchange(y),
                        "M": run_exchange(x),
                        "Ho": [act(text="Which item would you like?")] * 12,
                    }[str(job["arm"])]

            def backend(_: Any) -> Scripted:
                return Scripted([])

            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    first_jobs,
                    backend,
                    [run],
                    240,
                    30.0,
                    188,
                    exclude_uncommitted=True,
                    infra_continue=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(cm.committed(run), sorted(families))

            shim_journal(run, "mem0", 12)
            shim_journal(run, "honcho", 40)
            ingested: dict[tuple[str, str], list[str]] = {}

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {
                        "state": str((run / "mem0").resolve()),
                        "honcho_workspace": "changed-mind-pilot-v1",
                        "honcho_reasoning_level": None,
                        "queue": {"total": 8, "completed": 8, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]["id"]
                    )
                    return {"result": {}}
                f = families[body["scope"].removeprefix("customer:cmp-cm-p1-")]
                return {
                    "results": [
                        f"Agreed item {f['stale_id']}, then changed to item {f['target_id']}."
                    ]
                }

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(setup, run, cm.provider_inputs(run), "cm-pilot-v1")
            self.assertEqual(providers["refused"], [])
            self.assertEqual(len(ingested), 8)
            for (_, scope), episodes in ingested.items():
                prefix = scope.removeprefix("customer:")
                self.assertEqual(
                    episodes, [f"{prefix}-s1a", f"{prefix}-s1b"]
                )  # same customer, in order

            second = cm.select(public["jobs"], "sessions", cm.committed(run))
            self.assertEqual(len(second), 16)
            seen.clear()
            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    second,
                    backend,
                    [run],
                    240,
                    30.0,
                    188,
                    exclude_uncommitted=True,
                    history_fn=cm.history,
                    infra_continue=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual([j for j, _ in seen], second)
            for job, used in seen:
                system = used.systems[0]
                if job["arm"] == "Hn":
                    self.assertIn(NEUTRAL_HEADER + "Earlier session (1 of 2):", system)
                    self.assertIn("Most recent session (2 of 2):", system)
                elif job["arm"] == "R":
                    self.assertNotIn(NEUTRAL_HEADER, system)
            summary = cm.summarize(run, setup)
            arms = summary["arms"]
            self.assertEqual(
                {a: (v["successes"], v["n"], v["stale_commitment"]) for a, v in arms.items()},
                {"Hn": (4, 4, 0), "M": (0, 4, 4), "Ho": (0, 4, 0), "R": (4, 4, 0)},
            )
            m_rows = [r for r in summary["rows"] if r["arm"] == "M"]
            self.assertTrue(
                all(
                    r["memory_has_X"] and r["memory_has_Y"] and r["wrong_variant_other"] == 0
                    for r in m_rows
                )
            )
            self.assertEqual(summary["verdict"], "PASS")
            self.assertEqual(len(summary["rows"]), 24)


class HonchoHighTests(unittest.TestCase):
    """Hoh dev check: Honcho at its highest level, retrieval only, per-call shim accounting."""

    @classmethod
    def setUpClass(cls) -> None:
        from research.studies import changed_mind

        cls.cm = changed_mind
        cls.setup = changed_mind.prepare()

    def test_gateway_uses_the_per_request_level(self) -> None:
        from research.harness import memory_gateway as gateway

        asked: list[Any] = []

        class Peer:
            def chat(self, question: str, reasoning_level: str | None = None) -> str:
                asked.append(reasoning_level)
                return "memo"

        class Workspace:
            def peer(self, name: str) -> Peer:
                return Peer()

        honcho = object.__new__(gateway.HonchoStore)
        honcho.clients, honcho.factory = {}, lambda workspace: Workspace()
        saved = dict(gateway.CONFIG)
        try:
            gateway.CONFIG.clear()
            gateway.CONFIG.update(honcho_workspace="w", honcho_reasoning_level=None)
            honcho.search("customer:x", "q")
            honcho.search("customer:x", "q", "max")
        finally:
            gateway.CONFIG.clear()
            gateway.CONFIG.update(saved)
        self.assertEqual(asked, [None, "max"])  # null config: level omitted, server default (low)

    def test_retrieval_only_with_level_and_per_call_cost(self) -> None:
        from unittest import mock

        cm, setup = self.cm, self.setup
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            shim_journal(run, "honcho", 52)
            journal = run / "shims" / "honcho.calls.jsonl"
            posts: list[tuple[str, dict[str, Any]]] = []
            calls = iter(range(1, 100))

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                posts.append((path, body))
                if path == "/status":
                    return {
                        "state": "x",
                        "honcho_workspace": "changed-mind-pilot-v1",
                        "honcho_reasoning_level": None,
                        "queue": {"total": 42, "completed": 42, "pending": 0, "in_progress": 0},
                    }
                with journal.open("a", encoding="utf-8") as handle:
                    for _ in range(3):
                        i = next(calls)
                        handle.write(
                            json.dumps({"event": "copilot-request-started", "call_id": i}) + "\n"
                        )
                        handle.write(json.dumps(billed(i)) + "\n")
                family = setup["families"][body["scope"].removeprefix("customer:cmp-cm-p1-")]
                return {"results": [f"Latest agreement: item {family['target_id']}."]}

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                result = cm.hoh_retrieve(setup, run)
            self.assertEqual(result["refused"], [])
            searches = [b for path, b in posts if path == "/search"]
            self.assertEqual(len(searches), 4)
            self.assertFalse(any(path == "/ingest" for path, _ in posts))
            self.assertTrue(
                all(b["reasoning_level"] == "max" and b["provider"] == "honcho" for b in searches)
            )
            self.assertEqual(
                {(r["shim_requests"], r["shim_credits"]) for r in result["retrievals"]}, {(3, 0.3)}
            )
            job = {"session": 2, "family": "D1", "arm": "Hoh"}
            text, meta = cm.history(run, job)
            self.assertIn(setup["families"]["D1"]["target_id"], text or "")
            self.assertEqual((meta or {}).get("provider"), "honcho")
            with mock.patch(
                "research.harness.provider_ingest.post",
                return_value={
                    "state": "x",
                    "honcho_workspace": "ae-customer",
                    "honcho_reasoning_level": None,
                },
            ):
                self.assertTrue(cm.hoh_retrieve(setup, run)["refused"])


class ChangedMindEvaluationTests(unittest.TestCase):
    """Changed-mind evaluation (tag changed-mind-eval-v1): generation and a full dry pass."""

    @classmethod
    def setUpClass(cls) -> None:
        from research.studies import changed_mind

        cls.cm = changed_mind
        cls.tag = {"tag": "changed-mind-eval-v1", "commit": "0" * 40, "seed": eval_seed("0" * 40)}
        cls.setup = changed_mind.prepare(cls.tag["seed"])

    def test_generation_and_tag_check(self) -> None:
        self.assertIsNone(self.cm.eval_tag_state("no-such-tag-for-tests"))
        families = list(self.setup["families"].values())
        self.assertEqual(sorted(f["family"] for f in families), [f"F{i:02d}" for i in range(1, 33)])
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        self.assertTrue(
            all(
                (f["first"], f["last"])
                in {(a, b) for a in self.cm.EVAL_FIRST for b in self.cm.EVAL_LAST}
                for f in families
            )
        )
        pilot = self.cm.prepare()["families"].values()
        others = {
            x for f in [*pilot, *SETUP["families"].values()] for x in (f["user_id"], f["order_id"])
        }
        self.assertFalse(others & {x for f in families for x in (f["user_id"], f["order_id"])})
        self.assertTrue(
            all(len({f["stale_id"], f["target_id"], f["rejected_id"]}) == 3 for f in families)
        )

    @slow
    def test_end_to_end_dry_pass(self) -> None:
        from unittest import mock

        from research.analysis.changed_mind_analysis import (
            analyse,
            rows_from_runs,
            write_csv,
        )
        from research.analysis.common import read_csv

        cm, setup = self.cm, self.setup
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            public = cm.eval_plan(setup, "dry pass", self.tag)
            seen: list[dict[str, Any]] = []

            class Policy(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    job = {k: fields[k] for k in ("session", "family", "arm")}
                    seen.append(job)
                    f = families[str(job["family"])]
                    x, y = f["stale_id"], f["target_id"]

                    def execute(item: str) -> list[str]:
                        return [
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

                    decline = [act(text="I can't act on that without the exact item.")] * 12
                    self.replies = {
                        "S1a": [act(text="Options."), act(text=f"Item {x}: is that the one?")],
                        "S1b": [act(text=f"Item {y}: is that the one?")],
                        "Hn": execute(y),
                        "Hoh": execute(y),
                        "M": execute(x),
                        "Ho": decline,
                        "N": decline,
                    }[str(job["arm"])]

            def backend(_: Any) -> Policy:
                return Policy([])

            options = {
                "exclude_uncommitted": True,
                "history_fn": cm.history,
                "infra_continue": True,
            }
            first = cm.select(public["jobs"], "session1", [])
            outcome = asyncio.run(
                run_jobs(setup, run, first, backend, [run], 3120, 360.0, 2688, **options)
            )
            self.assertEqual((outcome["refused"], len(first)), ([], 64))
            included = cm.committed(run)
            self.assertEqual(len(included), 32)

            shim_journal(run, "mem0", 96)
            shim_journal(run, "honcho", 336)
            ingested: dict[tuple[str, str], list[str]] = {}
            levels: dict[str, set[Any]] = {}

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {
                        "state": str((run / "mem0").resolve()),
                        "honcho_workspace": "changed-mind-eval-v1",
                        "honcho_reasoning_level": None,
                        "queue": {"total": 64, "completed": 64, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]["id"]
                    )
                    return {"result": {}}
                levels.setdefault(body["provider"], set()).add(body.get("reasoning_level"))
                f = families[body["scope"].removeprefix("customer:cmp-cm-e1-")]
                return {"results": [f"Item {f['stale_id']}, later item {f['target_id']}."]}

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(
                    setup,
                    run,
                    cm.provider_inputs(run, "cmp-cm-e1-"),
                    "cm-eval-v1",
                    ("M", "Ho", "Hoh"),
                )
            self.assertEqual(providers["refused"], [])
            self.assertEqual(len(ingested), 64)  # Hoh reuses Honcho's ingestion
            self.assertTrue(
                all(
                    ids[0].endswith("-s1a") and ids[1].endswith("-s1b") for ids in ingested.values()
                )
            )
            self.assertEqual(levels, {"mem0": {None}, "honcho": {None, "max"}})
            self.assertEqual(len(providers["retrievals"]), 96)

            second = cm.select(public["jobs"], "sessions", included)
            self.assertEqual(len(second), 160)
            seen.clear()
            outcome = asyncio.run(
                run_jobs(setup, run, second, backend, [run], 3120, 360.0, 2688, **options)
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, second)  # the plan's seeded order

            rows = rows_from_runs(run)
            result = analyse(rows)
            self.assertEqual(
                (result["included"], result["complete"], result["leakage_sessions"]), (32, True, 0)
            )
            arms = {
                a: (v["successes"], v["n"], v["stale"], v["declined"])
                for a, v in result["arms"].items()
            }
            self.assertEqual(
                arms,
                {
                    "N": (0, 32, 0, 32),
                    "Hn": (32, 32, 0, 0),
                    "M": (0, 32, 32, 0),
                    "Ho": (0, 32, 0, 32),
                    "Hoh": (32, 32, 0, 0),
                },
            )
            primary, secondary = result["primary_success"], result["secondary_stale"]
            self.assertEqual(
                (primary["M vs Hn"]["reference_only"], primary["Hoh vs Hn"]["p_holm"]), (32, 1.0)
            )
            self.assertEqual(secondary["M vs Hn"]["arm_only"], 32)
            self.assertEqual(result["hoh_vs_ho_success"]["arm_only"], 32)
            self.assertEqual(result["manipulation_hn_vs_n"]["arm_only"], 32)
            self.assertEqual(result["provider_memory"]["Hoh"]["has_both"], 32)
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), result)


class DatedCheckTests(unittest.TestCase):
    """Dated dev check: backdated sessions, identical date labels and "Today is" sentence."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research.studies import changed_mind

        cls.cm, cls.today = changed_mind, dt.date(2026, 11, 15)
        cls.setup = changed_mind.prepare()

    def source(self, root: Path) -> Path:
        for name, f in self.setup["families"].items():
            for arm, item in (("S1a", f["stale_id"]), ("S1b", f["target_id"])):
                messages = [
                    {"role": "assistant", "content": OPENING},
                    {"role": "user", "content": "Please don't make the exchange today."},
                    {"role": "assistant", "content": f"Agreed item {item}."},
                ]
                report = {
                    "session": 1,
                    "family": name,
                    "arm": arm,
                    "commitment": True,
                    "messages": messages,
                }
                (root / f"{name}-s1-{arm}-a1.json").write_text(json.dumps(report), encoding="utf-8")
        return root

    def test_dates_inputs_and_gateway_created_at(self) -> None:
        from research.harness import memory_gateway as gateway

        cm, today = self.cm, self.today
        self.assertEqual(
            cm.session_label(today, "a"),
            "Earlier session (1 of 2), Thursday 12 November 2026, 14:20 UTC:",
        )
        self.assertEqual(cm.today_sentence(today), "Today is Sunday 15 November 2026 (UTC).")
        with tempfile.TemporaryDirectory() as tmp:
            source = self.source(Path(tmp))
            inputs = cm.dated_inputs(source, today)["D1"]
            history = cm.dated_history_text(source, "D1", today)
            for order, mem0, honcho in zip(
                "ab", inputs["episodes_mem0"], inputs["episodes_honcho"], strict=True
            ):
                label = cm.session_label(today, order)
                self.assertTrue(mem0["lines"][0][1].startswith(label + "\n"))  # Mem0 in-band header
                self.assertIn(label + "\n", history)  # identical label in Hn
                self.assertNotIn(
                    "session (", json.dumps(honcho["lines"])
                )  # Honcho: dates via created_at only
                self.assertEqual(honcho["times"][0], cm.session_start(today, order).isoformat())
                self.assertEqual(len(honcho["times"]), len(honcho["lines"]))
            self.assertEqual(inputs["episodes_honcho"][0]["times"][0][:10], "2026-11-12")
            self.assertEqual(inputs["episodes_honcho"][1]["times"][0][:10], "2026-11-14")
        sent: list[Any] = []

        class Peer:
            def message(self, content: str, **kwargs: Any) -> dict[str, Any]:
                sent.append(kwargs.get("created_at"))
                return {}

        class Session:
            id = "s"

            def add_messages(self, messages: list[Any]) -> None:
                pass

        class Workspace:
            def peer(self, name: str) -> Peer:
                return Peer()

            def session(self, name: str, peers: list[Any]) -> Session:
                return Session()

        honcho = object.__new__(gateway.HonchoStore)
        honcho.clients, honcho.factory = {}, lambda workspace: Workspace()
        honcho.wait = lambda honcho, limit=900: {}
        honcho.ingest(
            "customer:x",
            {"id": "e", "lines": [("customer", "a"), ("agent", "b")], "times": ["t1", "t2"]},
        )
        honcho.ingest("customer:x", {"id": "f", "lines": [("customer", "a")]})
        self.assertEqual(sent, ["t1", "t2", None])

    def test_dry_pass_today_sentence_summary_and_gates(self) -> None:
        from unittest import mock

        cm, today = self.cm, self.today
        setup = {**self.setup, "today": cm.today_sentence(today)}
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            source, run = self.source(Path(tmp) / "src"), Path(tmp) / "run"
            run.mkdir()
            shim_journal(run, "mem0", 12)
            shim_journal(run, "honcho", 45)
            ingested: dict[tuple[str, str], list[dict[str, Any]]] = {}

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    return {
                        "state": str((run / "mem0").resolve()),
                        "honcho_workspace": "changed-mind-dated-v1",
                        "honcho_reasoning_level": None,
                        "queue": {"total": 8, "completed": 8, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]
                    )
                    return {"result": {}}
                f = families[body["scope"].removeprefix("customer:cmp-cm-t1-")]
                if body["provider"] == "mem0" and f["family"] == "D4":
                    raise TimeoutError("down")
                return {
                    "results": [
                        f"On 2026-11-12 item {f['stale_id']}; on 2026-11-14 changed to item {f['target_id']}."
                    ]
                }

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                providers = provider_phase(
                    setup, run, cm.dated_inputs(source, today), "cm-dated-v1"
                )
            self.assertEqual(providers["refused"], [])
            self.assertTrue(
                all("times" in e for (p, _), eps in ingested.items() if p == "honcho" for e in eps)
            )
            self.assertFalse(
                any("times" in e for (p, _), eps in ingested.items() if p == "mem0" for e in eps)
            )
            public = cm.dated_plan(setup, "dry", today, source)
            self.assertEqual(len(public["jobs"]), 12)
            systems: dict[str, str] = {}

            class Policy(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    f = families[str(fields["family"])]
                    arm = str(fields["arm"])
                    self.key = f"{fields['family']}-{arm}"
                    item = {"Hn": f["target_id"], "M": f["stale_id"]}.get(arm)
                    self.replies = (
                        [act(text="I can't act on that.")] * 12
                        if item is None
                        else [
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
                    )

                async def complete(
                    self, system: str, prompt: str, response_schema: Any = None
                ) -> str:
                    systems.setdefault(self.key, system)
                    return await super().complete(system, prompt, response_schema)

            outcome = asyncio.run(
                run_jobs(
                    setup,
                    run,
                    public["jobs"],
                    lambda _: Policy([]),
                    [run],
                    200,
                    25.0,
                    144,
                    exclude_uncommitted=True,
                    history_fn=cm.dated_history(today, source),
                    infra_continue=True,
                )
            )
            self.assertEqual(outcome["refused"], [])
            policy_today = setup["policy"] + "\n\n" + cm.today_sentence(today)
            self.assertEqual(len(systems), 12)
            for key, system in systems.items():
                self.assertTrue(
                    system.startswith(ACTOR_SYSTEM + policy_today), key
                )  # same sentence, same place
                self.assertEqual(system.count("Today is"), 1, key)
            self.assertNotIn(
                NEUTRAL_HEADER, systems["D4-M"]
            )  # retrieval error: no memory, still dated
            summary = cm.dated_summary(run, setup, today, source)
            rows = {(r["family"], r["arm"]): r for r in summary["rows"]}
            self.assertEqual(len(rows), 12)
            self.assertTrue(
                all(
                    rows[(f, "Hn")]["success"] and rows[(f, "Hn")]["date_correct"] for f in families
                )
            )
            self.assertEqual(
                sum(rows[(f, "M")]["stale_commitment"] > 0 for f in families), 4
            )  # policy ignores memory
            self.assertTrue(
                all(
                    rows[(f, "Ho")]["declined"] and rows[(f, "Ho")]["shows_backdated_date"]
                    for f in families
                )
            )
            self.assertTrue(rows[("D1", "Ho")]["date_correct"] and rows[("D1", "Ho")]["has_X"])
            self.assertEqual(summary["verdict"], "PASS")
            self.assertEqual(summary["retrievals_ok"], {"mem0": 3, "honcho": 4})


class DatedEvaluationTests(unittest.TestCase):
    """Dated changed-mind evaluation (tag changed-mind-dated-eval-v1): generation, scopes, dry pass."""

    @classmethod
    def setUpClass(cls) -> None:
        import datetime as dt

        from research.studies import changed_mind

        cls.cm, cls.today = changed_mind, dt.date(2026, 11, 16)
        seed = eval_seed("1" * 40)
        cls.tag = {
            "tag": changed_mind.DE_TAG,
            "commit": "1" * 40,
            "seed": seed,
            "sources": (*changed_mind.EVAL_SOURCES, "changed_mind_dated_analysis.py"),
        }
        cls.setup = changed_mind.prepare(seed, dated=True)

    @slow
    def test_generation_caps_and_workspace_map(self) -> None:
        from unittest import mock

        from research.harness import memory_gateway as gateway

        cm = self.cm
        self.assertIsNone(cm.de_tag_state("no-such-tag-for-tests"))
        families = list(self.setup["families"].values())
        self.assertEqual(sorted(f["family"] for f in families), [f"G{i:02d}" for i in range(1, 33)])
        self.assertEqual(Counter(f["target_position"] for f in families), {0: 8, 1: 8, 2: 8, 3: 8})
        self.assertTrue(
            all(
                (f["first"], f["last"]) in {(a, b) for a in cm.DE_FIRST for b in cm.DE_LAST}
                for f in families
            )
        )
        others = [
            *SETUP["families"].values(),
            *cm.prepare()["families"].values(),
            *cm.prepare(cm.CM_EVAL_SEED)["families"].values(),
        ]
        keys = {x for f in others for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        self.assertFalse(
            keys
            & {x for f in families for x in (f["user_id"], f["order_id"], (f["first"], f["last"]))}
        )
        self.assertTrue(
            all(len({f["stale_id"], f["target_id"], f["rejected_id"]}) == 3 for f in families)
        )
        caps = cm.de_caps()
        self.assertEqual((caps["hard_cap"], caps["credit_stop"]), (3408, 400.0))
        self.assertEqual(sum(caps["caps"].values()), 3408)
        self.assertLessEqual(caps["conservative_at_caps"], 400.0)
        self.assertEqual(len(set(cm.DE_PREFIXES.values())), 3)
        self.assertEqual(cm.DE_PREFIXES["M"], cm.DE_CFG["prefix"])
        store = object.__new__(gateway.HonchoStore)
        store.clients, store.factory = {}, lambda workspace: workspace
        config = {
            "honcho_workspace": cm.DE_CFG["workspace"],
            "honcho_workspace_by_prefix": cm.DE_WORKSPACES,
        }
        with mock.patch.dict(gateway.CONFIG, config, clear=True):
            self.assertEqual(
                store.workspace("customer:cmp-cm-d2d-G01"), "changed-mind-dated-eval-v1-dated"
            )
            self.assertEqual(
                store.workspace("customer:cmp-cm-d2u-G01"), "changed-mind-dated-eval-v1-undated"
            )
            self.assertEqual(store.workspace("customer:"), "changed-mind-dated-eval-v1-undated")

    @slow
    def test_end_to_end_dry_pass(self) -> None:
        from unittest import mock

        from research.analysis.changed_mind_dated_analysis import (
            analyse,
            rows_from_runs,
            write_csv,
        )
        from research.analysis.common import read_csv

        cm, today = self.cm, self.today
        setup = {**self.setup, "today": cm.today_sentence(today)}
        families = setup["families"]
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            public = cm.de_plan(setup, "dry pass", self.tag, today)
            (run / "manifest.json").write_text(setup["manifest"] + "\n", encoding="utf-8")
            (run / "plan.json").write_text(json.dumps(public), encoding="utf-8")
            self.assertEqual(public["today_sentence"], "Today is Monday 16 November 2026 (UTC).")
            seen: list[dict[str, Any]] = []
            systems: dict[str, str] = {}

            class Policy(FakeBackend):
                def write(self, event: str, **fields: object) -> None:
                    if event != "commitment-session-started":
                        return
                    job = {k: fields[k] for k in ("session", "family", "arm")}
                    seen.append(job)
                    self.key = f"{job['family']}-{job['arm']}"
                    f = families[str(job["family"])]
                    x, y = f["stale_id"], f["target_id"]

                    def execute(item: str) -> list[str]:
                        return [
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

                    decline = [act(text="I can't act on that without the exact item.")] * 12
                    self.replies = {
                        "S1a": [act(text="Options."), act(text=f"Item {x}: is that the one?")],
                        "S1b": [act(text=f"Item {y}: is that the one?")],
                        "Hn": execute(y),
                        "M": execute(x),
                        "Mi": execute(y),
                        "Ho": decline,
                        "Hod": execute(y),
                    }[str(job["arm"])]

                async def complete(
                    self, system: str, prompt: str, response_schema: Any = None
                ) -> str:
                    systems.setdefault(self.key, system)
                    return await super().complete(system, prompt, response_schema)

            options = {
                "exclude_uncommitted": True,
                "history_fn": cm.dated_history(today, run),
                "infra_continue": True,
            }
            first = cm.select(public["jobs"], "session1", [])
            outcome = asyncio.run(
                run_jobs(
                    setup, run, first, lambda _: Policy([]), [run], 3408, 400.0, 2688, **options
                )
            )
            self.assertEqual((outcome["refused"], len(first)), ([], 64))
            included = cm.committed(run)
            self.assertEqual(len(included), 32)

            shim_journal(run, "mem0", 192)
            shim_journal(run, "honcho", 528)
            ingested: dict[tuple[str, str], list[dict[str, Any]]] = {}
            searched: dict[tuple[str, str], int] = {}
            drained: list[str] = []

            def gateway(
                path: str, body: dict[str, Any], url: str = "", timeout: int = 0
            ) -> dict[str, Any]:
                if path == "/status":
                    drained.append(body.get("scope", ""))
                    return {
                        "state": str((run / "mem0").resolve()),
                        "honcho_workspace": cm.DE_CFG["workspace"],
                        "honcho_workspace_by_prefix": cm.DE_WORKSPACES,
                        "honcho_reasoning_level": None,
                        "queue": {"total": 64, "completed": 64, "pending": 0, "in_progress": 0},
                    }
                if path == "/ingest":
                    ingested.setdefault((body["provider"], body["scope"]), []).append(
                        body["episode"]
                    )
                    return {"result": {}}
                key = (body["provider"], body["scope"])
                searched[key] = searched.get(key, 0) + 1
                prefix, name = body["scope"].removeprefix("customer:")[:11], body["scope"][-3:]
                f = families[name]
                dated = (
                    "On 13 November item {x}; on 15 November changed to item {y}."
                    if prefix != "cmp-cm-d2u-"
                    else "Item {x}, later item {y}. Do not process today."
                )
                return {"results": [dated.format(x=f["stale_id"], y=f["target_id"])]}

            with mock.patch("research.harness.provider_ingest.post", side_effect=gateway):
                providers = cm.de_providers(setup, run, today)
            self.assertEqual((providers["refused"], providers["ingestion_errors"]), ([], []))
            self.assertEqual(drained.count("customer:cmp-cm-d2u-"), 1)
            self.assertEqual(drained.count("customer:cmp-cm-d2d-"), 1)
            self.assertEqual(len(ingested), 128)  # four separate scopes per family
            for f in included:
                streams = {
                    (p, prefix): ingested[(p, f"customer:{prefix}{f}")]
                    for p, prefix in (
                        ("mem0", "cmp-cm-d2u-"),
                        ("mem0", "cmp-cm-d2i-"),
                        ("honcho", "cmp-cm-d2u-"),
                        ("honcho", "cmp-cm-d2d-"),
                    )
                }
                for (provider, prefix), episodes in streams.items():
                    self.assertEqual([e["id"][-4:] for e in episodes], ["-s1a", "-s1b"])
                    dated_text = provider == "mem0" and prefix == "cmp-cm-d2i-"
                    for order, episode in zip("ab", episodes, strict=True):
                        label = cm.session_label(today, order)
                        self.assertEqual(
                            episode["lines"][0][1].startswith(label + "\n"), dated_text
                        )
                        self.assertEqual("times" in episode, prefix == "cmp-cm-d2d-")
                    if prefix == "cmp-cm-d2d-":
                        self.assertEqual(
                            [e["times"][0][:10] for e in episodes], ["2026-11-13", "2026-11-15"]
                        )
                undated = [
                    [line for _, line in e["lines"]] for e in streams[("mem0", "cmp-cm-d2u-")]
                ]
                self.assertEqual(
                    undated,
                    [[line for _, line in e["lines"]] for e in streams[("honcho", "cmp-cm-d2u-")]],
                )
            self.assertEqual(len(providers["retrievals"]), 128)
            self.assertEqual(len(searched), 128)
            self.assertEqual(
                {k[1][9:20] for k in searched if k[0] == "mem0"}, {"cmp-cm-d2u-", "cmp-cm-d2i-"}
            )
            self.assertEqual(
                {k[1][9:20] for k in searched if k[0] == "honcho"}, {"cmp-cm-d2u-", "cmp-cm-d2d-"}
            )

            second = cm.select(public["jobs"], "sessions", included)
            self.assertEqual(len(second), 160)
            seen.clear()
            systems.clear()
            outcome = asyncio.run(
                run_jobs(
                    setup, run, second, lambda _: Policy([]), [run], 3408, 400.0, 2688, **options
                )
            )
            self.assertEqual(outcome["refused"], [])
            self.assertEqual(seen, second)  # the plan's seeded order
            policy_today = setup["policy"] + "\n\n" + cm.today_sentence(today)
            self.assertEqual(len(systems), 160)
            for key, system in systems.items():
                self.assertTrue(
                    system.startswith(ACTOR_SYSTEM + policy_today), key
                )  # same sentence, same place
                self.assertEqual(system.count("Today is"), 1, key)
                self.assertIn(NEUTRAL_HEADER, system, key)
            self.assertIn(cm.session_label(today, "b"), systems["G01-Hn"])

            rows = rows_from_runs(run)
            result = analyse(rows)
            self.assertEqual(
                (result["included"], result["complete"], result["leakage_sessions"]), (32, True, 0)
            )
            arms = {
                a: (v["successes"], v["n"], v["stale"], v["declined"])
                for a, v in result["arms"].items()
            }
            self.assertEqual(
                arms,
                {
                    "Hn": (32, 32, 0, 0),
                    "M": (0, 32, 32, 0),
                    "Mi": (32, 32, 0, 0),
                    "Ho": (0, 32, 0, 32),
                    "Hod": (32, 32, 0, 0),
                },
            )
            primary, secondary = result["primary_success"], result["secondary_stale"]
            self.assertEqual(set(primary), {"Mi vs M", "Hod vs Ho"})
            self.assertEqual(
                (primary["Mi vs M"]["arm_only"], primary["Hod vs Ho"]["arm_only"]), (32, 32)
            )
            self.assertEqual(secondary["Mi vs M"]["reference_only"], 32)
            self.assertEqual(
                result["descriptive_vs_hn"]["Ho vs Hn"]["success"]["reference_only"], 32
            )
            memory = result["provider_memory"]
            self.assertEqual((memory["Hod"]["date_correct"], memory["M"]["date_correct"]), (32, 0))
            self.assertEqual(
                (memory["M"]["deferral_present"], memory["Mi"]["deferral_present"]), (32, 0)
            )
            write_csv(rows, run / "public.csv")
            self.assertEqual(analyse(read_csv(run / "public.csv")), result)


if __name__ == "__main__":
    unittest.main()
