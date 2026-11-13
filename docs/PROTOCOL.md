# Protocol status and claim gates

## Status

This file documents the **offline development model**, not a preregistration of
comparative product experiments. Development fixture outcomes are known and
intentionally exercise two broken controls. No scientific novelty or product
failure follows from them.

The repository now also contains a local Qwen application. Its separate
[development validation plan](APPLICATION-STUDY.md) and
[application contract](LOCAL-APP.md) do not turn these offline outcomes into
comparative product results.

The proposed future study has three proof-topology strata, 100 independent
worlds per stratum, and three execution repeats per world/condition. This is a
candidate design, not an executed or statistically powered superiority study.
Actual provider models, native operations, completion barriers, configuration,
timeouts, retries, cost, and eligible sample counts are not frozen.

Before any main experiments: complete those choices, commit the protocol and
scenario manifest, tag that commit, and include the revision in every main run.
No registration tag is claimed for this development prototype.

## Offline contract

- Immutable source IDs identify evidence; distinct sessions allow source-scope tests.
- Rules are positive conjunctions; multiple rules/direct statements give alternatives.
- A conclusion is usable iff at least one complete source proof remains active.
- Independent evidence is not a model's own restatement of an existing conclusion.
- An unknown source/session is an error; repeat deletion of a known source/session is idempotent.
- Reconsolidation must not resurrect an unsupported conclusion.
- Queries are fresh symbolic calls, with no retained conversational answer context.

The reference and oracle use different algorithms: source-proof propagation
versus boolean forward chaining. The harness independently maintains planned
source activity rather than letting an implementation define its own expected
answers.

## Applicable executable checks

Run `python -m unittest discover -s tests -v`. Test names below live in
[test_contracts.py](../tests/test_contracts.py).

| Threat | Independent check A | Independent check B |
|---|---|---|
| Incorrect AND/OR oracle | `test_explicit_and_or_fixtures` | `test_all_deletion_subsets_match_independent_rebuild` |
| Deletion/order/rebuild errors | `test_session_removal_and_unknown_ids` | `test_deletion_order_and_reconsolidation_are_invariant` |
| Ground-truth coupling | `test_public_payload_excludes_grading_fields` | `test_swapping_oracle_labels_cannot_change_observations` |
| Hidden oracle access | `test_memory_has_no_oracle_dependency` | `test_swapping_oracle_labels_cannot_change_observations` |
| Implementation defining its own expected source state | `test_runner_detects_ignored_source_intervention` | `test_all_deletion_subsets_match_independent_rebuild` |
| Scenario/order artifacts | `test_renaming_and_input_order_do_not_change_outcomes` | `test_all_deletion_subsets_match_independent_rebuild` |
| Ablation/denominator mistakes | `test_closed_form_ablations_and_denominators` | `test_sham_and_unrelated_controls_always_pass` |
| Replay/integrity errors | `test_json_roundtrip_replay_and_tamper_detection` | `test_hash_seed_does_not_change_results` |
| Invalid-input masking | `test_invalid_inputs_are_explicit` | `test_cli_rejects_bad_limits_and_malformed_json` |

These are executable software checks, not two independent research replications.
The hash/replay check is not tamper-proof certification. The custom referee
must reject claims extending past the tested model.

## Currently unvalidated threats

Vendor configuration fairness, stochastic seed variance, language/judge bias,
enterprise authorization, and remote physical erasure remain unvalidated.
The application adds unit-tested epoch guards around concurrent writes/answers,
not a comprehensive distributed-systems concurrency study. These broader threats are **not passed**;
claims about them are blocked.

Do not treat synthetic renaming as validation of natural-language paraphrase
robustness. Do not treat successful local replay as replay of an actual memory
service. Do not substitute cached responses for new post-intervention reads.

## Future native-operation caveats

Honcho already has source lineage and representation history. The audited
release is `70c67624169683b9e265517aec95a51b8077cabc` (v3.6.1), published
2026-11-11; inspected main is
`5c7d24b32d275bce38daedbe81feaebc31393587`, with different peer-card history
handling. Never merge those into one deployment label.

The inspected message update path is metadata-only; native message deletion is
not exposed. Session deletion and conclusion deletion are different contracts.
Deleting a conclusion while its raw sources remain can permit legitimate
re-derivation. A real adapter needs a capability manifest and supported source
intervention, not output filtering pretending to be deletion.

References: [release](https://github.com/plastic-labs/honcho/releases/tag/v3.6.1),
[message router](https://github.com/plastic-labs/honcho/blob/70c67624169683b9e265517aec95a51b8077cabc/src/routers/messages.py),
[conclusion router](https://github.com/plastic-labs/honcho/blob/70c67624169683b9e265517aec95a51b8077cabc/src/routers/conclusions.py),
[peer-card history change](https://github.com/plastic-labs/honcho/pull/1590).
