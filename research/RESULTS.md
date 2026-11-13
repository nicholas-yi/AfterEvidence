# Research feasibility and metering results

## What this report is

A real-task feasibility and cost report, not a demo score, paper result,
completed four-condition comparison, or retrospectively preregistered study.

The original UI was not extended for this work. The research used the
unmodified native retail environment and tools from MIT-licensed tau2-bench
at `c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4`.

## Initial feasibility trials

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

## Initial measured usage

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

## Bounded baseline follow-up: 2026-11-13

The next allowance covered at most **90 requests**, at most 30 per selected
development task, including both the actor and simulated customer. The fixed
cohort was official training tasks **0, 1, 2**. A local pre-run record captured
the source hashes, caps, seed, and scorer controls before new inference.
It is a development record, **not main-study preregistration**.

### Zero-inference scorer controls

The [native scoring adapter](native_scoring.py) now checks the reference
trajectory before initializing Copilot. For tasks 0 and 1:

- Every reference action executed without a suppressed reference exception.
- Native reference ENV reward was 1.0.
- The reference changed the database.
- An empty trajectory did not match that target.

Task 2 failed the strict preflight: reference action 2, `get_product_details`,
raised **"Product not found"** for the referenced product. It received **zero
model calls** and was not silently replaced by an easier task. This is a
conservative reference-replay exclusion, not proof that its final database
goal is undefined or that the whole benchmark is incorrect. The upstream ENV
evaluator logs reference exceptions and continues; this pilot does not accept
that as a fully validated reference.

### All inference attempts, including repairs

| Task / adapter | Requests | Duration | Outcome | AI credits |
|---|---:|---:|---|---:|
| 0 / original flat action | 14 | 93.125 s | Rejected a message carrying a placeholder tool name; no episode score | 1.546155 |
| 1 / nested message-or-tool action | 4 | 16.000 s | Rejected an empty message; no episode score | 0.208421 |
| 1 / shared nonempty-value action | 17 | 102.422 s | Normal `USER_STOP`; native ENV **1.0**, native task-basis **1.0** | 1.8368675 |
| 2 | 0 | Not run | Strict reference preflight failed | 0 |

Both schema failures remain in their original journals. Repairs were recorded
before the next attempt; no invalid action was silently stripped or executed.
Task 1's failed four requests count toward its 30-request cap: its total was
**21**, not 17. Task 0 was not retried. Different adapter versions were used,
so these attempts must not be pooled as an efficacy estimate.

The live schema now uses one nonempty `value` for either customer-facing text
or a tool name, plus JSON-encoded arguments. It has no irrelevant empty name
field or nested union. Native tool-name/argument validation remains in place.
Historical schemas remain readable for replay, not live inference.

### What the completed episode establishes

The actor verified the customer, consulted native account/order/product tools,
obtained confirmation, and executed the thermostat-only exchange required by
task 1's fallback instruction. The keyboard remained unchanged. The simulated
customer ended with the native stop marker.

A fresh, zero-inference replay of the saved episode reproduced both rewards
and the assessment. Task 1's reward basis contains DB and NL_ASSERTION, but its
NL assertion list is empty; **no LLM judge was called**. The task-basis score
therefore does not certify general policy compliance. Its communication list
is also empty, so a communication reward of 1 is not an independent quality test.
This is a custom actor adapter, not an official leaderboard submission.

The general scoring path leaves nonempty required NL assertions explicitly
unassessed rather than invoking an unapproved provider or declaring a full
reward. Premature termination is reported as incomplete, with a failing CLI
exit, rather than a completed episode.

### What remains unresolved

