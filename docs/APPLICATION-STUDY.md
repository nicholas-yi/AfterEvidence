# Local application development validation plan

This is a fixed-fixture integration plan, **not a preregistered main study**.
Connectivity calibration and a four-call project workflow have already run.
The initial owner/date fixture is not unseen test data.

## Resource and model scope

- Local Ollama, loopback HTTP only; no cloud models or downloads.
- Installed model: `qwen3.5:4b`, Q4_K_M, 4.2B parameters.
- Observed model digest:
  `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`.
- Current configuration: temperature 0, presence penalty 0, request seed 42,
  context 4096, output budget 384, thinking off.
- The initial 8192-context development attempt hit a local consolidation timeout
  and was interrupted. Its journal and interrupted-trial manifest remain saved.
- Consolidation lineage is assigned by the host from the actual input snapshot,
  not copied back from model-generated opaque IDs. Answers use short source labels
  that the host maps back to verified source IDs.
- No paid external services, parameter updates, or reinforcement learning.

## Fixed cases and observations

The five packs in [packs.py](../afterevidence/packs.py) cover project decisions,
support policies, tutoring, research evidence, and operations procedures.
The local model sees only the source notes, the ordinary task/question, and
the output schema. Expected field sets and correctness checks stay in the
evaluation driver, not the model prompt.

For each pack:

1. Ingest its three synthetic notes as one source record and extract quoted fields.
2. Verify the expected field coverage and availability of an explicit rule plan.
3. Perform real local-model external-memory consolidation.
4. Ask the same question in raw-source, awake-facts, and repaired-memory modes.
5. Record exact answers, citations, model digest, input/output hashes, tokens,
   latency, failures, and the final application snapshot.

The project case additionally replaces the source, checks the changed owner,
reconsolidates, adds independent support, removes the original supporting
record, and finally removes the last support. It checks preserved ownership,
withdrawn dependent plans, absence of erased values in application read
surfaces, and an explicit no-evidence abstention.

## Interpretation limits

- Passing structural checks does not prove semantic correctness.
- Non-project open-ended answers are not assigned a fabricated accuracy score.
- These are five engineered demonstrations, not five independent research
  replications. No population confidence interval or superiority claim follows.
- A model failure or validation rejection remains a reported failed case.
- Raw model-call records are retained and flushed after each request to the
  adjacent `.calls.jsonl` journal only for these fixed synthetic fixtures.
  The ordinary application stores hashes/usage, not plaintext model-call logs.
- Physical erasure from SQLite pages, backups, browser/OS memory, or Ollama's
  internal caches is outside the tested contract.

Run with:

```powershell
python -m afterevidence evaluate-app --output results\qwen-application-development.json
```

For an explicitly labeled targeted retest, use `--packs operations tutoring`
with a new output path. Its denominator is the selected cases, not all five.
Keep earlier failed outputs/journals; do not silently replace them.

The full comparative-memory protocol and main-study registration remain a
separate future gate.
