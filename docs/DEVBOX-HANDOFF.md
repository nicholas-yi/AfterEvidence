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
| Proposed next cohort | 12 one-per-family train tasks; **not approved, not preflighted, not run** |
| Latest laptop validation | 66 core/publication tests and 28 research tests passed; Ruff, research Pyright, and old-journal replay passed |
| Devbox environment | Vendor pins checked out; research venv **incomplete** (see below) |
| Main study | Not run, not preregistered; no demonstrated memory improvement |

Task 1 has no nonempty NL assertions or communication targets. Its task-basis
score is not an independent policy-compliance or conversation-quality
certificate. Tasks 0-4 share one customer (0 and 1 also share an order), so
they are not independent examples for a later split. The simulated dialogues interpreted
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

### Devbox setup status (2026-11-13)

On the Windows devbox, both vendor checkouts are at the exact pinned commits
and `research\.venv` exists, but the pinned packages are **not installed**:

- The devbox network fails the TLS handshake with `files.pythonhosted.org`
  for every client (uv, curl/Schannel, PowerShell). `pypi.org` metadata works.
- The machine-configured feed in `C:\ProgramData\pip\pip.ini` is reachable but
  lacks 11 pinned versions, apparently because it lags new releases:
  `fastapi 0.162.5`, `openai 3.50.0`, `click 8.5.1`, `typer 0.29.1`,
  `regex 2026.11.9`, `loguru 0.8.0`, `filelock 4.2.10`,
  `importlib-metadata 10.2.0`, `markdown-it-py 4.3.0`, `annotated-doc 0.0.6`,
  and `ruff 0.17.5`.
- No pin was relaxed and no insecure override was used. Choices that need the
  owner's decision: wait for the feed to carry the pins; use the HTTPS mirror
  the laptop used (see [design notes](../research/DESIGN.md#existing-environment-and-adapters));
  or certify a separately recorded devbox constraint set.

Until then, only dependency-free checks run here: the 66 core tests, the
memory/costing/task-audit research tests, and `research.task_audit`. Pyright
1.1.414 (exact pin, from the feed) reports 0 errors on the core project and
new audit files. Ruff was pre-checked with 0.17.4, the newest feed version;
public CI's 0.17.5 run is the formatting gate.

## Offline validation first

From the repository root, after research environment setup:

```powershell
.\research\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\research\.venv\Scripts\python.exe -m unittest research.test_memory_methods research.test_costing research.test_copilot_backend research.test_tau_action research.test_native_scoring -v
.\research\.venv\Scripts\python.exe -m ruff check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m ruff format --check afterevidence tests research scripts
.\research\.venv\Scripts\python.exe -m pyright --project research\pyrightconfig.json
.\research\.venv\Scripts\python.exe -m research.native_scoring --tasks 0 1 2
.\research\.venv\Scripts\python.exe -m research.task_audit
```

These commands send no model prompts. The final preflight command deliberately
returns exit code 1: tasks 0 and 1 validate; task 2 reports the known strict
reference failure. The corresponding unit test expects that failure. Do not
edit the benchmark or weaken validation merely to make all output green.

The public CI covers the core and dependency-free research controls, including
the task-audit tests, not the vendor-dependent native integration tests above.

## Next gate: proposed cohort awaiting approval

[The offline audit](../research/RESULTS.md#offline-task-audit-2026-11-13-devbox)
proposes train tasks **20, 35, 66, 69, 73, 75, 78, 80, 81, 82, 88, 91**: one per
customer family. Each is outside the exposed 0-4 family, shares no customer with
the test split, has valid reference IDs and a write action, and needs no NL judge.
The judge-free restriction is a disclosed scoring-coverage bias.

Before approval, the pinned environment must run zero-inference
`research.native_scoring --tasks ...` on them; drop any that fail and record why.
Planning estimate only: at the 30-request-per-task cap, 360 requests total. At
the follow-up's observed 0.103-0.110 credits/request, that is about **37-40 AI
credits (~$0.37-$0.40 allowance value)** with no judges. This is not a
guaranteed bound or an approval.

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
Task 2 fails strict reference preflight because its reference copies the
tool docstring's placeholder product ID. Tasks 0-4 are one customer; the
Google Home versus Google Assistant dialogue interpretation needs review.
This is not a reliable multi-task baseline or a memory-efficacy result.

Proceed offline: finish the pinned environment, then run zero-inference
native preflight on the proposed cohort in docs/DEVBOX-HANDOFF.md and record
any exclusions. Draft simulator-calibration checks and a customer-disjoint
held-out partition proposal. Keep hidden scoring criteria, reference actions,
and task_audit output out of actor/memory inputs. Do not inspect held-out test
outcomes for tuning or silently select only easy/passing tasks. Make useful
source/test/documentation improvements, but do not start model calls until I
approve a concrete cohort, total request cap (including actor, simulator,
retries and judges), and cost estimate.

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
