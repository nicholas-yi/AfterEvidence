"""Retrievers used inside benchmark episodes. Standard library only.

A retriever maps the customer's first message to memory text. Every condition
returns at most the caller's character cap (enforced in `tau_copilot`).

Specs:
- {"kind": "items", "path": ...}: precomputed items with embeddings, ranked by cosine
  similarity, multiplied by (0.5 + 0.5 * weight) when items carry sleep weights.
- {"kind": "gateway", "url": ..., "provider": ..., "scope": ...}: a third-party memory
  system behind the local memory gateway.
- {"kind": "text", "text": ...}: fixed text (tests and per-customer session memory).
"""

from __future__ import annotations

import json
import math
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

OLLAMA = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
PACK_CHARS = 2400


def embed(texts: Sequence[str], role: str, url: str = OLLAMA) -> list[list[float]]:
    """Embed with nomic-embed-text task prefixes (`document` or `query`)."""
    prefix = {"document": "search_document: ", "query": "search_query: "}[role]
    request = urllib.request.Request(
        url.rstrip("/") + "/api/embed",
        data=json.dumps({"model": EMBED_MODEL, "input": [prefix + t for t in texts]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())["embeddings"]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def pack(ranked: Sequence[tuple[str, str]], limit: int = PACK_CHARS) -> tuple[str, list[str]]:
    parts: list[str] = []
    ids: list[str] = []
    used = 0
    for identifier, text in ranked:
        entry = f"[{identifier}] {text.strip()}"
        room = limit - used - (2 if parts else 0)
        if room < 40:
            break
        if len(entry) > room:
            entry = entry[: room - 4] + " ..."
        parts.append(entry)
        ids.append(identifier)
        used += len(entry) + (2 if len(parts) > 1 else 0)
    return "\n\n".join(parts), ids


def rank_items(items: Sequence[dict[str, Any]], query_vector: Sequence[float]) -> list[dict]:
    scored = []
    for item in items:
        score = cosine(query_vector, item["embedding"])
        if "weight" in item:
            score *= 0.5 + 0.5 * float(item["weight"])
        scored.append((score, item["id"], item))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [dict(item, score=round(score, 4)) for score, _, item in scored]


def items_retriever(path: Path) -> Callable[[str], dict[str, Any]]:
    items = json.loads(path.read_text(encoding="utf-8"))["items"]

    def retrieve(query: str) -> dict[str, Any]:
        ranked = rank_items(items, embed([query], "query")[0])
        text, ids = pack([(item["id"], item["text"]) for item in ranked])
        return {
            "text": text,
            "ids": ids,
            "meta": {"scores": {i["id"]: i["score"] for i in ranked[: len(ids)]}},
        }

    return retrieve


def gateway_retriever(url: str, provider: str, scope: str) -> Callable[[str], dict[str, Any]]:
    def retrieve(query: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url.rstrip("/") + "/search",
            data=json.dumps({"provider": provider, "scope": scope, "query": query}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            value = json.loads(response.read())
        text, ids = pack([(f"{provider}-{n}", t) for n, t in enumerate(value["results"], 1)])
        return {
            "text": text,
            "ids": ids,
            "meta": {"provider": provider, "raw_count": len(value["results"])},
        }

    return retrieve


def build_retriever(spec: dict[str, object]) -> Callable[[str], dict[str, Any]]:
    kind = spec.get("kind")
    if kind == "items":
        return items_retriever(Path(str(spec["path"])))
    if kind == "gateway":
        return gateway_retriever(str(spec["url"]), str(spec["provider"]), str(spec["scope"]))
    if kind == "text":
        fixed = str(spec["text"])
        return lambda _query: {"text": fixed, "ids": ["text"], "meta": {}}
    raise ValueError(f"Unknown memory retriever kind: {kind!r}")
