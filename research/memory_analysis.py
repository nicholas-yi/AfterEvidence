"""Analysis for the memory study. Standard library only.

Success = native ENV reward 1 on a normally terminated episode; every other status
(failed action contract, request cap, incomplete) counts as failure. Each memory
condition is compared with `none` on the same task and replicate (paired), using an
exact two-sided McNemar test with Holm correction across conditions.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from research.costing import summarize_micro


def success(report: dict[str, Any]) -> int:
    return int(report.get("status") == "scored" and report.get("native_env_reward") == 1)


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
            "mean_episode_credits": round(sum(e["credits"] for e in episodes) / n, 4) if n else None,
            "contract_failures": sum(r.get("status") == "failed" for r in reports.values()),
            "no_report": sum(r.get("status") == "no-report" for r in reports.values()),
            "capped": sum(r.get("status") == "budget-capped" for r in reports.values()),
            "memory_errors": sum(bool((r.get("memory") or {}).get("error")) for r in reports.values()),
            "mean_memory_chars": round(
                sum(len(str((r.get("memory") or {}).get("text") or "")) for r in reports.values()) / n, 1
            ) if n else None,
        }  # fmt: skip
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
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--conditions", nargs="+", required=True)
    parser.add_argument(
        "--retrieval-journals", type=Path, help="JSON map condition -> shim journal path"
    )
    parser.add_argument("--svg", type=Path)
    parser.add_argument("--title", default="Memory conditions: success vs cost")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--jobs", type=Path, help="Planned jobs; missing reports count as failures."
    )
    parser.add_argument("--exclude-missing", action="store_true", help="Sensitivity analysis.")
    args = parser.parse_args()
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
