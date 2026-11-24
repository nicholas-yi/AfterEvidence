from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from afterevidence.application import FIELD_HINTS, Application, parse_cards, parse_facts
from afterevidence.ollama import Ollama, OllamaError, Reply
from afterevidence.packs import PACKS, Card, ExtractedFact, get_pack, plans
from afterevidence.runner import canonical
from afterevidence.store import Episode, StateChanged, Store


class ScriptedModel:
    model = "test-local"

    def __init__(self) -> None:
        self.responses: list[dict[str, object] | OllamaError] = []
        self.requests: list[tuple[str, str, dict[str, object]]] = []
        self.before_reply: Callable[[], object] | None = None

    def models(self) -> list[dict[str, object]]:
        return [{"name": self.model, "size": 1, "digest": "test-digest"}]

    def complete(self, system: str, prompt: str, schema: dict[str, object]) -> Reply:
        self.requests.append((system, prompt, schema))
        if self.before_reply:
            action, self.before_reply = self.before_reply, None
            action()
        if not self.responses:
            raise AssertionError("Unexpected model request.")
        data = self.responses.pop(0)
        if isinstance(data, OllamaError):
            raise data
        return Reply(data, self.model, "test-digest", "input-hash", "output-hash", 20, 10, 0.01)


def facts_output(pack: str, facts: list[dict[str, object]]) -> dict[str, object]:
    get_pack(pack)
    return {"facts": facts}


class ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "memory.sqlite3"
        self.store = Store(self.path)
        self.model = ScriptedModel()
        self.app = Application(self.store, self.model)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def fact(
        self,
        relation: str,
        value: str,
        *,
        subject: str = "Atlas",
        pack: str = "project",
        operation: str = "assert",
        session: str = "notes",
    ) -> Episode:
        text = f"{subject}: {relation} = {value}."
        episode = self.store.add_episode(pack, subject, text, "Observation", session)
        self.store.apply_extraction(
            episode.id,
            self.store.epoch(pack),
            (ExtractedFact(relation, value, text, operation, 0.9),),
        )
        return episode

    def consolidate(self, subject: str = "Atlas") -> str:
        snapshot = self.store.snapshot("project")
        facts = snapshot.facts(subject)
        self.store.apply_sleep(
            "project",
            subject,
            snapshot.epoch,
            (Card("summary", "Morgan's release is scheduled.", 0.7, (facts[0].id,)),),
        )
        return next(
            claim.id
            for claim in self.store.snapshot("project").claims
            if claim.origin == "qwen-sleep"
        )

    def test_persistence_and_independent_support_preservation(self) -> None:
        first = self.fact("owner", "Morgan")
        self.fact("deadline", "2026-12-04")
        summary = self.consolidate()
        second = self.fact("owner", "Morgan", session="independent")
        self.store.remove_episode(first.id)
        reopened = Store(self.path).snapshot("project")
        owner = next(claim for claim in reopened.facts("Atlas") if claim.relation == "owner")
        self.assertEqual(owner.proofs, frozenset({frozenset({second.id})}))
        card = next(claim for claim in reopened.claims if claim.id == summary)
        self.assertEqual(card.status, "live")
        self.assertTrue(all(first.id not in proof for proof in card.proofs))

    def test_last_required_source_removal_clears_derived_content(self) -> None:
        owner = self.fact("owner", "PrivateOwnerSentinel")
        self.fact("deadline", "2026-12-04")
        snapshot = self.store.snapshot("project")
        self.store.apply_sleep(
            "project",
            "Atlas",
            snapshot.epoch,
            (
                Card(
                    "summary",
                    "PrivateOwnerSentinel owns the release.",
                    0.8,
                    (snapshot.facts("Atlas")[0].id,),
                ),
            ),
        )
        self.store.remove_episode(owner.id)
        public = canonical(self.app.state("project"))
        self.assertNotIn("PrivateOwnerSentinel", public)
        self.assertTrue(
            any(claim.status == "withdrawn" for claim in self.store.snapshot("project").claims)
        )
        self.store.remove_episode(owner.id)

    def test_affected_subject_changes_without_hiding_unrelated_memory(self) -> None:
        self.fact("owner", "Morgan")
        self.consolidate()
        self.fact("owner", "Taylor", subject="Birch")
        self.consolidate("Birch")
        self.fact("deadline", "2026-12-04")
        snapshot = self.store.snapshot("project")
        self.assertTrue(
            any(
                claim.subject == "Atlas"
                and claim.origin == "qwen-sleep"
                and claim.status == "dirty"
                for claim in snapshot.claims
            )
        )
        self.assertTrue(
            any(
                claim.subject == "Birch" and claim.origin == "qwen-sleep" and claim.status == "live"
                for claim in snapshot.claims
            )
        )

    def test_explicit_correction_does_not_resurrect_old_value_when_removed(self) -> None:
        self.fact("owner", "Morgan")
        newer = self.fact("owner", "Jordan", operation="correct")
        self.assertEqual(
            [claim.value for claim in self.store.snapshot("project").facts("Atlas")], ["Jordan"]
        )
        self.store.remove_episode(newer.id)
        self.assertEqual(self.store.snapshot("project").facts("Atlas"), ())

    def test_conflicts_block_answers_and_resolve_when_conflicting_source_removed(self) -> None:
        self.fact("owner", "Morgan")
        second = self.fact("owner", "Jordan")
        self.assertEqual(self.store.snapshot("project").facts("Atlas"), ())
        with self.assertRaises(StateChanged):
            self.app.ask("project", "Atlas", "Who owns the release?")
        self.assertEqual(self.model.requests, [])
        self.store.remove_episode(second.id)
        self.assertEqual(
            [claim.value for claim in self.store.snapshot("project").facts("Atlas")], ["Morgan"]
        )

    def test_case_insensitive_subjects_share_rule_plans(self) -> None:
        self.fact("owner", "Morgan", subject="atlas")
        self.fact("deadline", "2026-12-04", subject="Atlas")
        self.assertTrue(
            any(
                claim.origin == "rule" and claim.status == "live"
                for claim in self.store.snapshot("project").claims
            )
        )

    def test_source_order_does_not_depend_on_uuid_when_timestamps_match(self) -> None:
        with (
            patch("afterevidence.store.now", return_value="2026-11-12T12:00:00+00:00"),
            patch("afterevidence.store.uuid4", side_effect=[UUID(int=2), UUID(int=1)]),
        ):
            first = self.store.add_episode(
                "project", "Atlas", "First observation.", "First", "notes"
            )
            second = self.store.add_episode(
                "project", "Atlas", "Later correction.", "Second", "notes"
            )
        self.assertEqual(
            [episode.id for episode in self.store.snapshot("project").episodes],
            [first.id, second.id],
        )

    def test_session_removal_clears_multiple_sources_and_preserves_others(self) -> None:
        self.fact("owner", "Morgan", session="remove")
        self.fact("deadline", "2026-12-04", session="remove")
        self.fact("goal", "Accessibility", session="keep")
        self.store.remove_session("project", "remove")
        self.assertEqual(
            [claim.relation for claim in self.store.snapshot("project").facts("Atlas")], ["goal"]
        )
        with self.assertRaises(LookupError):
            self.store.remove_session("project", "does-not-exist")

    def test_source_replacement_is_versioned_and_erases_unsupported_old_text(self) -> None:
        episode = self.fact("owner", "OldOwnerSentinel")
        replacement = self.store.remove_episode(episode.id, "Atlas: owner = NewOwner.")
        self.assertIsNotNone(replacement)
        if replacement is None:
            self.fail("Replacement source missing")
        self.assertEqual(replacement.supersedes, episode.id)
        self.assertNotIn("OldOwnerSentinel", canonical(self.app.state("project")))
        with self.assertRaises(StateChanged):
            self.store.apply_extraction(episode.id, self.store.epoch("project"), ())

    def test_stale_sleep_is_rejected_without_resurrecting_deleted_evidence(self) -> None:
        episode = self.fact("owner", "Morgan")
        self.model.responses.append(
            {"summary": "Morgan owns the release.", "confidence": 0.8, "extra": None}
        )
        self.model.before_reply = lambda: self.store.remove_episode(episode.id)
        with self.assertRaises(StateChanged):
            self.app.sleep("project", "Atlas")
        self.assertFalse(
            any(
                claim.origin == "qwen-sleep" and claim.status == "live"
                for claim in self.store.snapshot("project").claims
            )
        )

    def test_stale_answer_is_discarded(self) -> None:
        episode = self.fact("owner", "Morgan")
        self.model.responses.append({"answer": "Morgan", "unknown": False, "citations": ["S1"]})
        self.model.before_reply = lambda: self.store.remove_episode(episode.id)
        with self.assertRaises(StateChanged):
            self.app.ask("project", "Atlas", "Who owns it?")

    def test_deleted_source_cannot_receive_late_extraction(self) -> None:
        episode = self.store.add_episode(
            "project", "Atlas", "Morgan owns Atlas.", "Observation", "notes"
        )
        self.model.responses.append(
            facts_output(
                "project",
                [
                    {
                        "relation": "owner",
                        "value": "Morgan",
                        "quote": "Morgan owns Atlas.",
                        "operation": "assert",
                        "confidence": 0.9,
                    },
                ],
            )
        )
        self.model.before_reply = lambda: self.store.remove_episode(episode.id)
        with self.assertRaises(StateChanged):
            self.app.extract(episode.id)
        self.assertEqual(self.store.snapshot("project").facts("Atlas"), ())

    def test_bad_model_output_is_explicit_and_retryable(self) -> None:
        episode = self.store.add_episode(
            "project", "Atlas", "Morgan owns Atlas.", "Observation", "notes"
        )
        self.model.responses.append(
            facts_output(
                "project",
                [
                    {
                        "relation": "owner",
                        "value": "Invented",
                        "quote": "Morgan owns Atlas.",
                        "operation": "assert",
                        "confidence": 0.9,
                    },
                ],
            )
        )
        with self.assertRaises(ValueError):
            self.app.extract(episode.id)
        self.assertEqual(self.store.episode(episode.id).extraction_status, "error")
        with self.assertRaises(StateChanged):
            self.app.ask("project", "Atlas", "Who owns it?")
        self.model.responses.append(
            facts_output(
                "project",
                [
                    {
                        "relation": "owner",
                        "value": "Morgan",
                        "quote": "Morgan owns Atlas.",
                        "operation": "assert",
                        "confidence": 0.9,
                    },
                ],
            )
        )
        self.assertEqual(self.app.extract(episode.id)["status"], "ready")

    def test_no_evidence_abstains_without_calling_model(self) -> None:
        result = self.app.ask("project", "Atlas", "What should happen?")
        self.assertTrue(result["unknown"])
        self.assertFalse(result["model_used"])
        self.assertEqual(self.model.requests, [])

    def test_dirty_model_cards_never_enter_answer_context(self) -> None:
        self.fact("owner", "Morgan")
        self.consolidate()
        self.fact("goal", "Accessibility")
        self.model.responses.append({"answer": "Morgan", "unknown": False, "citations": ["S1"]})
        result = self.app.ask("project", "Atlas", "Who owns it?")
        self.assertNotIn("Morgan's release is scheduled.", self.model.requests[-1][1])
        self.assertTrue(result["warnings"])

    def test_call_telemetry_does_not_persist_prompts_or_responses(self) -> None:
        episode = self.fact("owner", "PrivateOwnerSentinel")
        self.model.responses.append(
            {"answer": "PrivateOwnerSentinel", "unknown": False, "citations": ["S1"]}
        )
        self.app.ask("project", "Atlas", "PrivateQuestionSentinel?")
        self.store.remove_episode(episode.id)
        public = canonical(self.app.state("project"))
        self.assertNotIn("PrivateQuestionSentinel", public)
        self.assertNotIn("PrivateOwnerSentinel", public)
        self.assertIn("input-hash", public)

    def test_unknown_answer_citations_are_rejected(self) -> None:
        self.fact("owner", "Morgan")
        self.model.responses.append(
            {"answer": "Morgan", "unknown": False, "citations": ["invented-source"]}
        )
        with self.assertRaises(ValueError):
            self.app.ask("project", "Atlas", "Who owns it?")

    def test_short_model_citations_are_resolved_to_source_ids(self) -> None:
        source = self.fact("owner", "Morgan")
        self.model.responses.append({"answer": "Morgan", "unknown": False, "citations": ["S1"]})
        result = self.app.ask("project", "Atlas", "Who owns it?")
        self.assertEqual(result["citations"], (source.id,))
        self.assertNotIn(source.id, self.model.requests[-1][1])

    def test_consolidation_lineage_is_assigned_by_host(self) -> None:
        cards = parse_cards(
            {"summary": "A concise summary.", "confidence": 0.8, "extra": None},
            {"fact-a", "fact-b"},
        )
        self.assertEqual(cards[0].citations, ("fact-a", "fact-b"))
        with self.assertRaises(ValueError):
            parse_cards(
                {"summary": "Claim", "confidence": 0.8, "extra": None, "citations": ["invented"]},
                {"fact-a"},
            )

    def test_review_rejects_and_restores_a_model_assertion_without_deleting_source(self) -> None:
        source = self.fact("owner", "Morgan")
        self.fact("deadline", "2026-12-04")
        owner = next(
            claim
            for claim in self.store.snapshot("project").facts("Atlas")
            if claim.relation == "owner"
        )
        self.assertEqual(self.store.review_claim(owner.id, True), "rejected")
        self.assertEqual(self.store.episode(source.id).status, "active")
        self.assertFalse(
            any(
                claim.relation == "owner" for claim in self.store.snapshot("project").facts("Atlas")
            )
        )
        self.assertFalse(
            any(
                claim.origin == "rule" and claim.status == "live"
                for claim in self.store.snapshot("project").claims
            )
        )
        self.assertEqual(self.store.review_claim(owner.id, False), "live")
        self.assertTrue(
            any(
                claim.origin == "rule" and claim.status == "live"
                for claim in self.store.snapshot("project").claims
            )
        )

    def test_rejected_model_summary_is_not_silently_readded_by_sleep(self) -> None:
        self.fact("owner", "Morgan")
        summary_id = self.consolidate()
        self.store.review_claim(summary_id, True)
        self.model.responses.append(
            {"summary": "Morgan's release is scheduled.", "confidence": 0.7, "extra": None}
        )
        result = self.app.sleep("project", "Atlas")
        self.assertEqual(result["status"], "review-needed")
        self.assertEqual(result["cards"], 0)
        self.assertTrue(result["warnings"])
        self.assertEqual(
            next(
                claim.status
                for claim in self.store.snapshot("project").claims
                if claim.id == summary_id
            ),
            "rejected",
        )

    def test_source_erasure_clears_rejected_content_and_prevents_restore(self) -> None:
        source = self.fact("owner", "ReviewPrivateSentinel")
        owner = self.store.snapshot("project").facts("Atlas")[0]
        self.store.review_claim(owner.id, True)
        self.store.remove_episode(source.id)
        self.assertNotIn("ReviewPrivateSentinel", canonical(self.app.state("project")))
        with self.assertRaises(StateChanged):
            self.store.review_claim(owner.id, False)

    def test_review_cannot_override_a_rule_or_unknown_claim(self) -> None:
        self.fact("owner", "Morgan")
        self.fact("deadline", "2026-12-04")
        rule = next(
            claim
            for claim in self.store.snapshot("project").claims
            if claim.origin == "rule" and claim.status == "live"
        )
        with self.assertRaises(ValueError):
            self.store.review_claim(rule.id, True)
        with self.assertRaises(LookupError):
            self.store.review_claim("missing", True)

    def test_model_failure_leaves_visible_failed_source(self) -> None:
        self.model.responses.append(OllamaError("Local model unavailable."))
        with self.assertRaises(OllamaError):
            self.app.wake("project", "Atlas", "Morgan owns Atlas.")
        episode = self.store.snapshot("project").episodes[0]
        self.assertEqual(episode.extraction_status, "error")
        self.assertIn("unavailable", episode.error)

    def test_all_five_packs_have_real_rule_actions(self) -> None:
        scenarios = {
            "project": {"owner": ("Morgan", "a"), "deadline": ("2026-12-04", "b")},
            "support": {
                "refund_window_days": ("30 days", "a"),
                "request_age_days": ("14 days", "b"),
            },
            "tutoring": {
                "topic": ("fractions", "a"),
                "assessment_independent": ("independent", "b"),
                "assessment_score": ("40%", "c"),
            },
            "research": {
                "result": ("12% improvement", "a"),
                "evidence_status": ("invalidated", "b"),
            },
            "operations": {
                "dependency_version": ("2.0", "a"),
                "verified_version": ("1.0", "b"),
                "procedure": ("restart the worker", "c"),
            },
        }
        self.assertEqual(set(scenarios), {pack.id for pack in PACKS})
        for pack, facts in scenarios.items():
            candidates, warnings = plans(pack, "Subject", facts)
            self.assertTrue(candidates, pack)
            self.assertFalse(warnings)
            self.assertTrue(set(candidates[0].premises) <= {value[1] for value in facts.values()})

    def test_every_field_has_an_explicit_semantic_description(self) -> None:
        for pack in PACKS:
            for field in pack.fields:
                self.assertIn(field, FIELD_HINTS)
                self.assertTrue(FIELD_HINTS[field].strip())

    def test_parsers_reject_unknown_premises_bad_confidence_and_empty_sleep(self) -> None:
        with self.assertRaises(ValueError):
            parse_cards({"summary": "", "confidence": 0.5, "extra": None}, {"a"})
        with self.assertRaises(ValueError):
            parse_cards({"summary": "Claim", "confidence": 2, "extra": None}, {"a"})
        with self.assertRaises(ValueError):
            parse_cards(
                {"summary": "Claim", "confidence": 0.5, "extra": None, "citations": ["b"]}, {"a"}
            )
        episode = self.store.add_episode("project", "Atlas", "Morgan owns Atlas.", "Note", "notes")
        with self.assertRaises(ValueError):
            parse_facts(
                facts_output(
                    "project",
                    [
                        {
                            "relation": "unknown",
                            "value": "Morgan",
                            "quote": episode.text,
                            "operation": "assert",
                            "confidence": 0.9,
                        }
                    ],
                ),
                episode,
            )

    def test_missing_rule_inputs_are_reported_without_invented_facts(self) -> None:
        episode = self.store.add_episode(
            "operations", "Service Pine", "Current version is 2.0.", "Note", "notes"
        )
        with self.assertRaises(ValueError):
            parse_facts({"facts": {"dependency_version": None}}, episode)
        parsed = parse_facts(
            facts_output(
                "operations",
                [
                    {
                        "relation": "dependency_version",
                        "value": "2.0",
                        "quote": episode.text,
                        "operation": "assert",
                        "confidence": 0.9,
                    },
                ],
            ),
            episode,
        )
        self.store.apply_extraction(episode.id, self.store.epoch("operations"), parsed)
        self.assertIn("verified_version", " ".join(self.store.snapshot("operations").warnings))

    def test_required_summary_schema_preserves_optional_hypothesis(self) -> None:
        cards = parse_cards(
            {
                "summary": "The assessment score was 40%.",
                "confidence": 0.8,
                "extra": {
                    "kind": "hypothesis",
                    "text": "More practice may help.",
                    "confidence": 0.4,
                },
            },
            {"fact-a"},
        )
        self.assertEqual([card.kind for card in cards], ["summary", "hypothesis"])

    def test_ollama_rejects_nonlocal_endpoints(self) -> None:
        for url in (
            "https://example.com",
            "http://example.com",
            "http://127.0.0.1:11434/other",
            "http://user:secret@localhost:11434",
            "http://127.0.0.1:11434?x=1",
        ):
            with self.assertRaises(ValueError):
                Ollama(base_url=url)

    def test_cloud_tag_aliases_are_rejected_even_with_local_metadata(self) -> None:
        for name in ("qwen:cloud", "qwen:4b-cloud"):
            client = Ollama(name)
            with (
                patch.object(
                    client, "models", return_value=[{"name": name, "size": 1, "digest": "test"}]
                ),
                self.assertRaisesRegex(OllamaError, "Only an already-installed local model"),
            ):
                client.selected_model()


if __name__ == "__main__":
    unittest.main()
