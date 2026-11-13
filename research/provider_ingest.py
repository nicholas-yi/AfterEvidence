"""Resumable ingestion of recorded episodes into gateway-backed memory providers.

Standard library only. Progress is appended to a JSONL ledger so an interrupted
ingestion resumes without storing any episode twice.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

GATEWAY = "http://127.0.0.1:8900"
WRITE_LOCK = Lock()


def post(
    path: str, body: dict[str, Any], url: str = GATEWAY, timeout: int = 1800
) -> dict[str, Any]:
    request = urllib.request.Request(
        url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def done(ledger: Path) -> set[tuple[str, str, str]]:
    if not ledger.exists():
        return set()
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
    return {(r["provider"], r["scope"], r["episode"]) for r in rows if r["status"] == "ok"}


def ingest_provider(
    provider: str, scope: str, episodes: list[dict], ledger: Path, gateway: str = GATEWAY
) -> list[dict]:
    finished = done(ledger)
    rows = []
    for episode in episodes:
        if (provider, scope, episode["id"]) in finished:
            continue
        started = time.monotonic()
        try:
            body = {"provider": provider, "scope": scope, "episode": episode}
            result = post("/ingest", body, url=gateway)
            row: dict[str, Any] = {"status": "ok", "result": result}
        except (urllib.error.URLError, TimeoutError) as error:
            detail = (
                error.read().decode()[:300] if isinstance(error, urllib.error.HTTPError) else ""
            )
            row = {"status": "error", "error": f"{error} {detail}".strip()}
        row.update(provider=provider, scope=scope, episode=episode["id"],
                   seconds=round(time.monotonic() - started, 1))  # fmt: skip
        with WRITE_LOCK, ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest recorded episodes into memory providers.")
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--providers", nargs="+", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--gateway", default=GATEWAY)
    args = parser.parse_args()
    episodes = json.loads(args.episodes.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=len(args.providers)) as pool:
        results = list(
            pool.map(
                lambda p: ingest_provider(p, args.scope, episodes, args.ledger, args.gateway),
                args.providers,
            )
        )
    print(
        json.dumps(
            {p: sum(r["status"] == "ok" for r in rows) for p, rows in zip(args.providers, results)}
        )
    )


if __name__ == "__main__":
    main()
