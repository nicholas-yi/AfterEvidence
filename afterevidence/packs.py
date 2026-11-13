from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Pack:
    id: str
    title: str
    description: str
    fields: tuple[str, ...]
    subject: str
    examples: tuple[str, ...]
    correction: str
    question: str

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "fields": self.fields,
            "subject": self.subject,
            "examples": self.examples,
            "correction": self.correction,
            "question": self.question,
        }


PACKS = (
    Pack(
        "project",
        "Project decisions",
        "Turn changing owners, dates, and decisions into supported next actions.",
        ("owner", "deadline", "goal", "decision", "dependency", "priority"),
        "Atlas",
        (
            "Morgan is the release owner for Atlas.",
            "Atlas has a release deadline of 2026-12-04.",
            "Atlas has a goal of shipping the accessibility improvements.",
        ),
        "Correction: Jordan is the release owner for Atlas.",
        "Who is the current release owner? Give just the person's name.",
    ),
    Pack(
        "support",
        "Customer support",
        "Check policy context without taking payments or issuing refunds.",
        ("subscription_tier", "refund_window_days", "request_age_days", "order_status", "issue"),
        "Case Cedar",
        (
            "Case Cedar has a refund window of 30 days.",
            "The request age for Case Cedar is 14 days.",
            "Case Cedar has a subscription tier of Pro.",
        ),
        "Correction: the request age for Case Cedar is 45 days.",
        "Is the request within the documented refund window? Explain without issuing a refund.",
    ),
    Pack(
        "tutoring",
        "Adaptive tutoring",
        "Keep tentative learning hypotheses separate from observed assessments.",
        ("topic", "assessment_score", "assessment_independent", "practice_goal", "misconception"),
        "Riley",
        (
            "Riley is studying fractions.",
            "Riley has an assessment score of 40%.",
            "Riley's assessment was independent.",
        ),
        "Correction: Riley's assessment was assisted, not independent.",
        "What is the next appropriate learning step, given the assessment evidence?",
    ),
    Pack(
        "research",
        "Research notebook",
        "Reconsider interpretations when experimental evidence changes.",
        ("hypothesis", "result", "evidence_status", "dataset", "method"),
        "Trial Cedar",
        (
            "Trial Cedar has a result of a 12% improvement.",
            "Trial Cedar has an evidence status of valid.",
            "Trial Cedar used the synthetic Dataset Pine.",
        ),
        "Correction: Trial Cedar has an evidence status of invalidated.",
        "Can the reported improvement be treated as established evidence? Explain.",
    ),
    Pack(
        "operations",
        "Coding and operations",
        "Remember candidate procedures, then revalidate them when environments change.",
        ("dependency_version", "verified_version", "procedure", "environment", "test_status"),
        "Service Pine",
        (
            "Service Pine currently uses dependency version 2.0.",
            "The procedure for Service Pine is restart the worker.",
            "The verified dependency version for the Service Pine procedure is 1.0.",
        ),
        "Correction: Service Pine currently uses dependency version 1.0.",
        "Should the remembered procedure be trusted for the current dependency version?",
    ),
)


def get_pack(pack_id: str) -> Pack:
    for pack in PACKS:
        if pack.id == pack_id:
            return pack
    raise ValueError(f"Unknown scenario pack: {pack_id}")


@dataclass(frozen=True)
class ExtractedFact:
    relation: str
    value: str
    quote: str
    operation: str
    confidence: float


@dataclass(frozen=True)
class Card:
    kind: str
    text: str
    confidence: float
    citations: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    text: str
    premises: tuple[str, ...]


