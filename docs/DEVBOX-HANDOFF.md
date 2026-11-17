# Devbox handoff

Updated 2026-11-16. The research track's current state, how to rebuild it, and
the rules for resuming. Results are in [research results](../research/RESULTS.md);
costs in [costs](../research/COSTS.md); setup in
[research setup](../research/README.md#reproducibility-and-setup).

## Get the source

```powershell
git clone https://github.com/nicholas-yi/AfterEvidence.git
cd AfterEvidence
git status --short --branch
```

For an existing checkout, inspect local changes first and use
`git pull --ff-only` only when safe. Do not overwrite another machine's work.

## Current state

| Item | State |
|---|---|
| Memory study v1 | Tag `memory-study-v1`; Studies 1-3 complete; **null result** for task success, not equivalence ([results](../research/RESULTS.md#memory-study-v1)); test-split outcomes spent |
| Public evidence | Per-episode [CSV](../research/data/memory-study-v1-episodes.csv) reproduces every Study 1/2 table; CI test `research.test_memory_csv` |
| Staleness diagnostic | [Stage A](../research/DESIGN.md#follow-up-staleness-aware-memory-stage-a-run-stage-b-not-requested) run (36 dev episodes); floor check failed; Stage B not requested; no v2 tag |
| Necessary-memory pilot | [Pilot v4](../research/DESIGN.md#follow-up-necessary-memory-pilots-and-evaluation) passed all gates (Hn 4/4, Hc 4/4, R 4/4, N 0/4) after v1-v3 stopped on harness defects or a timeout; v5 (Mem0, Honcho) passed its integration gate (4/4 each). [Evaluation](../research/RESULTS.md#necessary-memory-evaluation) `commitment-eval-v1` (+ `-amend1`) ran partially (125 of 160 session-2 sessions; stopped by a second timeout): Hn 26/26 vs N 0/28; M 24/24, Ho 19/23, Hc 23/24. [Changed-mind evaluation](../research/RESULTS.md#changed-mind-evaluation) (tag `changed-mind-eval-v1`, 31 families): Hn 30/31; M 13/31 with 13 stale; Ho 3/31 and Hoh (`max`) 2/31, mostly declining. Dated dev check (4 families): Hn-dated 4/4, M-inband 3/4 (1 stale), Ho-dated 0/4. [Dated evaluation](../research/RESULTS.md#dated-changed-mind-evaluation) (tag `changed-mind-dated-eval-v1`, 31 families): Hn 29/31; M 17/31 (9 stale) and Mi 17/31 (5 stale); Ho 3/31 and Hod 8/31, mostly declining; neither date treatment significant. [Honcho features](../research/RESULTS.md#honcho-features-evaluation) (tag `honcho-features-eval-v1`, 32 families): Honcho message search 14/32 vs dialectic 8/32 (not significant); with a customer who names the item when asked, no memory 32/32, transcripts 32/32, Honcho 27/32, Mem0 30/32 (2 superseded items executed); nothing significant |
| Simulator review | No human review yet. Private worksheets and CSV indexes for all 602 memory-study episodes, with a proposed default sample, in `research/runs/memory-study/review/` |
| Memory-study stack | Docker (Neo4j, Hindsight, Honcho), Ollama embeddings, provider venv, shims, and gateway on the devbox, stopped with data retained ([runbook](../research/MEMORY-STUDY.md)) |
| Devbox environment | Exact 81-entry lock reproduced; offline checks pass |
| Earlier baselines | Cohort, audits, and pilots: [development history](../research/RESULTS.md#development-history) |

Usage: devbox cohort 162 of 360 approved requests / 16.05978 credits; memory
study 12,428 of 16,000 started / 1,425.05 recorded credits (8 aborted requests
unbilled); staleness Stage A 74 of 144 / 1.07 credits; necessary-memory pilots
v1-v3 203 of 240 / 24.11 credits (one unbilled), v4 155 of 264 / 17.50 credits; v5 81 of 160 / 8.13 credits (incl. provider shims); evaluation 1,365 of 2,816 / 152.99 (155.99 charged); changed-mind pilot 209 of 240 / 23.07; Honcho `max` check 53 of 100 / 6.53; changed-mind evaluation 2,118 of 3,120 / 239.15; dated dev check 132 of 200 / 15.09; dated evaluation 2,197 of 3,408 / 243.38; Honcho features 327 of 350 + 200 (Stage 1, 1b) / 37.84 and 2,286 of 3,000 / 259.08.
Cumulative about **21,848 requests / 2,475.08 credits** (about $24.75),
allowance measurements,
not invoices. Unused allowance never authorizes new inference.

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
- No power hold, local server, browser, or chat process migrates with Git.

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
.\research\.venv\Scripts\python.exe -m unittest research.test_memory_methods research.test_costing research.test_copilot_backend research.test_tau_action research.test_native_scoring research.test_task_audit research.test_simulator_review research.test_memory_study research.test_memory_csv research.test_staleness research.test_staleness_runner research.test_commitment_pilot -v
.\research\.venv\Scripts\python.exe -m ruff check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m ruff format --check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m pyright --project research\pyrightconfig.json
.\research\.venv\Scripts\python.exe -m research.native_scoring --tasks 0 1 2
.\research\.venv\Scripts\python.exe -m research.task_audit
```

These send no model prompts. `native_scoring` deliberately exits 1: tasks 0
and 1 validate; task 2 reports the known strict reference failure, which a unit
test expects. Do not weaken validation to make output green. Public CI runs the
core and dependency-free research tests, not the SDK- or vendor-dependent ones.

## Next gates

1. Human review of simulator fidelity from the private packet (decisions in
   [results](../research/RESULTS.md#remaining-gates-and-next-steps)).
2. Any new study (staleness redesign, more power, another retrieval style)
   needs a committed, tagged protocol and explicit approval of design, total
   request cap (actor, simulator, providers, retries, judges), and cost.
3. An approved, validated NL-assertion judge before judge-needing tasks.

## Working rules

- Never tune on spent test-split outcomes; preserve failures and null results.
- Keep hidden scoring criteria, reference actions, and `task_audit` output out
  of actor and memory inputs.
- Keep the flat `WireCommand` contract, old-journal decoding, fail-before-inference
  reference checks, explicit incomplete statuses, SDK tool isolation, and
  complete cost accounting. Nonempty NL assertions stay visibly unassessed
  without an approved evaluator.
- No Google-style Sleep training is implemented; do not claim one.
- Never push raw runs, account data, provider state, or credentials, and never
  expose the local HTTP server.

## Private evidence is not in this clone

Git excludes `research/runs/`, `data/`, `results/`, vendor checkouts, virtual
environments, caches, runtimes, and account state. The devbox keeps the
`cohort-20261113b-*` files, everything under `research/runs/memory-study/`
(bank, memory artifacts, study reports and journals, shim journals, `review/`
packet, provider Docker volumes), `research/runs/staleness/stage-a/`, and
`research/runs/commitment/pilot/`, `pilot-v2/`, `pilot-v3/`, `pilot-v4/`, `eval-v1/`, `cm-pilot-v1/`, `cm-hoh-v1/`, `cm-eval-v1/`, `cm-dated-v1/`, `cm-dated-eval-v1/`, `hf-dev-v1/`, `hf-dev-v2/`, `hf-eval-v1/` and `pilot-v5/` (its own Mem0 store and gateway config; Honcho workspace `commitment-pilot-v5` in the stopped Honcho volume).
Provider secrets live in git-ignored `research/providers/`. The source laptop
keeps the `research/runs/baseline-20261113-*` plan, amendments, task reports
and journals, summary, and earlier pilot evidence.

Journals can contain prompts and quota snapshots: transfer only needed files
over an approved private channel. Do not reconstruct missing logs, rerun spent
calls, or claim a historical replay on a fresh clone.

## Resuming after sleep or a closed chat

A saved chat is not a running process: local inference, scripts, and network
connections can pause or drop when the machine sleeps. To resume, reopen the
repository, read the results rather than the chat, and inspect the last run's
journal. A `started` request without a completed billing record is unknown
usage, not a free or successful call. The drivers refuse existing output paths;
start a fresh, labeled attempt only after accounting for the earlier one.

[keep-awake.ps1](../scripts/keep-awake.ps1) holds automatic idle sleep for a
bounded time while its terminal stays open (display may still turn off; releases
on AC disconnect unless `-ContinueOnBattery`). It cannot detect when a chat
finishes and does not override manual sleep, lid close, or critical battery.

```powershell
.\scripts\keep-awake.ps1 -Minutes 120
.\scripts\keep-awake.ps1 -Status
.\scripts\keep-awake.ps1 -Stop
```

Truly unattended work needs an approved always-on machine with durable logging;
nothing here starts one.
