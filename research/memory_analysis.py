"""Analysis for the memory study. Standard library only.

Success = native ENV reward 1 on a normally terminated episode; every other status
(failed action contract, request cap, incomplete) counts as failure. Each memory
condition is compared with `none` on the same task and replicate (paired), using an
exact two-sided McNemar test with Holm correction across conditions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from research.costing import summarize_micro

STUDY1_CONDITIONS = (
    "none",
    "raw",
    "consolidated",
    "sleep",
    "workflows",
    "mem0",
    "graphiti",
    "hindsight",
    "honcho",
)
STUDY2_CONDITIONS = ("none", "session", "mem0", "honcho")
EPISODE_FIELDS: tuple[str, ...] = (
    "study",
    "session",
    "task",
    "family",
    "condition",
    "replicate",
    "success",
    "failure_class",
    "requests_started",
    "actor_sim_credits",
    "provider_credits_allocated",
    "retrieved_chars",
)
RESAMPLES = 10_000


def success(report: dict[str, Any]) -> int:
    return int(report.get("status") == "scored" and report.get("native_env_reward") == 1)


def failure_class(report: dict[str, Any]) -> str:
    """Empty for success; otherwise wrong_final_db, contract, budget_cap, harness, or other."""
    status = report.get("status")
    if status == "scored":
        return "" if report.get("native_env_reward") == 1 else "wrong_final_db"
    if status == "failed" and "action" in str(report.get("error") or ""):
        return "contract"
    return {"budget-capped": "budget_cap", "no-report": "harness"}.get(str(status), "other")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(centre - half, 3), round(centre + half, 3))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial test on discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (len(ordered) - rank) * p))
        adjusted[name] = round(running, 4)
    return adjusted


def journal_cost(path: Path) -> dict[str, float]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    started = sum(r.get("event") == "copilot-request-started" for r in rows)
    completed = [r for r in rows if r.get("event") == "copilot-request-completed"]
    credits = summarize_micro(completed)["ai_credits"] if completed else 0.0
    return {"started": started, "completed": len(completed), "credits": float(str(credits))}


def load_condition(
    directory: Path, planned: list[dict[str, Any]] | None = None, include_missing: bool = True
) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for path in sorted(directory.glob("task-*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        key = (str(report["task_id"]), str(report.get("seed")))
        report["_cost"] = journal_cost(path.with_suffix(".calls.jsonl"))
        result[key] = report
    # Intent-to-treat: a planned episode that produced no report counts as a failure.
    for job in planned or []:
        key = (str(job["task"]), str(job.get("seed")))
        if key in result or not include_missing:
            continue
        journal = Path(str(job["output"])).with_suffix(".calls.jsonl")
        cost = (
            journal_cost(journal)
            if journal.exists()
            else {"started": 0, "completed": 0, "credits": 0.0}
        )
        result[key] = {
            "task_id": job["task"],
            "seed": job.get("seed"),
            "status": "no-report",
            "_cost": cost,
        }
    return result


def compare(
    root: Path,
    conditions: list[str],
    baseline: str = "none",
    jobs: list[dict[str, Any]] | None = None,
    include_missing: bool = True,
) -> dict[str, Any]:
    data = {
        name: load_condition(
            root / name, [j for j in jobs or [] if j.get("condition") == name], include_missing
        )
        for name in conditions
    }
    base = data[baseline]
    rows: dict[str, Any] = {}
    pvalues: dict[str, float] = {}
    for name in conditions:
        reports = data[name]
        k = sum(success(r) for r in reports.values())
        n = len(reports)
        episodes = [r["_cost"] for r in reports.values()]
        row: dict[str, Any] = {
            "episodes": n,
            "successes": k,
            "rate": round(k / n, 3) if n else None,
            "wilson95": wilson(k, n),
            "mean_requests": round(sum(e["started"] for e in episodes) / n, 2) if n else None,
            "mean_episode_credits": round(sum(e["credits"] for e in episodes) / n, 4)
            if n
            else None,
            "contract_failures": sum(r.get("status") == "failed" for r in reports.values()),
            "no_report": sum(r.get("status") == "no-report" for r in reports.values()),
            "capped": sum(r.get("status") == "budget-capped" for r in reports.values()),
            "memory_errors": sum(
                bool((r.get("memory") or {}).get("error")) for r in reports.values()
            ),
            "mean_memory_chars": round(
                sum(len(str((r.get("memory") or {}).get("text") or "")) for r in reports.values())
                / n,
                1,
            )
            if n
            else None,
        }
        if name != baseline:
            pairs = [key for key in reports if key in base]
            b = sum(success(reports[key]) and not success(base[key]) for key in pairs)
            c = sum(success(base[key]) and not success(reports[key]) for key in pairs)
            row.update(paired=len(pairs), wins=b, losses=c, mcnemar_p=round(mcnemar_exact(b, c), 4))
            pvalues[name] = row["mcnemar_p"]
        rows[name] = row
    for name, adjusted in holm(pvalues).items():
        rows[name]["holm_p"] = adjusted
    return rows


def _episode_row(
    study: str,
    session: str,
    task: str,
    family: str,
    condition: str,
    replicate: str,
    report: dict[str, Any],
    provider_share: float,
) -> dict[str, Any]:
    memory = report.get("memory")
    return {
        "study": study,
        "session": session,
        "task": task,
        "family": family,
        "condition": condition,
        "replicate": replicate,
        "success": success(report),
        "failure_class": failure_class(report),
        "requests_started": report["_cost"]["started"],
        "actor_sim_credits": round(report["_cost"]["credits"], 9),
        "provider_credits_allocated": round(provider_share, 9),
        "retrieved_chars": len(str(memory.get("text") or "")) if isinstance(memory, dict) else "",
    }


def export_episodes(root: Path, out: Path) -> int:
    """Public per-episode table from the private study directory: no transcripts, prompts,
    tool payloads, customer names, account data, or provider state. Provider calls cannot be
    attributed to single episodes, so each condition's provider total is split evenly."""
    rows: list[dict[str, Any]] = []
    jobs = json.loads((root / "study1" / "jobs.json").read_text(encoding="utf-8"))
    shims = root / "shims"
    for condition in STUDY1_CONDITIONS:
        reports = load_condition(
            root / "study1" / condition, [j for j in jobs if j["condition"] == condition]
        )
        journal = shims / f"{condition}-study1.calls.jsonl"
        total = journal_cost(journal)["credits"] if journal.exists() else 0.0
        for (task, seed), report in sorted(
            reports.items(), key=lambda kv: (int(kv[0][0]), kv[0][1])
        ):
            rows.append(
                _episode_row(
                    "study1", "test", task, "", condition, seed, report, total / len(reports)
                )
            )
    families = json.loads((root / "study2-families.json").read_text(encoding="utf-8"))
    family_of, session_of = {}, {}
    for index, sessions in enumerate(families.values(), start=1):
        for position, item in enumerate(sessions):
            family_of[str(item["task"])] = f"F{index:02d}"
            session_of[str(item["task"])] = "first" if position == 0 else "later"
    for condition in STUDY2_CONDITIONS:
        reports = load_condition(root / "study2" / condition)
        journal = shims / f"{condition}-study2.calls.jsonl"
        total = journal_cost(journal)["credits"] if journal.exists() else 0.0
        later = sum(session_of[task] == "later" for task, _ in reports)
        for (task, seed), report in sorted(reports.items(), key=lambda kv: int(kv[0][0])):
            share = total / later if session_of[task] == "later" else 0.0
            rows.append(
                _episode_row(
                    "study2",
                    session_of[task],
                    task,
                    family_of[task],
                    condition,
                    seed,
                    report,
                    share,
                )
            )
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, EPISODE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def read_episodes(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["success"] = int(row["success"])
        row["requests_started"] = int(row["requests_started"])
        for key in ("actor_sim_credits", "provider_credits_allocated"):
            row[key] = float(row[key])
    return rows


def cluster_effect(clusters: dict[str, list[int]], seed: int = 0) -> dict[str, Any]:
    """Post-hoc paired difference with a cluster bootstrap 95% CI and a cluster sign-flip p.

    `clusters` maps a task (Study 1) or family (Study 2) to its per-pair differences
    (condition success minus no-memory success)."""
    keys = sorted(clusters)
    pairs = sum(len(v) for v in clusters.values())
    estimate = sum(sum(v) for v in clusters.values()) / pairs
    rng = random.Random(seed)
    boots = []
    for _ in range(RESAMPLES):
        sample = rng.choices(keys, k=len(keys))
        boots.append(sum(sum(clusters[k]) for k in sample) / sum(len(clusters[k]) for k in sample))
    boots.sort()
    sums = [sum(clusters[k]) for k in keys]
    observed = abs(sum(sums))
    rng = random.Random(seed)
    extreme = sum(
        abs(sum(s if rng.random() < 0.5 else -s for s in sums)) >= observed - 1e-12
        for _ in range(RESAMPLES)
    )
    return {
        "difference": round(estimate, 4),
        "ci95": (
            round(boots[int(0.025 * RESAMPLES)], 4),
            round(boots[int(0.975 * RESAMPLES) - 1], 4),
        ),
        "bootstrap_se": round(statistics.stdev(boots), 4),
        "sign_flip_p": round((extreme + 1) / (RESAMPLES + 1), 4),
        # Unrounded, for display: 4-decimal values can round the wrong way at one decimal.
        "exact": (estimate, boots[int(0.025 * RESAMPLES)], boots[int(0.975 * RESAMPLES) - 1]),
    }


def tables_from_csv(path: Path) -> dict[str, Any]:
    """Recompute every reported Study 1 and Study 2 table, plus post-hoc bounds, from the CSV."""
    rows = read_episodes(path)
    result: dict[str, Any] = {}
    for study, conditions, cluster_field in (
        ("study1", STUDY1_CONDITIONS, "task"),
        ("study2", STUDY2_CONDITIONS, "family"),
    ):
        selected = [r for r in rows if r["study"] == study and r["session"] != "first"]
        by = {
            c: {(r["task"], r["replicate"]): r for r in selected if r["condition"] == c}
            for c in conditions
        }
        base = by["none"]
        table: dict[str, Any] = {}
        pvalues: dict[str, float] = {}
        for name in conditions:
            episodes = list(by[name].values())
            n, k = len(episodes), sum(r["success"] for r in episodes)
            row: dict[str, Any] = {
                "episodes": n,
                "successes": k,
                "rate": round(k / n, 3),
                "wilson95": wilson(k, n),
                "mean_requests": round(sum(r["requests_started"] for r in episodes) / n, 2),
                "mean_episode_credits": round(sum(r["actor_sim_credits"] for r in episodes) / n, 4),
                "provider_credits_per_episode": round(
                    sum(r["provider_credits_allocated"] for r in episodes) / n, 4
                ),
                "failures": dict(Counter(r["failure_class"] for r in episodes if not r["success"])),
            }
            if name != "none":
                keys = [key for key in by[name] if key in base]
                wins = sum(by[name][x]["success"] and not base[x]["success"] for x in keys)
                losses = sum(base[x]["success"] and not by[name][x]["success"] for x in keys)
                clusters: dict[str, list[int]] = {}
                for x in keys:
                    clusters.setdefault(base[x][cluster_field], []).append(
                        by[name][x]["success"] - base[x]["success"]
                    )
                row.update(
                    paired=len(keys),
                    wins=wins,
                    losses=losses,
                    mcnemar_p=round(mcnemar_exact(wins, losses), 4),
                    post_hoc=cluster_effect(clusters),
                )
                pvalues[name] = row["mcnemar_p"]
            table[name] = row
        for name, adjusted in holm(pvalues).items():
            table[name]["holm_p"] = adjusted
        result[study] = table
    return result


def pareto_svg(rows: dict[str, Any], extra_credits: dict[str, float], title: str) -> str:
    """Two-panel row chart: success rate with Wilson 95% interval, and credits per episode."""
    names = [n for n, r in rows.items() if r["rate"] is not None]
    costs = {n: rows[n]["mean_episode_credits"] + extra_credits.get(n, 0.0) for n in names}
    row_h, top, label_w, panel_w, gap = 34, 70, 120, 330, 60
    width = label_w + 2 * panel_w + gap + 40
    height = top + row_h * len(names) + 60
    left_x, right_x = label_w, label_w + panel_w + gap
    max_cost = max(costs.values()) * 1.1

    def rate_x(rate: float) -> float:
        return left_x + panel_w * rate

    def cost_x(cost: float) -> float:
        return right_x + panel_w * cost / max_cost

    bottom = top + row_h * len(names)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'font-family="sans-serif" font-size="13">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="16">{title}</text>',
        f'<text x="{left_x + panel_w / 2}" y="52" text-anchor="middle">'
        "Task success rate (95% interval)</text>",
        f'<text x="{right_x + panel_w / 2}" y="52" text-anchor="middle">AI credits per episode</text>',
    ]
    for tick in range(0, 11, 2):
        x = rate_x(tick / 10)
        parts.append(f'<line x1="{x}" y1="{top - 8}" x2="{x}" y2="{bottom}" stroke="#eee"/>')
        parts.append(f'<text x="{x}" y="{bottom + 18}" text-anchor="middle">{tick / 10:.1f}</text>')
    for tick in range(5):
        value = max_cost * tick / 4
        x = cost_x(value)
        parts.append(f'<line x1="{x}" y1="{top - 8}" x2="{x}" y2="{bottom}" stroke="#eee"/>')
        parts.append(f'<text x="{x}" y="{bottom + 18}" text-anchor="middle">{value:.1f}</text>')
    base = rows.get("none", {}).get("rate")
    if base is not None:
        x = rate_x(base)
        parts.append(
            f'<line x1="{x}" y1="{top - 8}" x2="{x}" y2="{bottom}" stroke="#888" '
            'stroke-dasharray="4 3"/>'
        )
    for index, name in enumerate(names):
        y = top + row_h * index + row_h / 2
        row = rows[name]
        low, high = row["wilson95"]
        colour = "#666" if name == "none" else "#1f6feb"
        run_end = cost_x(row["mean_episode_credits"])
        parts += [
            f'<text x="{label_w - 10}" y="{y + 4}" text-anchor="end">{name}</text>',
            f'<line x1="{rate_x(low)}" y1="{y}" x2="{rate_x(high)}" y2="{y}" '
            f'stroke="{colour}" stroke-width="2"/>',
            f'<circle cx="{rate_x(row["rate"])}" cy="{y}" r="5" fill="{colour}"/>',
            f'<text x="{rate_x(high) + 6}" y="{y + 4}" font-size="11">'
            f"{row['successes']}/{row['episodes']}</text>",
            f'<rect x="{right_x}" y="{y - 8}" width="{run_end - right_x}" height="16" '
            f'fill="{colour}" opacity="0.8"/>',
        ]
        if extra_credits.get(name):
            parts.append(
                f'<rect x="{run_end}" y="{y - 8}" width="{cost_x(costs[name]) - run_end}" '
                'height="16" fill="#f0883e"/>'
            )
        parts.append(
            f'<text x="{cost_x(costs[name]) + 6}" y="{y + 4}" font-size="11">'
            f"{costs[name]:.2f}</text>"
        )
    parts += [
        f'<text x="{left_x}" y="{height - 14}" font-size="11">dashed line: no-memory rate</text>',
        f'<text x="{right_x}" y="{height - 14}" font-size="11">'
        "blue: actor + simulator; orange: provider retrieval</text>",
        "</svg>",
    ]
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse memory-study results.")
    parser.add_argument("--csv", type=Path, help="Recompute Study 1/2 tables from the public CSV.")
    parser.add_argument("--export-csv", type=Path, help="Write the public CSV from --root.")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--conditions", nargs="+")
    parser.add_argument(
        "--retrieval-journals", type=Path, help="JSON map condition -> shim journal path"
    )
    parser.add_argument("--svg", type=Path)
    parser.add_argument("--title", default="Memory conditions: success vs cost")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--jobs", type=Path, help="Planned jobs; missing reports count as failures."
    )
    parser.add_argument("--exclude-missing", action="store_true", help="Sensitivity analysis.")
    args = parser.parse_args()
    if args.csv:
        print(json.dumps(tables_from_csv(args.csv), indent=1))
        return
    if args.export_csv:
        if not args.root:
            parser.error("--export-csv needs --root (the private memory-study directory).")
        print(f"wrote {export_episodes(args.root, args.export_csv)} episodes")
        return
    if not (args.root and args.conditions and args.out):
        parser.error("--root, --conditions, and --out are required for journal analysis.")
    jobs = json.loads(args.jobs.read_text(encoding="utf-8")) if args.jobs else None
    rows = compare(args.root, args.conditions, jobs=jobs, include_missing=not args.exclude_missing)
    extra: dict[str, float] = {}
    if args.retrieval_journals:
        for name, path in json.loads(args.retrieval_journals.read_text(encoding="utf-8")).items():
            cost = journal_cost(Path(path))
            episodes = rows.get(name, {}).get("episodes") or 1
            extra[name] = cost["credits"] / episodes
            rows[name]["retrieval_credits_total"] = round(cost["credits"], 4)
            rows[name]["retrieval_requests_total"] = cost["started"]
    args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    if args.svg:
        args.svg.write_text(pareto_svg(rows, extra, args.title), encoding="utf-8", newline="\n")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
