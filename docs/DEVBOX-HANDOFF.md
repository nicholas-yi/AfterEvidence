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
| Task 2 diagnosis | Offline audit: the failing ID is the tool docstring's placeholder, shared by sibling tasks 2-4 |
| Entity overlap | Tasks 0-4 are one customer; 38 of 74 train tasks share a customer with the test split |
| Reference policy | v2: only scripted, non-mutating "not found" lookups may fail; train preflight 70 validated, 4 rejected |
| Devbox cohort | 12 approved tasks run once: **9 scored 1.0**, 3 failed the action contract; 162 of 360 requests; replay agreed |
| Simulator review | Worksheets generated; AI-assistant preliminary pass done; **human confirmation pending** |
| Latest laptop validation | 66 core/publication tests and 28 research tests passed; Ruff, research Pyright, and old-journal replay passed |
| Devbox validation | Exact 81-entry lock reproduced; core, research, Ruff 0.17.5, and research Pyright checks pass; preflight 0/1/2 matches laptop |
| Main study | Not run, not preregistered; no demonstrated memory improvement |

Task 1 has no nonempty NL assertions or communication targets. Its task-basis
score is not an independent policy-compliance or conversation-quality
certificate. Tasks 0-4 share one customer (0 and 1 also share an order), so
they are not independent examples for a later split. The pinned catalog has no
"Google Home" thermostat; the reference uses the Google Assistant variant
([analysis](../research/RESULTS.md#google-home-versus-google-assistant-tasks-0-and-1)).
A matching database still does not establish simulator fidelity.

The devbox cohort used **162 of 360 approved requests** and **16.05978 AI
credits** (about $0.16 in allowance value). Cumulative Copilot usage is
**220 requests / 22.09146 credits**. These are not separate API invoices.
The unused 198 requests are not permission to change the cohort, retry tasks,
add judges, switch models, or start a main study. Obtain explicit approval for
the next inference plan.

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

### Restricted-network setup (validated on the devbox, 2026-11-13)

The Windows devbox fails the TLS handshake with `files.pythonhosted.org` for
every client (uv, curl/Schannel, PowerShell); `pypi.org` metadata works. Its
machine-configured feed (`C:\ProgramData\pip\pip.ini`) lagged 11 pins:
`fastapi 0.162.5`, `openai 3.50.0`, `click 8.5.1`, `typer 0.29.1`,
`regex 2026.11.9`, `loguru 0.8.0`, `filelock 4.2.10`,
`importlib-metadata 10.2.0`, `markdown-it-py 4.3.0`, `annotated-doc 0.0.6`,
and `ruff 0.17.5`.

No pin was relaxed and TLS verification stayed on:

1. For each missing pin, read the official SHA-256 from
   `https://pypi.org/pypi/<name>/<version>/json`, download the matching
   `py3-none-any` or `cp312-win_amd64` wheel from the same path on the HTTPS
   Tsinghua mirror ([design notes](../research/DESIGN.md#existing-environment-and-adapters)),
   and keep it only if its SHA-256 equals PyPI's. All 11 matched.
2. Install from the configured feed plus that local wheel directory:

   ```powershell
   uv pip install --native-tls --index-url <configured feed> --find-links <verified wheels> `
     --python .venv\Scripts\python.exe -r requirements.txt -c dependencies.lock.txt
   ```

3. Compare `uv pip freeze` with `dependencies.lock.txt`: all 81 entries matched
   exactly, with no extras.

The `pyright` wrapper could not download Node.js here. The same
`pyright==1.1.414` with its `[nodejs]` extra, installed in a separate tool
environment, ran `--project research\pyrightconfig.json` against the locked
venv. That tool environment is not part of the research lock.

## Offline validation first

From the repository root, after research environment setup:

```powershell
.\research\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\research\.venv\Scripts\python.exe -m unittest research.test_memory_methods research.test_costing research.test_copilot_backend research.test_tau_action research.test_native_scoring research.test_task_audit research.test_simulator_review -v
.\research\.venv\Scripts\python.exe -m ruff check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m ruff format --check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m pyright --project research\pyrightconfig.json
.\research\.venv\Scripts\python.exe -m research.native_scoring --tasks 0 1 2
.\research\.venv\Scripts\python.exe -m research.task_audit
```

These commands send no model prompts. The `native_scoring` preflight deliberately
returns exit code 1: tasks 0 and 1 validate; task 2 reports the known strict
reference failure. The corresponding unit test expects that failure. Do not
edit the benchmark or weaken validation merely to make all output green.

The public CI covers the core and dependency-free research controls, including
the task-audit and simulator-review tests, not the vendor-dependent native
integration tests above.

## Next gate: decisions after the devbox cohort

[The cohort results](../research/RESULTS.md#development-cohort-run-2026-11-13-devbox)
show nine valid scored episodes and three actor action-contract failures.
Decisions needed before more inference:

1. Whether to change the adapter's malformed-action handling (for example one
   bounded, counted re-ask), then rerun a fresh, separately approved cohort.
2. A human confirmation of the simulator worksheet
   (`research/runs/cohort-20261113b-simulator-review.md`, devbox only).
3. Committing the [held-out partition](../research/RESULTS.md#held-out-partition-proposal)
   and judge policy for the 11 judge-needing test tasks into a tagged protocol.

Experience-bank construction from the nine scored episodes is offline work, but
it must use only observations and actions, never references or scorer output.

## Private evidence is not in this clone

Git intentionally excludes `research/runs/`, `data/`, `results/`, vendor
checkouts, virtual environments, caches, runtimes, and account state.
The devbox retains the `cohort-20261113b-*` plan, reports, journals, summary,
and simulator worksheet. The source laptop retains:

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

Known evidence: on the devbox, an approved 12-task cohort (one customer family
each, customer-disjoint from the test split, judge-free) scored native
ENV/task-basis reward 1.0 on 9 tasks; 3 failed the flat action contract early.
Zero-inference replay agreed. Task 2 is still rejected by reference preflight
(copied placeholder product ID). Reference policy v2 allows only scripted,
non-mutating failed lookups. The simulator worksheet awaits human review.
This is a single-seed development baseline, not a memory-efficacy result.

Proceed offline: confirm the environment and offline checks, then work on the
next-gate items in docs/DEVBOX-HANDOFF.md: options for malformed actor actions,
the held-out partition and judge policy as protocol drafts, and experience-bank
construction from observations and actions only. Keep hidden scoring criteria,
reference actions, and task_audit output out of actor/memory inputs. Do not
inspect held-out test outcomes for tuning or silently select only easy/passing
tasks. Make useful source/test/documentation improvements, but do not start
model calls until I approve a concrete cohort, total request cap (including
actor, simulator, retries and judges), and cost estimate.

The devbox cohort allowance was 360 requests; 162 were used. Its unused 198
are not blanket authorization. Cumulative usage is 220 requests / 22.09146 AI
credits. Raw journals and quota records are private and not in Git. Ask for the
needed private evidence before historical replay or lesson extraction; do not
invent or automatically regenerate it.

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
