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


def load_condition(directory: Path) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for path in sorted(directory.glob("task-*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        key = (str(report["task_id"]), str(report.get("seed")))
        report["_cost"] = journal_cost(path.with_suffix(".calls.jsonl"))
        result[key] = report
    return result


def compare(root: Path, conditions: list[str], baseline: str = "none") -> dict[str, Any]:
    data = {name: load_condition(root / name) for name in conditions}
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
    points = []
    for name, row in rows.items():
        if row["rate"] is None:
            continue
        cost = row["mean_episode_credits"] + extra_credits.get(name, 0.0)
        points.append((name, cost, row["rate"], row["wilson95"]))
    width, height, pad = 720, 440, 70
    max_cost = max(p[1] for p in points) * 1.15 or 1
    xs = lambda c: pad + (width - 2 * pad) * c / max_cost  # noqa: E731
    ys = lambda r: height - pad - (height - 2 * pad) * r  # noqa: E731
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="sans-serif" font-size="12">',
        f'<rect width="{width}" height="{height}" fill="white"/>',
        f'<text x="{width / 2}" y="24" text-anchor="middle" font-size="15">{title}</text>',
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="black"/>',
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="black"/>',
        f'<text x="{width / 2}" y="{height - 25}" text-anchor="middle">Mean AI credits per episode (actor + simulator + memory retrieval)</text>',
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" text-anchor="middle">Task success rate</text>',
    ]  # fmt: skip
    for tick in range(0, 11, 2):
        y = ys(tick / 10)
        parts.append(f'<line x1="{pad - 4}" y1="{y}" x2="{pad}" y2="{y}" stroke="black"/>'
                     f'<text x="{pad - 8}" y="{y + 4}" text-anchor="end">{tick / 10:.1f}</text>')  # fmt: skip
    for tick in range(5):
        cost = max_cost * tick / 4
        x = xs(cost)
        parts.append(
            f'<text x="{x}" y="{height - pad + 16}" text-anchor="middle">{cost:.2f}</text>'
        )
    for name, cost, rate, (low, high) in points:
        x, y = xs(cost), ys(rate)
        colour = "#888" if name == "none" else "#1f6feb"
        parts.append(
            f'<line x1="{x}" y1="{ys(low)}" x2="{x}" y2="{ys(high)}" stroke="{colour}" stroke-width="1"/>'
        )
        parts.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{colour}"/>')
        parts.append(f'<text x="{x + 8}" y="{y - 6}">{name}</text>')
    parts.append("</svg>")
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
    args = parser.parse_args()
    rows = compare(args.root, args.conditions)
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
        args.svg.write_text(pareto_svg(rows, extra, args.title), encoding="utf-8")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
