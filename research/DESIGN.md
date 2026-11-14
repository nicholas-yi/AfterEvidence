# Experience memory study: design and feasibility record

## Status and purpose

This is a research track, not another application demo. Its question is:

> Does memory distilled from an agent's own earlier task experience improve
> later action-level task completion, and what happens when the evidence for
> a remembered lesson is withdrawn?

No positive result, novelty, registered main experiment, or full official
benchmark score is currently claimed. The first run is a native-task
development feasibility check. The UI application is not the experimental
environment and its hard-coded scenario rules are not used in this study.

## Benchmark selection

### MemoryArena

Primary sources: [paper](https://arxiv.org/abs/2602.16313),
[official code](https://github.com/ZexueHe/MemoryArena),
[license request](https://github.com/ZexueHe/MemoryArena/issues/2),
[dataset](https://huggingface.co/datasets/ZexueHe/memoryarena).

The read-only audit found action-executing shopping/travel settings, but
substantial extra assets and no clear top-level code license at the inspected
revision. The dataset separately declares CC-BY-4.0. Public readability is not
permission to copy the code into this project. A license clarification or a
carefully separated licensed-data implementation would be needed before reuse.
This is a practical selection decision, not a critique of the scientific work.

### LifelongAgentBench

Primary sources: [paper](https://arxiv.org/abs/2505.11942),
[official code](https://github.com/caixd-220529/LifelongAgentBench),
[dataset](https://huggingface.co/datasets/csyq/LifelongAgentBench).

The authors provide skill-related sequential tasks and native action scoring,
but the inspected release did not establish code/data licensing clearly.
Docker is installed on this machine, but its Linux daemon was not running.
No benchmark tasks were copied, executed, or relicensed.

### Selected: native tau2-bench retail

- [Official repository](https://github.com/sierra-research/tau2-bench).
- Commit: `c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4`.
- MIT license retained in the separate, unmodified vendor checkout.
- Native retail environment: database state, sixteen tools, domain policy,
  user simulator, orchestrator, and scorer.
- Official split file: `data/tau2/domains/retail/split_tasks.json`.
- Development uses only the official `train` split.

Tau2 does not natively claim that carrying memory between independent test
customers is its standard protocol. The prospective cross-task-memory study
is therefore an **explicit extension**, not an official leaderboard submission.
Official evaluation task outcomes must not be used to tune memory.

## Existing environment and adapters

The benchmark lives under `research/vendor/tau2-bench`, git-ignored and pinned.
It is not bundled as newly authored MIT code. The optional native dependencies
are isolated in `research/.venv`, not added to the application's runtime.

PyPI metadata was reachable, but package files failed TLS negotiation at the
default file host. The packages were installed through the HTTPS Tsinghua
PyPI mirror with certificate verification enabled. No insecure/trusted-host
override was used. Exact resolved versions are in `dependencies.lock.txt`.

The task feasibility driver uses native agent/user/tool orchestration.
It does not hand the expected tool-call list or evaluation criteria to the
agent or its memory. User instructions are given only to the native user
simulator, as intended by the benchmark.

## Scoring boundary

Reference actions are one route to a target database state, not the only
allowed agent route. The native ENV scorer replays actions to compare final
database states. See the upstream [evaluation guide](https://github.com/sierra-research/tau2-bench/blob/c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4/docs/evaluation.md).

The $0 local pilot reports **native ENV goal reward only**. Some task contracts
also require communication or natural-language policy assertions, normally
judged by other model calls. ENV reward is not substituted for the full
official reward. An action-level success can still violate policy, and a
no-action task can have a trivially matching database. Both must be disclosed.

Before any main comparison, require nontrivial validated reference state
changes for the primary DB endpoint, record skipped policy/communication
criteria, and verify gold reference replay does not fail. Any full-contract
claim needs the appropriate independently validated scoring.

## Four candidate conditions

1. **None:** no cross-task memory.
2. **Raw:** lexical retrieval of earlier observed trajectories.
3. **Consolidated:** local-model lessons generated from the same fixed
   development experience bank.
4. **Revised:** the same lesson bank, with explicit provenance/policy-version
   checks before retrieval.

The policy, agent, tools, user model, turn limits, and inference configuration
must otherwise match. Do not give the revised condition extra task-solving
rules. The UI's five hand-coded domain planners are excluded.

At present retrieval uses a **shared character cap**, not an exact Qwen-token
matched budget. Actual input/output tokens must be measured and reported.
Per-episode generation limits and the total study budget must be frozen.
Do not advertise this as an equal-token experiment without implementing and
verifying that constraint.

All model-produced lessons conservatively retain the actual source input set;
model-proposed citations cannot prove an omitted input had no influence.
Explicit AND/OR proof cases are software invariants, not a model's ability to
discover causal dependencies.

On the unchanged native tasks, consolidated and revised retrieval can be
identical. A difference should not be invented. Source-withdrawal or policy
changes must be a separately labeled intervention/extension, with sham and
preservation controls; they are not silently part of the native task set.

## Data separation and leakage requirements

- Fix a small development task set before main evaluation.
- Acquire the experience bank only from that set.
- Feed only observations, agent actions, tool responses, and explicitly
  permitted development feedback into the consolidator.
- Never feed reference actions, hidden goals, scorer explanations, or test
  outcomes into memory generation/retrieval.
- Check customer/order/entity overlap between learning and evaluation
  partitions before selecting main tasks. Independent tasks may share a
  database, so disjoint task IDs alone do not guarantee isolation.
- Reset the native environment and conversational state for every episode.
- Freeze memory for held-out transfer; do not silently learn from test
  failures. A later online-learning study requires a separate protocol.
- Include all failures/timeouts and retain request-start journals.

## Feasibility gate before registration

First establish native local-model task execution and user-simulator fidelity.
If the agent is at a performance floor, or local simulation is too slow or
unfaithful, request a provider/model and explicit spend budget rather than
claiming a memory effect from unusable baselines.

Only after that gate: implement/test the complete agent-memory integration,
freeze hypotheses/task manifest/analysis, commit and tag the actual protocol,
then run main experiments. Development is never retrospectively called
preregistration. The original task requires this gate, so no main study
should start merely because a loop can execute.

## Google Sleep connection

[Google Sleep Sections 3.2-3.4](https://arxiv.org/html/2606.03979v2#S3) concern
parameter expansion, Knowledge Seeding, distillation plus RL imitation, and
synthetic-curriculum self-improvement.

This proposed study concerns external experience consolidation and revision.
It tests a related functional question, not Google's algorithm. No weights
are trained and no Sleep reproduction is claimed. A later parametric track
would require an appropriate training setup and its own controlled protocol.

## Follow-up: staleness-aware memory (Stage A run; Stage B not requested)

A controlled synthetic diagnostic ([staleness.py](staleness.py),
[runner](staleness_runner.py)) asked whether provenance and validity metadata
stop an actor acting on seeded stale memory (None / Plain / Annotated; reset,
corrected, and still-valid regimes). Its owner-approved Stage A (36 dev
episodes, 74 requests, 1.07 credits) failed the pre-specified floor: every
episode looked up the account, no condition chose the stale value (Plain 0/8),
and all 12 still-valid episodes abstained rather than use unconfirmed memory.
Stage B (864 episodes) was not requested and no v2 tag exists.

## Follow-up: necessary-memory pilots and evaluation

Question: when the only record of an earlier agreement is the earlier
conversation, does giving the agent that transcript let it act correctly, and
does the v1 caution header suppress it? Approvals: pilots v1-v3 shared 240
requests (50-credit stop); v4 had a separate 264 requests (40-credit stop).
Evaluation is not approved. Code: [commitment_pilot.py](commitment_pilot.py), tests
[test_commitment_pilot.py](test_commitment_pilot.py).

| Element | Specification |
|---|---|
| Family | New synthetic customer with one delivered order of a train-only product (Gaming Mouse, Electric Toothbrush, Garden Hose, Pet Bed) that has ≥ 4 in-stock alternatives; added to an isolated copy of the pinned DB; target position among alternatives 0, 1, 2, 3; sealed manifest |
| Session 1 (no memory) | Scripted customer asks for alternatives, rejects one, names the target, and agrees only when the agent confirms that exact variant, deferring execution. Must change no DB |
| Session 2 | "Please go ahead with the exchange we agreed last time." Tools show variants, not the agreed one; the customer never restates it (refuses wrong proposals; answers clarifications with "we already agreed") |
| Arms | N: no history. Hc: session-1 dialogue under the exact v1 `MEMORY_HEADER`. Hn: same under "Previous-session transcript for this customer:". R: N plus the target restated (pilot-only feasibility control) |
| History | Session-1 customer/agent text only, no tool payloads, ≤ 8,000 characters, never truncated |
| Oracle | Success = normal completion + native DB equals the reference exchange + exchange arguments use the agreed variant + explicit confirmation before any mutation. Wrong-variant and unauthorized attempts counted |
| Caps and stops | ≤ 12 actor requests (1 counted re-ask) and ≤ 12 tools per session; per-approval request cap and settled-credit stop (above); v4 ran a smoke phase (C1/C2 session 1 + R, both R must succeed) before the rest; stop at any call > 1 credit, or billing mismatch; fatal stop on missing session-1 commitment, target leakage, invalid reference, or header mismatch; no retries except under the infrastructure policy below |
| Gates | Session-1 agreement 4/4; R 4/4; Hn ≥ 3/4; N ≤ 1/4; zero leakage; Hc descriptive. Any failure kills the line |

| Pilot result | Value |
|---|---|
| Sessions run | C1 session 1: commitment (7 requests, 1 re-ask). C2 session 1: no commitment (10 requests); fatal stop; 0 of 16 session-2 runs |
| Spend | 17 requests started and billed, 1.94 recorded credits (max call 0.17) |
| Verdict | **KILL** (session-1 gate failed). Not rerun |
| Cause | Harness defect, not agent behaviour: the agent confirmed the exact target by item ID, but its message also described the current item, so the scripted customer's option-value matcher also matched a rejected alternative and kept asking. Fixed offline (item IDs take precedence) with a regression test; the pilot outcome stands |
| v2 replay gate (2026-11-14, zero calls) | Replaying the recorded C1/C2 session-1 dialogues through the fixed customer: both now agree on the target. The sweep of every agent message still found the rejected alternative matched by option values in all 5 C2 confirmations (masked only because they carried IDs), and a candidate specificity rule collapsed plain option lists. Matching is now item-ID only (ID-less proposals get a request for the exact item ID; leakage checks still test option values). A Lead review then found target leakage by feedback (only the target got consent, so N could search by elimination); session-2 consent outside R is now target-blind, with a property test over every family, arm, and alternative |
| Pilot v2 (2026-11-14, harness `4a8f854`) | C1 session 1: explicit agreement on item 8214883393, DB unchanged (6 requests, 4 lookups). C2 session 1: its 4th request exceeded the 150 s per-call timeout and was aborted unbilled, so the session failed before any agreement; the fatal session-1 check (and the billing-mismatch stop) ended the pilot; 0 of 16 session-2 runs. 10 requests started, 9 billed, 0.86 recorded credits. Session-1 gate failed on a service timeout, not agent behaviour or a scripted-customer defect; not rerun |
| Infrastructure policy (`dea6b94`, before v3) | A failed session whose last model request got no response (per-call timeout, SDK/transport error, abort) is re-attempted once from scratch; a second is fatal; agent outcomes are never re-attempted. A journaled abort is charged 1.0 credit; an un-journaled mismatch still stops |
| Pilot v3 (2026-11-14) | No infrastructure failures; 176 requests, all billed, 21.32 credits. Session 1: 4/4 explicit agreements. Session 2 successes: N 0/4, Hc 0/4, Hn 0/4, R 2/4 (C3, C4); no wrong-variant or unauthorized attempts. Gates R and Hn failed: **KILL**. Descriptive only: all 8 Hc/Hn sessions first proposed exactly the agreed variant; N never singled one out |
| v3 cause | Harness logic, not agent behaviour: policy-compliant agents asked for an explicit yes after the customer's conditional consent ("If that's the one…"), and the confirmed customer could not answer a re-confirmation (it repeated its card or ended the call; "submitted" in future-tense text read as done). R's restatement lacked the item ID that ID-only matching needs. Fixed offline with regression tests: unconditional target-blind consent, a repeated explicit yes, one payment answer, past-tense completion only, R restates the item ID. Not rerun |

| Pilot v4 (2026-11-14, harness `2305ef6`) | Logic unchanged from fix `7111889`, which was designed after seeing v3's session-2 transcripts and is target-blind. Before any call: a replay of all 20 v3 dialogues and a synthetic sweep of confirmation styles (explicit yes, asking twice, payment then final check, "before I submit", summaries with and without IDs, choose-from-list) passed. Fresh session-1 runs. Smoke passed (C1/C2 R both succeeded). Full run: 20 sessions, 155 requests, all billed, 17.50 credits (max call 0.16), no infrastructure events. **All gates passed** |

Pilot v4, per family (successes; each cell: proposals before consent / lookups /
requests; every session 1 attempt, 0 wrong-variant, 0 unauthorized):

| Family | Session 1 | N | Hc | Hn | R |
|---|---|---|---|---|---|
| C1 | agreed (–/3/5) | fail (0/3/11) | ✓ (1/3/6) | ✓ (1/4/7) | ✓ (1/4/7) |
| C2 | agreed (–/4/6) | fail (0/3/11) | ✓ (1/3/6) | ✓ (1/3/6) | ✓ (1/5/10) |
| C3 | agreed (–/4/6) | fail (0/3/11) | ✓ (1/4/8) | ✓ (1/4/7) | ✓ (1/4/9) |
| C4 | agreed (–/4/6) | fail (0/3/11) | ✓ (1/3/6) | ✓ (1/4/7) | ✓ (1/4/9) |
| Total | 4/4 | 0/4 | 4/4 | 4/4 | 4/4 |

N agents said they had no record of an agreement and asked for the item; the
customer never named it, so N cannot succeed by construction. The pass shows the
task is solvable from the transcript and the caution header did not block it on
4 dev families; it is a feasibility check, not an effect estimate. Spend: v1-v3
203 of 240 requests (24.11 credits recorded, 25.11 charged); v4 155 of 264
(17.50 of the 40-credit stop).

Pilot v5 (provider integration; separate approval: 160 requests including both
provider shims, 25-credit stop; harness `c20f63e`):

| Element | Specification |
|---|---|
| Arms | M (Mem0) and Ho (Honcho), C1-C4; everything else as Hn (actor, policy, tools, customer, oracle, caps, neutral header) |
| Ingest | The frozen v4 session-1 dialogues (same text as Hn; SHA-256 in `plan.json`), no tool payloads or outcome line. Fresh scopes: Mem0 `user_id` `cmp-p5-<family>` in a new store directory, `run_id` per session; Honcho workspace `commitment-pilot-v5`, a peer per customer plus an agent peer, one session per conversation. Honcho deriver queue drained (two empty polls) before retrieval |
| Retrieval | Once, before the session, with the customer's first session-2 message. Mem0 library-default search (top_k 20; v1's `limit=10` was ignored by mem0 2.2.1, so unchanged). Honcho dialectic on the customer peer at the server default level, which is `low` at `5c7d24b` (the level v1 set explicitly). Rendered as in v1, capped at 8,000 characters; a retrieval error means no memory block |
| Gate (integration only) | Ingestion 4/4 per provider with the queue drained; retrieval without error ≥ 3/4 per provider; zero leakage outside the memory block; no harness-logic defect. Shim caps Mem0 14, Honcho 50, episodes ≤ 96 |

| Family | M: memory chars (ID / options) | M | Ho: memory chars (ID / options) | Ho |
|---|---|---|---|---|
| C1 | 522 (✓/✓) | ✓ (1/4/7) | 668 (✓/✓) | ✓ (1/4/10) |
| C2 | 877 (✓/✓) | ✓ (1/4/7) | 544 (✗/✓) | ✓ (1/4/7) |
| C3 | 747 (✓/✓) | ✓ (1/4/7) | 679 (✓/✓) | ✓ (1/4/7) |
| C4 | 1,056 (✓/✓) | ✓ (1/4/7) | 522 (✓/✓) | ✓ (1/4/7) |

Cells: whether the retrieved text contains the agreed item ID and all its option
values; outcome (proposals before consent / lookups / requests). Every session
had 1 attempt, 0 wrong-variant and 0 unauthorized attempts. In C2-Ho the memory
named the options but not the ID, and the agent resolved the ID from the product
catalogue. **Integration gate passed**: ingestion 4/4 each (Honcho queue 24/24
work units completed), retrieval 8/8 without error, zero leakage, no infrastructure
events. One Honcho dialectic call got a shim 502 (a forced tool call answered in
text twice); Honcho's client retried and the retrieval succeeded. v1 Honcho
workspaces and the v1 Mem0 store were unchanged (read-only counts and file hashes
before and after). Spend: 81 of 160 requests (episodes 59, Mem0 4, Honcho 18),
8.13 of 25 credits (max call 0.20). Descriptive only; no efficacy claim.

### Necessary-memory evaluation v1 (pre-specified before tag `commitment-eval-v1`)

| Element | Pre-specified |
|---|---|
| Approval | Owner, 2026-11-14 ~03:40 ET: one evaluation; hard cap 2,816 requests (episodes ≤ 2,304; Mem0 shim ≤ 112; Honcho shim ≤ 400); settled-credit stop 310 (journaled aborts charged 1.0); a single call > 1 credit or an un-journaled mismatch stops; infrastructure policy unchanged |
| Families | 32 fresh, generated only after the tag: seed = int(first 8 hex of SHA-256(tag commit SHA)), namespace `AE-COMMIT-EVAL-v1-<seed>`. Templates: train-only products (≥ 5 in stock, an ID in a train task, no product ID, item ID or name in any test task; 10 products, which drops the pilots' Pet Bed). Target position 0-3 balanced 8/8/8/8; names and IDs disjoint from the DB and C1-C4; reference exchanges validated offline; manifest hash in `plan.json` |
| Sessions | Session 1 per family → exclusion → ingestion (fresh scopes: Mem0 store under `eval-v1`, `user_id` `cmp-eval-<family>`; Honcho workspace `commitment-eval-v1`, queue drained) → one retrieval per provider arm → session-2 arms N, Hc, Hn, M, Ho in a seeded shuffled order recorded in `plan.json`. Harness as v4/v5; sources frozen at the tag (the runner refuses if any differ) |
| Unit; exclusion | Family. No explicit session-1 commitment → excluded from every arm, reported, not replaced |
| Outcome | Oracle success as in the pilots; any other status (contract failure, cap, incomplete) is a failure |
| Primary | Hn vs N, family-paired exact McNemar, two-sided α = 0.05 |
| Secondaries | M vs Hn, Ho vs Hn, Hc vs Hn; exact McNemar, Holm-adjusted across the three |
| Failure handling | One fresh re-attempt after an infrastructure failure; a second is a fatal stop. Ingestion error: recorded, retrieval proceeds; retrieval error: that session runs without memory and counts. A cap, credit or shim stop, leakage, or a harness-logic defect stops the run with no fix-and-continue; partial results are reported as partial |
| Power | Ceiling effects are expected: Hc, Hn, M and Ho were 4/4 in the pilots. A Holm-significant secondary needs ≥ 7 discordant families all in one direction, so secondaries detect only large losses and a non-significant secondary is not evidence of equivalence. The primary is expected to be large: N can succeed only by guessing an ID (≤ 1 in 4) |
| Descriptive | Wilson 95% intervals; retrieved-ID and option booleans; proposals before consent; lookups; requests and credits per session; whether the agent recovered when provider memory lacked the ID |
| Analysis | [commitment_analysis.py](commitment_analysis.py) only; public per-session CSV without transcripts, names or memory text |

| Evaluation v1 run (2026-11-14) | Status |
|---|---|
| Protocol | Tag `commitment-eval-v1` → `a2a2c1d` (CI green). Seed 529098645; manifest `dfad5449…`; 32 families, 192 planned sessions; 10-product template pool |
| Session 1 | 32/32 explicit commitments, DB unchanged; none excluded. 186 requests, all billed, 19.05 credits; no infrastructure events |
| **Stopped** | Harness-logic defect found before the provider phase: `final_reports()` matched only `C`-prefixed family IDs, so the session-1 reports of `E01`-`E32` were invisible to the exclusion check, H-arm histories and analysis. The runner would have refused at the next phase ("session 1 incomplete"), so no invalid data were produced. The pre-tag exclusion test passed vacuously. No session-2 arm ran; no provider service was started; v1 and v5 Mem0 stores unchanged (file hashes) |
| Deviation | Post-tag fix of report discovery only (pattern `[CE]`, plus a non-vacuous regression test); no change to scoring, prompts, customer, oracle, retrieval or analysis; no session-2 outcome existed |
| Amendment 1 (Lead decision under owner delegation, 04:25 ET) | Resume the same run; no regenerated families, no rerun of session 1; same approval and caps (the 186 requests count). Audit of family-ID and path assumptions found no other defect on the eval path (E01 reusing C1's street number in the synthetic address is cosmetic and left unchanged, since session 1 ran on it). An end-to-end dry pass over a copy of the real run (fake actor and gateway, zero calls; fails on `a2a2c1d`) covers exclusion, ingestion scopes, H-arm histories (hash-equal to the session-1 dialogue), retrieval, the 160 session-2 jobs in plan order, the ledger and the analysis (5 arms × 32). Tag `commitment-eval-v1-amend1`: sources frozen there; seed and manifest still from `commitment-eval-v1`; the runner refuses if any of the 66 recorded session-1 artifacts ([hashes](commitment-eval-v1-amend1-hashes.json), aggregate `be330f3d…`) differ. Any further harness defect stops the run |
| Providers | An operator error (a truncated output pipe) ended the first providers process after 13 Mem0 ingestions, all recorded and none in flight; it resumed from the ingestion ledger. Ingestion 64/64; Honcho queue 202/202; retrieval 64/64 without error (2 Honcho shim 502s retried by Honcho's client). v1 and v5 stores unchanged (Honcho counts, Mem0 hashes) |
| Session 2 | 125 of 160 sessions in plan order, then the pre-specified fatal stop: E19-Ho timed out at 150 s on both attempts. One other timeout (E03-N) recovered on its re-attempt. 35 planned sessions not run. Results and analysis: [RESULTS](RESULTS.md#necessary-memory-evaluation) |
| Spend | 1,365 of 2,816 requests (episodes 1,222 of 2,304; Mem0 shim 32 of 112; Honcho shim 111 of 400); 152.99 credits recorded, 155.99 charged (3 aborts) of 310; max call 0.20 |

### Changed-mind pilot

Owner-approved pilot only (2026-11-14 ~12:15 ET; evaluation not approved). Code:
[changed_mind.py](changed_mind.py) on the commitment-pilot harness; tests in
[test_commitment_pilot.py](test_commitment_pilot.py).

| Element | Specification |
|---|---|
| Question | When the customer changes their mind between sessions, does memory let the agent act on the latest agreement (Y) rather than the earlier one (X)? |
| Families | D1-D4, new namespace `AE-CHANGED-MIND-PILOT-v1` (seed from it), train-only template pool as eval v1; names and IDs disjoint from the DB, C1-C4 and E01-E32; Y at positions 0-3 once each, X two places after Y, rejected variant one after; Y and X reference exchanges validated |
| Session 1a | Agree X by item ID and defer (the commitment-pilot session-1 customer, target X) |
| Session 1b | Separate session, no memory for the actor: "I've changed my mind... I'd now like the <Y options>" (X never named); agent re-proposes X → "No, I changed my mind"; asks about the earlier item → "the one we agreed last time" without its ID; other or several IDs → asks for Y's exact ID; Y alone by ID → agree and defer; DB unchanged |
| Session 2 | "Please go ahead with the exchange we agreed last time"; target-blind consent outside R (one reply for X, Y or any single-ID proposal; property-tested); X never restated |
| Arms | Hn: 1a then 1b transcripts labelled "Earlier session (1 of 2)" and "Most recent session (2 of 2)" under the neutral header (≤ 8,000 characters). M: Mem0, 1a then 1b ingested for `user_id` `cmp-cm-p1-<family>`, `run_id` per session. Ho: Honcho workspace `changed-mind-pilot-v1`, 1a and 1b as two sessions of the same customer peer, queue drained. R: Y restated with its ID (harness control). One retrieval with the first session-2 message. N and Hc omitted from the pilot |
| Oracle | Success = Y executed (native DB = Y reference), consent first, no unauthorized mutation. **Stale commitment** = an exchange to X, counted separately from other wrong variants. Descriptive: retrieved memory contains Y's ID / X's ID |
| Leakage | X's ID or option set, like Y's, may appear only inside the memory block, in every arm including R |
| Budget | 240 requests total (episodes ≤ 188, Mem0 shim ≤ 12, Honcho shim ≤ 40); settled-credit stop 30; a single call > 1 credit, an un-journaled mismatch or a cap stops; journaled aborts charged 1.0 |
| Infrastructure rule (this design onward; not retroactive to eval v1) | One fresh re-attempt after an infrastructure failure; a second failure on the same session marks it failed (infra) and the run **continues**. Only budget, ledger, leakage or harness-logic stops halt the run |
| Gates (integration, not efficacy) | 1a and 1b agreements 4/4 each; R 4/4; ingestion and retrieval OK for ≥ 3/4 families per provider, Honcho queue drained; zero leakage outside memory; no harness defect. Hn, M and Ho outcomes are results, not gates |
