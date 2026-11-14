# Agent memory research track

This is separate from the local UI demonstration.

The research question is whether memory distilled from actual prior agent
experience improves later tool-use task outcomes, without retaining unsupported
lessons after evidence changes.

## What is verified so far

- Official MIT `tau2-bench` source pinned at
  `c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4`.
- Its native retail runtime initializes with sixteen tools.
- One native local-Qwen development conversation completed in 400.968 seconds,
  made real tool calls, and received **ENV reward 0**. This is not a full official
  task score and says nothing yet about a memory intervention.
- A three-request Copilot micro-pilot completed in 11.75 seconds using enabled
  Claude Haiku 5.5, native user instructions/policy, and no hidden reference
  actions. It did **not** complete or score a whole task.
- Its recorded consumption was **0.1135835 AI credits**, about **$0.001136 in
  credit value**, not a separate paid API invoice.
- The subsequently authorized full-conversation development allowance was
  capped at **20 requests total**. Two exposed an unstructured-action failure;
  eighteen ran the repaired structured-action adapter and performed a real
  native exchange, but reached the cap before conversation termination.
  That attempt did not produce a completed task score.
- Those initial 23 completed Copilot requests consumed **2.4402365 AI credits**,
  about **$0.024402 in credit value**. Every failed/capped attempt remains logged.
- A subsequent bounded development cohort produced one normally completed
  task-1 episode with native ENV/task-basis reward **1.0**, reproduced by fresh
  zero-inference replay. Two preceding schema failures remain counted; task 2
  was blocked before inference by a strict reference-replay error.
- This follow-up used **35 of 90 authorized requests**, **3.5914435 AI credits**,
  about **$0.035914 in credit value**. Cumulative Copilot usage was then **58 requests
  and 6.03168 credits**. A single completed sibling task is not an accuracy or
  memory-efficacy estimate; simulator interpretation still needs calibration.
- A 12-task development cohort on the devbox (one customer family each,
  customer-disjoint from the test split) scored native ENV/task-basis reward
  **1.0 on 9 tasks**; 3 failed the actor action contract early. It used
  **162 of 360 approved requests** and **16.05978 AI credits**. Cumulative
  usage is **220 requests and 22.09146 credits**. This is a single-seed,
  judge-free development baseline, not an accuracy or memory-efficacy result.
- Reference preflight now allows only scripted, non-mutating failed lookups
  (policy v2); unscripted and business-rule failures are still rejected.
