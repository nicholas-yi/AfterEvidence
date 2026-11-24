"""Light test helpers: no benchmark, SDK or provider needed."""

from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path
from typing import Any


def require(*modules: str) -> None:
    """Skip the importing test module unless the pinned research dependencies are installed."""
    missing = [m for m in modules if importlib.util.find_spec(m) is None]
    if missing:
        raise unittest.SkipTest(
            f"needs {', '.join(missing)} (pinned research setup, research/README.md)"
        )


BENCHMARK = ("tau2", "loguru")
slow = unittest.skipUnless(
    os.environ.get("AFTEREVIDENCE_SLOW") == "1", "slow dry pass; set AFTEREVIDENCE_SLOW=1"
)


def billed(call_id: int) -> dict[str, Any]:
    usage = {"usage": {"input_tokens": 1, "output_tokens": 1}, "requests": {"count": 1}}
    return {
        "event": "copilot-request-completed",
        "call_id": call_id,
        "metrics": {
            "ai_credits_status": "complete",
            "total_nano_aiu": 1e8,
            "model_metrics": {"m": usage},
        },
    }


def shim_journal(directory: Path, label: str, cap: int, *rows: dict[str, Any]) -> None:
    (directory / "shims").mkdir(parents=True, exist_ok=True)
    events = [{"event": "shim-started", "label": label, "request_limit": cap}, *rows]
    (directory / "shims" / f"{label}.calls.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )
