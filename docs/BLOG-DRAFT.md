# Does agent memory help when the agent has to act? Nine approaches, one null result

*Draft. Numbers come from [the memory study](../research/RESULTS.md#memory-study-v1);
the protocol was [committed and tagged](../research/PROTOCOL-MEMORY.md) before
any test episode ran.*

## TL;DR

- On a customer-service benchmark scored by the store's database state, nine
  memory setups produced **no detectable change in task success**: 75% with no
  memory, 73-83% with memory, and every corrected p-value was 1.0. With two
  runs per task only large effects were detectable, so this is not evidence
  that memory and no memory are equivalent.
- That includes Mem0, Graphiti, Hindsight, Honcho, induced workflows, and a
  memory-level take on Google's "sleep" consolidation (not a reproduction of
  its weight training).
- When the same customer came back, memory of their earlier sessions did
  slightly *worse* than none. The clearest failure came from facts that had
  stopped being true.
- In a small deletion probe, a deleted conversation's identifiers disappeared
  from all four memory products (Honcho only on a recheck minutes later). That
  is a narrow check, not proof that everything derived from it was erased.

## The setup

[tau2-bench](https://github.com/sierra-research/tau2-bench) retail gives an
agent real tools (look up orders, exchange items, cancel, change addresses) and
a simulated customer. Success requires a completed, scored episode whose final
database matches the target; this does not certify conversational quality or
general policy compliance.

- One model everywhere: Claude Haiku 5.5 (via GitHub Copilot) as agent,
  simulated customer, and each memory system's internal LLM. Embeddings were
  local (`nomic-embed-text`).
- Memory came from 30 earlier conversations with customers who never appear
  in the test set. It was retrieved once from the customer's opening message,
  capped at 2,400 characters, and labeled as possibly outdated.
- Study 1: 26 judge-free test tasks, two runs each, paired against the same
  task without memory. Study 2: database scoring only; eight later sessions'
  natural-language assertions were unassessed.

## Result 1: memory from other customers did not move success

![Study 1](figures/study1-success-cost.svg)

| Memory | Success | Credits / episode |
|---|---:|---:|
| None | 39/52 | 2.02 |
| Raw transcripts | 41/52 | 2.25 |
| One-pass lessons | 41/52 | 2.27 |
| Sleep-style lessons | 42/52 | 2.11 |
| Induced workflows | 43/52 | 1.97 |
| Mem0 | 43/52 | 2.05 |
| Graphiti | 42/52 | 2.17 |
| Hindsight | 38/52 | 2.44 |
| Honcho | 41/52 | 2.25 |

Credits are recorded agent + simulator credits per planned episode, plus
retrieval for Hindsight (0.31) and Honcho (0.17); building memory is excluded.

Why memory added no detectable benefit is unresolved; failure causes were not
comprehensively established. One possible explanation, not tested here: the
baseline agent was already given the store policy, so most of what memory could
teach ("verify identity first", "exchanges need delivered orders") was already
in context.

### What about "sleep"?

Google's [Language Models Need Sleep](https://arxiv.org/abs/2606.03979)
consolidates experience into model weights. That cannot run on a hosted model,
so the study tested the memory-level idea instead: replay each episode, merge
similar lessons, weight each by how many episodes support it, and prune the
weak ones. 89 candidate lessons became 4. Success was 42/52, statistically
indistinguishable from everything else. What the support counts did buy was
graceful deletion: removing a source episode left all 4 lessons standing with
less support, while one-pass lessons that cite every source had to be dropped.

## Result 2: remembering the same customer can backfire

16 customers had several tasks each. Every later session ran with and without
memory of that customer's earlier sessions. The benchmark resets the database
between sessions, so a remembered change might no longer hold.

| Memory | Success on 22 later sessions |
|---|---:|
| None | 20 |
| Session transcripts | 19 |
| Mem0 | 18 |
| Honcho | 17 |

None of these differences is significant. The clearest loss is instructive:
Mem0 and Honcho both recalled that a customer's address change was done and her
old address was "no longer on file". In the current database it was still on
file, and both agents changed the wrong order. The agent without memory got it
right. This illustrates a reset-state staleness risk, not evidence that memory
generally harms agents.

## Result 3: deleted identifiers disappear (a narrow check)

Each provider stored three conversations; one was deleted through the
provider's own API. Mem0, Graphiti, and Hindsight immediately showed no
identifier from the deleted conversation and kept all others. Honcho still
showed one identifier right after deletion and none a few minutes later; why
was not established. The probe matches literal identifiers only, so a
paraphrased fact derived from the deleted conversation would not be caught.

## Caveats

One model, one domain, two runs per task: only large effects were detectable.
Study 1 used tasks scorable without an LLM judge; Study 2 was scored on the
database alone. Providers ran their default pipelines on a substituted model.
Retrieval was a single shot, not an agent deciding when to recall. No human has
yet reviewed the simulated customers' fidelity. These results say "no large
effect detected here", not "memory never helps" and not "memory is equivalent
to none".

## What I would try next

- **Staleness-aware memory:** store when and from what each fact came, and
  have the agent check current tool results before acting on it. A controlled
  synthetic diagnostic is [proposed](../research/DESIGN.md#proposed-follow-up-staleness-aware-memory-approval-pending-not-tagged-not-run)
  but not yet approved or run.
- **Harder tasks or a weaker base agent**, where a no-memory agent has more
  room to fail.
- **Agentic retrieval** instead of one up-front lookup.

## Inspect the implementation

The public [AfterEvidence](https://github.com/nicholas-yi/AfterEvidence)
repository provides the [protocol](../research/PROTOCOL-MEMORY.md),
[runbook](../research/MEMORY-STUDY.md), and implementation; historical journals
and provider state remain private. The study can be repeated with new model
calls (results will vary), but the reported tables cannot be recomputed from the
public repository alone. The study logged 12,428 started requests and 1,425.05
recorded credits; eight billing snapshots are missing. About $14.25 is recorded
allowance value, not an invoice.
