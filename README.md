<div align="center">

# Forget-Me-Not

**Does an AI agent's memory of past conversations help it get real work done?<br>
Does stale memory mislead it? And does deleting a memory actually remove it?**

[![CI](https://github.com/nicholas-yi/AfterEvidence/actions/workflows/ci.yml/badge.svg)](https://github.com/nicholas-yi/AfterEvidence/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

<sub>Repository and Python package: <code>AfterEvidence</code></sub>

</div>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/memory-effects-dark.svg">
  <img alt="Forest plot of the change in task success versus no memory for eleven memory conditions across two studies. Every 95% interval crosses zero, and shaded bands show that only differences of roughly 15 to 20 points (Study 1) or 17 to 28 points (Study 2) were reliably detectable." src="docs/figures/memory-effects-light.svg" width="100%">
</picture>

<sub><b>Figure 1. No memory design changed task success detectably.</b> Each dot is the change in
success rate when the agent gets memory, against the same tasks without memory; the bar is a 95%
task-clustered bootstrap interval (customer-clustered in Study 2). Intervals that cross the zero line
are consistent with no effect. Effects inside the shaded band are too small for this study to detect
reliably. Data: <a href="research/data/memory-study-v1-episodes.csv">per-episode CSV</a>; regenerate
with <code>python -m research.figures</code>.</sub>

---

## The problem

AI agents increasingly come with **memory**: systems such as Mem0, Graphiti, Hindsight and Honcho
store what happened in earlier conversations and hand the relevant parts back later. The promise is
an assistant that learns from experience. Three questions are rarely tested where it matters, on
tasks where the agent has to take the *right action*:

1. **Does memory help?** Do lessons from earlier customers make the agent better at new ones?
2. **Can memory hurt?** What happens when a remembered fact is no longer true?
3. **Does deleting really delete?** When a user removes a conversation, does everything derived
   from it disappear while everything else stays?

## Why it is hard to measure

- **Chat benchmarks score words, not actions.** An agent can say the right thing and still change
  the wrong order.
- **Each memory product is evaluated its own way.** Different models, prompts and tasks make
  published results hard to compare.
- **Small benchmarks hide small effects.** With a few dozen tasks only large differences are
  detectable, and a null result is easy to misread as "no effect".

Forget-Me-Not compares nine memory designs under identical conditions, on tasks scored by whether
the store's database ends up exactly right, with the analysis fixed before any test episode ran.

## How the experiment works

```mermaid
flowchart TD
    H[("Past episodes")] --> M["Memory system<br/>none · transcripts · lessons<br/>Mem0 · Graphiti · Hindsight · Honcho"]
    M -->|"retrieved once,<br/>≤ 2,400 characters"| A["Agent<br/>Claude Haiku 5.5"]
    C["Simulated customer<br/>Claude Haiku 5.5"] <--> A
    A <--> T["16 retail tools"]
    T <--> DB[("Store database")]
    DB --> S{"Scorer:<br/>is the final database<br/>exactly right?"}
```

### A benchmark where actions have consequences

The study uses the retail domain of [τ²-bench](https://github.com/sierra-research/tau2-bench),
pinned to an exact commit and run unmodified. A simulated customer asks for returns, exchanges,
cancellations and address changes. The agent works through 16 tools under a written store policy.
An episode counts as a success only if it ends normally and the final database matches the
reference outcome.

### The same model in every role

The same model, Claude Haiku 5.5 (via GitHub Copilot), plays the agent, the simulated customer, and
the internal LLM inside every memory system. Embeddings come from one local model. Differences
between conditions therefore come from the memory, not from a different model. Study 9 repeats the
change-of-mind task with `gpt-6-luna` in every role.

### Nine memory designs on one budget

Memory is built from 30 earlier episodes whose customers never appear in the test tasks. It is
retrieved once from the customer's first message, capped at 2,400 characters for every condition,
and labelled as possibly outdated: current tool results and the store policy take precedence.

| Condition | What the agent receives |
|---|---|
| none | No memory (the baseline) |
| raw transcripts | The most similar past conversations |
| one-pass lessons | Up to six lessons from one pass over all episodes ([ExpeL](https://arxiv.org/abs/2308.10144)-style) |
| sleep-style lessons | Lessons replayed, merged, weighted by how many episodes support them, and pruned |
| workflows | Up to six reusable step sequences from successful episodes ([AWM](https://arxiv.org/abs/2409.07429)-style) |
| [Mem0](https://github.com/mem0ai/mem0), [Graphiti](https://github.com/getzep/graphiti), [Hindsight](https://github.com/vectorize-io/hindsight), [Honcho](https://github.com/plastic-labs/honcho) | Each open-source system with its default pipeline |

The sleep-style condition borrows the memory-level idea of replay, reweighting and pruning from
[Language Models Need Sleep](https://arxiv.org/abs/2606.03979). That paper also trains model
weights, which a hosted model cannot do, so only the memory-level idea is tested.

### Nine studies

| Study | Question | Design |
|---|---|---|
| **1. Other customers** | Does memory of earlier, different customers help on new tasks? | 9 conditions × 26 test tasks × 2 runs = 468 episodes |
| **2. Same customer** | Does memory of a customer's earlier sessions help their later ones? | 16 customers, 22 later sessions × 4 conditions; the database resets between sessions, so remembered facts can be stale |
| **3. Deletion** | After deleting one conversation, is everything derived from it gone, and is everything else intact? | 3 conversations per system; delete one through the system's own API, then probe |
| **4. Remembering an agreement** | When a task is impossible without memory, does memory let the agent finish it? | 32 customers; an agreement in one conversation, "go ahead" in the next; 5 conditions |
| **5. A change of mind** | If the customer changed the agreement later, does memory make the agent act on the latest one? | 32 customers; agreement, then a changed agreement, then "go ahead"; 5 conditions |
| **6. Dated memories** | With real time between those conversations, does dating them help each memory system act on the latest agreement? | 32 new customers; Study 5 with the agreements 3 and 1 days old; each system undated vs dated; 5 conditions |
| **7. Honcho features** | Does Honcho's raw message search beat its summarized answer, and does memory cause harm when the customer helps? | 32 new customers; Study 6's dated task; 6 conditions, 3 of them with a customer who names the item when asked |
| **8. More Honcho features** | Do Honcho's dreaming, an on-demand memory tool, or facts the app writes into Honcho help it act on the latest agreement? | 32 new customers; Study 6's dated task; 5 conditions, including the app's facts given directly without Honcho |
| **9. A second model** | Do the change-of-mind results hold when another model plays every role? | 32 new customers; Study 6's dated task with `gpt-6-luna` instead of Claude Haiku 5.5; 4 conditions |

### An analysis fixed before the data

- The [analysis protocol](research/PROTOCOL-MEMORY.md) was committed and git-tagged
  (`memory-study-v1`) before any test episode; the runner refuses the test split without that tag.
- Each memory condition is compared with no memory on the same tasks and runs, using an exact
  McNemar test with Holm correction across conditions. Success rates carry Wilson 95% intervals.
- Effect sizes (added afterwards, labelled as such) use a task-clustered bootstrap and a sign-flip
  permutation test, with the smallest effect the design could reliably detect.
- A hard budget of 16,000 model requests was checked before every episode. Episodes were never
  retried or replaced, and every failure, including harness failures, counts as a failure.

## Results

| Study | Question | Headline | Data |
|---|---|---|---|
| 1 | Does memory of other customers help? | No condition changed success detectably (73-83% vs 75% without memory) | [CSV](research/data/memory-study-v1-episodes.csv) |
| 2 | Does memory of the same customer help? | Slightly worse, not significant; stale memory caused one wrong-address action | [CSV](research/data/memory-study-v1-episodes.csv) |
| 3 | Does deleting a conversation remove it? | Every system removed its literal identifiers (Honcho after a delay) | — |
| 4 | When a task needs memory, does memory deliver? | No memory 0/28; transcripts 26/26; Mem0 24/24; Honcho 19/23 | [CSV](research/data/commitment-eval-v1-episodes.csv) |
| 5 | After a change of mind, does memory follow the latest agreement? | Transcripts 30/31; Mem0 13/31 (13 acted on the superseded item); Honcho 3/31 (mostly declined) | [CSV](research/data/changed-mind-eval-v1-episodes.csv) |
| 6 | Does dating the memories help? | No significant change for Mem0 or Honcho | [CSV](research/data/changed-mind-dated-eval-v1-episodes.csv) |
| 7 | Honcho's search vs its answer; a customer who repeats the item | Search 14/32 vs answer 8/32 (n.s.); with a helpful customer no memory 32/32, Mem0 twice harmful | [CSV](research/data/honcho-features-eval-v1-episodes.csv) |
| 8 | Do dreaming, a memory tool or app-written facts help Honcho? | App-written facts 26/30 vs 8/30 (significant); the same facts without Honcho 29/30 | [CSV](research/data/honcho-stage3-eval-v1-episodes.csv) |
| 9 | Do Studies 6-7 hold with another model? | `gpt-6-luna`: Honcho 27/32, transcripts 30/32, Mem0 20/32 with 10 superseded | [CSV](research/data/second-model-eval-v1-episodes.csv) |

Each study's details:

<details>
<summary><b>Study 1: memory from other customers</b></summary>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/study1-success-cost-dark.svg">
  <img alt="Two panels for nine memory conditions. Left: success rates between 73% and 83% with overlapping 95% intervals around the 75% no-memory rate. Right: AI credits per episode between 1.97 and 2.44, with small extra retrieval costs for Hindsight and Honcho." src="docs/figures/study1-success-cost-light.svg" width="100%">
</picture>

<sub><b>Figure 2. Success and cost were similar across conditions.</b> Left: success rate with its
Wilson 95% interval and successes out of 52 paired episodes; the dashed line is the no-memory rate.
Right: recorded AI credits per episode for the agent and customer, plus (orange) model calls the
memory system made at retrieval; building the memory is excluded. Data:
<a href="research/data/memory-study-v1-episodes.csv">per-episode CSV</a>.</sub>

| Condition | Success | Change vs. no memory (95% CI) |
|---|---:|---:|
| none | 39 / 52 (75%) | — |
| raw transcripts | 41 / 52 (79%) | +3.8 pts (−5.8, +13.5) |
| one-pass lessons | 41 / 52 (79%) | +3.8 pts (−9.6, +17.3) |
| sleep-style lessons | 42 / 52 (81%) | +5.8 pts (−7.7, +19.2) |
| workflows | 43 / 52 (83%) | +7.7 pts (−5.8, +21.2) |
| Mem0 | 43 / 52 (83%) | +7.7 pts (−3.8, +21.2) |
| Graphiti | 42 / 52 (81%) | +5.8 pts (−5.8, +17.3) |
| Hindsight | 38 / 52 (73%) | −1.9 pts (−15.4, +11.5) |
| Honcho | 41 / 52 (79%) | +3.8 pts (−7.7, +15.4) |

**No memory design changed task success detectably** (every Holm-corrected p = 1.0). The design could
reliably detect only differences of about 15-20 points, so this is *not* evidence that memory is
useless, only that any benefit here is smaller than that.

- The sleep-style process kept 4 of 89 candidate lessons and produced the shortest memory
  (1,555 characters), with no detectable difference from simpler one-pass lessons.
- Memory from Mem0, Graphiti, Hindsight and raw transcripts carried other customers' order numbers
  (1.6-7.2 per episode), but no agent ever used another customer's identifier in a tool call.

</details>

<details>
<summary><b>Study 2: memory of the same customer</b></summary>

| Condition | Success on later sessions | Change vs. no memory (95% CI) |
|---|---:|---:|
| none | 20 / 22 (91%) | — |
| session transcripts | 19 / 22 (86%) | −4.5 pts (−20.0, +10.5) |
| Mem0 | 18 / 22 (82%) | −9.1 pts (−22.7, 0.0) |
| Honcho | 17 / 22 (77%) | −13.6 pts (−33.3, +4.8) |

Without memory the agent already succeeded on 91% of later sessions, leaving little room to improve.
Memory was, if anything, slightly worse, but no difference is significant, and with only a few
customers differing these intervals are rough. Two of Honcho's five failures were malformed actions
in the first three requests rather than anything its memory said. The clearest failure came from
**stale memory**:

> A customer had changed her address in an earlier session, but the database had since been reset.
> Mem0 and Honcho both "remembered" that the change was done and the old address was gone. Both
> agents acted on that memory and changed the address on the wrong order. The agent without memory
> checked the account and got it right.

This is a single task (n = 1), so it illustrates a failure mode rather than measuring its frequency.

</details>

<details>
<summary><b>Study 3: deleting a conversation</b></summary>

| System | Deleted conversation's identifiers after delete | Other memories kept |
|---|---|---:|
| Mem0 | removed | 100% |
| Graphiti | removed | 100% |
| Hindsight | removed | 100% |
| Honcho | still visible immediately; removed on a recheck minutes later | 100% |
| sleep-style lessons | 4 of 4 lessons kept, with reduced support counts | — |
| one-pass lessons | 0 of 6 lessons kept (each cited every source) | — |

Every system eventually removed the deleted conversation's literal identifiers. The probe checks
exact identifiers only, not paraphrased or derived facts, so it shows deletion working at the
surface, not that the information is fully erased. Lessons that track how many episodes support
them degrade gracefully when one source is withdrawn; lessons that depend on every source collapse.

</details>

<details>
<summary><b>Study 4: remembering an agreement</b></summary>

Some tasks cannot be done without memory. 32 synthetic customers each agreed an exact replacement
item with the agent, then came back in a new conversation and said only "please go ahead with the
exchange we agreed last time".

| What the agent was given | Completed the agreed exchange |
|---|---:|
| Nothing | 0 of 28 |
| The earlier conversation | 26 of 26 |
| The earlier conversation, under a "verify current facts" caution | 23 of 24 |
| Mem0's memory of it | 24 of 24 |
| Honcho's memory of it | 19 of 23 |

Without memory the agent can only guess, so the first two rows confirm that the task needs memory
(all 22 customers with both conditions flipped from failure to success). Mem0's memory kept the exact
item ID in 20 of 24 conversations and Honcho's in 11 of 23. Agents often recovered a missing ID from
the product catalogue, but twice the agent declined to act on Honcho's notes. The differences between
memory designs are not statistically significant at this size. 125 of 160 planned conversations ran;
the run stopped early after a repeated service timeout. Data:
[per-conversation CSV](research/data/commitment-eval-v1-episodes.csv).

</details>

<details>
<summary><b>Study 5: a change of mind</b></summary>

32 synthetic customers agreed a replacement item, then in a later conversation changed their mind and
agreed a different one, then came back and said only "please go ahead with the exchange we agreed last
time". 31 customers completed both agreements.

| What the agent was given | Carried out the latest agreement | Carried out the superseded one | Declined to act |
|---|---:|---:|---:|
| Nothing | 0 of 31 | 0 | 31 |
| Both earlier conversations | 30 of 31 | 0 | 0 |
| Mem0's memory of them | 13 of 31 | 13 | 5 |
| Honcho's memory, default reasoning | 3 of 31 | 0 | 28 |
| Honcho's memory, highest reasoning level | 2 of 31 | 0 | 29 |

Mem0 usually recalled both items, often noting the change, yet the agent chose the old one about as
often as the new one. With Honcho's memory the agent mostly refused to act, always pointing to an
earlier "not today" and sometimes to conflicting notes; a higher reasoning level did not change that. Every memory
condition did significantly worse than the plain transcripts. These results come from one model, each
system's default pipeline and one synthetic task, so they describe this setup, not the products. Data:
[per-conversation CSV](research/data/changed-mind-eval-v1-episodes.csv).

</details>

<details>
<summary><b>Study 6: dating the memories</b></summary>

Study 5 again with 32 new customers (31 completed both agreements), the agreements dated 3 and 1 days
before the follow-up, and every agent told today's date.

| What the agent was given | Carried out the latest agreement | Carried out the superseded one | Declined and asked |
|---|---:|---:|---:|
| Both earlier conversations, dated | 29 of 31 | 0 | 2 |
| Mem0, undated / dates written into the text | 17 / 17 of 31 | 9 / 5 | 5 / 9 |
| Honcho, undated / backdated timestamps | 3 / 8 of 31 | 0 / 0 | 28 / 22 |

Neither date treatment changed success or superseded actions significantly (Mem0 9 vs 9 discordant
customers; Honcho 7 vs 2, adjusted p = 0.36), although the dated memories reported the right dates (Mem0 28, Honcho 31 of 31).
Declining is a safe failure here only because the scripted customer never repeats the item; a real
one would likely say it when asked. Data:
[per-conversation CSV](research/data/changed-mind-dated-eval-v1-episodes.csv).

</details>

<details>
<summary><b>Study 7: Honcho's features and a helpful customer</b></summary>

32 new customers, Study 6's dated setup. Honcho's raw message search, rather than its summarized
answer, gave the agent both items' exact IDs every time:

| What the agent was given | Customer | Carried out the latest agreement | Carried out the superseded one |
|---|---|---:|---:|
| Honcho's summarized answer | never repeats the item | 8 of 32 | 0 |
| Honcho's message search | never repeats the item | 14 of 32 | 0 |
| Nothing | names the item when asked | 32 of 32 | 0 |
| Both earlier conversations, dated | names the item when asked | 32 of 32 | 0 |
| Honcho's summarized answer | names the item when asked | 27 of 32 | 0 |
| Mem0, dates in the text | names the item when asked | 30 of 32 | 2 |

None of the pre-specified comparisons was significant (search vs summary 11 vs 5 discordant
customers, p = 0.21). With a customer who names the item on request, no memory was enough, and memory
mattered mainly through harm: Mem0's memory twice led the agent to the superseded item, Honcho's never
did. Data: [per-conversation CSV](research/data/honcho-features-eval-v1-episodes.csv).

</details>

<details>
<summary><b>Study 8: what helps Honcho act on the latest agreement</b></summary>

Study 6's dated setup with 30 new customers who never repeat the item (2 more were excluded because
their first agreement failed):

| What the agent was given | Carried out the latest agreement | Declined |
|---|---:|---:|
| Honcho's summarized answer | 8 of 30 | 22 |
| The same, after Honcho "dreamed" over each customer | 12 of 30 | 18 |
| No memory up front, but a tool to ask Honcho mid-conversation | 1 of 30 | 29 |
| Facts our app wrote into Honcho, then Honcho's answer | 26 of 30 | 4 |
| The same facts given directly, without Honcho | 29 of 30 | 1 |

Only the app-written facts beat Honcho's plain answer significantly (adjusted p < 0.001), and giving
those facts straight to the agent did as well, so the gain came from the app summarizing each
conversation into "what was agreed last", not from Honcho itself. The agent rarely used the memory
tool (5 of 30 conversations). No condition carried out the superseded item. Data:
[per-conversation CSV](research/data/honcho-stage3-eval-v1-episodes.csv).

</details>

<details>
<summary><b>Study 9: a second model</b></summary>

Study 6's dated setup with 32 new customers, `gpt-6-luna` playing the agent, the customer and the
LLM inside each memory system, and a customer who never repeats the item:

| What the agent was given | Carried out the latest agreement | Carried out the superseded one | Declined |
|---|---:|---:|---:|
| Both earlier conversations, dated | 30 of 32 | 0 | 0 |
| Mem0, dates in the text | 20 of 32 | 10 | 1 |
| Honcho's summarized answer | 27 of 32 | 0 | 2 |
| Honcho's message search | 28 of 32 | 0 | 0 |

Mem0 did significantly worse than the transcripts on both success and superseded actions (adjusted
p = 0.04 and 0.006), as with Claude Haiku 5.5. Honcho's two conditions were close to the transcripts,
unlike with Claude Haiku 5.5 (8 and 14 of 32), where the agent mostly declined to act. Both the agent
and Honcho's internal model changed, so this cannot say which one mattered. Data:
[per-conversation CSV](research/data/second-model-eval-v1-episodes.csv).

</details>

### Takeaways

- **Measure memory on actions, not answers.** The revealing failures (wrong order, stale address)
  only appear when the agent has to act.
- **Memory gains here are small, if they exist.** Detecting a 5-point improvement would need roughly
  ten times as many paired episodes as this study used.
- **Stale memory is the sharper risk.** A memory system that does not know when a fact has expired
  can turn a correct agent into an incorrect one.
- **When a task depends on memory, memory decides it, and summaries can drop what matters.** Given the
  earlier conversation word for word, agents honoured the agreement 49 of 50 times (the miss was a
  malformed tool call); a summarized memory sometimes lost the exact item number.
- **Memory needs to know what came last.** When an agreement changed, transcripts kept the order and
  the agent followed the latest one; summarized memories either revived the superseded agreement or
  left the agent unsure enough to do nothing. Giving them real dates did not significantly change that.
- **A helpful customer covers most memory gaps; harm is what remains.** When the customer named the
  item on request, no memory succeeded every time, while a memory that recalled the old agreement could
  still steer the agent to it.
- **Write down what was decided.** Having the app summarize each conversation into the latest
  agreement fixed most failures (29 of 30 given directly, 26 of 30 through Honcho); what the memory
  system stored on its own did not.
- **Model choice can matter as much as the memory system.** With `gpt-6-luna` in every role, Honcho's
  hesitation largely disappeared while Mem0's superseded-item harm remained.
- **Deletion needs provenance.** Systems can only forget cleanly if they record where each memory
  came from.

## Verify the numbers

Every Study 1, 2 and 4-9 table and both figures are recomputed from public per-episode tables,
[memory-study-v1-episodes.csv](research/data/memory-study-v1-episodes.csv),
[commitment-eval-v1-episodes.csv](research/data/commitment-eval-v1-episodes.csv),
[changed-mind-eval-v1-episodes.csv](research/data/changed-mind-eval-v1-episodes.csv),
[changed-mind-dated-eval-v1-episodes.csv](research/data/changed-mind-dated-eval-v1-episodes.csv),
[honcho-features-eval-v1-episodes.csv](research/data/honcho-features-eval-v1-episodes.csv),
[honcho-stage3-eval-v1-episodes.csv](research/data/honcho-stage3-eval-v1-episodes.csv) and
[second-model-eval-v1-episodes.csv](research/data/second-model-eval-v1-episodes.csv), which contain no
transcripts, prompts, customer names or account data. CI fails if a published number or figure
stops matching it:

```powershell
python -m research.benchmark verify   # every published table and both figures, from the CSVs
python -m research.benchmark list     # each study's CSV and the command that recomputes its table
```

Rerunning the episodes needs the pinned benchmark, Copilot access and a request budget; see the
[research setup](research/README.md). The study started 12,428 model requests and recorded 1,425
Copilot AI credits (about $14.25 of allowance); see [costs](research/COSTS.md). Full tables, failure
causes and deviations are in the [results](research/RESULTS.md).

## Local app

The repository also contains a small local workspace that extracts quoted facts from your notes
with a local [Ollama](https://ollama.com) model, builds memory from them, and revises that memory
when a source note is corrected or deleted. A conclusion is withdrawn when a fact it depends on is
removed, and kept while an alternative supporting source remains. It runs entirely on your machine;
see [the local app guide](docs/LOCAL-APP.md).

```powershell
python -m afterevidence doctor
python -m afterevidence serve
```

## Limitations

- **Two models, one domain.** Studies 1-8 use Claude Haiku 5.5 in every role, on retail customer
  service. Study 9 repeated the change-of-mind task with `gpt-6-luna`, and Honcho's results changed
  markedly, so the findings depend on the model; other models, retrieval styles or domains may differ.
- **Low power.** 26 tasks × 2 runs can detect only large effects (about 15-20 points).
- **Mostly one retrieval per episode.** Memory was fetched once from the first message; only Study 8
  tried an on-demand memory tool, with one model and one tool design.
- **Default pipelines.** Each memory system ran its default configuration on a substituted model;
  their published results use other models. Builders can propose tuned configurations as separate
  arms ([fairness rules](research/README.md#fairness-to-memory-system-builders)).
- **Simulated customers and narrow scoring.** The customer is an LLM whose fidelity has not been
  human-reviewed, and scoring checks the database, not conversational quality.

## Open questions

| Question | Status |
|---|---|
| Does labelling memories with when they were written, and whether they were later corrected, stop an agent from acting on stale ones? | A first small synthetic run could not separate the conditions: the agent checked the live account every time, ignoring stale and valid memories alike. No comparison result. |
| Would provider memory that records when each fact was agreed, or retrieval that asks for the latest agreement, close the gap to transcripts in Study 5? | Dates tested in Study 6: dated memories reported the right dates (Mem0 28, Honcho 31 of 31) but did not significantly change the outcome for either system. Study 7: Honcho's raw message search instead of its summary carried exact IDs every time but did not significantly change success (14 vs 8 of 32). Study 8: facts the app writes into Honcho did (26 vs 8 of 30), as did the same facts without Honcho (29 of 30). Retrieval that asks for the latest agreement is not yet tested. |
| Do agents that query memory step by step, rather than once up front, benefit more? | Study 8 gave the agent an on-demand Honcho memory tool instead of up-front memory: it called it in 5 of 30 conversations and succeeded once. Other tool designs and models are not yet tested. |

Designs: [research design](research/DESIGN.md).

## Validate

No model, credentials or benchmark download needed:

```powershell
python -m pip install ".[dev]"
python -m unittest discover -s tests -v
python -m unittest research.test_memory_methods research.test_costing research.test_memory_csv -v
ruff check afterevidence tests research scripts
pyright
```

## Code tour

| Path | What it does |
|---|---|
| [`research/PROTOCOL-MEMORY.md`](research/PROTOCOL-MEMORY.md) | The analysis protocol, git-tagged `memory-study-v1` before any test episode |
| [`research/RESULTS.md`](research/RESULTS.md) | Full tables, failure causes and deviations |
| [`research/memory_bank.py`](research/memory_bank.py) | Builds the in-house memories: transcripts, lessons, sleep-style lessons, workflows |
| [`research/memory_gateway.py`](research/memory_gateway.py) | Adapters for Mem0, Graphiti, Hindsight and Honcho |
| [`research/tau_copilot.py`](research/tau_copilot.py) | Runs one τ²-bench episode with the agent, simulated customer and memory |
| [`research/memory_analysis.py`](research/memory_analysis.py) | Statistics, including recomputation from the public CSV |
| [`research/figures.py`](research/figures.py) | Draws the README figures from the public CSV |
| [`research/data/`](research/data/memory-study-v1-episodes.csv) | The public per-episode table |
| [`afterevidence/`](afterevidence/) | The local memory app: extraction, store, revision and web UI |
| [`tests/`](tests/) | App, lifecycle and documentation tests |

## Related work

Most memory benchmarks score answers to questions about past conversations:
[LoCoMo](https://arxiv.org/abs/2402.17753), [LongMemEval](https://arxiv.org/abs/2410.10813) (including
knowledge updates) and [MemoryAgentBench](https://arxiv.org/abs/2507.05257) (including selective
forgetting). A newer line scores memory by what an agent does:

| Benchmark | What memory is | How it is scored | Systems compared |
|---|---|---|---|
| [MemoryArena](https://arxiv.org/abs/2602.16313) (ICML 2026) | Across interdependent sessions (web, planning, search, reasoning) | Task success | Memory agents and long-context baselines |
| [Mem2ActBench](https://aclanthology.org/2026.acl-long.370/) (ACL 2026) | Preferences and task state from long interrupted chats | Tool and parameter choice | Seven memory frameworks |
| [MemGym](https://arxiv.org/abs/2605.20833) | Within one long episode: compressing the agent's own trajectory (its tau2-bench track runs all four domains) | Paired success with vs without memory, plus memory-isolated scores | Summary, A-Mem, MemoryBank, LightMem, SimpleMem |
| **Forget-Me-Not** | Across conversations with the same or other customers, including an agreement later superseded | Final store database vs a reference, with the analysis tagged before the data | Mem0, Graphiti, Hindsight and Honcho default pipelines, transcripts, lessons; deletion through each system's API |

What this repository adds is harm and deletion: whether remembered agreements lead to the *wrong*
action once superseded (Studies 5-9), and whether deleting a conversation removes what was derived
from it (Study 3), scored without an LLM judge. Vendor-reported results on the QA benchmarks use
each vendor's own model and settings and often disagree with each other; these studies hold the
model and task fixed and run each system's open-source default. [ExpeL](https://arxiv.org/abs/2308.10144)
and [Agent Workflow Memory](https://arxiv.org/abs/2409.07429) inspired two memory conditions; other
studies of agent memory and forgetting include [Memora](https://arxiv.org/abs/2604.20006),
[Bemula](https://arxiv.org/abs/2610.18052), [GateMem](https://arxiv.org/abs/2606.18829) and
[execution-state unlearning](https://arxiv.org/abs/2609.04875).

## License

[MIT](LICENSE). τ²-bench and each memory system keep their own licenses and are not bundled.
Databases, run journals, credentials and model weights are never published.
