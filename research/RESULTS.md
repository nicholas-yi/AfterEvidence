# Research feasibility and metering results

## What this report is

A real-task feasibility and cost report, not a demo score, paper result,
completed four-condition comparison, or retrospectively preregistered study.

The original UI was not extended for this work. The research used the
unmodified native retail environment and tools from MIT-licensed tau2-bench
at `c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4`.

## Executed trials

| Trial | Actual model requests | Outcome | Duration |
|---|---:|---|---:|
| Native local Qwen development task 0 | 12 | Terminated normally; native ENV reward **0** | 400.968 s |
| Copilot access/metering micro-pilot | 3 | Completed; **not a whole task or scored episode** | 11.750 s |
| Copilot full-task attempt, prose output | 2 | Rejected because actor output violated the JSON-action contract | 10.813 s |
| Structured-action retry within the remaining budget | 18 | Executed real tools; stopped at the explicit request cap before termination | 108.312 s |

Failed setup attempts were preserved. Model-unavailable, incompatible-version,
relative-directory, and invalid-limit failures occurred before sending a model
prompt. No credential was extracted from VS Code or pasted into source.

### Why the native baseline is not yet a useful main-study baseline

The local model did not achieve the native database goal on the first complex
development task. The Copilot actor was capable of querying the native tools
and executing an actual exchange, but its conversation was not completed
within the authorized cap.

An additional **zero-inference** native replay used the actual recorded
messages and final assistant reply:

- 25 observed messages replayed.
- All five reference actions validated without a suppressed reference failure.
- The reference changed the database, so this was not a trivial no-action match.
- The observed partial database **did not match** the native target.
- No terminal user message was invented, no model was called, and no complete
  official pass was inferred.

The observed dialogue raises interpretation/user-simulator-fidelity questions
around requested compatibility and which items the user ultimately agreed
to exchange. That is a diagnostic lead, **not proof that the benchmark is
incorrect or that memory would fix the failure**.

### What was repaired in the adapter

Prompting alone did not enforce JSON. The adapter now uses the SDK's supported
structured-response contract, validates the resulting message/tool choice,
validates arguments against the native tool schema, and lets only the native
orchestrator execute the tool.

Timeouts explicitly abort the SDK generation. A stopped waiter is not treated
as proof that generation stopped. Incomplete/capped runs now produce a
nonzero CLI exit status and preserve partial observed messages.

## Measured usage

All 23 completed Copilot requests were through the existing authenticated
Copilot allowance, using account-enabled Claude Haiku 5.5:

- Input: **184,686 tokens**.
- Output: **9,947 tokens**.
- Recorded usage: **2.4402365 AI credits**.
- Dollar-equivalent credit value: **$0.024402365** at the published conversion.
- No separately billed OpenAI/Anthropic API was used.

The SDK returned complete billing status. Root session totals were summed
once; nested model/provider/event copies were not counted again.

Before/after account quota snapshots and overage settings remain in the
private local journals. An unchanged rounded quota display is not proof of
free usage, and legacy request counters are not automatically AI-credit
balances or an exact monthly-call allowance.

See [cost assumptions and planning estimates](COSTS.md).

## Preserved evidence

The following local outputs are git-ignored; do not commit account snapshots
or raw journals into the public benchmark implementation:

- `runs/local-4b-feasibility-0.json` and its `.calls.jsonl`.
- `runs/copilot-micro-01.jsonl` through `copilot-micro-04.jsonl`, including
  failed pre-inference setup attempts.
- `runs/copilot-native-feasibility-0.json` and its `.calls.jsonl`.
- `runs/copilot-native-structured-feasibility-0.json` and its `.calls.jsonl`.

Run the zero-inference accounting/replay:

```powershell
.\research\.venv\Scripts\python.exe -m research.costing research\runs\copilot-native-structured-feasibility-0.calls.jsonl
.\research\.venv\Scripts\python.exe -m research.replay_partial research\runs\copilot-native-structured-feasibility-0.calls.jsonl --task 0
```

The replay is explicitly a post-hoc partial-state check, not a native completed
episode or a hidden substitute for the full scorer.

## Software verification versus scientific evidence

The memory-method controls test raw retrieval, consolidated/revised retrieval,
AND/OR support, source withdrawal, policy versioning, and character budgets.
They do **not** show that an agent learned useful lessons.

The SDK tests cover no-host-tool isolation, explicit request caps, real usage
schema accounting, incomplete/missing accounting rejection, structured action
parsing, cancellation, and failure exit status.

The existing 62 application/offline tests remained passing. The focused
research tests and targeted Pyright check also passed. No native test-set
outcome has been used for prompt tuning; these are development tasks.

## Remaining gates

1. Establish several valid, independently checked development episodes with
   a capable actor and a faithful user simulator, under an explicit new cap.
2. Audit customer/entity overlap and freeze an appropriate held-out partition.
3. Generate an actual experience/lesson bank from allowed development feedback
   only, and wire all four conditions to the same actor/tools/policy/budgets.
4. Validate the full scoring scope and report policy compliance separately
   from database-goal checks.
5. Commit/tag the actual main-study protocol before running main evaluation.
6. Only then measure memory effects, including null/negative results.

No larger model run is implied by the apparent cheapness of the micro-pilot.
No Google-style parameter expansion, Knowledge Seeding, or RL dreaming was
implemented in this research track.
