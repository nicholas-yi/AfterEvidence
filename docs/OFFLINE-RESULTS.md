# Offline development results

Date: 2026-11-12. Scope: deterministic positive-Horn-rule software fixtures.
No external model, memory product, API credential, paid cloud service, or public
publication was used for this run.

## What actually ran

```powershell
python -m unittest discover -s tests -v
python -m afterevidence run --worlds-per-topology 10 --seed 42 --output results\offline-demo.json
python -m afterevidence verify results\offline-demo.json
python -m compileall -q afterevidence tests
```

- Python: 3.12.10.
- Tests: **18 passed**.
- Three proof topologies, ten generated ID variants each: **30 distinct worlds**.
- Three local policies, two consolidation conditions, two branches: **360 trajectories**.
- Four checkpoints and two probes per trajectory: **2,880 observations**.
- Deterministic replay: passed.
- Pylance file diagnostics: no issues reported for the implementation and tests.
- No comparative main experiment or preregistration tag exists.

The variants change opaque identifiers/input order, not linguistic semantics.
They must not be presented as 30 independent natural-language scenarios.

## Measured counts

| Local implementation | Correct | Stale | Over-deleted | All observations |
|---|---:|---:|---:|---:|
| Proof-aware reference | 960 | 0 | 0 | 960 |
| Flat-union negative control | 940 | 20 | 0 | 960 |
| Delete-all-affected negative control | 940 | 0 | 20 | 960 |

Every observed negative-control error occurred in the preconsolidated,
actual-intervention branch:

| Broken control | Topology | Checkpoint | Errors |
|---|---|---|---:|
| Flat union | Sole conjunction | After partial deletion | 10 stale |
| Flat union | Independent alternative | After final sufficient-proof removal | 10 stale |
| Delete-all-affected | Independent alternative | After partial deletion | 10 over-deleted |
| Delete-all-affected | Redundant direct support | After partial deletion | 10 over-deleted |

The unrelated and sham controls were checked separately. Neither broken policy
is a proxy for Honcho, Stashbird, Mem0, Graphiti, Zep, or Letta.

These counts demonstrate that the fixtures distinguish two deliberately
incorrect policies from the specified proof-aware contract. They do not
estimate a population error rate, establish scientific novelty, or predict
real-system behavior. Statistical confidence intervals on this deliberately
constructed software demonstration would be misleading.

## Provenance and replay

Raw local report: `results/offline-demo.json`, generated
and git-ignored rather than a committed main-study dataset.
It is a local evidence path, not a downloadable file in the public release.

Package-source SHA-256:

```text
7bd3d29f2c0a07ef048eaafebb2d3d3730cc48a95455089bdeac1725bebc03d6
```

Report SHA-256:

```text
32962163c3b7ceaaf261e776ccd35c903d8ba436f236a6ccbf1cc5928f9fca1c
```

The source digest covers Python package files, not all documentation/test files.
The report digest covers canonical report content before the digest field is
added. It is not a signature. Verification regenerates the run from its seed
and count, requiring matching source/runtime; it does not certify third-party
data or reproduce a remote deployment.

## Referee evidence and remaining gates

The [protocol](PROTOCOL.md) maps applicable threats to pairs of executable
checks. In particular:

- Explicit AND/OR fixtures plus all-deletion-subset checks independently test
  the proof implementation against boolean surviving-log reconstruction.
- Payload-boundary and swapped-oracle tests establish that grading labels do
  not determine actual memory observations.
- An ignored-deletion fault injection proves that the runner does not let the
  implementation's own source state define its expected result.
- Closed-form denominator checks, preservation/sham checks, JSON tamper
  detection, and hash-seed-independent replay address harness artifacts.

The saved [referee agent](../.github/agents/referee.agent.md) must still reject
comparative/scientific claims without their additional evidence. No LLM
referee approval or external replication is claimed here.

Language understanding, real inference formation, arbitrary hypothesis truth,
native deletion/correction behavior, asynchronous races, authorization,
physical erasure, stochastic model variance, and fair vendor configuration
remain unvalidated.

## Resource status and next work

Authorized external spend: **$0**. Runtime dependencies: none.
An optional standalone type-checker download encountered TLS errors; existing
Pylance diagnostics were used instead. No TLS verification was disabled.

Before real-product/model experiments, obtain an approved deployment/model
access arrangement, check actual licenses and operations, freeze the protocol
and manifests, and commit/tag the registration. Use free/local resources only
unless a separate external-spend budget is explicitly authorized. Existing
Copilot chat usage is not an API key or billing authorization for another
provider.