- There is only **one completed new episode**, not a useful accuracy estimate.
- Tasks 0 and 1 are sibling variants for the same customer and order, not
  independent samples or a valid train/evaluation separation. The later
  [offline audit](#offline-task-audit-2026-11-13-devbox) found that tasks 0-4,
  including task 2, all belong to that one customer.
- The task-1 simulator accepted a Google Assistant variant for a request
  phrased as Google Home; task-0 dialogue challenged that mapping. This
  interpretation must be calibrated independently before studying memory.
  A matching database alone does not establish simulator fidelity.
- Task 2 needs reference-artifact review before model spend or inclusion;
  the offline audit traced it to a copied docstring placeholder ID.
- No experience bank, four-condition result, or main-study preregistration
  was produced by this follow-up.

### Follow-up usage and preserved evidence

All **35 new requests** have complete billing evidence:

- Input: **279,026 tokens**; output: **14,633 tokens**.
- Consumption: **3.5914435 AI credits**, about **$0.035914435 in credit value**.
- **55 of the 90 authorized requests were unused**; they were not reallocated
  to unapproved tasks or used to chase a passing result.
- Including the initial pilots: **58 requests**, **463,712 input** and
  **24,580 output tokens**, **6.03168 AI credits** ($0.0603168 in credit value).

These are allowance measurements, not separate API invoices. Private local
evidence remains under `runs/`: `baseline-20261113-plan.json`, the two
`baseline-20261113-amendment-*.json` records, all three task journals/reports,
and `baseline-20261113-summary.json`. Do not publish raw journals, quota
snapshots, or account data.

## Offline task audit: 2026-11-13 (devbox)

Zero model calls. [task_audit.py](task_audit.py) reads the pinned retail
`tasks.json`, `split_tasks.json`, `db.json`, and tool source as plain JSON/text.
It derives each task's customers and orders from its reference actions, joins
train tasks that share a customer or order into families, and flags reference
identifiers absent from the initial database. It is a static audit, **not** a
native preflight, simulator check, or difficulty estimate. Its output is derived
from hidden reference actions and must never reach an actor, simulator, or memory.

```powershell
python -m research.task_audit
python -m research.task_audit --rows
```

### Task 2 reference mismatch

- Failing action: `2_1`, the second reference action (native preflight numbers
  from 1), `get_product_details(product_id="6086499569")`.
- `6086499569` is neither a product ID nor an item ID in the pinned database.
  It is the example ID in the pinned `get_product_details` docstring
  ("The product id, such as '6086499569'"), so the reference appears to have
  copied a placeholder. The task's user instructions never mention it.
- The same action appears as action 2 of train tasks **2, 3, and 4**. Among the
  user, order, product, and item ID arguments the audit checks, these are the
  only unscripted invalid references across all 114 retail tasks.
- It is a read-only lookup, so it does not change the target database. Upstream
  ENV scoring logs and continues. Strict preflight still rejects it by design;
  this audit does not weaken that rule.
- Task 2 also gates on a nonempty NL assertion ("10 t-shirt options"; 10 of the
  T-shirt product's 12 variants are available). Without an approved judge it
  could not receive a full task-basis score anyway. Sibling task 4 carries an
  open upstream issue (`issue_2b74ee61`) disputing that same "10" expectation.

Train tasks 46 and 47 also reference missing order IDs (`#9502126`, `#9502127`),
but their user instructions script those wrong numbers deliberately. The audit
marks them `scripted_in_user_instructions`. Strict preflight would also reject
them; whether intended failed lookups should be allowed is an open protocol
decision, not something changed here.

### Customer/order overlap

| Finding | Count |
|---|---:|
| Train / test tasks | 74 / 40 |
| Train families sharing a customer or order | 46 (29 singletons; largest 5) |
| Train tasks whose customer also appears in a test task | **38 of 74** |
| Train tasks needing an NL-assertion judge for full task-basis scoring | 29 |
| Train tasks with no resolvable customer (no lookup in reference) | 3 (24, 50, 57) |
| Train tasks whose reference has no write action | 6 |

- Tasks **0-4 are one customer family**. The entire earlier 0,1,2 cohort was
  one customer, not two independent customers plus a sibling. The completed
  task-1 episode exposes that family; it should not supply later development
  examples.
- Over half of the train split shares customers with the official test split,
  so the native split alone does **not** give held-out entity separation.
  A main study needs a customer-disjoint partition or explicit exclusions,
  decided in the protocol before evaluation.

### Proposed next development cohort (not approved, not run)

Deterministic rule, using no model outcomes: exclude the exposed family, tasks
sharing a customer with test, unresolved customers, invalid references, open
upstream issues, references without a write, and tasks needing an unapproved
NL judge. Then take the lowest-numbered eligible task per family.

- Eligible: 16 tasks in 12 families.
- Proposed: **20, 35, 66, 69, 73, 75, 78, 80, 81, 82, 88, 91**.

The judge-free filter restricts scoring coverage to DB checks. That is a
disclosed selection bias, not neutral sampling; the excluded judge-needing
tasks may differ systematically in difficulty. These tasks still need native
zero-inference preflight in the pinned environment before any model spend.

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

The prior public release passed 66 core/publication tests. The follow-up adds
native positive/negative scorer controls, fail-before-Copilot reference checks,
pending-judge and premature-termination checks, action-contract regressions,
and historical-journal compatibility. No native test-set outcome has been used
for prompt tuning; these are development tasks.

## Remaining gates

1. Extend the single completed episode to several valid, independently checked
   development episodes with a capable actor and calibrated user simulator.
   Any replacement/expanded cohort needs an explicit plan and authorization;
   unused allowance is not permission to change the selected tasks silently.
2. Freeze an appropriate held-out partition. The overlap audit is done (38 of
   74 train tasks share a test customer); the partition decision is not.
3. Generate an actual experience/lesson bank from allowed development feedback
   only, and wire all four conditions to the same actor/tools/policy/budgets.
4. Validate the full scoring scope and report policy compliance separately
   from database-goal checks.
5. Commit/tag the actual main-study protocol before running main evaluation.
6. Only then measure memory effects, including null/negative results.

No larger model run is implied by the apparent cheapness of the micro-pilot.
No Google-style parameter expansion, Knowledge Seeding, or RL dreaming was
implemented in this research track.
