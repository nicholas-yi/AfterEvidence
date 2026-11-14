"""Study 2 analysis: memory conditions vs no memory on the same later sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.memory_analysis import holm, load_condition, mcnemar_exact, success, wilson


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse the same-customer study.")
    parser.add_argument("--root", type=Path, default=Path("research/runs/memory-study/study2"))
    parser.add_argument("--families", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    families = json.loads(args.families.read_text(encoding="utf-8")).values()
    later = [(s["task"], "1") for family in families for s in family[1:]]
    first = [(family[0]["task"], "1") for family in families]
    data = {c: load_condition(args.root / c) for c in ("none", "session", "mem0", "honcho")}
    none = data["none"]
    rows: dict[str, dict] = {}
    pvalues: dict[str, float] = {}
    for name, reports in data.items():
        keys = [k for k in later if k in reports]
        k = sum(success(reports[key]) for key in keys)
        row: dict = {"later_sessions": len(keys), "successes": k, "rate": round(k / len(keys), 3) if keys else None,
                     "wilson95": wilson(k, len(keys)),
                     "mean_requests": round(sum(reports[x]["_cost"]["started"] for x in keys) / len(keys), 2) if keys else None,
                     "mean_episode_credits": round(sum(reports[x]["_cost"]["credits"] for x in keys) / len(keys), 4) if keys else None,
                     "memory_errors": sum(bool((reports[x].get("memory") or {}).get("error")) for x in keys)}  # fmt: skip
        if name != "none":
            pairs = [key for key in keys if key in none]
            wins = sum(success(reports[x]) and not success(none[x]) for x in pairs)
            losses = sum(success(none[x]) and not success(reports[x]) for x in pairs)
            row.update(
                paired=len(pairs),
                wins=wins,
                losses=losses,
                mcnemar_p=round(mcnemar_exact(wins, losses), 4),
            )
            pvalues[name] = row["mcnemar_p"]
        rows[name] = row
    for name, adjusted in holm(pvalues).items():
        rows[name]["holm_p"] = adjusted
    first_done = [k for k in first if k in none]
    rows["none_first_sessions"] = {
        "sessions": len(first_done),
        "successes": sum(success(none[k]) for k in first_done),
    }
    args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
