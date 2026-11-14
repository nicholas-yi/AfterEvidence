# AfterEvidence

**Does external memory distilled from an agent's past conversations help it act
on later tasks, and what happens when that memory is stale or deleted?**

The research track runs pinned, unmodified [tau2-bench](https://github.com/sierra-research/tau2-bench)
retail tasks, where an episode counts only if the store's final database is
right. One model (Claude Haiku 5.5 via GitHub Copilot) is the agent, the
simulated customer, and every memory system's internal LLM. The protocol was
[committed and tagged](research/PROTOCOL-MEMORY.md) (`memory-study-v1`) before
any test episode ran.

![Study 1: success and cost per memory condition](docs/figures/study1-success-cost.svg)

## Findings

1. **No detectable effect on task success, and only large effects were
   detectable.** Nine conditions (no memory, raw transcripts, one-pass lessons,
   a memory-level "sleep" replay/reweight/prune analogue, induced workflows,
   Mem0, Graphiti, Hindsight, Honcho) on 26 test tasks × 2 runs: 75% without
   memory, 73-83% with, every Holm-corrected p = 1.0. Post-hoc paired
   differences range from −1.9 to +7.7 points, and every task-clustered 95%
   interval includes zero (widest −15.4 to +21.2). The design could reliably
   detect only differences of about 15-20 points; this is not evidence of
   equivalence.
2. **Stale memory can mislead an agent that acts (one task, n = 1).** With
   memory of the same customer's earlier sessions, later sessions scored 17-19
   of 22 against 20 without memory (not significant). In task 110, Mem0 and
   Honcho recalled an address change that a database reset had undone, and both
   agents changed the wrong order. Honcho's count also includes two early
   action-format failures, not memory content.
3. **A narrow deletion probe passed.** After deleting one of three stored
   conversations, its literal identifiers disappeared from Mem0, Graphiti, and
   Hindsight immediately and from Honcho on a recheck minutes later. Paraphrased
   or derived facts were not tested, so this is not evidence of semantic erasure.

A follow-up [staleness diagnostic](research/DESIGN.md#follow-up-staleness-aware-memory-stage-a-run-stage-b-not-requested)
ran its approved 36-episode Stage A and failed its pre-specified floor: the
agent always checked the live account, never chose the stale value, and also
declined valid memory it could not confirm. It was not scaled up. A follow-up
pilot on memory the agent strictly needs was stopped at its first gate by a
scripted-customer defect before any memory comparison ran.

Full tables, failure causes, deviations, and limitations:
[research results](research/RESULTS.md). Usage: [costs](research/COSTS.md)
(12,428 requests started and 1,425.05 Copilot AI credits recorded for the
memory study). No Google-style Sleep training (parameter expansion, Knowledge
Seeding, RL dreaming) was implemented.

## Verify the numbers

Every Study 1 and Study 2 table is recomputed from a public per-episode table,
[memory-study-v1-episodes.csv](research/data/memory-study-v1-episodes.csv)
(no transcripts, prompts, customer names, or account data), and a CI test
asserts the published figures:

```powershell
python -m research.memory_analysis --csv research/data/memory-study-v1-episodes.csv
python -m unittest research.test_memory_csv -v
```

Rerunning the episodes needs the pinned environment, Copilot access, and an
approved budget; see [research setup](research/README.md) and the
[devbox handoff](docs/DEVBOX-HANDOFF.md). Earlier pilots and audits are under
[development history](research/RESULTS.md#development-history).

## Local app

A separate local workspace extracts quoted assertions from notes with a local
Ollama model, consolidates external memory, and revises it when a source is
corrected or removed (AND within a proof, OR across alternative proofs). It is
a development preview with no accuracy claim; see [the local app](docs/LOCAL-APP.md).

```powershell
python -m afterevidence doctor
python -m afterevidence serve
```

## Validate

No model, credentials, or benchmark download needed:

```powershell
python -m pip install ".[dev]"
python -m unittest discover -s tests -v
python -m unittest research.test_memory_methods research.test_costing research.test_memory_csv -v
ruff check afterevidence tests research scripts
pyright
```

The app binds to loopback; do not expose it to the internet. Databases, run
journals, credentials, quota snapshots, vendors, and model weights are never
published, and source deletion is application-level removal, not certified
erasure from disk, caches, backups, or weights.

## Research context

Related work includes [Stashbird](https://arxiv.org/abs/2609.34242),
[Memora](https://arxiv.org/abs/2604.20006),
[Bemula](https://arxiv.org/abs/2610.18052),
[GateMem](https://arxiv.org/abs/2606.18829),
and [execution-state unlearning](https://arxiv.org/abs/2609.04875).
**Disclosure:** the author of this repository is a co-author of Stashbird.
Stashbird was not run in this study, and no Stashbird code or internal data is
used here. [Google's Sleep paper](https://arxiv.org/abs/2606.03979) informs the
distinction between experience and durable capability; it was not reproduced.

## License

[MIT](LICENSE). Third-party code and data retain their own licenses.
