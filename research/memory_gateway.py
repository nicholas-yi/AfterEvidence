"""Local gateway exposing third-party memory systems behind one small HTTP interface.

Runs in the separate providers environment. Every provider keeps its own default
pipeline; only its LLM and embedding endpoints are redirected to its own metered
Copilot shim (embeddings go to local nomic-embed-text). Operations:

- POST /ingest {provider, scope, episode}: store one recorded episode.
- POST /search {provider, scope, query[, reasoning_level]}: memory strings for one query
  (reasoning_level: per-request Honcho dialectic level, overriding the config).
- POST /delete {provider, scope, episode_id}: remove one source episode.
- POST /dump {provider, scope}: list stored memory strings (lifecycle probes).
- POST /status {provider}: isolation settings in force; for Honcho, waits for a drained
  deriver queue and returns its counts.

Optional config keys isolate later pilots from the memory-study stores: "state" (Mem0
directory), "honcho_workspace" (workspace for "customer:" scopes) and
"honcho_reasoning_level" (null = the server default). Absent keys keep v1 behaviour.
Episodes without an "outcome" get no outcome line. Optional "times" (ISO strings, one per line)
become Honcho message created_at values; Mem0 has no equivalent in its open-source release.

Scopes starting with "customer:" are per-customer (same-customer study); any other
scope is a shared agent-level store (cross-customer study).
"""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

STATE = Path(__file__).resolve().parent / "runs" / "memory-study" / "gateway"
CONFIG: dict[str, Any] = {}


def state() -> Path:
    return Path(CONFIG.get("state") or STATE)


def shim(provider: str) -> str:
    return CONFIG["shims"][provider]


def turns(episode: dict[str, Any]) -> list[tuple[str, str]]:
    result = [(speaker, text) for speaker, text in episode["lines"]]
    if "outcome" in episode:
        result.append(
            ("agent", f"[outcome] Automatic check for this conversation: {episode['outcome']}.")
        )
    return result


def transcript(episode: dict[str, Any]) -> str:
    names = {"customer": "Customer", "agent": "Agent", "tool": "Agent tool"}
    return "\n".join(f"{names[s]}: {t}" for s, t in turns(episode))


