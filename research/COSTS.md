# Model access and measured cost estimates

## Subscription is not an API balance

[ChatGPT Plus](https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus)
is a chat subscription; ordinary API use is separately billed. Buying a
$20/month chat plan does not buy a fixed number of API requests.

The user selected **existing GitHub Copilot allowance**, not a separately paid
OpenAI/Anthropic API. The supported [Copilot SDK](https://github.com/github/copilot-sdk)
can use that account. API keys are unnecessary for this route.

## Actual measured three-request pilot

Model: account-enabled `claude-haiku-5.5`.

| Metric | Recorded value |
|---|---:|
| Completed SDK requests | 3 |
| Underlying model requests reported by session metrics | 3 |
| Input tokens | 8,217 |
| Output tokens | 385 |
| Duration | 11.75 seconds |
| AI-credit usage | 0.1135835 |
| Dollar-equivalent credit value | $0.001135835 |

These are allowance-consumption metrics, not a cash invoice. No directly
billed OpenAI/Anthropic API was used; GitHub's actual billing remains the
authority for any allowance or overage treatment.

The pinned SDK reports nano-AI units. The summary divides by `1e9` to express
AI credits and then applies GitHub's published **1 AI credit = $0.01** rate.
See [usage metrics](https://github.com/github/copilot-sdk/blob/ed814e4134fdba86e2e88b82dcac85b1c125ed8a/docs/features/usage-and-billing.md)
and [Copilot billing](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing).

Do not double-count the same charge in root, per-model, provider, event, and
session snapshots. `costing.py` sums one completed fresh-session total per
request and rejects incomplete/missing accounting instead of declaring it free.

## Account-quota interpretation

The authorized check returned a remaining-percentage snapshot before and
immediately after the micro-pilot. The user's raw values remain in the private
local journal. A rounded, unchanged snapshot is not proof of no consumption.
Quota reporting may lag, and the
legacy request counters must not be equated to raw model calls or AI credits.
The returned reset timestamp should not be assumed to establish a monthly
billing schedule without confirming the account's billing page.

To guarantee no additional charges, configure
the account/admin budget and stop-on-budget setting described by GitHub.
This project does not silently change billing settings.

Raw quota/account values are retained only in the local git-ignored journals,
not duplicated into committed research data.

## Planning estimates, not quotes

The local-Qwen native conversation used 12 model calls and 45,492 input /
816 output tokens. It is only one failed development conversation; another
model's tokenization, trajectory length, reasoning, and caching will differ.

At [GPT-5.4 mini's listed API rates](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
of $0.75/M input and $4.50/M output, that exact token volume would be about:

| Illustrative scope | Base inference only |
|---|---:|
| One conversation | $0.037791 |
| 24 conversations | $0.906984 |
| 96 conversations | $3.627936 |

This was a separate-provider illustration, **not** a model available through
this account, an approved purchase, or a full-study bill. The Copilot account
did not offer that model during the check.

For the selected Copilot Haiku model, the measured micro-pilot averaged about
0.0379 credits per request. A simple 10-30-request conversation projection
would be roughly **0.38-1.14 credits** ($0.0038-$0.0114 in credit value).
The micro-pilot contains two short user-simulator requests and one larger
agent request, so that average can underestimate an agent-heavy conversation.

For planning only, reserve **1-5 credits per full development conversation**
before new measurements. This is not a guaranteed bound or a correctness claim.
Consolidation, a distinct policy judge, retries, malformed outputs, and longer
conversations must all be included in the eventual study budget.

### Larger, still bounded development trace

The user next authorized at most 20 requests for one native-task pilot:

| Attempt | Requests | Input tokens | Output tokens | AI credits | Credit-value equivalent |
|---|---:|---:|---:|---:|---:|
| Plain-JSON adapter rejected a prose reply | 2 | 8,021 | 270 | 0.1137425 | $0.001137425 |
| Structured-action retry, capped before termination | 18 | 168,448 | 9,292 | 2.2129105 | $0.022129105 |
| Including the earlier 3-request micro-pilot | **23** | **184,686** | **9,947** | **2.4402365** | **$0.024402365** |

No requests beyond the approved 20 were made in that full-conversation gate.
The cap stopped a real action-executing conversation; it did not produce a
completed benchmark pass. A format failure is not counted as a scored episode.

The 18-request trace is a better planning basis than the three-message
opening. It generated much more output per request. At the same measured
cost, 24 such **partial** trajectories would consume about 53.11 credits
($0.53 value), and 96 about 212.44 credits ($2.12 value), before completing
the conversations or adding consolidation and independent scoring.

For a 24-trajectory exploratory comparison, a **100-300-credit planning
reserve** ($1-$3 in allowance value) is more defensible than extrapolating
only the short opening. For 96 trajectories, reserve **400-1,000 credits**
($4-$10 value). These are provisional estimates, not guaranteed maximum
charges or evidence that the underlying agent is adequate.

The next step is to finish a small number of valid scored development tasks
within a newly approved request cap. A main study remains blocked on that
feasibility gate and on a frozen, committed/tagged protocol.

## Guardrails and failed setup attempts

- Micro-pilot: three total requests.
- The runtime rejected a 10-credit per-session limit; its supported minimum
  is 30. The pilot used that explicit minimum, not an unbounded session.
- A per-session credit limit is not a cash prepayment. It also does not replace
  the account's overage/budget settings.
- Older incompatible SDK/runtime, unavailable-model, relative-path, and
  too-small-limit attempts failed before inference. Their started journals
  remain, but they are not counted as completed successful model calls.
- The previous local Qwen pilot completed with ENV reward 0, not a memory win.
- No registered main experiment or full four-condition result exists yet.

## 2026-11-13 baseline follow-up

A new allowance authorized at most 90 requests across development tasks 0, 1,
and 2, capped at 30 per task. The source-hashed development plan and adapter
amendments were saved before their respective calls.

| Attempt | Requests | Input tokens | Output tokens | AI credits |
|---|---:|---:|---:|---:|
| Task 0, rejected mixed message/tool fields | 14 | 113,326 | 7,728 | 1.546155 |
| Task 1, rejected empty message | 4 | 18,315 | 375 | 0.208421 |
| Task 1, repaired action contract; completed | 17 | 147,385 | 6,530 | 1.8368675 |
| Task 2, blocked by strict reference preflight | 0 | 0 | 0 | 0 |
| **Follow-up total** | **35** | **279,026** | **14,633** | **3.5914435** |

The follow-up consumed about **$0.035914435 in allowance value**, not a separate
API invoice. Task 1 used 21 requests including its failed attempt. Its completed
episode received native ENV/task-basis reward 1.0 and took 102.422 seconds;
that single successful trajectory alone is not the total cost of development.

All 35 started requests have completed billing snapshots. The 55 unused
requests were not spent on replacement tasks or unapproved judges. No API plan
was purchased. Cumulative Copilot usage including the earlier pilots is now
**58 requests and 6.03168 AI credits**, about **$0.0603168 in credit value**.

The first two attempts used different action schemas; the failed attempts are
retained and counted. These figures are development accounting, not an
efficacy estimate or a guaranteed price for another model or task cohort.
See [the full result and remaining gates](RESULTS.md#bounded-baseline-follow-up-2026-11-13).

## 2026-11-13 devbox cohort

The owner approved 12 train tasks at 30 requests each (**360 total**, covering
actor, simulator, and failures; no judges). Each task ran once; unused requests
were not reallocated.

| Task | Requests | Input tokens | Output tokens | AI credits |
|---|---:|---:|---:|---:|
| 20 (contract failure) | 2 | 8,362 | 270 | 0.118005 |
| 35 | 23 | 220,499 | 10,179 | 2.7859365 |
| 66 (contract failure) | 2 | 8,257 | 190 | 0.084552 |
| 69 | 16 | 117,343 | 4,468 | 1.36866 |
| 73 | 11 | 72,777 | 2,353 | 0.80881 |
| 75 | 12 | 88,101 | 2,946 | 0.9989615 |
| 78 | 24 | 231,043 | 7,443 | 2.7493245 |
| 80 (contract failure) | 4 | 17,796 | 472 | 0.181288 |
| 81 | 15 | 130,108 | 4,821 | 1.5347965 |
| 82 | 18 | 155,412 | 6,641 | 1.898079 |
| 88 | 15 | 117,832 | 3,822 | 1.351349 |
| 91 | 20 | 177,643 | 7,541 | 2.180018 |
| **Cohort total** | **162** | **1,345,173** | **51,146** | **16.0597800** |

- About **$0.1606 in allowance value**; 198 of the 360 approved requests unused.
- Every started request has a completed billing snapshot (`research.costing`).
- Observed 0.099 credits per request, below the 0.103-0.110 planning range,
  because no task reached its 30-request cap. Scored episodes averaged 17.1
  requests and about 1.74 credits.
- The premium-interaction quota display read 99.9% before and after; a rounded
  display is not evidence of zero usage.

Cumulative Copilot usage across all pilots: **220 requests**,
**1,808,885 input / 75,726 output tokens**, **22.09146 AI credits**
(about $0.2209 in allowance value). These are allowance measurements, not
separate API invoices.

## Memory study v1

Approved hard cap: **16,000 requests**, enforced before each episode from every
journal (episodes, builders, provider shims). Planning estimate: 1,200-1,600
credits.

| Component | Requests | AI credits |
|---|---:|---:|
| Learning-pool episodes (30 tasks + one probe) | 559 | 62.64 |
| Smoke tests (shim, two development episodes) | 46 | 5.10 |
| Internal memory builders (raw, consolidated, sleep, workflows) | 33 | 2.26 |
| Mem0 ingestion + Study 2 calls | 53 | 7.23 |
| Graphiti ingestion | 197 | 53.07 |
| Hindsight ingestion + Study 1 retrieval | 205 | 46.76 |
| Honcho ingestion + Study 1 and 2 calls | 469 | 34.93 |
| Study 1 episodes (468 planned) | 8,911 | 990.85 |
| Study 2 episodes (104) | 1,887 | 213.88 |
| Study 3 provider calls | 68 | 8.32 |
| **Total started** | **12,428** | **1,425.05 recorded** |

- About **$14.25 in allowance value**, not a separate cash invoice; 117.9M input
  and 5.13M output tokens.
- Ingestion alone (30 bank episodes plus one scratch smoke test): Mem0 4.4,
  Honcho 12.9, Hindsight 30.4, Graphiti 53.1 credits.
- 12,420 of 12,428 started requests have completed billing snapshots. Eight were
  aborted (credential timeouts or a crash): counted as started, cost unknown, so
  1,425.05 is the recorded total, not a complete one. Recounted from every
  journal on 2026-11-13.
- Study 1 credits per episode (1.97-2.27; none 2.02): recorded actor + simulator
  credits averaged over all 52 planned episodes, plus retrieval 0.31 (Hindsight)
  and 0.17 (Honcho). Mem0 and Graphiti retrieval made no model calls; embeddings
  ran locally and were not billed. One-off construction (builders, ingestion)
  is excluded from per-episode figures.
- Study 2 figure credits are actor + simulator only; its Mem0 (2.81) and Honcho
  (13.28) provider calls are in the table rows above.
- Cumulative Copilot usage across all AfterEvidence pilots and studies:
  **12,648 requests** and about **1,447.14 AI credits** (about $14.47).
- Staleness Stage A (owner-approved cap 144 requests / 36 credits, 2026-11-13):
  **74 requests** started, all billed, **1.07 AI credits** recorded (max single
  call 0.026). Cumulative: **12,722 requests**, about **1,448.21 credits**.
- Necessary-memory pilot (owner-approved cap 240 requests / 60 credits,
  2026-11-14; killed at the session-1 gate): **17 requests** started, all
  billed, **1.94 AI credits** (max single call 0.17). Cumulative: **12,739
  requests**, about **1,450.14 credits**.
- Necessary-memory pilot v2 (same approval; 2026-11-14; stopped at the
  session-1 gate by a call timeout): **10 requests** started, 9 billed, **0.86
  AI credits** recorded (one aborted request's cost unknown). Pilot v1 + v2: 27
  of 240 requests, 2.79 of 60 credits. Cumulative: **12,749 requests**, about
  **1,451.00 credits** recorded.
- Necessary-memory pilot v3 (same approval; 2026-11-14; killed at its R/Hn
  gates): **176 requests**, all billed, **21.32 AI credits**. Pilots v1-v3: 203
  of 240 requests; 24.11 credits recorded, 25.11 charged with v2's abort at 1.0.
  Cumulative: **12,925 requests**, about **1,472.32 credits** recorded.
- Necessary-memory pilot v4 (separate owner approval: cap 264 requests /
  40-credit stop; 2026-11-14; all gates passed): **155 requests**, all billed,
  **17.50 AI credits** (max single call 0.16; 0.113 credits per request; v3 +
  v4 pooled 0.117). Cumulative: **13,080 requests**, about **1,489.82 credits**
  recorded.
- Necessary-memory pilot v5 (separate owner approval: cap 160 requests including
  provider shims / 25-credit stop; 2026-11-14; integration gate passed): **81
  requests**, all billed, **8.13 AI credits** (episodes 59 / 6.48, Mem0 shim 4 /
  0.40, Honcho shim 18 / 1.25; max single call 0.20). Cumulative: **13,161
  requests**, about **1,497.95 credits** recorded.
- Necessary-memory evaluation v1 (owner approval: 2,816 requests / 310-credit
  stop; tags `commitment-eval-v1` and `-amend1`; partial, stopped by a second
  timeout): **1,365 requests** (session 1 186, session 2 1,036, Mem0 shim 32,
  Honcho shim 111), **152.99 AI credits** recorded, 155.99 charged with 3 aborts
  at 1.0 (max single call 0.20). Cumulative: **14,526 requests**, about
  **1,650.94 credits** recorded.
- Changed-mind pilot (owner approval: 240 requests including provider shims /
  30-credit stop; 2026-11-14; integration gates passed): **209 requests** (episodes
  180, Mem0 shim 8, Honcho shim 21), all billed, **23.07 AI credits** (max single
  call 0.20). Cumulative: **14,735 requests**, about **1,674.01 credits** recorded.
- Honcho `max` check (owner approval: 100 requests / 12-credit stop): **53 requests**
  (episodes 46, Honcho shim 7), **6.53 AI credits**.
- Changed-mind evaluation (owner approval: 3,120 requests / 360-credit stop; tag
  `changed-mind-eval-v1`): **2,118 requests** (episodes 1,835, Mem0 shim 62, Honcho
  shim 221), **239.15 AI credits** recorded, 240.15 charged with 1 abort at 1.0 (max
  single call 0.22). Cumulative: **16,906 requests**, about **1,919.69 credits** recorded.
- Dated changed-mind dev check (owner approval: 200 requests / 25-credit stop): **132
  requests** (episodes 101, Mem0 shim 8, Honcho shim 23), **15.09 AI credits**.
  Cumulative: **17,038 requests**, about **1,934.78 credits** recorded.
- Dated changed-mind evaluation (owner approval: 3,408 requests / 400-credit stop;
  tag `changed-mind-dated-eval-v1`): **2,197 requests** (episodes 1,735, Mem0 shim
  124, Honcho shim 338), **243.38 AI credits**, no aborts (max single call 0.23). A
  providers-phase launch error was rejected before any billed call. Cumulative:
  **19,235 requests**, about **2,178.16 credits** recorded.
- Honcho features (owner decision "staged_auto"; tag `honcho-features-eval-v1`): Stage 1
  dev check **205 requests** (episodes 176, Mem0 shim 8, Honcho shim 21), **23.86 credits**;
  Stage 1b rerun **122 requests**, **13.98 credits**; Stage 2 evaluation **2,286 requests**
  (episodes 2,031, Mem0 shim 64, Honcho shim 191) of 3,000, **259.08 AI credits** recorded,
  260.08 charged with one abort at 1.0 (max single call 0.22). Cumulative: **21,848
  requests**, about **2,475.08 credits** recorded.