- **Memory study v1** ([protocol](PROTOCOL-MEMORY.md), [results](RESULTS.md#memory-study-v1)):
  nine memory conditions (none; raw transcripts; one-pass lessons; a sleep-style
  replay/reweight/prune analogue; induced workflows; Mem0; Graphiti; Hindsight;
  Honcho) on 26 test tasks × 2 runs showed **no detectable effect on task
  success** (75% without memory vs 73-83% with; all Holm p = 1.0). Same-customer
  memory was slightly worse than none (not significant), with a clear loss from
  stale remembered facts. A deletion probe found no literal identifiers of the
  deleted conversation afterwards (Honcho only on a recheck). Total 12,428
  requests started; 1,425.05 AI credits recorded.
- The source-aware retrieval/accounting/isolation/action-parser tests pass.

No four-condition result from the original design exists; the memory study
replaced it. Do not treat the application examples or software invariants as
agent-learning evidence.

## Files and commands

- [Design and selection audit](DESIGN.md).
- [Cost estimates and resource boundaries](COSTS.md).
- [Actual feasibility outcomes and remaining gates](RESULTS.md).
- [Benchmark and SDK pins](benchmark-lock.json).
- [Non-editable dependency constraints](dependencies.lock.txt), combined with the source pins.
- [Source-aware memory controls](memory_methods.py).
- [Native scorer preflight and assessment](native_scoring.py).
- [Zero-inference task/customer overlap and reference-ID audit](task_audit.py).
- [Zero-inference simulator-calibration worksheets](simulator_review.py).
- [Offline fixtures, scorer and stop rules for the proposed staleness diagnostic](staleness.py)
  (approval pending; see [design](DESIGN.md)).
- Memory study: [protocol](PROTOCOL-MEMORY.md), [runbook](MEMORY-STUDY.md),
  [Copilot shim](copilot_shim.py), [provider gateway](memory_gateway.py),
  [memory builders](memory_bank.py), [retrievers](memory_retrievers.py),
  [runner](study_runner.py), [Study 1](study1.py), [Study 2](study2.py),
  [Study 3](lifecycle.py), [analysis](memory_analysis.py) and
  [Study 2 analysis](study2_analysis.py), [providers lock](providers.lock.txt).
- [Native local-model feasibility driver](tau_pilot.py).
- [Three-request SDK micro-pilot](copilot_micro.py).
- [Full native-environment Copilot pilot driver](tau_copilot.py),
  exercised through a complete native-scored development conversation, but not
  yet a reliable multi-task actor/simulator baseline.

From the project root:

```powershell
python -m unittest research.test_memory_methods research.test_costing research.test_task_audit research.test_simulator_review research.test_memory_study -v
.\research\.venv\Scripts\python.exe -m unittest research.test_copilot_backend research.test_tau_action research.test_native_scoring -v
.\research\.venv\Scripts\python.exe -m pyright --project research\pyrightconfig.json
.\research\.venv\Scripts\python.exe -m research.native_scoring --tasks 0 1 2
python -m research.task_audit
.\research\.venv\Scripts\python.exe -m research.copilot_quota
.\research\.venv\Scripts\python.exe -m research.costing research\runs\copilot-micro-04.jsonl
.\research\.venv\Scripts\python.exe -m research.replay_partial research\runs\copilot-native-structured-feasibility-0.calls.jsonl
```

Commands that consume model allowance require the explicit pilot request cap:

```powershell
.\research\.venv\Scripts\python.exe -m research.copilot_micro --output research\runs\NEW-micro.jsonl
.\research\.venv\Scripts\python.exe -m research.tau_copilot --task 0 --requests 20 --output research\runs\NEW-native-pilot.json
```

These are opt-in examples, not standing authorization or a registered
main experiment. A quota check is not a promise that billing settings prevent
overages; verify the account's stop-on-budget settings.

The zero-inference preflight command deliberately exits nonzero for the pinned
task 2 reference lookup failure. It reports every selected task; do not silently
drop that result or treat a reference-control trajectory as agent success.

## Methodological boundaries

- Native ENV scoring compares actual database states. It is not replaced by
  matching one expected tool-call list.
- Some official tasks additionally require communication and policy assertion
  checks; ENV-only success is not a full official pass.
- The Copilot driver uses a custom JSON-action adapter with native task/tools
  and scoring. It is not the unchanged upstream model agent.
- Copilot sessions have no built-in tools, custom instructions, skills,
  persistent memory, or repository-context retrieval. Native benchmark tools
  are executed only by the benchmark orchestrator.
- No evaluation reference actions or hidden criteria are supplied to the
  actor or memory.
- The official training split is used for development only. No official test
  outcome has been used for tuning in this track.
- Main task/entity separation, memory-bank construction, full-condition
  integration, analysis, and commit/tagged preregistration remain required.
- Source withdrawal is a separately labeled extension, not a native
  benchmark feature or a proven novel contribution.

## Reproducibility and setup

The research environment requires Python 3.12 and is separate from the
dependency-free application. The validated native setup is Windows; other
platforms are not certified by the current runs.

Create separate checkouts at the exact revisions in `benchmark-lock.json`:

```powershell
git clone --no-checkout https://github.com/sierra-research/tau2-bench.git research\vendor\tau2-bench
git -C research\vendor\tau2-bench checkout --detach c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4
git clone --filter=blob:none --sparse https://github.com/github/copilot-sdk.git research\vendor\copilot-sdk
git -C research\vendor\copilot-sdk sparse-checkout set python
git -C research\vendor\copilot-sdk checkout --detach ed814e4134fdba86e2e88b82dcac85b1c125ed8a
cd research
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt -c dependencies.lock.txt
.\.venv\Scripts\python.exe -m copilot download-runtime --version 1.0.111-0
cd ..
copilot login
```

The official SDK installer checks its runtime release checksums. If a
certificate/proxy setup is required, use your OS trust configuration; never
disable TLS verification. The local development installation used a public
PyPI mirror after the default file host failed TLS negotiation.

The connector defaults to the matching Windows managed-cache path. An explicitly
verified runtime at another location can be selected with
`AFTEREVIDENCE_COPILOT_RUNTIME`; this is a path, not a credential. Do not select
an arbitrary executable or claim another runtime version is an equivalent pin.

Both vendor repositories are separate git-ignored checkouts. Preserve their
licenses and exact revisions. Runtime credentials are handled by supported
Copilot sign-in, never extracted from VS Code or committed.

The initial old CLI/SDK combination was incompatible with current model
metadata. The setup now uses the official pinned SDK source and matching
1.0.111-0 runtime, downloaded by the SDK with checksum verification. Windows
system certificate trust was used; certificate verification was never disabled.
The user's standalone CLI was updated and signed in by the user.

Results, per-call journals, quota snapshots, and account data stay under the
git-ignored `research/runs` directory. They are not public artifacts or
permanent user memories. No API plan was purchased, no API key was requested
in chat, and no main-study efficacy result exists.
