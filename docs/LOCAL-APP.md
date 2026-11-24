# Local memory application

A local-first workspace that extracts quoted assertions from notes with a local
Ollama model, consolidates external memory, and revises it when evidence is
corrected or removed. It is a development preview, separate from the
[research track](../research/README.md). Nothing here is a semantic-accuracy,
comparative, or product result.

## Run it

Python 3.11+ and an installed Ollama model; no Python runtime dependencies, API
key, or frontend build. The app uses Ollama's structured chat API at
`http://127.0.0.1:11434` directly.

```powershell
ollama list
python -m afterevidence doctor
python -m afterevidence serve --model qwen3.5:4b --port 8765
```

Open http://127.0.0.1:8765. The app binds only to loopback, never downloads or
switches models, and never calls a cloud provider; `--model` selects another
installed local model. Ctrl+C stops the app, not Ollama. If port 8765 is busy,
use that server or another port; do not kill an unrelated process.

## Five domains

Each pack scopes extraction fields and ships three example notes. The subject
(project, customer case, learner, experiment, service) is explicit user
metadata, not guessed entity resolution. Drafts stay scoped to their tab;
examples substitute the selected subject and never attach another subject's facts.

| Pack | Explicit rule (not a model discovery) |
|---|---|
| Project | Owner + ISO deadline → release check-in |
| Support | Request age vs refund-window days; staff review required |
| Tutoring | Independent vs assisted assessments; practice or reassessment |
| Research | Reported result vs validated evidence |
| Operations | Current vs previously verified dependency version; review and testing |

No plan sends a message, issues a refund, changes infrastructure, or runs a
remembered command. A rule that cannot read a value (use ISO dates, numeric day
counts, explicit scores) shows a warning, never a fabricated default.

## How memory is built and revised

```text
Note + subject -> local extraction -> quoted assertions -> rule plans -> SQLite
Sleep / repair -> snapshot of one subject's assertions -> summary + optional
                  tentative memory -> source-family lineage + epoch-checked commit
Correction / deletion -> new immutable ID or source removal -> recompute proofs
                  -> clear unsupported content, exclude dirty memories, rebuild plans
Question -> fresh context per mode -> answer + source IDs -> epoch check
```

- **Grounding, not truth.** An extracted value must appear in a verbatim quote
  from its note. That checks grounding, not the relation, the speaker's honesty,
  or real-world truth. Confidence is an uncalibrated self-rating. Model
  summaries, hypotheses, procedures, and plans stay separate from source
  assertions and rule plans. Missing rule inputs are warnings, never guesses.
- **Support.** Sources within one proof are AND; alternative complete proofs
  are OR. A model's own summary is never re-ingested as independent evidence.
  Distinct records are distinct sources, not statistically independent ones.
  Model memories conservatively depend on all of the subject's current facts,
  assigned by the host; rule plans may use narrower premises.
- **Staleness.** Inference runs outside write transactions. If evidence changes
  during extraction, consolidation, or answering, the stale result is rejected
  explicitly; retry against the new state. Answers cite short labels (S1, S2)
  that the host maps to real source IDs.
- **Review.** *Reject model claim* removes a wrong relation or unsupported
  interpretation from memory-guided context without deleting the source;
  *Show inactive history* → *Restore for review* reverses it. An identical
  rejected memory is not re-added by Sleep, but a paraphrase or new evidence can
  need another review. Review is not semantic unlearning.
- **Corrections.** *Correct source* replaces a note with a new immutable ID and
  re-extracts. An explicit correction in a new note supersedes the older value;
  removing it does not resurrect the old one. Unqualified conflicts block
  memory-guided answers until corrected or removed. *Re-read note* re-extracts
  the same text without counting it as new evidence.
- **Deletion.** *Delete source* is idempotent and preserves independently
  supported assertions. *Delete session* removes all active sources in that
  pack/session (confirmed in the UI); an empty session is an explicit error.
  Removed text, unsupported values, unsupported model content, and quotes are
  cleared from application read surfaces; inactive IDs remain for audit. This
  is **not certified physical erasure** (SQLite pages/WAL, backups, browser/OS
  memory, Ollama caches).

## Answer modes

**Raw** (active source notes, a baseline), **Awake** (current nonconflicting
assertions), and **Repaired** (assertions plus usable rule and model memories)
use the same model with fresh context; earlier answers are never fed back.
Memory-guided modes refuse subjects with unfinished extraction or conflicts and
abstain without a model call when no usable evidence exists. Repaired answers
include explicit rules, so differences from Raw cannot be attributed to
consolidation alone. The UI refreshes every three seconds and clears an answer
when the evidence epoch changes; it is not a multi-user or authorization system.

## Persistence and boundaries

Default database `data\memory.sqlite3`; source and claim changes are
transactional. The app logs model name/digest, input/output hashes, tokens,
latency, and errors, not plaintext prompts or responses (the synthetic
evaluation driver keeps a labeled raw journal; never use it for private notes).
Data and results are git-ignored. Browser writes need a per-server token and a
matching local origin. Qwen's manifest identifies Apache License 2.0; weights and
Ollama are not bundled (`ollama show qwen3.5:4b --license`).