def plans(
    pack_id: str, subject: str, facts: dict[str, tuple[str, str]]
) -> tuple[list[Plan], list[str]]:
    get_pack(pack_id)
    result: list[Plan] = []
    warnings: list[str] = []
    required = {
        "project": {"owner", "deadline"},
        "support": {"refund_window_days", "request_age_days"},
        "tutoring": {"topic", "assessment_independent"},
        "research": {"result", "evidence_status"},
        "operations": {"dependency_version", "verified_version", "procedure"},
    }[pack_id]
    missing = required - facts.keys()
    if missing:
        return [], [
            f"{subject}: rule plan needs {', '.join(sorted(missing))}. Check the source and extraction."
        ]

    def add(text: str, *relations: str) -> None:
        result.append(Plan(text, tuple(facts[key][1] for key in relations)))

    if pack_id == "project" and {"owner", "deadline"} <= facts.keys():
        try:
            date.fromisoformat(facts["deadline"][0])
        except ValueError:
            warnings.append(
                "Use an explicit ISO date (YYYY-MM-DD) for a rule-based release check-in."
            )
        else:
            add(
                f"Arrange a release check-in with {facts['owner'][0]} by {facts['deadline'][0]} for {subject}.",
                "owner",
                "deadline",
            )
    elif pack_id == "support" and {"refund_window_days", "request_age_days"} <= facts.keys():
        values = [
            re.fullmatch(r"(\d+)(?:\s+days?)?", facts[key][0], re.IGNORECASE)
            for key in ("refund_window_days", "request_age_days")
        ]
        if any(value is None for value in values):
            warnings.append("Refund rules require an explicit nonnegative number of days.")
        else:
            numbers = [int(value.group(1)) for value in values if value is not None]
            disposition = "within" if numbers[1] <= numbers[0] else "outside"
            add(
                f"{subject} is {disposition} the documented refund window. Staff review is required; do not issue payment.",
                "refund_window_days",
                "request_age_days",
            )
    elif pack_id == "tutoring" and {"topic", "assessment_independent"} <= facts.keys():
        independence = facts["assessment_independent"][0].casefold()
        if independence in {"assisted", "not independent", "no", "false"}:
            add(
                f"Assess {subject} independently on {facts['topic'][0]} before inferring mastery.",
                "topic",
                "assessment_independent",
            )
        elif "assessment_score" in facts:
            score = re.fullmatch(r"(\d{1,3})(?:%|/100)?", facts["assessment_score"][0])
            if score is None or int(score.group(1)) > 100:
                warnings.append("Practice rules require an assessment score between 0 and 100.")
            elif independence in {"independent", "yes", "true"} and int(score.group(1)) < 70:
                add(
                    f"Offer {subject} targeted practice on {facts['topic'][0]}, then reassess; mastery is not established.",
                    "topic",
                    "assessment_score",
                    "assessment_independent",
                )
        else:
            warnings.append(
                f"{subject}: an explicit assessment_score is needed before recommending score-based practice."
            )
    elif pack_id == "research" and {"result", "evidence_status"} <= facts.keys():
        if facts["evidence_status"][0].casefold() in {"invalidated", "retracted", "invalid"}:
            add(
                f"Recheck claims based on {subject}; the reported result must not be treated as established evidence.",
                "result",
                "evidence_status",
            )
        else:
            add(
                f"Seek independent validation of {subject}; a reported result alone does not establish a general claim.",
                "result",
                "evidence_status",
            )
    elif (
        pack_id == "operations"
        and {"dependency_version", "verified_version", "procedure"} <= facts.keys()
    ):
        if facts["dependency_version"][0].casefold() != facts["verified_version"][0].casefold():
            add(
                f"Revalidate the candidate procedure '{facts['procedure'][0]}' for {subject} on version "
                f"{facts['dependency_version'][0]}; it was verified on {facts['verified_version'][0]}.",
                "dependency_version",
                "verified_version",
                "procedure",
            )
        else:
            add(
                f"The remembered procedure for {subject} matches the recorded dependency version. "
                "Review and test it before execution; this app runs no commands.",
                "dependency_version",
                "verified_version",
                "procedure",
            )
    return result, warnings
