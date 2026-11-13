from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import TextIO

from .application import Application
from .ollama import Ollama, OllamaError, Reply
from .packs import PACKS, get_pack
from .runner import canonical, source_digest
from .store import StateChanged, Store
from .validation import text_value


class RecordedModel:
    def __init__(self, client: Ollama, journal: TextIO | None = None):
        self.client = client
        self.model = client.model
        self.records: list[dict[str, object]] = []
        self.journal = journal

    def _record(self, record: dict[str, object]) -> None:
        self.records.append(record)
        if self.journal is not None:
            self.journal.write(canonical(record) + "\n")
            self.journal.flush()

    def models(self) -> list[dict[str, object]]:
        return self.client.models()

    def complete(self, system: str, prompt: str, schema: dict[str, object]) -> Reply:
        record: dict[str, object] = {
            "system": system,
            "prompt": prompt,
            "schema": schema,
            "model": self.model,
            "options": dict(self.client.options),
        }
        if self.journal is not None:
            self.journal.write(canonical({**record, "status": "started"}) + "\n")
            self.journal.flush()
        try:
            reply = self.client.complete(system, prompt, schema)
        except (OllamaError, ValueError) as error:
            record.update({"error": str(error), "status": "failed"})
            self._record(record)
            raise
        record.update({"response": reply.data, "metrics": reply.metrics(), "status": "completed"})
        self._record(record)
        return reply


def evaluate_application(
    client: Ollama, journal: TextIO | None = None, pack_ids: tuple[str, ...] | None = None
) -> dict[str, object]:
    selected_packs = PACKS if pack_ids is None else tuple(get_pack(name) for name in pack_ids)
    if not selected_packs or len({pack.id for pack in selected_packs}) != len(selected_packs):
        raise ValueError("Select distinct, nonempty scenario packs for evaluation.")
    revision = source_digest()
    selected = client.selected_model()
    recorded = RecordedModel(client, journal)
    started = time.monotonic()
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="afterevidence-eval-") as directory:
        store = Store(Path(directory) / "synthetic.sqlite3")
        app = Application(store, recorded)
        for pack in selected_packs:
            case: dict[str, object] = {
                "pack": pack.id,
                "subject": pack.subject,
                "notes": list(pack.examples),
                "question": pack.question,
                "answers": {},
                "semantic_accuracy": None,
            }
            cases.append(case)
            try:
                print(f"[{pack.id}] Qwen extraction", flush=True)
                wake = app.wake(
                    pack.id,
                    pack.subject,
                    "\n".join(pack.examples),
                    "Synthetic development example",
                    "evaluation",
                )
                case["wake"] = wake
                initial = store.snapshot(pack.id)
                relations = {claim.relation for claim in initial.facts(pack.subject)}
                expected_relations = {
                    "project": {"owner", "deadline", "goal"},
                    "support": {"refund_window_days", "request_age_days", "subscription_tier"},
                    "tutoring": {"topic", "assessment_score", "assessment_independent"},
                    "research": {"result", "evidence_status", "dataset"},
                    "operations": {"dependency_version", "verified_version", "procedure"},
                }[pack.id]
                checks: dict[str, bool] = {
                    "expected_fields_extracted": expected_relations <= relations,
                    "rule_plan_available": any(
                        claim.origin == "rule" and claim.status == "live"
                        for claim in initial.claims
                    ),
                }
                case["checks"] = checks
                print(f"[{pack.id}] Qwen consolidation", flush=True)
                case["sleep"] = app.sleep(pack.id, pack.subject)
                answers: dict[str, object] = {}
                for mode in ("raw", "awake", "repaired"):
                    print(f"[{pack.id}] answer mode={mode}", flush=True)
                    answer = app.ask(pack.id, pack.subject, pack.question, mode)
                    answers[mode] = answer
                    checks[f"{mode}_returned_current_citations"] = bool(
                        answer["citations"]
                    ) and answer["epoch"] == store.epoch(pack.id)
                case["answers"] = answers
                if pack.id == "project":
                    print("[project] correction, independent support, and deletion", flush=True)
                    source_id = str(wake["episode_id"])
                    correction = app.correct(
                        source_id, "\n".join(pack.examples).replace("Morgan", "Jordan")
                    )
                    case["correction"] = correction
                    checks["owner_corrected"] = any(
                        claim.relation == "owner" and claim.value == "Jordan"
                        for claim in store.snapshot(pack.id).facts(pack.subject)
                    )
                    case["repair"] = app.sleep(pack.id, pack.subject)
                    corrected_answer = app.ask(pack.id, pack.subject, pack.question)
                    case["corrected_answer"] = corrected_answer
                    checks["corrected_owner_answer_exact"] = (
                        str(corrected_answer["answer"]).strip(" .\n").casefold() == "jordan"
                    )
                    duplicate = app.wake(
                        pack.id,
                        pack.subject,
                        "Jordan is the release owner for Atlas.",
                        "Independent support example",
                        "independent",
                    )
                    replacement_id = text_value(
                        correction["episode_id"], "Replacement source ID", 80
                    )
                    store.remove_episode(replacement_id)
                    checks["independent_owner_preserved"] = any(
                        claim.relation == "owner" and claim.value == "Jordan"
                        for claim in store.snapshot(pack.id).facts(pack.subject)
                    )
                    checks["missing_deadline_plan_withdrawn"] = not any(
                        claim.origin == "rule" and claim.status == "live"
                        for claim in store.snapshot(pack.id).claims
                    )
                    store.remove_episode(str(duplicate["episode_id"]))
                    abstention = app.ask(pack.id, pack.subject, pack.question)
                    case["after_deletion"] = abstention
                    checks["last_support_removal_abstains"] = (
                        abstention["unknown"] is True and abstention["model_used"] is False
                    )
                    checks["deleted_value_not_in_application_state"] = "Jordan" not in canonical(
                        app.state(pack.id)
                    ) and "Morgan" not in canonical(app.state(pack.id))
                case["status"] = (
                    "passed-structural-checks"
                    if all(checks.values())
                    else "failed-structural-checks"
                )
                case["final_state"] = app.state(pack.id)
            except (OllamaError, ValueError, StateChanged) as error:
                case["status"] = "failed"
                case["error"] = str(error)
                case["final_state"] = app.state(pack.id)
                print(f"[{pack.id}] FAILED: {error}", flush=True)
    passed = sum(case.get("status") == "passed-structural-checks" for case in cases)
    unchanged = source_digest() == revision
    return {
        "mode": "synthetic-application-development",
        "external_spend_usd": 0,
        "source_sha256": revision,
        "source_unchanged": unchanged,
        "model": selected,
        "status": "passed" if passed == len(selected_packs) and unchanged else "failed",
        "requested_packs": [pack.id for pack in selected_packs],
        "cases_passed_structural_checks": passed,
        "cases_total": len(selected_packs),
        "seconds": time.monotonic() - started,
        "cases": cases,
        "model_calls": recorded.records,
        "limitations": [
            "Fixed synthetic development fixtures, not a held-out benchmark or preregistered main study.",
            "Three answer modes use the same local Qwen model. No statistical superiority is inferred.",
            "Citations and field/plan checks are programmatic; semantic accuracy is not automatically scored.",
            "Earlier connectivity and project smoke calibration preceded this development run.",
            "No Google-style parameter expansion, Knowledge Seeding, or RL training is performed.",
        ],
    }