def safe(scope: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", scope)


class Mem0Store:
    def __init__(self) -> None:
        self.instances: dict[str, Any] = {}

    def memory(self, scope: str):
        # One embedded Qdrant per process (Mem0 shares a migrations store); scopes are
        # separated by Mem0's own agent_id / user_id filters.
        del scope
        if "shared" not in self.instances:
            from mem0 import Memory

            base, token = shim("mem0"), CONFIG["token"]
            self.instances["shared"] = Memory.from_config({
                "llm": {"provider": "openai", "config": {
                    "model": CONFIG["model"], "openai_base_url": base, "api_key": token, "temperature": 0}},
                "embedder": {"provider": "openai", "config": {
                    "model": "nomic-embed-text", "openai_base_url": base, "api_key": token, "embedding_dims": 768}},
                "vector_store": {"provider": "qdrant", "config": {
                    "path": str(state() / "mem0-qdrant" / "bank"), "collection_name": "ae",
                    "embedding_model_dims": 768, "on_disk": True}},
                "history_db_path": str(state() / "mem0-history-bank.db"),
            })  # fmt: skip
        return self.instances["shared"]

    @staticmethod
    def owner(scope: str) -> dict[str, str]:
        if scope.startswith("customer:"):
            return {"user_id": scope.removeprefix("customer:")}
        return {"agent_id": scope}

    def ingest(self, scope: str, episode: dict[str, Any]) -> dict[str, Any]:
        roles = {"customer": "user", "agent": "assistant", "tool": "assistant"}
        messages = [
            {"role": roles[s], "content": ("[tool] " if s == "tool" else "") + t}
            for s, t in turns(episode)
        ]
        owner = self.owner(scope)
        result = self.memory(scope).add(
            messages,
            run_id=episode["id"],
            metadata={"episode": episode["id"]},
            user_id=owner.get("user_id"),
            agent_id=owner.get("agent_id"),
        )
        return {"events": len((result or {}).get("results", []))}

    def search(self, scope: str, query: str) -> list[str]:
        # Library-default search (top_k 20); mem0 2.2.1 ignored the limit=10 that v1 passed.
        found = self.memory(scope).search(query, filters=self.owner(scope))
        return [item["memory"] for item in found.get("results", [])]

    def delete(self, scope: str, episode_id: str) -> dict[str, Any]:
        owner = self.owner(scope)
        self.memory(scope).delete_all(
            run_id=episode_id, user_id=owner.get("user_id"), agent_id=owner.get("agent_id")
        )
        return {"deleted_run": episode_id}

    def dump(self, scope: str) -> list[str]:
        found = self.memory(scope).get_all(filters=self.owner(scope), limit=1000)
        return [item["memory"] for item in found.get("results", [])]


class GraphitiStore:
    def __init__(self) -> None:
        self.client = None
        self.uuids_path = STATE / "graphiti-episodes.json"
        self.uuids: dict[str, str] = (
            json.loads(self.uuids_path.read_text()) if self.uuids_path.exists() else {}
        )

    async def graph(self):
        if self.client is None:
            from graphiti_core import Graphiti
            from graphiti_core.cross_encoder.client import CrossEncoderClient
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

            class OrderPreserving(CrossEncoderClient):
                # Default search uses reciprocal-rank fusion; no logprob reranker is configured.
                async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
                    return [(p, 1.0 / (i + 1)) for i, p in enumerate(passages)]

            base, token, model = shim("graphiti"), CONFIG["token"], CONFIG["model"]
            llm = OpenAIGenericClient(
                LLMConfig(api_key=token, model=model, small_model=model, base_url=base)
            )
            embedder = OpenAIEmbedder(
                OpenAIEmbedderConfig(
                    api_key=token,
                    embedding_model="nomic-embed-text",
                    embedding_dim=768,
                    base_url=base,
                )
            )
            neo = CONFIG["neo4j"]
            self.client = Graphiti(
                neo["uri"],
                neo["user"],
                neo["password"],
                llm_client=llm,
                embedder=embedder,
                cross_encoder=OrderPreserving(),
            )
            await self.client.build_indices_and_constraints()
        return self.client

    async def ingest(self, scope: str, episode: dict[str, Any]) -> dict[str, Any]:
        from graphiti_core.nodes import EpisodeType

        graph = await self.graph()
        result = await graph.add_episode(
            name=episode["id"], episode_body=transcript(episode),
            source_description="retail customer-service conversation",
            reference_time=datetime.now(timezone.utc), source=EpisodeType.message, group_id=safe(scope),
        )  # fmt: skip
        self.uuids[f"{scope}|{episode['id']}"] = result.episode.uuid
        self.uuids_path.write_text(json.dumps(self.uuids))
        return {"nodes": len(result.nodes), "edges": len(result.edges)}

    async def search(self, scope: str, query: str) -> list[str]:
        graph = await self.graph()
        edges = await graph.search(query, group_ids=[safe(scope)], num_results=10)
        return [edge.fact for edge in edges]

    async def delete(self, scope: str, episode_id: str) -> dict[str, Any]:
        graph = await self.graph()
        await graph.remove_episode(self.uuids.pop(f"{scope}|{episode_id}"))
        self.uuids_path.write_text(json.dumps(self.uuids))
        return {"deleted_episode": episode_id}

    async def dump(self, scope: str) -> list[str]:
        graph = await self.graph()
        records, _, _ = await graph.driver.execute_query(
            "MATCH ()-[e:RELATES_TO]->() WHERE e.group_id = $g AND e.invalid_at IS NULL RETURN e.fact AS fact",
            g=safe(scope),
        )
        return [record["fact"] for record in records]


class HindsightStore:
    """Uses the client's native async API on the gateway loop (its sync wrappers are loop-bound)."""

    def __init__(self) -> None:
        from hindsight_client import Hindsight

        self.client = Hindsight(base_url=CONFIG["hindsight"], timeout=600)
        self.banks: set[str] = set()

    async def bank(self, scope: str) -> str:
        bank_id = "ae-" + safe(scope)
        if bank_id not in self.banks:
            try:
                await self.client.acreate_bank(bank_id=bank_id, name=bank_id)
            except Exception:  # already exists
                pass
            self.banks.add(bank_id)
        return bank_id

    async def ingest(self, scope: str, episode: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.aretain(
            await self.bank(scope), transcript(episode), document_id=episode["id"],
            context="retail customer-service conversation",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )  # fmt: skip
        return {"success": bool(getattr(response, "success", True))}

    async def search(self, scope: str, query: str) -> list[str]:
        response = await self.client.arecall(await self.bank(scope), query, max_tokens=1024)
        return [result.text for result in response.results]

    async def delete(self, scope: str, episode_id: str) -> dict[str, Any]:
        await self.client.documents.delete_document(
            bank_id=await self.bank(scope), document_id=episode_id
        )
        return {"deleted_document": episode_id}

    async def dump(self, scope: str) -> list[str]:
        response = await self.client.alist_memories(await self.bank(scope), limit=1000)
        return [item.get("text", "") if isinstance(item, dict) else getattr(item, "text", "")
                for item in response.items]  # fmt: skip


class HonchoStore:
    def __init__(self) -> None:
        from honcho import Honcho

        self.clients: dict[str, Any] = {}
        self.factory = lambda workspace: Honcho(
            base_url=CONFIG["honcho"], workspace_id=workspace, timeout=600
        )

    def workspace(self, scope: str):
        customer = CONFIG.get("honcho_workspace", "ae-customer")
        name = customer if scope.startswith("customer:") else "ae-" + safe(scope)
        if name not in self.clients:
            self.clients[name] = self.factory(name)
        return self.clients[name]

    @staticmethod
    def customer_id(scope: str, episode: dict[str, Any]) -> str:
        if scope.startswith("customer:"):
            return safe(scope.removeprefix("customer:"))
        return "customer-" + safe(episode["id"])

    def wait(self, honcho: Any, limit: float = 900) -> dict[str, int]:
        # Work is enqueued asynchronously after add_messages, so require two empty polls.
        deadline = time.monotonic() + limit
        empty = 0
        time.sleep(5)
        while time.monotonic() < deadline:
            status = honcho.queue_status()
            busy = (status.pending_work_units or 0) + (status.in_progress_work_units or 0)
            empty = empty + 1 if busy == 0 else 0
            if empty >= 2:
                return {k: getattr(status, f"{k}_work_units", 0) or 0
                        for k in ("total", "completed", "in_progress", "pending")}  # fmt: skip
            time.sleep(3)
        raise TimeoutError("Honcho deriver queue did not drain.")

    def ingest(self, scope: str, episode: dict[str, Any]) -> dict[str, Any]:
        honcho = self.workspace(scope)
        agent, customer = honcho.peer("agent"), honcho.peer(self.customer_id(scope, episode))
        session = honcho.session(safe(episode["id"]), peers=[agent, customer])
        speakers = {"customer": customer, "agent": agent, "tool": agent}
        times = episode.get("times") or []
        session.add_messages([
            speakers[s].message(("[tool] " if s == "tool" else "") + t,
                                **({"created_at": times[i]} if i < len(times) else {}))
            for i, (s, t) in enumerate(turns(episode))
        ])  # fmt: skip
        return {"session": session.id, "queue": self.wait(honcho)}

    def search(self, scope: str, query: str, level: str | None = None) -> list[str]:
        honcho = self.workspace(scope)
        if scope.startswith("customer:"):
            peer = honcho.peer(self.customer_id(scope, {}))
            question = f"What is known about this customer that is relevant to their new request? Request: {query}"
        else:
            peer = honcho.peer("agent")
            question = (
                "What has this support agent learned from past conversations that is relevant to "
                f"handling this new customer request? Request: {query}"
            )
        level = level or CONFIG.get("honcho_reasoning_level", "low")
        answer = peer.chat(question, reasoning_level=level) if level else peer.chat(question)
        text = getattr(answer, "content", answer)
        return [str(text)] if text else []

    def delete(self, scope: str, episode_id: str) -> dict[str, Any]:
        self.workspace(scope).session(safe(episode_id)).delete()
        return {"deleted_session": episode_id}

    def dump(self, scope: str) -> list[str]:
        honcho = self.workspace(scope)
        peer = (
            honcho.peer("agent")
            if not scope.startswith("customer:")
            else honcho.peer(self.customer_id(scope, {}))
        )
        return [str(peer.representation(max_conclusions=100))]


STORES: dict[str, Any] = {}


def store(provider: str):
    factories = {
        "mem0": Mem0Store,
        "graphiti": GraphitiStore,
        "hindsight": HindsightStore,
        "honcho": HonchoStore,
    }
    if provider not in factories:
        raise HTTPException(status_code=400, detail=f"Unknown provider {provider!r}")
    if provider not in STORES:
        STORES[provider] = factories[provider]()
    return STORES[provider]


async def call(provider: str, method: str, *args: Any) -> Any:
    target = getattr(store(provider), method)
    if asyncio.iscoroutinefunction(target):
        return await target(*args)
    return await asyncio.to_thread(target, *args)


app = FastAPI()
LOCKS: dict[str, asyncio.Lock] = {}


def lock(provider: str) -> asyncio.Lock:
    return LOCKS.setdefault(provider, asyncio.Lock())


@app.post("/ingest")
async def ingest(request: Request):
    body = await request.json()
    async with lock(body["provider"]):
        return {"result": await call(body["provider"], "ingest", body["scope"], body["episode"])}


@app.post("/search")
async def search(request: Request):
    body = await request.json()
    level = (body["reasoning_level"],) if body.get("reasoning_level") else ()
    return {"results": await call(body["provider"], "search", body["scope"], body["query"], *level)}


@app.post("/delete")
async def delete(request: Request):
    body = await request.json()
    async with lock(body["provider"]):
        return {"result": await call(body["provider"], "delete", body["scope"], body["episode_id"])}


@app.post("/status")
async def status(request: Request):
    body = await request.json()
    result: dict[str, Any] = {"state": str(state().resolve()),
                              "honcho_workspace": CONFIG.get("honcho_workspace", "ae-customer"),
                              "honcho_reasoning_level": CONFIG.get("honcho_reasoning_level", "low")}  # fmt: skip
    if body.get("provider") == "honcho":
        honcho = store("honcho")
        result["queue"] = await asyncio.to_thread(honcho.wait, honcho.workspace("customer:"))
    return result


@app.post("/dump")
async def dump(request: Request):
    body = await request.json()
    return {"results": await call(body["provider"], "dump", body["scope"])}


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Memory-provider gateway for the memory study.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8900)
    args = parser.parse_args()
    CONFIG.update(json.loads(args.config.read_text(encoding="utf-8")))
    state().mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
