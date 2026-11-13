# Memory study protocol (v1)

Status: written after development data collection and **before any test-split
episode**. It is committed and tagged `memory-study-v1`; `research.tau_copilot`
refuses the test split unless that tag exists. Development results were used to
fix bugs and design memory builders, never test outcomes.

This is an exploratory, single-model study, not a leaderboard submission.

## Questions

1. **Cross-customer transfer (Study 1).** Does memory distilled from earlier
   conversations with *other* customers change success on new test tasks?
2. **Returning customer (Study 2).** Does memory of the *same* customer's earlier
   sessions help later sessions, or mislead when remembered facts are stale?
3. **Deletion lifecycle (Study 3).** When a source conversation is deleted, does
   each system remove what it derived from it and keep everything else?

No direction is predicted. Null and negative results are reported as found.

## Fixed setup

| Item | Value |
|---|---|
| Benchmark | tau2-bench retail at `c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4` |
| Actor and user simulator | Copilot `claude-haiku-5.5` via the pinned SDK and runtime 1.0.111-0 |
| Action contract | Flat `WireCommand`; one counted re-ask per malformed action; never repaired |
| Episode limits | 30 model requests (actor + simulator + re-asks), 60 orchestrator steps |
| Reference policy | `strict-except-scripted-lookups-v2` |
| Memory placement | Retrieved once from the customer's first message; injected after the policy under a fixed header saying tools and policy take precedence |
| Memory budget | 2,400 characters for every condition |
| Embeddings (internal conditions, Mem0, Graphiti, Hindsight, Honcho) | local `nomic-embed-text` (768 dimensions) |
| Provider LLM calls | the same Copilot model through a per-provider metered shim |

## Learning pool and memory construction

- Pool: the 33 train tasks whose customers resolve and never appear in a test
  task. Tasks 2, 3, and 4 fail reference preflight, leaving **30 episodes**
  run once without memory (23 succeeded).
- Builders read only what the agent saw and did plus a binary outcome label
  (native ENV reward 1 or not). They never read reference actions, task
  instructions, or scorer details.
- Lesson texts are instructed to omit customer names and identifiers.

### Conditions (Study 1)

| Condition | Memory |
|---|---|
| `none` | No memory |
| `raw` | Past episode transcripts (trajectory exemplars), embedding-ranked |
| `consolidated` | Up to six global lessons from one pass over all episodes (ExpeL-style) |
| `sleep` | Non-parametric sleep analogue: per-episode lessons, merge by similarity (cosine ≥ 0.85), weight by distinct supporting episodes, downscale to the strongest, prune below 0.25 (keep at least four), rewrite survivors; retrieval multiplies similarity by 0.5 + 0.5 × weight |
| `workflows` | Up to six reusable workflows induced from successful episodes (AWM-style) |
| `mem0` | Mem0 OSS, agent-level store, default extraction and search |
| `graphiti` | Graphiti on Neo4j, default episode ingestion and hybrid search |
| `hindsight` | Hindsight server, retain then recall |
| `honcho` | Honcho server, agent peer queried through the dialectic at `low` reasoning |

The Google "Language Models Need Sleep" method trains model weights; it cannot
apply to a hosted model. `sleep` tests only the memory-level idea of replay,
reweighting, and pruning.

Not included: Stashbird requires internal cloud resources and was not run.

## Study 1 design

- Test tasks (26): the official test tasks that pass reference preflight,
  change the database, and have no natural-language assertions, so the native
  task-basis score needs no judge:
  5, 9, 17, 18, 26, 27, 32, 33, 42, 49, 51, 53, 55, 56, 61, 71, 74, 77, 79, 86,
  90, 94, 97, 100, 101, 102.
- 9 conditions × 26 tasks × 2 replicates = 468 episodes, shuffled with seed
  20261113. Copilot sampling is not seeded; replicates are independent runs.
- Memory is frozen; test episodes never write to memory.

## Study 2 design

- 16 train families in which one customer has several tasks (38 tasks). Tasks
  2, 3, 4, 105 and tasks without a write in the reference are excluded.
- Every session first runs without memory; those transcripts are the shared
  history. Each later session (22) also runs with memory of the same
  customer's earlier sessions: `session` (plain transcripts, most recent first),
  `mem0` (per-customer store), and `honcho` (customer peer).
- The database resets between sessions, so remembered actions can be stale.
- Eight later sessions have natural-language assertions; Study 2 reports the
  native ENV (database) reward only and marks those assertions unassessed.

## Study 3 design

Three bank episodes from three different customers are ingested into each
provider in an isolated scope; the first is deleted through each provider's own
delete operation. Probes are identifiers occurring in exactly one episode. Report
whether deleted identifiers disappear and what fraction of the others remain.
Internal lesson stores are checked from their recorded provenance.

## Metrics and analysis

- **Primary:** success = normal termination and native ENV reward 1. Contract
  failures, request caps, and incomplete episodes count as failures.
- Per condition: success rate with Wilson 95% interval.
- Each memory condition vs `none`, paired by task and replicate: exact two-sided
  McNemar test, Holm-corrected across the eight conditions (α = 0.05).
- **Cost:** AI credits per episode from journals, plus provider retrieval credits
  from per-study shim journals; memory build credits reported separately.
- Secondary, descriptive only: requests per episode, re-asks, memory errors,
  retrieved characters.

With 52 pairs per comparison, only large differences are detectable. Small
effects will not be distinguishable from zero and will be reported that way.

## Budget and stop rules

- Approved hard cap: **16,000 Copilot requests** across the whole memory study,
  counted from every journal (episodes, builders, shims), enforced before each
  episode starts.
- No retries or replacements of finished jobs. A provider retrieval error is
  recorded and that episode runs without memory.
- If the cap stops the study early, the incomplete set is reported as such.

## Deviations

Any change after tagging is recorded in `RESULTS.md` with its reason and the
affected episodes. No analysis choice is changed after seeing test outcomes.

## Frozen artifacts (private; hashes are the first 16 hex digits of SHA-256)

Stored under the git-ignored `research/runs/memory-study/`.

| Artifact | SHA-256 prefix |
|---|---|
| `memory/episodes.json` | `32e7a1a5f35b7c46` |
| `memory/raw.json` | `01b1c6d4ecb3d5ec` |
| `memory/consolidated.json` | `0617971097272480` |
| `memory/sleep.json` | `e90fe478c59c1595` |
| `memory/workflows.json` | `19a47390283f7740` |
| `study1/jobs.json` | `df0d6d288ba3b257` |
| `study2-families.json` | `59d84b1a53880891` |

Provider stores: all 30 bank episodes ingested into Mem0 2.2.1, Graphiti 0.31.2
(Neo4j 5.26), Hindsight (image digest `d2bc230a714e`), and Honcho (commit
`5c7d24b`; deriver queue drained, 867 of 867 work units). Retrieval smoke tests
returned memory for all eight conditions; two development episodes confirmed
the memory header reached every actor prompt. Requests spent before tagging:
1,229 of 16,000.
