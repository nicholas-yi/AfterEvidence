# Smaller models, smaller studies, and cost

## This project is not training model weights

Current work uses inference to extract assertions, consolidate external memory,
and operate benchmark tools. It has not trained an adapter, fine-tuned Qwen,
or implemented Google's parameter-growing Sleep method.

There are three different ways to make an experiment smaller:

| Choice | Helps with | Main risk |
|---|---|---|
| Fewer development tasks, seeds, or turns | Iteration speed and inference budget | Weak precision or an incomplete task |
| A smaller/cheaper inference model | Per-token cost and sometimes latency | More errors, retries, or longer trajectories can erase the saving |
| A smaller model for actual training | Training memory, compute, and adapter feasibility | Poor task capability or transfer; not a substitute for an adequate baseline |

## Recommended sequence

1. Use a small, declared development set to prove the runtime, scoring, and
   actor/simulator behavior. Preserve failed attempts.
2. Use a capable, fixed baseline before studying memory effects. A weak actor
   at a performance floor is a confound, not a cheap research success.
3. Use smaller models for bounded extraction or consolidation only after
   checking the kinds of errors that affect downstream actions.
4. Keep a distinct, calibrated evaluator where judgment is required. Do not
   assume a cheap judge is reliable because it returns valid JSON.
5. Account for the entire pipeline: agent, simulator, consolidation, retrieval,
   evaluation, retries, and discarded outputs. Fixed memory cost is part of
   the comparison, not free preprocessing.
6. Freeze the main sample and analysis before running it. Do not keep shrinking
   the sample or dropping hard tasks until the desired result appears.

The local 4B model's first native-task development failure does not establish
that all small models are unsuitable. Equally, a tiny passing fixture does not
show that the smallest model is adequate for a real tool-use study.

If parameter training becomes justified later, a small open model and an
adapter can be a feasibility starting point. That requires an explicit training
setup, data/license checks, transfer evaluation, and its own budget. A LoRA
experiment alone is not a reproduction of Google's Sleep architecture.
