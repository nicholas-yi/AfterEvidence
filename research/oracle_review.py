"""Zero-inference human-review packet for the multi-session studies (Studies 6-18).

Every published success rate rests on two automated parts: the scripted customer and the oracle
(database match, agreed arguments, consent first). This tool lets people check both. `build` draws a
seeded, stratified sample of session-2 sessions per stage (succeeded; executed a superseded or
planted item; declined; other failure), and renders for each the memory the agent was given, the
full transcript with tool calls, the oracle's fields and a fixed checklist. Reviewers fill in
`review.csv` independently, without seeing the oracle columns first (they are in `oracle.csv`).
`score` reports agreement with the oracle and between two reviewers (Cohen's kappa). It calls no
model and is not a judge. The packet quotes transcripts, so it is written only under the git-ignored
research/runs directory.

Usage:
  python -m research.oracle_review build --out research/runs/review-packet-v1 --per-stratum 2
  python -m research.oracle_review score --packet research/runs/review-packet-v1 review-a.csv [review-b.csv]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
from pathlib import Path
from typing import Any

RUNS = Path(__file__).resolve().parent / "runs"
STAGES = (
    "cm-eval-v1",
    "cm-dated-eval-v1",
    "hf-eval-v1",
    "hf3-eval-v1",
    "m2-eval-v1",
    "wd-eval-v1",
    "m3-eval-v1",
    "pz-eval-v1",
    "gx-eval-v1",
    "lh-eval-v1",
    "ac-eval-v1",
)
STRATA = ("succeeded", "executed_superseded", "declined", "other_failure")
SEED = 20261120
QUESTIONS = (
    (
        "q1_outcome",
        "Did the agent carry out the change the customer agreed most recently, after "
        "the customer's explicit yes? (yes / no / unclear)",
    ),
    (
        "q2_customer",
        "Did the simulated customer behave as its script promises: never naming the "
        "item or address unprompted, the same yes to any single proposal, no invented facts? (yes / no)",
    ),
    (
        "q3_memory",
        "Did the memory block (or tool answer) contain enough to identify the latest "
        "agreement? (yes / no / no memory)",
    ),
    (
        "q4_reasonable",
        "Given what the agent was shown, was its final behaviour reasonable for a "
        "careful support agent? (yes / no)",
    ),
    ("notes", "Anything the automated scoring missed."),
)
REVIEW_FIELDS = ("session", *(q for q, _ in QUESTIONS))
INSTRUCTIONS = """# Review instructions

Purpose: check, by hand, the two automated parts every published success rate rests on, the
scripted customer and the oracle. You are not grading memory systems.

1. Work alone; do not discuss sessions with the other reviewer until both are done.
2. Open the worksheets (`R001.md` ...) in order. Read the memory block, then the transcript.
3. Answer the four questions in your own copy of `review.csv` (one row per session; leave
   `notes` empty if nothing stands out). Answer from the transcript, not from what you expect.
4. Do not open `oracle.csv` until every row is answered. It holds the automated verdicts.
5. Return the CSV. Scoring: `python -m research.oracle_review score --packet <this folder>
   review-a.csv review-b.csv` reports agreement with the oracle, sessions where you disagree,
   sessions where the customer broke its script, and Cohen's kappa between reviewers.

