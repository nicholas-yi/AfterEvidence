# Local memory application

## Access your Qwen installation

Your local Ollama service uses `http://127.0.0.1:11434`. The application uses
its structured chat API directly; an Ollama Python SDK or API key is unnecessary.

```powershell
ollama list
ollama run qwen3.5:4b
python -m afterevidence doctor
python -m afterevidence serve --model qwen3.5:4b --port 8765
```

Open http://127.0.0.1:8765. The app binds only to loopback, not the LAN.
Ctrl+C stops a foreground application server. It does not stop your existing
Ollama service. If a server is already running on 8765, use that server or
choose another application port; do not kill an unrelated process.

The inspected installation contains Qwen 3.5 4B and 9B variants. Development
uses the smaller stock `qwen3.5:4b` model, not an automatic download or model
switch. CLI `--model` can select another already-installed local model.

## One application, five domains

Each pack scopes allowed extraction fields and provides three example notes.
The subject is explicit user metadata: project, customer case, learner,
experiment, or service. Entity resolution is not being silently delegated to
a guessed identity.

The subject input offers saved subjects from active source records. Unsaved
note/question drafts stay scoped to their use-case tab in the current browser
session rather than moving to a different domain when you switch tabs.

Example notes substitute your selected subject and select their example
session explicitly. They do not silently attach another subject's example
facts to your subject.

| Pack | Rule-backed behavior |
|---|---|
| Project | Combine owner and ISO deadline into a release check-in |
| Support | Compare supplied request age and refund-window days; require staff review |
| Tutoring | Distinguish independent from assisted assessments; propose practice/reassessment |
| Research | Distinguish a reported result from validated evidence |
| Operations | Compare current and previously verified dependency versions; require review/testing |

These plans are explicit application rules, not discoveries by the model.
No plan sends a message, issues a refund, changes infrastructure, or executes
a remembered shell command.

For deterministic rules, use source-written ISO dates, numeric day counts,
and explicit assessment scores. Qualitative notes can still be stored and
summarized. A rule that cannot interpret a value produces a visible warning,
not a fabricated default.

## Data flow

```text
Note + subject
    -> local Qwen extraction -> quoted source assertions -> explicit rule plans
    -> SQLite persistence

Sleep / repair
    -> snapshot of current assertions for one subject
    -> local Qwen summary + optional tentative memory
    -> source-family construction + epoch-checked commit

Correction / deletion
    -> immutable replacement ID or source removal
    -> recompute supporting proof families
    -> clear unsupported content, exclude dirty memories, rebuild rule plans

Question
    -> fresh context for selected mode
    -> local Qwen response + source IDs
    -> epoch check before returning an answer
```

Model inference occurs outside database write transactions. If source state
changes during extraction, consolidation, or answering, the stale result is
rejected explicitly. Retry against the new state; no success-shaped fallback
is substituted.

The local model uses short answer-time source aliases rather than spending
tokens copying database hashes. The host resolves them back to real IDs.
Consolidation provenance is attached from the actual input snapshot, not
accepted as an invented model citation.

## Assertions, hypotheses, and evidence

An extracted value must occur in a verbatim quote from its note. This checks
source grounding, **not** whether the model interpreted the relation correctly,
whether the speaker was truthful, or whether the claim is true in the world.
Inspect and correct mistakes.

The local model returns a list of supported assertions, not a nullable field
table. A nullable-table experiment proved unreliable and is retained as a
failed development trial. Missing inputs for a rule plan are surfaced as
warnings; they are never filled with guessed values. Consolidation has a
schema-required summary field, with a separate optional extra memory.

Model summaries, hypotheses, procedures, and plans are separate from source
assertions and from explicit rule-derived plans. Confidence is an uncalibrated
model self-rating.

Use **Reject model claim** when a quoted value has the wrong relation or a
generated interpretation is unsupported. This excludes the parsed claim from
memory-guided context without deleting the source. Enable **Show inactive
history** to **Restore for review**; current evidence/conflict checks still
apply. Rule plans are repaired through their premises, not this model-review
control.

Review is not semantic unlearning. An identical rejected model memory is not
silently re-added by Sleep while its current evidence remains, but a paraphrase,
new evidence, or explicit source reprocessing can require another review.
Source deletion still clears unsupported rejected content; erased content is
not restored by a review button. Raw-source comparison mode intentionally
remains a raw-source baseline, not a view filtered by model-claim review.

Within one sufficient source proof, sources are AND. Alternative complete
proofs are OR. Adding the same assertion from another source can extend its
support. A model's own summary is not re-ingested as independent evidence.
Distinct user-supplied records are treated as distinct source records, not as
a guarantee of statistically independent observations.

