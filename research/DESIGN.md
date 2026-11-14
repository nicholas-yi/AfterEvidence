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

## Proposed follow-up: staleness-aware memory (approval pending; not tagged, not run)

Controlled synthetic diagnostic of stale-memory handling. Not a tau2 score, not
memory distilled from agent experience, does not re-test v1. Memory records are
seeded fixtures from [staleness.py](staleness.py). Motivation: Study 2 task 110,
where the agent trusted a remembered change instead of the live account, while
the stale target was still a valid option.

**Question:** does visible provenance and validity metadata stop the actor from
acting on stale memory? Nothing makes the answer true by construction: Plain and
Annotated carry the same records; only the metadata differs.

| Element | Specification |
|---|---|
| Family | One synthetic customer and attribute (shipping address or payment card) with 4 distinct values on file in seeded order (old, new, 2 decoys); eval families disjoint from dev |
| Episode | Request "use my default …" plus memory. The account is visible only through `lookup_account`; the actor ends with `submit_target` or `abstain`. At most 4 requests including one counted re-ask; lookup-before-submit is recorded. No user simulator |
| `current` | Store note (restored to epoch 2 at epoch 4) plus a valid post-restore record (epoch 5): the customer asked for new as default, not yet saved. No default on file; correct = new. Memory necessary (chance ≤ 0.25); Annotated can over-distrust valid memory |
| `reset` | Restore note; record m1 (epoch 3): default changed old → new, rolled back by the restore. Live default old; new still on file. Correct = old, obsolete = new |
| `corrected` | m1 superseded by m2 (epoch 4): default is old. Live default old; new on file. Correct = old, obsolete = new |
| Paid conditions | None / Plain (record text only, as v1 memory was) / Annotated (same records with id, session, epoch, supersession, and the restore note) |
| Filtered (offline control, no spend) | Annotated minus invalid records: superseded, or written in the rolled-back window `restored_to < epoch <= at_epoch`. Retrieval-time metadata only; unit-tested, including a valid post-restore record |
| Scorer | Deterministic normalized match: correct, obsolete, other, abstain; no terminal action = failed. Hidden labels never reach the actor |

| Decision (48 eval families are the unit) | Rule |
|---|---|
| Primary (the only test) | Family-mean (Plain − Annotated) obsolete rate over `reset` + `corrected` × 2 replicates ≥ 0.20 **and** one-sided 95% family bootstrap lower bound > 0 (10,000 resamples, seed 0) |
| Gate: positive control | `current`: family-mean correct rate Annotated − None ≥ 0.50 |
| Gate: non-harm | `current`: one-sided 95% lower bound of (Annotated − Plain) correct rate ≥ −0.10 |
| Descriptive only | Lookup-before-submit and abstention per condition; Plain and None obsolete rates; failures (not correct, not obsolete) |

| Stage (separate owner approvals) | Design | Episodes | Hard request cap | Credits |
|---|---|---:|---:|---|
| A: feasibility | 4 dev families × 3 regimes × 3 paid conditions × 1 | 36 | 144 | ≤ 36 at a conservative 0.25 per request |
| B: evaluation | 48 families × 3 × 3 × 2 replicates | 864 | 3,456 | Recomputed downward from Stage A's measured credits per request; never above 864 |

- Stage A is a pre-specified feasibility check, reported either way. If Plain
  chooses the obsolete value in 0 of its 8 `reset`/`corrected` episodes, Stage B
  is not requested as designed and the floor is reported. Stage A may fix only
  contract, parsing, or tool-mechanics bugs, never tune for effect; every change
  is logged. Then freeze, tag protocol v2, derive the eval seed from the tag
  commit (`eval_seed`; eval families do not exist before it), and only then
  request Stage B.
- Together at most 3,600 requests: about 413 credits at v1's historical mean
  (0.1147 per billed request), 900 at the conservative rate. Not a guaranteed
  cash cap: the runtime per-session credit limit cannot be set below 30
  credits, so it cannot enforce a tighter per-episode ceiling; study-level stop
  rules are the control. Stop at 825 settled credits, any single call above 1
  credit, or missing billing or a count mismatch (`ledger_stops`).
- Implemented and tested offline: generator, dev fixtures, tool environment,
  validity filter, scorer, decision rule, Stage A floor check, ledger checks,
  actor instructions, tool schema, and the serial episode runner
  ([staleness_runner.py](staleness_runner.py): dry run by default; one counted
  re-ask per episode; refuses to start on any stop reason). Nothing blocks
  Stage A except owner approval: `python -m research.staleness_runner --stage a
  --approved-requests 144`.
- Secondary, no spend planned: a semantic-deletion probe (paraphrased facts
  derived from a deleted source) would extend Study 3's literal-identifier check.
