from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from itertools import combinations, permutations
from pathlib import Path
from unittest.mock import patch

from afterevidence.__main__ import main
from afterevidence.memory import Memory, Policy, derive_proofs
from afterevidence.model import Evidence, Rule, Topology, generate_world, oracle
from afterevidence.runner import canonical, public_payload, run_case, run_suite, verify_report


class ProofContracts(unittest.TestCase):
    def test_explicit_and_or_fixtures(self) -> None:
        evidence = (Evidence("e1", "s1", "a"), Evidence("e2", "s2", "b"), Evidence("e3", "s3", "q"))
        proofs = derive_proofs(evidence, (Rule(("a", "b"), "q"),))
        self.assertEqual(proofs["q"], frozenset({frozenset({"e1", "e2"}), frozenset({"e3"})}))

    def test_all_deletion_subsets_match_independent_rebuild(self) -> None:
        for topology in Topology:
            for seed in range(5):
                world = generate_world(seed, 0, topology)
                ids = tuple(item.id for item in world.evidence)
                for size in range(len(ids) + 1):
                    for removed in combinations(ids, size):
                        memory = Memory(world.evidence, world.rules, Policy.REFERENCE)
                        memory.consolidate()
                        for source in removed:
                            memory.delete(source)
                        active = set(ids) - set(removed)
                        self.assertEqual(memory.active, active)
                        expected = oracle(world.evidence, world.rules, active)
                        propositions = {item.proposition for item in world.evidence} | {
                            rule.conclusion for rule in world.rules
                        }
                        for proposition in propositions:
                            self.assertEqual(memory.query(proposition), proposition in expected)

    def test_deletion_order_and_reconsolidation_are_invariant(self) -> None:
        for topology in Topology:
            world = generate_world(7, 0, topology)
            for order in permutations(world.partial_delete + world.final_delete):
                memory = Memory(world.evidence, world.rules, Policy.REFERENCE)
                memory.consolidate()
                for source in order:
                    memory.delete(source)
                    memory.delete(source)
                    before = memory.query(world.target)
                    memory.consolidate()
                    self.assertEqual(memory.query(world.target), before)
                    self.assertTrue(memory.query(world.control))

    def test_session_removal_and_unknown_ids(self) -> None:
        evidence = (Evidence("a", "s", "p"), Evidence("b", "s", "q"), Evidence("c", "t", "r"))
        memory = Memory(evidence, (), Policy.REFERENCE)
        memory.consolidate()
        memory.delete_session("s")
        memory.delete_session("s")
        self.assertFalse(memory.query("p"))
        self.assertFalse(memory.query("q"))
        self.assertTrue(memory.query("r"))
        with self.assertRaises(ValueError):
            memory.delete("unknown")
        with self.assertRaises(ValueError):
            memory.delete_session("unknown")

    def test_cycles_and_minimal_proofs(self) -> None:
        rules = (Rule(("a",), "b"), Rule(("b",), "a"), Rule(("a", "b"), "a"))
        self.assertEqual(derive_proofs((), rules), {})
        self.assertEqual(
            derive_proofs((Evidence("e", "s", "a"),), rules)["b"], frozenset({frozenset({"e"})})
        )

    def test_invalid_inputs_are_explicit(self) -> None:
        for constructor in (
            lambda: Evidence("", "s", "a"),
            lambda: Rule((), "a"),
            lambda: Rule(("a", "a"), "b"),
            lambda: generate_world(-1, 0, Topology.CONJUNCTION),
            lambda: derive_proofs((Evidence("e", "s", "a"), Evidence("e", "t", "b")), ()),
        ):
            with self.assertRaises(ValueError):
                constructor()
        with self.assertRaises(ValueError):
            oracle((Evidence("e", "s", "a"),), (), {"unknown"})


