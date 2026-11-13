from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from .runner import run_suite, verify_report
from .application import Application
from .app_evaluation import evaluate_application
from .packs import PACKS
from .ollama import Ollama, OllamaError
from .store import StateChanged, Store
from .web import serve


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local-first memory application and offline lifecycle tests; no cloud calls."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run generated symbolic development worlds.")
    run.add_argument("--worlds-per-topology", type=int, default=10)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--output", type=Path)
    verify = commands.add_parser("verify", help="Replay a report with the current source/runtime.")
    verify.add_argument("report", type=Path)
    app = commands.add_parser("serve", help="Open the local Ollama-backed memory application.")
    app.add_argument("--db", type=Path, default=Path("data") / "memory.sqlite3")
    app.add_argument("--port", type=int, default=8765)
    doctor = commands.add_parser(
        "doctor", help="Check access to an already-installed local Ollama model."
    )
    evaluation = commands.add_parser(
        "evaluate-app", help="Run five synthetic development cases with real local Qwen."
    )
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--packs", nargs="+", choices=[pack.id for pack in PACKS])
    for command in (app, doctor, evaluation):
        command.add_argument("--model", default="qwen3.5:4b")
        command.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            client = Ollama(args.model, args.ollama_url)
            selected = client.selected_model()
            print(
                json.dumps(
                    {"endpoint": client.base_url, "selected": selected, "external_spend_usd": 0},
                    indent=2,
                )
            )
            return 0
        if args.command == "serve":
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
            serve(Application(Store(args.db), Ollama(args.model, args.ollama_url)), args.port)
            return 0
        if args.command == "evaluate-app":
            journal_path = args.output.with_suffix(".calls.jsonl")
            if args.output.exists() or journal_path.exists():
                raise ValueError(
                    "Evaluation output already exists. Choose a new path; no model calls were made."
                )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with journal_path.open("x", encoding="utf-8", newline="\n") as journal:
                evaluation_report = evaluate_application(
                    Ollama(args.model, args.ollama_url),
                    journal,
                    tuple(args.packs) if args.packs is not None else None,
                )
            with args.output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(evaluation_report, indent=2, sort_keys=True) + "\n")
            print(
                json.dumps(
                    {
                        key: evaluation_report[key]
                        for key in (
                            "status",
                            "cases_passed_structural_checks",
                            "cases_total",
                            "seconds",
                        )
                    },
                    indent=2,
                )
            )
            return 0 if evaluation_report["status"] == "passed" else 1
        if args.command == "verify":
            value: object = json.loads(args.report.read_text(encoding="utf-8"))
            verify_report(value)
            print("Verified deterministic replay. Offline development only; no vendor claims.")
            return 0
        report = run_suite(args.worlds_per_topology, args.seed)
        rendered = json.dumps(report, indent=2, sort_keys=True)
        if args.output is None:
            print(rendered)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(rendered + "\n")
            print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, OllamaError, StateChanged, sqlite3.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
