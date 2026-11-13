# Local application validation

## Status

The pre-publication application snapshot passed **62 automated regression tests**.
The final frozen real-Qwen development run passed structural checks for all
**five fixed packs**, and the real browser walkthrough completed.

This is not a semantic-accuracy claim. The browser also exposed unsupported
model interpretations, which were excluded using the new reversible review
controls. Quote matching and source lineage did not detect those errors.

This is not a preregistered main study, a held-out benchmark, a claim of
scientific novelty, or a comparison with another memory product.

## Verified environment

- Ollama: 0.40.16, already installed and running locally.
- Model: `qwen3.5:4b`, 4.2B parameters, Q4_K_M.
- Model digest:
  `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`.
- No model downloads, paid cloud calls, provider keys, or weight updates.
- App: http://127.0.0.1:8765, loopback-bound.

## Deterministic validation

That complete 62-test regression run passed. The source release adds separate
publication guards; the current CI is the authority for the latest test count.
The application checks cover:

- SQLite persistence and connection lifetime.
- Independent support preservation and required-premise invalidation.
- Source replacement, explicit correction, conflicts, session removal, and no
  resurrection of superseded facts.
- Stale extraction, consolidation, and answer rejection.
- Source-content clearing from application read surfaces.
- Untrusted model output, invented values/citations, and explicit retryable errors.
- Host-assigned consolidation lineage and short answer-source resolution.
- Required summary output, missing rule-premise warnings, and semantic field descriptions.
- UUID-independent ordering when source timestamps match.
- Reject/restore review, source preservation, suppression of an identical
  rejected model memory, and clearing rejected content when its sources disappear.
- Loopback-only model access, cloud-model rejection, and local browser request boundaries.
- Preservation of the original offline harness and deterministic replay.

The current offline compatibility run still produces 2,880 observations:
960/960 correct for the reference, 20 stale assertions for the intentionally
broken flat-union control, and 20 over-deletions for the intentionally broken
delete-all-affected control. These are software fixtures, not product scores.

## Actual model trials, including failures

### Connectivity and initial smoke calibration

A structured owner/date probe succeeded. A separate real local workflow
extracted two source notes, consolidated four cards, and returned the correct
owner with a source citation. The four workflow calls took approximately
21.485, 63.735, 89.469, and 60.750 seconds.

This was calibration, not unseen data. Its source revision was not captured
as a frozen main-study revision, and no population accuracy is inferred.

### Initial larger trial: interrupted, not a pass

Source digest:
`9dca74e8ab6a811317b39da76d5ca7dc3ced280ceb572438d3b8c49edc554c63`.

The initial 8192-context, 512-output-budget five-pack attempt encountered a
project consolidation timeout. Recorded successful extraction calls took
87.656 and 170.078 seconds. The command was stopped; no complete five-pack
result is claimed.

Evidence:

- Local interrupted-trial manifest: `results/qwen-application-development.interrupted.json`.
- Local completed-call journal: `results/qwen-application-development.calls.jsonl`.

That journal predates started-request logging, so an interrupted in-flight
request can have unknown usage. It must not be silently counted as zero cost
or a successful outcome.

### Compact trial

The revised protocol uses a 4096 context, 384 output tokens, presence penalty
0, temperature 0, seed 42, a 300-second timeout, host-assigned consolidation
lineage, and short answer-source aliases. It flushes request-start and
completion/failure records, so interrupted work remains visible.

The [development plan](APPLICATION-STUDY.md) defines all five cases, three
answer modes, and the project correction/preservation/deletion checks.
Passing structural checks will not be labeled semantic accuracy.

### Completed development-attempt ledger

