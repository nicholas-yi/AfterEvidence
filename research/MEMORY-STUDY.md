# Memory study runbook

How to rebuild the memory-study stack and rerun or audit it. The design and
analysis plan are fixed in [PROTOCOL-MEMORY.md](PROTOCOL-MEMORY.md); results are in
[RESULTS.md](RESULTS.md#memory-study-v1). Everything here runs locally. The only
billed calls are Copilot requests, all journaled and counted toward one cap.

## Architecture

```text
benchmark episode (research.tau_copilot, research venv)
  actor + user simulator -> Copilot SDK (isolated sessions, journaled)
  memory retrieval, once, from the customer's first message
     |- internal conditions: research.memory_retrievers (stdlib, local embeddings)
     '- providers: HTTP -> research.memory_gateway (providers venv)
           |- Mem0 (in process, Qdrant on disk)
           |- Graphiti (in process) -> Neo4j container
           |- Hindsight container
           '- Honcho API + deriver containers (Postgres/pgvector, Redis)
provider LLM calls -> research.copilot_shim (one per provider, metered, token-protected)
embeddings -> Ollama nomic-embed-text (local, not billed)
```

The shim translates OpenAI-style chat, JSON-mode, JSON-schema, and tool calls into
Copilot structured responses. It closes object schemas as Copilot requires, falls
back to instruction-only JSON for open schemas, and gives one counted re-ask for a
malformed reply. Every request needs a per-run bearer token.

## Prerequisites

- The pinned research environment ([setup](README.md#reproducibility-and-setup)).
- Docker Desktop, Ollama with `nomic-embed-text`, and Copilot sign-in.
- A separate providers environment (its own lock; never mixed into `research/.venv`):

  ```powershell
  cd research
  uv venv --python 3.12 .venv-providers
  uv pip install --python .venv-providers\Scripts\python.exe `
    mem0ai==2.2.1 graphiti-core==0.31.2 honcho-ai==2.9.0 hindsight-client==1.2.0 `
    qdrant-client==1.20.0 fastapi uvicorn
  ```

## Provider services

Secrets (shim token, Neo4j password) live in git-ignored `research/providers/`.

1. **Neo4j** for Graphiti: `neo4j:5.26-community`, bound to `127.0.0.1:7687`.
2. **Hindsight**: `ghcr.io/vectorize-io/hindsight@sha256:d2bc230a714e…`, with
   `HINDSIGHT_API_LLM_PROVIDER=openai`, `HINDSIGHT_API_LLM_BASE_URL` and
   `HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL` pointing at its shim through
   `host.docker.internal`, embedding dimensions 768. Its default reranker is kept.
3. **Honcho** at commit `5c7d24b` from its own repository:
   - Route every LLM feature (deriver, summary, dream, all dialectic levels) and
     embeddings to its shim in `.env`; set `EMBEDDING_VECTOR_DIMENSIONS=768` and
     run `scripts/configure_embeddings.py --yes` once.
   - On networks where `files.pythonhosted.org` is blocked, the image build can
     point `uv.lock` download URLs at a PyPI mirror. Every artifact keeps its
     locked SHA-256 and uv verifies it.
   - Start `database redis api deriver` with Docker Compose.
4. **Shims**, one per provider (ports 8811 Mem0, 8812 Graphiti, 8813 Hindsight,
   8814 Honcho), each with its own journal and request cap:

   ```powershell
   .\research\.venv\Scripts\python.exe -m research.copilot_shim --label mem0 --port 8811 `
     --requests 600 --journal research\runs\memory-study\shims\mem0-study1.calls.jsonl `
     --token <token> --host 0.0.0.0
   ```

   Bind to `0.0.0.0` only for shims that containers call; the token is mandatory.
5. **Gateway**: `research\.venv-providers\Scripts\python.exe -m research.memory_gateway --config research\providers\gateway.json`.
   Later pilots use their own config with the optional `state`, `honcho_workspace`
   and `honcho_reasoning_level` keys so they never touch the study's stores.

## Pipeline

All commands from the repository root. Outputs go under the git-ignored
`research/runs/memory-study/`.

| Step | Command | Model calls |
|---|---|---|
| Learning-pool episodes | `python -m research.study_runner <jobs-bank.json>` | Actor + simulator |
| Internal memories | `python -m research.memory_bank --bank …/bank --out …/memory` | Builder (journaled) |
| Provider ingestion | `python -m research.provider_ingest --episodes …/memory/episodes.json --providers mem0 graphiti hindsight honcho --scope bank --ledger …` | Provider shims |
| Study 1 | `python -m research.study1 --tag memory-study-v1` | Actor + simulator + retrieval |
| Study 2 | `python -m research.study2 --families …/study2-families.json` | Actor + simulator + provider shims |
| Study 3 | `python -m research.lifecycle` | Provider shims (ingestion only) |
| Analysis | `python -m research.memory_analysis --root …/study1 --conditions none raw … --out …` | None |
| Simulator review packet | `python -m research.simulator_review …/study1/*/task-*.json --jobs …/study1/jobs.json --output …/review/study1-worksheet.md --index …/review/study1-index.csv` (likewise bank, study2) | None |

The runner counts every started request in the study directory before each
episode and skips anything whose output already exists, so an interrupted run
resumes without retrying finished episodes. Ingestion keeps a JSONL ledger with
the same guarantee.

## Recovery and failure modes

- **Shim 502 errors**: read `shim-error` events in that shim's journal. A schema
  rejection means the schema needs closing; the shim already handles both
  closed and open object schemas.
- **Hindsight 500s from the gateway**: the client's sync wrappers are bound to
  one event loop, so the gateway uses its async methods.
- **Honcho**: ingestion waits for two consecutive empty deriver-queue polls;
  confirm `queue_status()` shows no pending work before freezing a store.
- **Budget**: the runner refuses to start an episode that could exceed the cap.
  Rotate shim journals between studies so retrieval costs stay attributable.
- Never publish `research/runs/`, `research/providers/`, provider data volumes,
  tokens, or journals.
