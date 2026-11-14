"""README figures, regenerated from the public per-episode CSV. Standard library only.

    python -m research.figures            # rewrite docs/figures/*-{light,dark}.svg
    python -m research.figures --check    # exit 1 if a committed figure is stale

Each figure has a light and a dark variant for GitHub's <picture> / prefers-color-scheme
pattern. Design follows Rougier, Droettboom & Bourne (2014), "Ten Simple Rules for Better
Figures", and Wilke, "Fundamentals of Data Visualization": a takeaway title, direct labels
instead of legends, no chartjunk, and the colour-blind-safe Okabe-Ito palette.
"""

from __future__ import annotations

import argparse
import sys
from html import escape
from pathlib import Path
from typing import Any

from research.memory_analysis import STUDY1_CONDITIONS, STUDY2_CONDITIONS, tables_from_csv

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "research" / "data" / "memory-study-v1-episodes.csv"
OUT = ROOT / "docs" / "figures"
POWER_MULTIPLIER = 2.80  # z(0.975) + z(0.80): smallest effect detectable with 80% power
NAMES = {
    "none": "No memory", "raw": "Raw transcripts", "consolidated": "One-pass lessons",
    "sleep": "Sleep-style lessons", "workflows": "Workflows", "mem0": "Mem0",
    "graphiti": "Graphiti", "hindsight": "Hindsight", "honcho": "Honcho",
    "session": "Session transcripts",
}  # fmt: skip
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#1f2328", "muted": "#59636e", "grid": "#d8dee4",
              "accent": "#0072B2", "second": "#E69F00", "band": "#59636e"},
    "dark": {"bg": "#0d1117", "ink": "#e6edf3", "muted": "#9198a1", "grid": "#30363d",
             "accent": "#56B4E9", "second": "#E69F00", "band": "#9198a1"},
}  # fmt: skip
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def _n(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _pp(value: float) -> str:
    text = f"{value * 100:+.1f}"
    return "0.0" if text in ("+0.0", "-0.0") else text.replace("-", "\u2212")


class Svg:
    def __init__(self, width: int, height: int, theme: dict[str, str]) -> None:
        self.w, self.h, self.t = width, height, theme
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="{FONT}" font-size="13">',
            f'<rect width="{width}" height="{height}" fill="{theme["bg"]}"/>',
        ]

    def text(self, x: float, y: float, s: str, *, anchor: str = "start", size: float = 13,
             weight: str = "normal", color: str | None = None) -> None:  # fmt: skip
        self.parts.append(
            f'<text x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}" font-size="{_n(size)}" '
            f'font-weight="{weight}" fill="{color or self.t["ink"]}">{escape(s)}</text>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str,
             width: float = 1, dash: str = "") -> None:  # fmt: skip
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
            f'stroke="{color}" stroke-width="{_n(width)}"{extra}/>'
        )

    def rect(self, x: float, y: float, w: float, h: float, color: str, opacity: float = 1) -> None:
        self.parts.append(
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(max(w, 0))}" height="{_n(h)}" '
            f'fill="{color}" fill-opacity="{_n(opacity)}"/>'
        )

    def circle(self, x: float, y: float, r: float, color: str) -> None:
        self.parts.append(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" fill="{color}"/>')

    def render(self) -> str:
        return "\n".join([*self.parts, "</svg>"]) + "\n"


def memory_effects(tables: dict[str, Any], theme: dict[str, str]) -> str:
    """Forest plot: paired success difference vs no memory, with detectable-effect bands."""
    studies = [
        ("Study 1 \u00b7 memory of other customers (26 tasks \u00d7 2 runs)", "study1",
         [c for c in STUDY1_CONDITIONS if c != "none"]),
        ("Study 2 \u00b7 memory of the same customer (22 later sessions, 16 customers)", "study2",
         [c for c in STUDY2_CONDITIONS if c != "none"]),
    ]  # fmt: skip
    lo, hi, row, label_w, plot_w = -0.40, 0.30, 26, 190, 520
    width = label_w + plot_w + 190
    rows = sum(len(c) for *_, c in studies)
    height = 92 + rows * row + len(studies) * 44 + 54
    svg, t = Svg(width, height, theme), theme

    def x(value: float) -> float:
        return label_w + plot_w * (value - lo) / (hi - lo)

    svg.text(16, 30, "Every memory condition\u2019s effect on task success is consistent with zero",
             size=16, weight="bold")  # fmt: skip
    svg.text(16, 52, "Change in success rate vs. the same tasks without memory, percentage points",
             color=t["muted"])  # fmt: skip
    y = 80
    for title, study, conditions in studies:
        effects = [tables[study][c]["post_hoc"] for c in conditions]
        ses = [e["bootstrap_se"] for e in effects]
        inner, outer = POWER_MULTIPLIER * min(ses), POWER_MULTIPLIER * max(ses)
        top, bottom = y + 22, y + 22 + len(conditions) * row
        svg.text(16, y + 12, title, weight="bold")
        svg.text(width - 16, y + 12,
                 f"shaded: |effect| below {inner * 100:.0f}\u2013{outer * 100:.0f} pts is not reliably detectable",
                 anchor="end", size=11, color=t["muted"])  # fmt: skip
        svg.rect(x(-outer), top, x(outer) - x(-outer), bottom - top, t["band"], 0.10)
        svg.rect(x(-inner), top, x(inner) - x(-inner), bottom - top, t["band"], 0.14)
        svg.line(x(0), top - 4, x(0), bottom, t["muted"], 1.2)
        for index, (condition, effect) in enumerate(zip(conditions, effects)):
            cy = top + row * index + row / 2
            difference, low, high = effect["exact"]
            svg.text(label_w - 12, cy + 4, NAMES[condition], anchor="end")
            svg.line(x(low), cy, x(high), cy, t["accent"], 2.2)
            svg.circle(x(difference), cy, 5, t["accent"])
            svg.text(x(hi) + 10, cy + 4,
                     f"{_pp(difference)}  ({_pp(low)}, {_pp(high)})",
                     size=12, color=t["muted"])  # fmt: skip
        y = bottom + 22
    axis = y - 8
    svg.line(label_w, axis, label_w + plot_w, axis, t["grid"])
    for tick in range(-40, 31, 10):
        svg.line(x(tick / 100), axis, x(tick / 100), axis + 5, t["muted"])
        label = f"{tick:+d}".replace("-", "\u2212") if tick else "0"
        svg.text(x(tick / 100), axis + 20, label, anchor="middle", size=12, color=t["muted"])
    svg.text(x(-0.36), axis + 40, "\u2190 memory hurt", size=12, color=t["muted"])
    svg.text(x(0.26), axis + 40, "memory helped \u2192", anchor="end", size=12, color=t["muted"])
    return svg.render()


def study1_success_cost(tables: dict[str, Any], theme: dict[str, str]) -> str:
    """Two panels: success rate with Wilson 95% interval, and AI credits per episode."""
    rows = tables["study1"]
    names = list(STUDY1_CONDITIONS)
    row, top, label_w, panel_w, gap = 30, 92, 170, 300, 70
    width = label_w + 2 * panel_w + gap + 70
    height = top + row * len(names) + 64
    svg, t = Svg(width, height, theme), theme
    left, right = label_w, label_w + panel_w + gap
    costs = {n: rows[n]["mean_episode_credits"] + rows[n]["provider_credits_per_episode"]
             for n in names}  # fmt: skip
    max_cost = 3.0

    def rate_x(value: float) -> float:
        return left + panel_w * (value - 0.5) / 0.5

    def cost_x(value: float) -> float:
        return right + panel_w * value / max_cost

    bottom = top + row * len(names)
    svg.text(16, 30, "Success stayed between 73% and 83% for every condition, at similar cost",
             size=16, weight="bold")  # fmt: skip
    svg.text(16, 52, "Study 1: 52 paired episodes per condition", color=t["muted"])
    svg.text(left, 80, "Task success (95% interval)", weight="bold")
    svg.text(right, 80, "AI credits per episode", weight="bold")
    for tick in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        svg.line(rate_x(tick), top - 6, rate_x(tick), bottom, t["grid"])
        svg.text(rate_x(tick), bottom + 18, f"{tick:.0%}", anchor="middle", size=12,
                 color=t["muted"])  # fmt: skip
    for tick in (0, 1, 2, 3):
        svg.line(cost_x(tick), top - 6, cost_x(tick), bottom, t["grid"])
        svg.text(cost_x(tick), bottom + 18, str(tick), anchor="middle", size=12, color=t["muted"])
    base = rows["none"]["rate"]
    svg.line(rate_x(base), top - 6, rate_x(base), bottom, t["muted"], 1.2, "4 3")
    for index, name in enumerate(names):
        cy = top + row * index + row / 2
        r = rows[name]
        color = t["muted"] if name == "none" else t["accent"]
        low, high = r["wilson95"]
        svg.text(label_w - 12, cy + 4, NAMES[name], anchor="end")
        svg.line(rate_x(low), cy, rate_x(high), cy, color, 2.2)
        svg.circle(rate_x(r["rate"]), cy, 5, color)
        svg.text(rate_x(high) + 6, cy + 4, f"{r['successes']}/{r['episodes']}", size=12,
                 color=t["muted"])  # fmt: skip
        run = r["mean_episode_credits"]
        svg.rect(right, cy - 8, cost_x(run) - right, 16, color, 0.85)
        if r["provider_credits_per_episode"]:
            svg.rect(cost_x(run), cy - 8, cost_x(costs[name]) - cost_x(run), 16, t["second"])
        svg.text(cost_x(costs[name]) + 6, cy + 4, f"{costs[name]:.2f}", size=12, color=t["muted"])
    svg.text(left, height - 14, "dashed line: success without memory", size=12, color=t["muted"])
    svg.rect(right, height - 24, 12, 12, t["second"])
    svg.text(right + 18, height - 14, "extra model calls the memory system made at retrieval",
             size=12, color=t["muted"])  # fmt: skip
    return svg.render()


FIGURES = {"memory-effects": memory_effects, "study1-success-cost": study1_success_cost}


def render_all() -> dict[Path, str]:
    tables = tables_from_csv(CSV)
    return {
        OUT / f"{name}-{variant}.svg": make(tables, THEMES[variant])
        for name, make in FIGURES.items()
        for variant in THEMES
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate README figures from the CSV.")
    parser.add_argument("--check", action="store_true", help="Fail if committed figures are stale.")
    args = parser.parse_args()
    stale = []
    for path, svg in render_all().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != svg:
                stale.append(path.name)
        else:
            path.write_text(svg, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("stale figures: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
