# Agent memory research track

This is separate from the local app. It asks whether agent memory helps an agent act correctly
on tau2-bench retail tasks, whether stale memory misleads it, and whether deletion removes what was
derived from a conversation. Twenty pre-registered studies are complete; their tables, deviations and
history are in [RESULTS](RESULTS.md), designs in [DESIGN](DESIGN.md), usage in [COSTS](COSTS.md).
Every published table is recomputed from a public CSV in CI (`python -m research.benchmark verify`).

## Code map

| Folder | What it holds |
|---|---|
| [benchmark.py](benchmark.py), [published.py](published.py), [figures.py](figures.py) | The public benchmark: `list` the studies and `verify` every published number and figure against the [public CSVs](data/) (no model calls; CI runs it) |
| [analysis/](analysis/) | One pre-specified analysis per study (CSV or private run to table), sharing [common.py](analysis/common.py) (rows, cohort, paired tests, command line) and [stats.py](analysis/stats.py) (exact McNemar, Holm, Wilson) |
| [harness/](harness/) | What every study runs on: [commitment_pilot.py](harness/commitment_pilot.py) (families, scripted customer, actor loop, oracle, leakage checks, budget ledger, infrastructure rule, provider retrieval), [memory_gateway.py](harness/memory_gateway.py) (Mem0, Graphiti, Hindsight, Honcho behind one HTTP API), [copilot_shim.py](harness/copilot_shim.py) and [copilot_backend.py](harness/copilot_backend.py) (capped, journaled model access and quota guard), [freeze.py](harness/freeze.py) (frozen sources and protocol tags), run tooling ([run_status.py](harness/run_status.py), [run_recovery.py](harness/run_recovery.py)), the [human-review packet](harness/oracle_review.py), and the Studies 1-3 builders ([memory_bank.py](harness/memory_bank.py), [study_runner.py](harness/study_runner.py), [memory_methods.py](harness/memory_methods.py)) |
| [studies/](studies/) | One runner per study: [study1.py](studies/study1.py), [study2.py](studies/study2.py), [lifecycle.py](studies/lifecycle.py) (Study 3), [changed_mind.py](studies/changed_mind.py) (5-6), [honcho_features.py](studies/honcho_features.py) (7), [honcho_stage3.py](studies/honcho_stage3.py) (8), [second_model.py](studies/second_model.py) (9), [followups.py](studies/followups.py) (10-12), [gaps.py](studies/gaps.py) (13-20) and the [staleness diagnostic](studies/staleness_runner.py); Study 4 runs from the harness |
| [tests/](tests/) | Research tests; [support.py](tests/support.py) holds light helpers, [fixtures.py](tests/fixtures.py) the benchmark-backed fake actor |
| [tools/](tools/) | Early one-off utilities kept for the record: the SDK micro-pilot, the quota check and a partial-episode replay |
| [locks/](locks/) | Pins: [benchmark and SDK](locks/benchmark-lock.json), [dependency constraints](locks/dependencies.lock.txt), [providers](locks/providers.lock.txt) |

Studies 1-3 also have a [protocol](PROTOCOL-MEMORY.md) and [runbook](MEMORY-STUDY.md). The native
preflight (`python -m research.harness.native_scoring --tasks 0 1 2`) deliberately exits nonzero for
the pinned task 2 reference lookup failure; do not treat a reference-control trajectory as agent
success.

Tags made before the package layout (every study tag up to `second-model-long-history-eval-v1`)
keep the flat layout: there a module is `research.<name>` (for example `research.gaps`), and
[run-eval.ps1](../scripts/run-eval.ps1) picks whichever layout its worktree has.

## Validate and run

```powershell
python -m research.benchmark verify                          # every published number, from the CSVs
python -m unittest discover -s research/tests -t . -v        # research tests (benchmark ones skip without it)
$env:AFTEREVIDENCE_SLOW = "1"                                # also run the slow fake-backend dry passes
.\research\.venv\Scripts\python.exe -m unittest discover -s research/tests -t .
pyright --project research\pyrightconfig.json --pythonpath research\.venv\Scripts\python.exe
```

Every live stage is a dry run unless given `--approved-requests` equal to its recorded cap and a
provenance `--note`; evaluations also need their annotated protocol tag, and the runner refuses if
its frozen sources differ from the tag or change during the run. Run a tagged study from its own
worktree so work on `main` cannot touch it:

```powershell
scripts\frozen-worktree.ps1 -Tag <tag>             # worktree at the tag; run data, venvs and stacks linked
scripts\frozen-worktree.ps1 -Tag <tag> -Remove     # afterwards
```

Live runs and shims also refuse to start if Copilot reports overage or under 50% of the monthly
allowance left. A quota check is not a promise that billing settings prevent overages; set a
spending limit in the account's billing settings.

### Add a memory system to the benchmark

1. In [memory_gateway.py](harness/memory_gateway.py), write a store with `ingest(scope, episode)`,
   `search(scope, query) -> list[str]`, `delete(scope, episode_id)` and `dump(scope)`, and register
   it in `store()`. Scopes are `customer:<prefix><family>`; an episode is
   `{"id", "lines": [(speaker, text), ...], "times": [ISO time per line] (optional)}`.
2. Add a retrieval arm to `RETRIEVERS` in [commitment_pilot.py](harness/commitment_pilot.py) and to the
   stage's arm list (for example in [honcho_features.py](studies/honcho_features.py)).
3. Run the research tests with the slow dry passes (`AFTEREVIDENCE_SLOW=1`), then a capped dev check; an evaluation needs an annotated protocol tag before its families are generated.
4. Publish the per-session CSV and its analysis, and add a `Table` with the published numbers to
   [published.py](published.py) so `verify` and CI check them.

### Fairness to memory-system builders

- **Defaults first, stated exactly.** Each system runs its open-source default pipeline at a pinned
  version (Mem0 `mem0ai==2.2.1`, Graphiti `graphiti-core==0.31.2`, Hindsight `hindsight-client==1.2.0`,
  Honcho server `5c7d24b` with `honcho-ai==2.9.0`; [providers lock](locks/providers.lock.txt)), with every
  internal LLM call served by the study's model through a capped shim. The settings each study used
  (reasoning level, search mode, timestamps, workspaces) are in its [design](DESIGN.md) rows and the
  gateway code; vendors' managed platforms and published scores use other models and settings.
- **Tuned configurations are welcome as separate arms.** A builder can propose a configuration,
  query wording or model available at the pinned version (or a newer pin) before a protocol tag. It
  runs as its own labelled arm ("vendor-tuned") beside the default on the same families, model and
  caps, with the analysis fixed at the tag; defaults are never replaced after results are seen.
- **Fixes are re-run, not patched in.** If a builder finds an integration bug in the gateway, the fix
  is committed, the affected study is marked, and a new tagged run measures it; published numbers
  stay as recorded.
- **Results describe this setup.** One synthetic retail task, simulated customers and the stated
  model(s); none of it is a product ranking.

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

Create separate checkouts at the exact revisions in `locks/benchmark-lock.json`:

```powershell
git clone --no-checkout https://github.com/sierra-research/tau2-bench.git research\vendor\tau2-bench
git -C research\vendor\tau2-bench checkout --detach c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4
git clone --filter=blob:none --sparse https://github.com/github/copilot-sdk.git research\vendor\copilot-sdk
git -C research\vendor\copilot-sdk sparse-checkout set python
git -C research\vendor\copilot-sdk checkout --detach ed814e4134fdba86e2e88b82dcac85b1c125ed8a
cd research
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt -c locks/dependencies.lock.txt
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
