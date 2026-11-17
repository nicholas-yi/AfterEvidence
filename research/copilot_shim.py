"""Local OpenAI-compatible endpoint that routes memory-provider LLM calls through Copilot.

Third-party memory systems (Mem0, Graphiti, Hindsight, Honcho) call an OpenAI-style
API for extraction and reasoning. This shim answers those calls with the same
isolated, journaled `CopilotBackend` used by the benchmark actor, so every provider
runs on one model and its usage is metered per instance under a hard request cap.
Embeddings are forwarded to a local Ollama model and never billed.

Tool calls and JSON output are produced through Copilot structured responses; a
malformed reply gets one counted re-ask, then the request fails visibly.
"""

import argparse
import asyncio
import json
import time
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

TOOL_REPLY_SCHEMA_KEYS = ("kind", "content", "tool_calls")


def text_of(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return json.dumps(content)


def split_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system = "\n\n".join(
        text_of(m.get("content")) for m in messages if m.get("role") in {"system", "developer"}
    )
    rest = []
    for message in messages:
        role = message.get("role")
        if role in {"system", "developer"}:
            continue
        entry: dict[str, Any] = {"role": role, "content": text_of(message.get("content"))}
        if message.get("tool_calls"):
            entry["tool_calls"] = [
                {
                    "id": call.get("id"),
                    "name": call.get("function", {}).get("name"),
                    "arguments": call.get("function", {}).get("arguments"),
                }
                for call in message["tool_calls"]
            ]
        if message.get("tool_call_id"):
            entry["tool_call_id"] = message["tool_call_id"]
        rest.append(entry)
    return system, rest


def tool_schema(names: list[str], force: bool) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(TOOL_REPLY_SCHEMA_KEYS),
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["tool_calls"] if force else ["message", "tool_calls"],
            },
            "content": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "arguments_json"],
                    "properties": {
                        "name": {"type": "string", "enum": names},
                        "arguments_json": {"type": "string"},
                    },
                },
            },
        },
    }


def parse_tool_reply(text: str, names: set[str], force: bool) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != set(TOOL_REPLY_SCHEMA_KEYS):
        raise ValueError("Tool reply must contain exactly kind, content and tool_calls.")
    if value["kind"] == "message":
        if force or not str(value["content"]).strip():
            raise ValueError("A nonempty message is only allowed when tools are optional.")
        return {"role": "assistant", "content": value["content"]}
    calls = []
    if value["kind"] != "tool_calls" or not value["tool_calls"]:
        raise ValueError("A tool reply needs at least one tool call.")
    for call in value["tool_calls"]:
        if call.get("name") not in names:
            raise ValueError(f"Unknown tool {call.get('name')!r}.")
        arguments = json.loads(call["arguments_json"])
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must decode to a JSON object.")
        calls.append(
            {
                "id": "call_" + uuid.uuid4().hex[:24],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(arguments)},
            }
        )
    return {"role": "assistant", "content": value["content"] or None, "tool_calls": calls}


def strict_schema(schema: Any) -> Any:
    """Close every object schema, as Copilot structured output requires.

    Returns None when a schema deliberately allows open objects; the caller then asks
    for JSON by instruction and validates the reply instead.
    """
    if isinstance(schema, list):
        items = [strict_schema(item) for item in schema]
        return _OPEN if any(item is _OPEN for item in items) else items
    if not isinstance(schema, dict):
        return schema
    result: dict[str, Any] = {}
    for key, value in schema.items():
        converted = (
            strict_schema(value)
            if key not in {"enum", "const", "required", "default", "examples"}
            else value
        )
        if converted is _OPEN:
            return _OPEN
        result[key] = converted
    is_object = result.get("type") == "object" or "properties" in result
    if is_object:
        extra = result.get("additionalProperties")
        if extra not in (None, False):
            return _OPEN
        result["additionalProperties"] = False
    return result


_OPEN = object()


def build_request(
    body: dict[str, Any],
) -> tuple[str, str, dict[str, Any] | None, str, set[str]]:
    """Return (system, prompt, response schema, mode, tool names) for one chat body."""
    system, rest = split_messages(list(body.get("messages") or []))
    prompt = json.dumps({"conversation": rest}, ensure_ascii=False)
    tools = [t.get("function", t) for t in body.get("tools") or []]
    choice = body.get("tool_choice")
    if tools and choice != "none":
        force = choice == "required" or isinstance(choice, dict)
        if isinstance(choice, dict):
            wanted = choice.get("function", {}).get("name")
            tools = [t for t in tools if t.get("name") == wanted] or tools
        instructions = (
            "You are the assistant in the conversation. Reply with one JSON object: "
            '{"kind":"message","content":"...","tool_calls":[]} to answer in text, or '
            '{"kind":"tool_calls","content":"","tool_calls":[{"name":"...","arguments_json":"{...}"}]} '
            "to call tools. arguments_json is a JSON-encoded object matching the tool parameters."
            + (" You must call a tool." if force else "")
            + "\nTOOLS:\n"
            + json.dumps(tools, ensure_ascii=False)
        )
        schema = tool_schema([t["name"] for t in tools], force)
        mode = "force" if force else "tools"
        return (
            f"{system}\n\n{instructions}".strip(),
            prompt,
            schema,
            mode,
            {t["name"] for t in tools},
        )
    fmt = body.get("response_format") or {}
    if fmt.get("type") == "json_schema":
        raw = (fmt.get("json_schema") or {}).get("schema") or {"type": "object"}
        closed = strict_schema(raw)
        if closed is _OPEN or closed is None:
            guide = (
                "Reply with one JSON object only, no prose or code fences, matching this JSON schema:\n"
                + json.dumps(raw, ensure_ascii=False)
            )
            return f"{system}\n\n{guide}".strip(), prompt, None, "json", set()
        guide = "Reply with one JSON object that matches the required schema."
        return f"{system}\n\n{guide}".strip(), prompt, closed, "json", set()
    if fmt.get("type") == "json_object":
        guide = "Reply with one JSON object only, no prose or code fences."
        return f"{system}\n\n{guide}".strip(), prompt, None, "json", set()
    guide = (
        "You are the assistant in the conversation above. Reply with the next assistant message."
    )
    return f"{system}\n\n{guide}".strip(), prompt, None, "text", set()