Interface: system typography, neutral surfaces with one accent, native controls
and confirmations, keyboard skip link and visible focus, dark, high-contrast,
reduced-motion and reduced-transparency variants, no animation on refreshed
evidence, and a CSS-only spinner. Lineage, confidence labels, errors, and review
controls are never hidden for visual tidiness. The guidance consulted
([Apple design](https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md),
[animations](https://github.com/emilkowalski/skills/blob/main/skills/animate/SKILL.md),
[animation performance](https://github.com/emilkowalski/skills/blob/main/skills/animation-performance/SKILL.md))
is not bundled; project conventions are original.

## Validation

### Real-Qwen development runs

Environment: Ollama 0.40.16; `qwen3.5:4b` (4.2B, Q4_K_M), digest
`d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`; no
downloads, cloud calls, keys, or weight updates. Fixed plan: for each of the five
[packs](../afterevidence/packs.py), ingest its three synthetic notes, check
field coverage and the rule plan, consolidate, and ask one question in all three
modes. The project case also replaces the source, adds independent support, and
removes supports one by one, checking preserved ownership, withdrawn plans,
cleared values, and a final abstention. Expected fields stay in the driver, not
the prompt. These are five engineered demonstrations on known fixtures, not
held-out data, a preregistered study, or a population estimate.

| Attempt | Outcome |
|---|---|
| Connectivity + project calibration | Owner/date probe passed; 4-call workflow (2 extractions, 4 cards, cited owner) took 21.485, 63.735, 89.469, 60.750 s |
| Initial five-pack, 8192 context / 512 output | Interrupted after a consolidation timeout; extractions took 87.656 and 170.078 s; source digest `9dca74e8ab6a811317b39da76d5ca7dc3ced280ceb572438d3b8c49edc554c63`; in-flight usage unknown |
| Compact, all five | 3/5 structural passes in 2622.875 s (tutoring omitted a summary; operations omitted `verified_version`) |
| Nullable-field schema, operations + tutoring | 0/2 (invalid `"null"` and all-null extractions rejected); approach removed |
| Facts-list retest, operations + tutoring | 1/2 in 33.969 s (tutoring omitted the topic) |
| Final field descriptions, all five | **5/5 structural passes in 90.860 s**, 29 local calls, all three modes, `source_unchanged` true |

Compact configuration: 4096 context, 384 output tokens, temperature 0, presence
penalty 0, seed 42, 300 s timeout, thinking off; request starts and outcomes are
flushed so interrupted work stays visible. Prompt and schema changes reused the
same notes: this is not generalization. Frozen trial package SHA-256
`6ef4294f22c8afc96c34dd0ac0759fb45c0cdb1b1d6db3c1a8d135add92562a0`;
review-enabled package `0b161ea00b676f16015e568c577d4fcf82b90c2cb442de5e18e5d2c99f502cc6`
(file hashes, not signatures). Local, unpublished evidence:
`results/qwen-application-{development.interrupted,compact,targeted-v02,targeted-final,final-five-pack}.json`
with adjacent `.calls.jsonl` journals. Rerun with
`python -m afterevidence evaluate-app --output results\<new>.json`
(`--packs operations tutoring` for a labeled targeted retest; never overwrite
earlier outputs).

The pre-publication snapshot passed **62 regression tests** (current CI is the
authority for the latest count), covering persistence, AND/OR support,
correction without resurrection, stale-write rejection, content clearing,
untrusted model output, host-assigned lineage, review controls, loopback-only
access, and deterministic replay.

Assistant-assisted browser walkthrough (not independent human annotation): all
five tabs, narrow-viewport layout without overflow, blocked blank notes, explicit
Sleep-without-evidence error. Real Qwen ingested three operations notes for
subject `Lifecycle Demo Pine` and answered citing all three. A procedure
mislabeled as `test_status` and an unsupported causal summary were rejected;
reject/restore/reject kept all sources. Deleting the verified-version source
withdrew the dependent plan, kept two unrelated assertions, and cleared the
answer; re-adding it created a new ID and restored the plan without resurrecting
the deleted episode. A fresh answer advised against the version-1.0 procedure on
current version 2.0 with three source links. Quote matching and lineage did not
catch those model errors.

### Offline lifecycle contracts

Deterministic positive-Horn-rule fixtures, 2026-11-12, Python 3.12.10, 18 tests
then: 3 proof topologies × 10 ID/order variants (30 worlds, not 30 independent
scenarios) × 3 policies × 2 consolidation conditions × 2 branches = 360
trajectories, 2,880 observations; deterministic replay passed; external spend $0.

| Implementation | Correct | Stale | Over-deleted |
|---|---:|---:|---:|
| Proof-aware reference | 960 | 0 | 0 |
| Flat-union negative control | 940 | 20 | 0 |
| Delete-all-affected negative control | 940 | 0 | 20 |

All control errors were in the preconsolidated intervention branch: flat union
10 stale after partial deletion of a sole conjunction and 10 after the final
sufficient proof was removed from an independent alternative; delete-all-affected
10 over-deletions each after partial deletion (independent alternative,
redundant direct support). Neither control is a proxy for any product. Source
SHA-256 `7bd3d29f2c0a07ef048eaafebb2d3d3730cc48a95455089bdeac1725bebc03d6`,
report `32962163c3b7ceaaf261e776ccd35c903d8ba436f236a6ccbf1cc5928f9fca1c`
(local `results/offline-demo.json`). Reproduce:

```powershell
python -m afterevidence run --worlds-per-topology 10 --seed 42 --output results\offline.json
python -m afterevidence verify results\offline.json
```

Contract: immutable source IDs; positive conjunctive rules with alternatives; a
conclusion is usable iff one complete source proof remains; restatements are not
independent evidence; unknown IDs are errors, repeated deletion is idempotent;
reconsolidation never resurrects; queries are fresh. The reference (proof
propagation) and oracle (boolean forward chaining) use different algorithms,
and the harness tracks planned source state itself.

#### Threat checks

Each threat has two executable checks in [test_contracts.py](../tests/test_contracts.py)
(software checks, not independent replications); no claim goes beyond them.

| Threat | Check A | Check B |
|---|---|---|
| Incorrect AND/OR oracle | `test_explicit_and_or_fixtures` | `test_all_deletion_subsets_match_independent_rebuild` |
| Deletion/order/rebuild errors | `test_session_removal_and_unknown_ids` | `test_deletion_order_and_reconsolidation_are_invariant` |
| Ground-truth coupling | `test_public_payload_excludes_grading_fields` | `test_swapping_oracle_labels_cannot_change_observations` |
| Hidden oracle access | `test_memory_has_no_oracle_dependency` | `test_swapping_oracle_labels_cannot_change_observations` |
| Implementation defining its expected state | `test_runner_detects_ignored_source_intervention` | `test_all_deletion_subsets_match_independent_rebuild` |
| Scenario/order artifacts | `test_renaming_and_input_order_do_not_change_outcomes` | `test_all_deletion_subsets_match_independent_rebuild` |
| Ablation/denominator mistakes | `test_closed_form_ablations_and_denominators` | `test_sham_and_unrelated_controls_always_pass` |
| Replay/integrity errors | `test_json_roundtrip_replay_and_tamper_detection` | `test_hash_seed_does_not_change_results` |
| Invalid-input masking | `test_invalid_inputs_are_explicit` | `test_cli_rejects_bad_limits_and_malformed_json` |

**Not passed (claims blocked):** language understanding and paraphrase
robustness, real inference formation, hypothesis truth, native product
deletion/correction, distributed concurrency (only epoch guards are tested),
stochastic variance, judge bias, vendor configuration fairness, authorization,
and physical erasure. Local replay is not replay of a real memory service.

A candidate comparative product study (3 proof-topology strata × 100 worlds ×
3 repeats) was sketched but never frozen, tagged, or run. Honcho caveat for any
native adapter: audited release v3.6.1 (`70c67624169683b9e265517aec95a51b8077cabc`,
2026-11-11) and inspected main (`5c7d24b32d275bce38daedbe81feaebc31393587`)
differ in peer-card history and must not share a label; message update is
metadata-only, session and conclusion deletion are different contracts, and a
deleted conclusion can be re-derived from remaining sources
([release](https://github.com/plastic-labs/honcho/releases/tag/v3.6.1),
[messages](https://github.com/plastic-labs/honcho/blob/70c67624169683b9e265517aec95a51b8077cabc/src/routers/messages.py),
[conclusions](https://github.com/plastic-labs/honcho/blob/70c67624169683b9e265517aec95a51b8077cabc/src/routers/conclusions.py),
[peer-card change](https://github.com/plastic-labs/honcho/pull/1590)).

## Model size and Google Sleep scope

Nothing here trains weights. Smaller studies, cheaper inference models, and
smaller trainable models trade different things (speed versus precision; cost
versus errors and retries that can erase savings; feasibility versus
capability). Prove the harness on a small declared set, use a capable fixed
baseline before studying memory (a floor-level actor is a confound), validate
small extractors and judges on downstream-relevant errors, count the whole
pipeline's cost, and freeze the sample before the main run. One 4B native-task
failure does not show all small models are unsuitable, and a passing fixture
does not show they suffice.

[Language Models Need Sleep, §3.2-3.4](https://arxiv.org/html/2606.03979v2#S3)
motivates separating capture from offline consolidation. Implemented: a wake /
external-memory consolidation / revision workflow. Not implemented: Knowledge
Seeding into expanded parameters, distillation plus RL imitation, expert
activation schedules, or RL curricula. The Sleep button updates no weights; a
LoRA experiment would not reproduce Google's architecture either.

## Troubleshooting

- **Ollama unavailable:** start Ollama (`ollama serve`) and check `ollama list`.
- **Model missing:** pass an installed model with `--model`; there are no pulls.
- **Slow:** calibration calls took about 20-90 s and one early call 170 s;
  requests are serialized per client. Don't run an evaluation and interactive
  use together.
- **Failed extraction:** the source stays visible with its error; retry,
  shorten, or delete. Failures never become empty successful memories.
- **Context/output budget, or changed evidence during a call:** explicit errors;
  shorten the note or retry.
- **403 after restart:** reload to get the new local token.
