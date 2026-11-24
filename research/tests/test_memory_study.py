from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from research.analysis.stats import holm, mcnemar_exact, wilson
from research.harness.copilot_shim import (
    _OPEN,
    build_request,
    complete_chat,
    parse_tool_reply,
    strict_schema,
)
from research.harness.memory_bank import cluster, sleep_weights
from research.harness.memory_retrievers import pack, rank_items
from research.harness.study_runner import run_jobs, started_requests
from research.studies.lifecycle import identifiers, mentions


class ShimTests(unittest.TestCase):
    def test_closed_schemas_are_made_strict_and_open_ones_fall_back(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "object", "properties": {}}}}
        closed = strict_schema(schema)
        self.assertFalse(closed["additionalProperties"])
        self.assertFalse(closed["properties"]["x"]["additionalProperties"])
        self.assertIs(
            strict_schema({"type": "object", "additionalProperties": {"type": "string"}}), _OPEN
        )
        body = {
            "messages": [],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": {"type": "object", "additionalProperties": True}},
            },
        }
        self.assertIsNone(build_request(body)[2])

    def test_tool_replies_are_validated_and_forced_calls_enforced(self) -> None:
        reply = json.dumps(
            {
                "kind": "tool_calls",
                "content": "",
                "tool_calls": [{"name": "lookup", "arguments_json": '{"id": 1}'}],
            }
        )
        message = parse_tool_reply(reply, {"lookup"}, force=True)
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"id": 1})
        text = json.dumps({"kind": "message", "content": "hi", "tool_calls": []})
        with self.assertRaises(ValueError):
            parse_tool_reply(text, {"lookup"}, force=True)
        with self.assertRaises(ValueError):
            parse_tool_reply(reply.replace("lookup", "other"), {"lookup"}, force=False)

    def test_one_counted_reask_then_visible_failure(self) -> None:
        class Backend:
            def __init__(self, replies: list[str]) -> None:
                self.replies, self.calls, self.events, self.last_metrics = replies, 0, [], None

            async def complete(self, system: str, prompt: str, schema: object) -> str:
                self.calls += 1
                return self.replies.pop(0)

            def write(self, event: str, **_fields: object) -> None:
                self.events.append(event)

        body = {
            "messages": [{"role": "user", "content": "x"}],
            "response_format": {"type": "json_object"},
        }
        good = Backend(["not json", '{"a": 1}'])
        result = asyncio.run(complete_chat(good, body))
        self.assertEqual(result["choices"][0]["message"]["content"], '{"a": 1}')
        self.assertEqual((good.calls, good.events), (2, ["shim-reask"]))
        with self.assertRaises(ValueError):
            asyncio.run(complete_chat(Backend(["bad", "still bad"]), body))


class MemoryTests(unittest.TestCase):
    def test_pack_respects_the_character_budget(self) -> None:
        text, ids = pack([("a", "x" * 300), ("b", "y" * 300)], limit=400)
        self.assertLessEqual(len(text), 400)
        self.assertEqual(ids, ["a", "b"])

    def test_weights_scale_similarity(self) -> None:
        items = [
            {"id": "low", "embedding": [1.0, 0.0], "weight": 0.0},
            {"id": "high", "embedding": [0.9, 0.1], "weight": 1.0},
        ]
        self.assertEqual(rank_items(items, [1.0, 0.0])[0]["id"], "high")

    def test_sleep_reweights_by_distinct_support_and_prunes(self) -> None:
        candidates = [
            {"episode": e, "text": t, "embedding": v}
            for e, t, v in [
                ("ep-1", "verify", [1.0, 0.0]),
                ("ep-2", "verify again", [0.99, 0.01]),
                ("ep-2", "verify twice", [0.98, 0.02]),
                ("ep-3", "rare", [0.0, 1.0]),
            ]
        ]
        groups = cluster(candidates, threshold=0.9)
        self.assertEqual(len(groups), 2)
        kept = sleep_weights(groups, keep_floor=0.6, minimum=1)
        self.assertEqual([(k["strength"], k["weight"]) for k in kept], [(2, 1.0)])


class AnalysisTests(unittest.TestCase):
    def test_statistics(self) -> None:
        self.assertEqual(mcnemar_exact(0, 0), 1.0)
        self.assertAlmostEqual(mcnemar_exact(0, 6), 0.03125)
        self.assertEqual(holm({"a": 0.01, "b": 0.04}), {"a": 0.02, "b": 0.04})
        low, high = wilson(9, 12)
        self.assertTrue(0.46 < low < 0.47 and 0.91 < high < 0.92)


class RunnerTests(unittest.TestCase):
    def test_existing_outputs_are_never_rerun_and_cap_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.calls.jsonl").write_text('{"event": "copilot-request-started"}\n' * 5)
            self.assertEqual(started_requests(root), 5)
            existing = root / "done.json"
            existing.write_text("{}")
            results = run_jobs(
                [
                    {"task": "1", "output": str(existing)},
                    {"task": "2", "output": str(root / "new.json")},
                ],
                root,
                cap=20,
                workers=1,
            )
            self.assertEqual(
                sorted(r["status"] for r in results), ["skipped-cap", "skipped-existing"]
            )


class LifecycleTests(unittest.TestCase):
    def test_identifier_probes(self) -> None:
        episode = {
            "text": 'call find_user_id_by_name_zip({"first_name": "Ann", "last_name": "Lee", "zip": "1"}) #W1234567'
        }
        probes = identifiers(episode)
        self.assertEqual(probes, {"#W1234567", "Ann Lee"})
        self.assertEqual(mentions(["ann lee returned"], probes), {"Ann Lee"})


if __name__ == "__main__":
    unittest.main()
