# Devbox handoff

Updated 2026-11-13. This is a development handoff, not a preregistration or a
completed memory-efficacy study.

## Get the source

```powershell
git clone https://github.com/nicholas-yi/AfterEvidence.git
cd AfterEvidence
git status --short --branch
```

For an existing checkout, inspect local changes first, then use
`git pull --ff-only` only when safe. Do not overwrite another machine's work.

Read [research results](../research/RESULTS.md), [costs](../research/COSTS.md),
and [research setup](../research/README.md#reproducibility-and-setup).
The app and the research harness are separate tracks. No new UI demo is needed.

## Exact stopping point

| Item | State |
|---|---|
| Application | Implemented local Ollama workspace; model output still needs human review |
| Baseline task 0 | New attempt stopped after 14 requests on a message carrying a placeholder tool name; no completed score |
| Baseline task 1 | Nested-schema attempt failed after 4 requests; flat-schema repair completed after another 17 |
| Completed episode | Normal `USER_STOP`; native ENV and task-basis rewards 1.0; fresh zero-inference replay agreed |
| Baseline task 2 | Strict reference action 2 raises "Product not found"; zero model calls, no replacement task |
| Latest validation | 66 core/publication tests and 28 research tests passed; Ruff, research Pyright, and old-journal replay passed |
| Main study | Not run, not preregistered; no demonstrated memory improvement |

Task 1 has no nonempty NL assertions or communication targets. Its task-basis
score is not an independent policy-compliance or conversation-quality
certificate. Tasks 0 and 1 share a customer and order, so they are not
independent examples for a later split. The simulated dialogues interpreted
Google Home versus Google Assistant differently; simulator calibration remains
a real gate, not something a matching database resolves.

The latest follow-up used **35 of 90 authorized requests**, counting failures.
It consumed **3.5914435 AI credits**, about **$0.035914435 in allowance value**.
Cumulative Copilot usage is **58 requests / 6.03168 credits**. These are not
separate API invoices. The remaining 55 requests are not permission to change
the cohort, add judges, switch models, or start a main study. Obtain explicit
approval for the next inference plan.

## Rebuild, do not copy the environment

- Research requires Python 3.12 and the exact separate vendor checkouts in
  [benchmark-lock.json](../research/benchmark-lock.json).
- Benchmark: `c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4`.
- SDK: `ed814e4134fdba86e2e88b82dcac85b1c125ed8a`.
- Matching SDK runtime: **1.0.111-0**. Do not replace these with "latest".
- Follow the research setup commands. Install `requirements.txt` together with
  `dependencies.lock.txt` from the research directory; then install root dev
  tools into that environment if needed:

  ```powershell
  uv pip install --python research\.venv\Scripts\python.exe ".[dev]"
  ```

- The validated setup is Windows. Check the devbox OS before choosing commands.
  Other platforms need their own interpreter paths, dependency validation, and
  matching runtime discovery; they are not certified by the Windows results.
  The connector accepts `AFTEREVIDENCE_COPILOT_RUNTIME` for an explicitly
  verified executable path.
- Use supported Copilot sign-in on the devbox when new access is approved.
  Never copy credentials, extract editor tokens, disable TLS verification,
  or put an API key in chat. No new provider purchase is authorized.
- No local model weights are bundled. Do not download models automatically.
- No laptop power hold, local server, browser, or chat process migrates with Git.
  The temporary laptop lid override ended and the original settings were restored.

## Offline validation first

From the repository root, after research environment setup:

```powershell
.\research\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\research\.venv\Scripts\python.exe -m unittest research.test_memory_methods research.test_costing research.test_copilot_backend research.test_tau_action research.test_native_scoring -v
.\research\.venv\Scripts\python.exe -m ruff check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m ruff format --check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m pyright --project research\pyrightconfig.json
.\research\.venv\Scripts\python.exe -m research.native_scoring --tasks 0 1 2
```

These commands send no model prompts. The final preflight command deliberately
returns exit code 1: tasks 0 and 1 validate; task 2 reports the known strict
reference failure. The corresponding unit test expects that failure. Do not
edit the benchmark or weaken validation merely to make all output green.

The public CI covers the core and dependency-free research controls, not the
vendor-dependent native integration tests above.

## Private evidence is not in this clone

Git intentionally excludes `research/runs/`, `data/`, `results/`, vendor
checkouts, virtual environments, caches, runtimes, and account state.
The source laptop retains:

- `research/runs/baseline-20261113-plan.json`.
- `research/runs/baseline-20261113-amendment-1.json` and `-2.json`.
- `research/runs/baseline-20261113-task-0.json` and its `.calls.jsonl`.
- `research/runs/baseline-20261113-task-1.json` and its `.calls.jsonl`.
- `research/runs/baseline-20261113-task-1-repaired.json` and its `.calls.jsonl`.
- `research/runs/baseline-20261113-summary.json` and the earlier pilot evidence.

The committed reports preserve the summaries, not independently inspectable raw
evidence. If exact historical replay or experience extraction is required,
request a private transfer of only the necessary run files. Journals can include
prompts and account/quota snapshots: review access and use an approved private
channel, never the public remote. Do not reconstruct missing logs, silently
rerun spent calls, or claim a historical replay on a fresh clone.

## Prompt to paste into the devbox agent

```text
Continue AfterEvidence in this checkout. Read docs/DEVBOX-HANDOFF.md,
research/RESULTS.md, research/COSTS.md, research/README.md, and
research/benchmark-lock.json before editing. Check Git status and preserve
existing changes.

My goal is credible research on whether external memory distilled from real
agent experience improves later tool-use tasks while handling corrections and
withdrawn evidence. Do not build another UI demo or claim Google Sleep training:
no parameter expansion, Knowledge Seeding, or RL dreaming was implemented.

Resume the baseline gate, not the main study. First recreate the exact pinned
research environment for this devbox's OS and run the offline checks in the
handoff. Do not copy a virtualenv or credentials from the laptop.

Known evidence: task 1 completed with native ENV/task-basis reward 1.0 and
zero-inference replay agreed. Two preceding format failures remain counted.
Task 2 fails strict reference preflight. Tasks 0 and 1 share a customer/order;
the Google Home versus Google Assistant dialogue interpretation needs review.
This is not a reliable multi-task baseline or a memory-efficacy result.

Proceed with offline development: inspect task 2's reference-artifact mismatch
without changing the pinned vendor, and audit train-only task/customer/order
overlap to propose independent development episodes and simulator-calibration
checks. Keep hidden scoring criteria and reference actions out of actor/memory
inputs. Do not inspect held-out test outcomes for tuning or silently select
only easy/passing tasks. Make useful source/test/documentation improvements,
but do not start model calls until I approve a concrete cohort, total request
cap (including actor, simulator, retries and judges), and cost estimate.

The prior allowance was 90 requests over tasks 0,1,2; 35 were used. Its unused
55 are not blanket authorization for a new cohort. Cumulative usage is 58
requests / 6.03168 AI credits. Raw journals and quota records are private and
not in Git. Ask for the needed private evidence before historical replay or
lesson extraction; do not invent or automatically regenerate it.

Keep the current flat WireCommand action contract and its regression tests.
Preserve old-journal decoding, fail-before-inference reference checks, explicit
incomplete statuses, SDK tool isolation, complete cost accounting, and native
scoring. A pending nonempty NL assertion must stay visibly unassessed unless
an evaluator is separately approved.

Do not run a main experiment until actor/simulator adequacy, held-out entity
separation, actual experience-bank construction, four-condition integration,
scoring coverage, and a committed/tagged prospective protocol are ready.
Preserve failures and null results. Report what is verified and what is blocked.
Never push raw run/account data or publish the local HTTP server.
```
