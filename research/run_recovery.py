"""Run tooling used by `scripts/run-eval.ps1`: closing sessions cut by a dead process, and a
read-only integrity snapshot of every provider store.

`recover` applies the infrastructure rule after the fact, and only with an owner decision on
record: a session whose process died with a model call in flight (journal present, no report)
gets the in-flight call journaled as aborted (charged 1.0 by the ledger) and a report marking
the attempt an infrastructure failure, so the runner re-attempts it. Completed sessions and
existing journal lines are never changed; every recovery is appended to `recoveries.json`.

`snapshot` hashes each Mem0 store and counts Honcho rows per workspace (read-only transaction)
so a run can show it did not touch earlier studies' memory.

Usage:
  python -m research.run_recovery recover <run dir> <reason> <owner decision>
  python -m research.run_recovery snapshot <runs root> <output json>"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

CLOSED = ("copilot-request-completed", "copilot-request-aborted")
HONCHO_COUNTS = (
    "select w, (select count(*) from peers where workspace_name=w), "
    "(select count(*) from sessions where workspace_name=w), "
    "(select count(*) from messages where workspace_name=w), "
    "(select count(*) from documents where workspace_name=w), "
    "(select max(created_at) from messages where workspace_name=w) "
    "from (select name as w from workspaces) t order by w"
)


def recover(run: Path, reason: str, decision: str) -> list[dict[str, Any]]:
    if not decision.strip():
        raise ValueError("A recovery needs the owner's decision on record.")
    records = []
    for journal in sorted(run.glob("*-s*-a*.calls.jsonl")):
        report = journal.with_name(journal.name.replace(".calls.jsonl", ".json"))
        if report.exists():
            continue
        text = journal.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in text.splitlines() if line]
        if not rows:
            continue
        started = [r["call_id"] for r in rows if r.get("event") == "copilot-request-started"]
        closed = {r["call_id"] for r in rows if r.get("event") in CLOSED}
        missing = [call for call in started if call not in closed]
        before = hashlib.sha256(journal.read_bytes()).hexdigest()
        with journal.open("a", encoding="utf-8", newline="\n") as handle:
            for call in missing:
                note = f"no response; {reason}; journaled by the recovery step, cost unknown"
                row = {"event": "copilot-request-aborted", "call_id": call, "billing": note}
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        head = rows[0]
        attempt = int(journal.name.rsplit("-a", 1)[1].split(".")[0])
        closed_report = {
            "session": head.get("session"),
            "family": head.get("family"),
            "arm": head.get("arm"),
            "status": "failed",
            "error": f"{reason}; no response",
            "termination": None,
            "requests_started": len(started),
            "success": False,
            "attempt": attempt,
            "infra_failure": True,
        }
        report.write_text(json.dumps(closed_report, indent=2) + "\n", encoding="utf-8")
        records.append(
            {
                "session": journal.name.replace(".calls.jsonl", ""),
                "aborted_calls": missing,
                "journal_sha256_before_append": before,
            }
        )
    log = run / "recoveries.json"
    history = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
    history.append(
        {
            "when_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "owner_decision": decision,
            "reason": reason,
            "sessions": records,
            "code_changed": False,
        }
    )
    log.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return records


def store_hash(directory: Path) -> str:
    if not directory.exists():
        return "MISSING"
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:16].upper()


def snapshot(runs: Path, container: str = "honcho-database-1") -> dict[str, Any]:
    stores = [runs / "memory-study" / "gateway", *sorted(runs.glob("commitment/*/mem0"))]
    out: dict[str, Any] = {p.relative_to(runs).as_posix(): store_hash(p) for p in stores}
    command = [
        "docker",
        "exec",
        "-e",
        "PGOPTIONS=-c default_transaction_read_only=on",
        container,
        "psql",
        "-U",
        "postgres",
        "-At",
        "-c",
        HONCHO_COUNTS,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        ok = result.returncode == 0
        out["honcho"] = result.stdout.strip().splitlines() if ok else ["ERROR " + result.stderr]
    except (OSError, subprocess.TimeoutExpired) as failure:
        out["honcho"] = [f"ERROR {failure}"]
    return out


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[0] == "recover":
        print(json.dumps(recover(Path(argv[1]), argv[2], argv[3]), indent=2))
        return 0
    if len(argv) == 3 and argv[0] == "snapshot":
        result = snapshot(Path(argv[1]))
        Path(argv[2]).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=1))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