class HarnessContracts(unittest.TestCase):
    def test_closed_form_ablations_and_denominators(self) -> None:
        from afterevidence.runner import summarize

        records = [
            record
            for topology in Topology
            for policy in Policy
            for consolidated in (False, True)
            for sham in (False, True)
            for record in run_case(generate_world(5, 0, topology), policy, consolidated, sham)
        ]
        summary = summarize(records)
        self.assertEqual(len(records), 288)
        self.assertEqual(
            summary[Policy.REFERENCE],
            {
                "observations": 96,
                "correct": 96,
                "stale": 0,
                "over-deleted": 0,
            },
        )
        self.assertEqual(summary[Policy.FLAT_UNION]["stale"], 2)
        self.assertEqual(summary[Policy.DELETE_AFFECTED]["over-deleted"], 2)

    def test_sham_and_unrelated_controls_always_pass(self) -> None:
        for topology in Topology:
            world = generate_world(99, 0, topology)
            for policy in Policy:
                for record in run_case(world, policy, True, True):
                    self.assertEqual(record.outcome, "correct")
                for record in run_case(world, policy, True, False):
                    if record.proposition == world.control:
                        self.assertEqual(record.outcome, "correct")

    def test_renaming_and_input_order_do_not_change_outcomes(self) -> None:
        for topology in Topology:
            first = generate_world(1, 0, topology)
            second = generate_world(2, 0, topology)
            for policy in Policy:
                expected = [record.outcome for record in run_case(first, policy, True, False)]
                renamed = [record.outcome for record in run_case(second, policy, True, False)]
                reordered = replace(
                    first,
                    evidence=tuple(reversed(first.evidence)),
                    rules=tuple(reversed(first.rules)),
                )
                self.assertEqual(expected, renamed)
                self.assertEqual(
                    expected,
                    [record.outcome for record in run_case(reordered, policy, True, False)],
                )

    def test_public_payload_excludes_grading_fields(self) -> None:
        world = generate_world(1, 0, Topology.CONJUNCTION)
        self.assertEqual(set(public_payload(world)), {"evidence", "rules"})
        payload = canonical(public_payload(world))
        for forbidden in (
            '"expected"',
            '"partial_delete"',
            '"final_delete"',
            '"target"',
            '"topology"',
        ):
            self.assertNotIn(forbidden, payload)

    def test_swapping_oracle_labels_cannot_change_observations(self) -> None:
        world = generate_world(1, 0, Topology.CONJUNCTION)
        normal = run_case(world, Policy.FLAT_UNION, True, False)
        with patch("afterevidence.runner.oracle", return_value=set()):
            swapped = run_case(world, Policy.FLAT_UNION, True, False)
        self.assertEqual([row.actual for row in normal], [row.actual for row in swapped])
        self.assertEqual(
            [row.public_input_sha256 for row in normal],
            [row.public_input_sha256 for row in swapped],
        )
        self.assertNotEqual([row.expected for row in normal], [row.expected for row in swapped])

    def test_memory_has_no_oracle_dependency(self) -> None:
        world = generate_world(1, 0, Topology.ALTERNATIVE)
        with patch(
            "afterevidence.model.oracle", side_effect=AssertionError("Oracle reached system")
        ):
            memory = Memory(world.evidence, world.rules, Policy.REFERENCE)
            memory.consolidate()
            memory.delete(world.partial_delete[0])
            self.assertTrue(memory.query(world.target))

    def test_runner_detects_ignored_source_intervention(self) -> None:
        world = generate_world(1, 0, Topology.CONJUNCTION)
        with patch.object(Memory, "delete", return_value=None):
            records = run_case(world, Policy.REFERENCE, True, False)
        target = next(
            row
            for row in records
            if (row.checkpoint == "after-partial-deletion" and row.proposition == world.target)
        )
        self.assertFalse(target.expected)
        self.assertTrue(target.actual)
        self.assertEqual(target.outcome, "stale")

    def test_boolean_settings_cannot_produce_unverifiable_reports(self) -> None:
        for count, seed in ((True, 42), (1, True)):
            with self.assertRaises(ValueError):
                run_suite(count, seed)

    def test_json_roundtrip_replay_and_tamper_detection(self) -> None:
        report = run_suite(1, 42)
        roundtrip: object = json.loads(canonical(report))
        verify_report(roundtrip)
        report["world_count"] = 100
        with self.assertRaises(ValueError):
            verify_report(report)
        for invalid in (
            [],
            {"seed": True, "worlds_per_topology": 1},
            {"seed": 1, "worlds_per_topology": 0},
        ):
            with self.assertRaises(ValueError):
                verify_report(invalid)

    def test_hash_seed_does_not_change_results(self) -> None:
        import os

        command = [
            sys.executable,
            "-c",
            "from afterevidence.runner import canonical,run_suite; print(canonical(run_suite(1,42)))",
        ]
        first = subprocess.check_output(
            command, env={**os.environ, "PYTHONHASHSEED": "1"}, text=True
        )
        second = subprocess.check_output(
            command, env={**os.environ, "PYTHONHASHSEED": "999"}, text=True
        )
        self.assertEqual(first, second)

    def test_cli_writes_and_verifies_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["run", "--worlds-per-topology", "1", "--output", str(path)]), 0
                )
                self.assertEqual(main(["verify", str(path)]), 0)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["run", "--output", str(path)])
            self.assertEqual(error.exception.code, 2)

    def test_cli_rejects_bad_limits_and_malformed_json(self) -> None:
        for arguments in (
            ["run", "--worlds-per-topology", "0"],
            ["run", "--worlds-per-topology", "1001"],
            ["run", "--seed", "-1"],
        ):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(arguments)
            self.assertEqual(error.exception.code, 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["verify", str(path)])

    def test_existing_evaluation_output_is_rejected_before_model_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            path.write_text("{}", encoding="utf-8")
            with (
                patch(
                    "afterevidence.__main__.Ollama",
                    side_effect=AssertionError("Model access not allowed"),
                ),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main(["evaluate-app", "--output", str(path)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(path.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