def strip_fences(text: str) -> str:
    return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def usage_of(metrics: object) -> dict[str, int]:
    inputs = outputs = 0
    if isinstance(metrics, dict):
        for model in (metrics.get("model_metrics") or {}).values():
            usage = model.get("usage") or {}
            inputs += int(usage.get("input_tokens") or 0)
            outputs += int(usage.get("output_tokens") or 0)
    return {"prompt_tokens": inputs, "completion_tokens": outputs, "total_tokens": inputs + outputs}


async def complete_chat(backend: Any, body: dict[str, Any]) -> dict[str, Any]:
    system, prompt, schema, mode, names = build_request(body)
    error = ""
    for attempt in range(2):
        note = (
            f"\n\nYour previous reply was invalid: {error}. Reply again correctly."
            if attempt
            else ""
        )
        text = await backend.complete(system + note, prompt, schema)
        try:
            if mode in {"tools", "force"}:
                message = parse_tool_reply(strip_fences(text), names, mode == "force")
            elif mode == "json":
                cleaned = strip_fences(text)
                json.loads(cleaned)
                message = {"role": "assistant", "content": cleaned}
            else:
                message = {"role": "assistant", "content": text}
            break
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)[:300]
            backend.write("shim-reask" if attempt == 0 else "shim-invalid", error=error)
    else:
        raise ValueError(f"Copilot reply stayed invalid after one re-ask: {error}")
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "copilot"),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }
        ],
        "usage": usage_of(backend.last_metrics),
    }


def embed(ollama: str, model: str, body: dict[str, Any]) -> dict[str, Any]:
    raw = body.get("input")
    inputs = raw if isinstance(raw, list) else [raw]
    request = urllib.request.Request(
        ollama.rstrip("/") + "/v1/embeddings",
        data=json.dumps({"model": model, "input": inputs}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        value = json.loads(response.read())
    value["model"] = body.get("model", model)
    return value


def create_app(args: argparse.Namespace):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse, StreamingResponse

    from research.copilot_backend import (
        CopilotBackend,
        isolated_client,
        quota_problem,
        quota_snapshot,
    )

    class ShimBackend(CopilotBackend):
        max_request_limit = 16000

    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app):
        client = isolated_client()
        await client.start()
        problem = quota_problem(await quota_snapshot(client))
        if problem:  # refuse to serve before any billed request
            await client.stop()
            raise RuntimeError(problem)
        journal = args.journal.open("x", encoding="utf-8", newline="\n")
        backend = ShimBackend(
            client,
            args.model,
            args.journal.parent / "shim-sessions",
            journal,
            request_limit=args.requests,
        )
        backend.write(
            "shim-started", label=args.label, model=args.model, request_limit=args.requests
        )
        state.update(backend=backend, client=client, journal=journal)
        try:
            yield
        finally:
            backend.write("shim-stopped", requests=backend.calls)
            journal.close()
            await client.stop()

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        # The shim spends Copilot allowance; every call must carry the per-run token.
        if args.token and request.headers.get("authorization") != f"Bearer {args.token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": args.model, "object": "model"}]}

    @app.get("/health")
    async def health():
        backend = state["backend"]
        return {"requests": backend.calls, "limit": backend.limit}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        try:
            result = await complete_chat(state["backend"], body)
        except Exception as exc:  # surfaced to the provider as an API error, never hidden
            state["backend"].write("shim-error", error=f"{type(exc).__name__}: {exc}"[:500])
            raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc
        if body.get("stream"):
            chunk = dict(result, object="chat.completion.chunk")
            chunk["choices"] = [
                {
                    "index": 0,
                    "delta": result["choices"][0]["message"],
                    "finish_reason": result["choices"][0]["finish_reason"],
                }
            ]

            async def events():
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")
        return JSONResponse(result)

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        body = await request.json()
        return JSONResponse(await asyncio.to_thread(embed, args.ollama, args.embed_model, body))

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenAI-compatible Copilot shim for memory providers."
    )
    parser.add_argument("--label", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--requests", type=int, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--model", default="claude-haiku-5.5")
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--embed-model", default="nomic-embed-text")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--token", required=True, help="Bearer token callers must present.")
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_app(args), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
