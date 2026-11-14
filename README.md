# AfterEvidence

**Memory you can inspect. Evidence you can revise.**

A local-first workspace and research toolkit for studying what an agent
remembers, where that understanding came from, and what should change when
its evidence changes.

[Get started](#local-workspace) · [Research](research/README.md) ·
[Results](research/RESULTS.md) · [Costs](research/COSTS.md) ·
[Continuity](docs/CONTINUITY.md) · [Devbox handoff](docs/DEVBOX-HANDOFF.md)

> **Development preview.** Source lineage is not a guarantee of truth.
> A tagged memory study compared nine memory approaches and found no detectable
> effect on task success. It makes no claim that any memory product fails, and
> it does not reproduce Google's Sleep training.

## Three separate tracks

| Track | What it does | Status |
|---|---|---|
| Local workspace | Ollama-backed extraction, external-memory consolidation, source review, corrections, and deletion | Implemented; human review remains necessary |
| Lifecycle contracts | Deterministic AND/OR proof cases, preservation, invalidation, and replay checks | Software invariants, not model-accuracy results |
| Agent-task research | Native retail tools and scoring with bounded, metered model access | Memory study v1 complete: null result |

## Local workspace

Python 3.11+ and a separately installed local Ollama model are required.
There are no Python runtime dependencies or frontend build steps for the app.

```powershell
git clone https://github.com/nicholas-yi/AfterEvidence.git
cd AfterEvidence
ollama list
python -m afterevidence doctor
python -m afterevidence serve
```

Open **http://127.0.0.1:8765**. The default model is `qwen3.5:4b`; select another
already-installed local model with `--model`. The app never downloads a model
or silently calls a cloud provider.

Optional package installation:

```powershell
python -m pip install .
afterevidence serve
```

To chat directly with the model, outside this app:

```powershell
ollama run qwen3.5:4b
```

### The workflow

1. **Capture.** Add a source note and an explicit subject.
2. **Inspect.** Review quoted model assertions and their actual source links.
3. **Consolidate.** Create an external-memory summary and optional tentative
   hypothesis, procedure, or plan.
4. **Use.** Ask from raw sources, current assertions, or usable derived memory.
5. **Revise.** Correct a source, reject a mistaken interpretation, or remove
   evidence without discarding independently supported knowledge.

Five small scenario packs cover project decisions, support, tutoring, research,
and operations. They are starting examples, not integrations with production
accounts or evidence of real-world effectiveness.

The interface uses native controls, system typography, keyboard navigation,
dark mode, restrained feedback, and reduced-motion/transparency variants.
See [design decisions](docs/DESIGN.md).

## What “supported” means

```text
q <- a AND b
q <- c
```

Removing `b` breaks the first proof. It must not remove `q` while `c` remains.
Removing `c` too makes `q` unsupported by the declared evidence.

The deterministic reference implements this rule exactly. Model-generated
prose has a weaker guarantee: lineage records its inputs, not semantic
entailment. **Inspect and reject unsupported interpretations.**

Conflicting assertions and unfinished extraction do not silently become
successful memories. Dirty memories are excluded; stale model writes and
answers are rejected when the evidence epoch changes.

## Current research boundary

The separate research track uses pinned, MIT-licensed `tau2-bench` retail
tasks—not the UI's hand-written scenario rules.

- A local-Qwen native task did not achieve its database goal.
- An initial bounded Copilot conversation hit its request limit and did not
  match the target database in partial replay.
- A subsequent Copilot development episode completed with native ENV and
  task-basis rewards of **1.0**, reproduced by zero-inference replay. It is
  one task, with no nonempty policy assertions to judge, not an accuracy estimate.
- Strict reference preflight blocked another selected task before inference;
  an offline audit traced it to a placeholder product ID in the reference.
- That audit also found 38 of 74 training tasks share a customer with the
  test split, so the native split alone does not isolate evaluation entities.
- A 12-task development cohort, one per customer family and customer-disjoint
  from the test split, scored 1.0 on 9 tasks; 3 failed the actor's action
  format early. It is one seed on a judge-free subset, not an accuracy estimate.
- **Memory study v1**, run under a protocol tagged before any test episode,
  compared no memory, raw transcripts, one-pass lessons, a sleep-style
  replay/reweight/prune analogue, induced workflows, Mem0, Graphiti, Hindsight,
  and Honcho on 26 test tasks × 2 runs. **None changed task success
  detectably** (75% without memory; 73-83% with; all corrected p = 1.0); with
  two runs per task only large effects were detectable, so this is not evidence
  of equivalence. Same-customer memory was slightly worse than none, not
  significantly, and stale remembered facts caused the clearest loss. In a
  three-conversation deletion probe, the deleted conversation's literal
  identifiers disappeared from all four providers (Honcho only on a recheck);
  that does not show complete semantic erasure.
- Usage was metered and failures retained. **No memory improvement is claimed.**

[Read the memory study](research/RESULTS.md#memory-study-v1), the
[blog draft](docs/BLOG-DRAFT.md), and
[measured cost assumptions](research/COSTS.md) before running model calls.

## Validate

The core suite runs without a model, credentials, or downloaded benchmark:

```powershell
python -m unittest discover -s tests -v
python -m unittest research.test_memory_methods research.test_costing -v
python -m afterevidence run --worlds-per-topology 10 --seed 42 --output results\offline.json
python -m afterevidence verify results\offline.json
```

Development tooling:

```powershell
python -m pip install ".[dev]"
ruff check afterevidence tests research scripts
ruff format --check afterevidence tests research scripts
pyright
node --check afterevidence/static/app.js
```

Live application evaluation is optional and consumes local inference time:

```powershell
python -m afterevidence evaluate-app --output results\application-development.json
```

See [the application validation report](docs/APPLICATION-RESULTS.md). Its fixed
development fixtures are not a population accuracy estimate.

## Privacy and publication

- The application binds to loopback. **Do not expose this development server
  directly to the internet.**
- Databases, local notes, prompts, raw model journals, credentials, quota
  snapshots, downloaded vendors, and runtime binaries are not published.
- Model weights, benchmark source, and third-party runtimes are not bundled
  under this project's license.
- Source deletion is application-level content removal, **not certified
  erasure from disk pages, caches, backups, browser memory, or model weights**.
- Research model access is explicit and separate from the local app.

## Sleep and continuity

Chat history, application data, and execution are different kinds of state.
Sleeping a laptop can interrupt local jobs even when the conversation is saved.

The optional [Windows guard](scripts/keep-awake.ps1) provides a bounded manual
idle-sleep hold, not automatic chat detection:

```powershell
.\scripts\keep-awake.ps1 -Minutes 120
.\scripts\keep-awake.ps1 -Status
.\scripts\keep-awake.ps1 -Stop
```

See [continuity and safe resume](docs/CONTINUITY.md).

## Research context

Relevant precedents include [Stashbird](https://arxiv.org/abs/2609.34242),
[Memora](https://arxiv.org/abs/2604.20006),
[Bemula](https://arxiv.org/abs/2610.18052),
[GateMem](https://arxiv.org/abs/2606.18829),
and [execution-state unlearning](https://arxiv.org/abs/2609.04875).
Forgetting, provenance, and truth maintenance are not new ideas.

[Google's Sleep paper](https://arxiv.org/abs/2606.03979) informs the distinction
between experience and durable capability. This project does **not** implement
parameter expansion, Knowledge Seeding, or RL dreaming.

## License

[MIT](LICENSE). Third-party code and data retain their own licenses.
