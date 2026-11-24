from __future__ import annotations

import json
import math
from pathlib import Path


def summarize_micro(rows: list[dict[str, object]]) -> dict[str, object]:
    completed = [row for row in rows if row.get("event") == "copilot-request-completed"]
    call_ids = [row.get("call_id") for row in completed]
    if not completed or len(set(call_ids)) != len(call_ids):
        raise ValueError("Cost evidence must contain distinct completed session snapshots.")
    nano_total = 0.0
    inputs = 0
    outputs = 0
    provider_calls = 0
    for row in completed:
        metrics = row.get("metrics")
        if not isinstance(metrics, dict) or metrics.get("ai_credits_status") not in {
            "AiCreditsStatus.COMPLETE",
            "complete",
        }:
            raise ValueError(
                "AI-credit usage is incomplete or unavailable; do not substitute zero."
            )
        amount = metrics.get("total_nano_aiu")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(amount)
            or amount < 0
        ):
            raise ValueError("AI-credit total must be a finite nonnegative number.")
        nano_total += amount
        models = metrics.get("model_metrics")
        if not isinstance(models, dict) or not models:
            raise ValueError("Per-model token accounting is unavailable.")
        for model in models.values():
            if not isinstance(model, dict) or not isinstance(model.get("usage"), dict):
                raise ValueError("Invalid per-model token accounting.")
            usage = model["usage"]
            input_count, output_count = usage.get("input_tokens"), usage.get("output_tokens")
            request_usage = model.get("requests")
            if not isinstance(request_usage, dict):
                raise ValueError("Provider request accounting is unavailable.")
            requests = request_usage.get("count")
            if (
                type(input_count) is not int
                or type(output_count) is not int
                or type(requests) is not int
                or min(input_count, output_count, requests) < 0
            ):
                raise ValueError(
                    "Token counts and provider requests must be explicit nonnegative integers."
                )
            inputs += input_count
            outputs += output_count
            provider_calls += requests
    return {
        "completed_session_requests": len(completed),
        "provider_model_requests": provider_calls,
        "input_tokens": inputs,
        "output_tokens": outputs,
        "total_nano_ai_units": nano_total,
        "ai_credits": nano_total / 1e9,
        "usd_equivalent_at_0_01_per_ai_credit": nano_total / 1e11,
        "note": "Recorded Copilot allowance consumption, not a separately paid API invoice.",
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Summarize fresh-session SDK billing evidence without double counting."
    )
    parser.add_argument("journal", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.journal.read_text(encoding="utf-8").splitlines()]
    print(json.dumps(summarize_micro(rows), indent=2))


if __name__ == "__main__":
    main()