| Attempt | Scope | Outcome |
|---|---|---|
| Initial larger run | Five packs planned | Interrupted after a local timeout; partial journal preserved |
| Compact run | All five packs | 3/5 structural passes in 2622.875 seconds; tutoring omitted a summary, operations omitted `verified_version` |
| Nullable-field experiment | Operations and tutoring | 0/2; invalid `"null"` assertions and all-null extraction were rejected; approach removed |
| Facts-list retest | Operations and tutoring | 1/2 in 33.969 seconds; operations passed, tutoring omitted the learning topic |
| Final field-description run | All five packs | **5/5 structural passes in 90.860 seconds**, 29 real local model calls |

Connectivity/project calibration preceded these five development attempts.
Failed attempts were not removed or relabeled. Prompt/schema changes used the
same known development notes; this is not held-out generalization.

Evidence:

- Local compact full run: `results/qwen-application-compact.json`.
- Local failed nullable-field experiment: `results/qwen-application-targeted-v02.json`.
- Local facts-list targeted retest: `results/qwen-application-targeted-final.json`.
- Local final five-pack run: `results/qwen-application-final-five-pack.json`.
- Corresponding adjacent `.calls.jsonl` files retain synthetic request starts,
  responses/failures, options, hashes, tokens, and timing.

These are local evidence paths, not files included in the public source release.
The public report retains aggregate outcomes and hashes; it does not publish
raw request journals or application databases.

Runtime varied substantially. These uncontrolled development observations do
not isolate a causal latency or memory-quality improvement.

### Final frozen five-pack run

| Pack | Structural result |
|---|---|
| Project decisions | Passed, including corrected owner, independent-support preservation, dependent-plan withdrawal, and final abstention |
| Customer support | Passed |
| Adaptive tutoring | Passed |
| Research notebook | Passed |
| Coding and operations | Passed |

All three answer modes ran for each case. The one model digest matched the
inspected installed Qwen artifact. `source_unchanged` was true.

Frozen trial package SHA-256:

```text
6ef4294f22c8afc96c34dd0ac0759fb45c0cdb1b1d6db3c1a8d135add92562a0
```

Reviewer controls were added afterward in response to browser findings and
validated separately with unit/API and browser checks. Pre-publication review-enabled
package SHA-256:

```text
0b161ea00b676f16015e568c577d4fcf82b90c2cb442de5e18e5d2c99f502cc6
```

These are package-file hashes, not signatures or registered main-study tags.
The final raw report retains its actual earlier frozen revision.

## Completed browser checks

- All five use-case tabs select the correct subject and controls.
- Mobile layout had no horizontal overflow in the tested narrow viewport.
- Blank-note submission was blocked without a model mutation request.
- Sleep without current evidence returned an explicit visible error.
- The new server's local connection status and browser initialization succeeded.
- Real Qwen ingested three separately sourced operations notes for the custom
  subject `Lifecycle Demo Pine`, generated external-memory output, and answered
  with links to all three actual source episodes.
- A model mislabeled a procedure as `test_status`; a generated summary also
  added an unsupported causal interpretation. Both were explicitly rejected.
  Reject/restore/reject preserved all three source notes.
- Deleting the verified-version source withdrew the dependent plan while
  preserving two unrelated assertions and clearing the displayed answer.
- Adding that evidence again created a new source ID and restored the
  rule-derived plan, rather than resurrecting the deleted episode.
- A fresh answer advised against trusting the version-1.0 procedure on current
  version 2.0 and exposed three current source links.
- Citation clicks highlighted their source, drafts stayed scoped to the
  correct use-case tab, and populated mobile layout had no horizontal overflow.

The walkthrough was assistant/reviewer-assisted, not an independently
human-annotated evaluation. It demonstrates operational controls, not
automatic semantic correctness or semantic unlearning.

The repaired answer mode includes explicit application rules as well as model
memory. Differences from raw/facts-only answers cannot be attributed solely
to consolidation.

## Limits

Quoted extraction is not semantic verification. Model self-confidence is not
calibrated. Source lineage is not a logical proof that model-generated prose
is entailed. Current tests do not establish enterprise authorization, physical
erasure, production scalability, population task accuracy, or Google-style
parameter-training behavior.