For model-created memories, all supplied current facts about that subject are
conservative dependencies assigned by the host. The model does not generate
opaque database IDs. Answer-time short labels (S1, S2, ...) are validated and
mapped back to actual episode IDs by the host.
Unrelated subjects are not added to that input. Explicit rule plans can use
narrower known premises. This favors conservative invalidation over pretending
to know which tokens the model actually depended on.

## Corrections, conflicts, and removal

- **Correct source** replaces an episode with a new immutable ID. The old
  source content is cleared, its lineage is invalidated, and the replacement
  is extracted again.
- **Explicit correction in a new note** supersedes older conflicting assertions
  for that field. Removing that correction does not automatically resurrect
  the old assertion. Reassert it explicitly if it becomes current again.
- **Unqualified conflicting assertions** remain conflicts. Memory-guided
  answers block until an explicit correction or source removal resolves them.
- **Re-read note** explicitly replaces a source version with the same text and
  runs the current extraction contract again. Use it after changing models or
  when a partial extraction needs review. It does not duplicate the old source
  as independent evidence.
- **Delete source** is idempotent for a known source ID, clears its application
  content, and preserves independently supported assertions.
- **Delete session** removes active sources matching that pack/session,
  including other subjects in that session. The UI confirms this scope.
  A session with no active matching sources returns an explicit not-found error.

Removed source text/title/subject/session, unsupported assertion values, model
content with no surviving source proof, and source quotes are cleared from
application read surfaces. Inactive metadata/IDs can remain for auditing.
This is **not certified physical erasure**: SQLite pages/WAL, backups, browser/OS
memory, and Ollama's internal caches are outside the guarantee.

## Answer modes

1. **Raw:** current active source notes; a comparison baseline.
2. **Awake:** current nonconflicting extracted assertions.
3. **Repaired:** current assertions plus usable rule/model memories.

All modes use the same local model and fresh per-question context. Previous
answers are not fed back as new evidence. Memory-guided modes reject subjects
with unfinished/failed extraction or conflicts. Dirty memories are excluded.
With no usable evidence, the app explicitly abstains without invoking a model.

The UI labels answer snapshots by evidence epoch and refreshes state every
three seconds. It clears an answer when it observes a newer epoch. It is not
a multi-user, strongly consistent collaboration or authorization system.

## Persistence, logging, and local boundaries

Default database: `data\memory.sqlite3`. Source/claim changes and event receipts
are transactional. SQLite connections close after each operation.

The ordinary app records model name/digest, input/output hashes, token counts,
latency, and errors. It does not retain plaintext model-call prompts/responses.
Synthetic development evaluation has a separate, explicitly labeled raw-call
journal. Do not use that evaluation driver for private production notes.

Application data and results are git-ignored. No cloud model, model download,
non-loopback adapter endpoint, or proxy-mediated model request is allowed.
Browser writes require a per-server token and matching local origin/host.
This development server is not an authenticated enterprise deployment.

The installed Qwen model's manifest identifies Apache License 2.0. Model
weights and the Ollama runtime are not bundled in this MIT-licensed repository;
check the exact third-party artifacts' terms before redistribution. The local
license can be inspected with `ollama show qwen3.5:4b --license`.

## Google paper scope

[Language Models Need Sleep, Sections 3.2-3.4](https://arxiv.org/html/2606.03979v2#S3)
motivates separating active experience capture from offline consolidation and
self-improvement.

**Implemented:** a wake/external-memory-consolidation/revision workflow with real
local-model inference and executable lifecycle checks.

**Not implemented:** upward Knowledge Seeding into expanded lower-frequency
parameter capacity, generalized distillation plus RL imitation, expert
activation/reset schedules, or RL-trained synthetic curricula.

No model weights are updated. The app's Sleep button is not a reproduction of
Google's method. Parameter-training experiments remain gated on a separately
verified training setup and experimental design.

## Troubleshooting

- **Ollama unavailable:** open Ollama or run `ollama serve`, then `ollama list`.
  The service should already be running before you open the app.
- **Model missing:** choose an installed model with `--model`. There are no
  automatic pulls. Do not select a cloud model.
- **Slow responses:** calibration calls took roughly 20-90 seconds; one larger
  initial trial took 170 seconds and consolidation timed out. The current compact
  configuration uses a 4096-token context, 384-token output cap, no presence
  penalty, and a 300-second timeout. Requests are serialized per client.
  Avoid running a live evaluation and interactive inference simultaneously.
- **Failed extraction:** the source remains visible with its error. Use Retry,
  shorten/clarify the note, or delete it. Failure does not become an empty
  successful memory.
- **Context/output budget:** use shorter notes or separate subjects. Oversized
  requests and truncated outputs are explicit errors.
- **Changed evidence during a call:** stale writes/answers are rejected. Retry.
- **403 after a restart:** reload the page to obtain the new local token.
- **No semantic accuracy score:** citations and structural checks do not prove
  answer correctness. Review the actual text and the evaluation limitations.