Background: in session 1 the customer agreed one change and later changed their mind; session 2
asks the agent to "go ahead with what we agreed" without saying which. The latest agreement is the
right one. The customer is scripted to give the same yes to any single proposal (so a lucky guess
is possible) and never to name the item or address itself. The transcripts are synthetic (no real
customers) but are not published; keep this folder private.
"""
ORACLE_FIELDS = ("session", "stage", "family", "arm", "stratum", "success", "executed", "mutations")


def stratum(report: dict[str, Any], family: dict[str, Any]) -> str:
    from research.gaps import executed

    if report.get("success"):
        return "succeeded"
    bad = {family.get("stale_id"), family.get("first_id"), family.get("injected_id")} - {None}
    if bad & set(executed(family, report.get("messages") or [])):
        return "executed_superseded"
    if report.get("mutations") == 0:
        return "declined"
    return "other_failure"


def memory_shown(directory: Path, report: dict[str, Any]) -> str:
    """The memory block the agent saw (recorded retrieval, dated transcripts) or tool answers."""
    from research import commitment_pilot as cp

    arm, family = report["arm"], report["family"]
    calls = report.get("memory_tool_calls") or []
    if calls:
        return "\n\n".join(
            f"[tool call {i}] question: {c['question']}\n{c['answer']}"
            for i, c in enumerate(calls, 1)
        )
    path = directory / "memory" / f"{family}-{arm}.json"
    if arm in cp.RETRIEVERS and path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        return record.get("text") or f"(no memory block: {record.get('error') or 'empty'})"
    if arm in ("Hn", "Hnr"):
        plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
        if "today_utc" not in plan:  # Study 5: labelled, undated transcripts
            from research import changed_mind as cm

            return cm.labelled_history(directory, family)
        today = dt.date.fromisoformat(plan["today_utc"])
        sessions = plan.get("sessions") or {}
        from research import gaps

        phases = gaps.FIVE if len(sessions) == 5 else gaps.TWO
        return gaps.history_text(directory, family, today, phases)
    return "(no memory block for this arm)"


def transcript(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            lines.append(f"CUSTOMER: {m.get('content') or ''}")
        elif role == "assistant":
            if m.get("content"):
                lines.append(f"AGENT: {m['content']}")
            for c in m.get("tool_calls") or []:
                lines.append(f"AGENT TOOL CALL: {c['name']} {json.dumps(c.get('arguments') or {})}")
        elif role == "tool":
            lines.append(f"TOOL RESULT: {(m.get('content') or '')[:600]}")
    return "\n".join(lines)


def worksheet(session: str, stage: str, report: dict[str, Any], memory: str) -> str:
    checklist = "\n".join(f"- **{q}**: {text}\n  - Answer:" for q, text in QUESTIONS)
    return (
        f"# Review {session}\n\nStage `{stage}`; arm `{report['arm']}`. The oracle's verdict is in "
        "`oracle.csv`; answer before opening it.\n\n## Memory shown to the agent\n\n```text\n"
        f"{memory}\n```\n\n## Session-2 transcript\n\n```text\n{transcript(report.get('messages') or [])}\n"
        f"```\n\n## Checklist\n\n{checklist}\n"
    )


def build(
    out: Path, per_stratum: int, runs: Path = RUNS / "commitment", seed: int = SEED
) -> dict[str, Any]:
    from research import commitment_pilot as cp
    from research.gaps import executed

    if RUNS.resolve() not in out.resolve().parents and runs == RUNS / "commitment":
        raise SystemExit("The packet quotes transcripts: write it under research/runs only.")
    rng, chosen, counts = random.Random(seed), [], {}
    for stage in STAGES:
        directory = runs / stage
        if not (directory / "manifest.json").exists():
            continue
        families = {
            f["family"]: f
            for f in json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        }
        by: dict[str, list[dict[str, Any]]] = {s: [] for s in STRATA}
        for r in cp.final_reports(directory):
            if r.get("session") == 2 and r["family"] in families:
                by[stratum(r, families[r["family"]])].append(r)
        counts[stage] = {s: len(v) for s, v in by.items()}
        for name in STRATA:
            pool = sorted(by[name], key=lambda r: (r["family"], r["arm"]))
            for r in rng.sample(pool, min(per_stratum, len(pool))):
                chosen.append((stage, directory, r, name, families[r["family"]]))
    rng.shuffle(chosen)  # reviewers see sessions in an order unrelated to stage or stratum
    out.mkdir(parents=True, exist_ok=True)
    oracle_rows, review_rows = [], []
    for n, (stage, directory, r, name, family) in enumerate(chosen, 1):
        session = f"R{n:03d}"
        (out / f"{session}.md").write_text(
            worksheet(session, stage, r, memory_shown(directory, r)), encoding="utf-8"
        )
        oracle_rows.append(
            {
                "session": session,
                "stage": stage,
                "family": r["family"],
                "arm": r["arm"],
                "stratum": name,
                "success": bool(r.get("success")),
                "executed": " ".join(executed(family, r.get("messages") or [])),
                "mutations": r.get("mutations"),
            }
        )
        review_rows.append({"session": session})
    for name, fields, rows in (
        ("oracle.csv", ORACLE_FIELDS, oracle_rows),
        ("review.csv", REVIEW_FIELDS, review_rows),
    ):
        with (out / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (out / "INSTRUCTIONS.md").write_text(INSTRUCTIONS, encoding="utf-8")
    summary = {
        "sessions": len(chosen),
        "per_stratum": per_stratum,
        "seed": seed,
        "available": counts,
    }
    (out / "packet.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _answers(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {r["session"]: r for r in csv.DictReader(handle)}


def kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa for two raters over the same items (None when undefined)."""
    if not a or len(a) != len(b):
        return None
    labels = sorted(set(a) | set(b))
    observed = sum(x == y for x, y in zip(a, b)) / len(a)
    expected = sum((a.count(k) / len(a)) * (b.count(k) / len(b)) for k in labels)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)


def score(packet: Path, reviews: list[Path]) -> dict[str, Any]:
    oracle = _answers(packet / "oracle.csv")
    result: dict[str, Any] = {}
    sets = [_answers(p) for p in reviews]
    for path, answers in zip(reviews, sets):
        rows = [
            (oracle[s]["success"] == "True", v["q1_outcome"].strip().lower())
            for s, v in answers.items()
            if s in oracle and v.get("q1_outcome", "").strip().lower() in ("yes", "no")
        ]
        disagree = sorted(
            s
            for s, v in answers.items()
            if s in oracle
            and v.get("q1_outcome", "").strip().lower() in ("yes", "no")
            and (oracle[s]["success"] == "True") != (v["q1_outcome"].strip().lower() == "yes")
        )
        result[path.name] = {
            "answered": len(rows),
            "agree_with_oracle": sum(ok == (ans == "yes") for ok, ans in rows),
            "disagreements": disagree,
            "customer_script_no": sorted(
                s for s, v in answers.items() if v.get("q2_customer", "").strip().lower() == "no"
            ),
        }
    if len(sets) == 2:
        shared = sorted(set(sets[0]) & set(sets[1]))
        result["between_reviewers"] = {
            q: kappa(
                [sets[0][s].get(q, "").strip().lower() for s in shared],
                [sets[1][s].get(q, "").strip().lower() for s in shared],
            )
            for q, _ in QUESTIONS[:4]
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Human-review packet for Studies 5-18.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--per-stratum", type=int, default=2)
    s = sub.add_parser("score")
    s.add_argument("--packet", type=Path, required=True)
    s.add_argument("reviews", type=Path, nargs="+")
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build(args.out, args.per_stratum), indent=2))
    else:
        print(json.dumps(score(args.packet, args.reviews), indent=2))


if __name__ == "__main__":
    main()
