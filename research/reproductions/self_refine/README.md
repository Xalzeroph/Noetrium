# Self-Refine reproduction lane

Source paper: https://arxiv.org/abs/2303.17651  
Official repository: https://github.com/madaan/self-refine

Status: scaffolded; mechanism fidelity frozen; benchmark matching pending.

## Scientific ownership

This reproduction owns the Self-Refine method semantics: initial generation, self-feedback, iterative refinement, task-specific stopping policy, task-specific prompt templates, and the requirement that the baseline reuses the same model across generator/feedback/refiner roles.

The generic `ReferenceSelfRefineMethod` exposes those roles as typed ports so experiments can bind a single model-backed implementation to all three roles without coupling method semantics to a provider SDK.

## Platform ownership

Noetrium owns model invocation, model/request budget admission, execution context, durable checkpoints/progress, evidence, experiment orchestration, artifact lineage and provider qualification. The reproduction must not create a second model runtime, checkpoint system, evidence store or experiment runner.

## Fidelity rule

Do not hard-code one global attempt count. The official repository has task-specific runners and stopping behavior. A matched experiment must pin the exact task runner, prompt set, model/configuration, sample split, attempt budget and evaluation procedure used for that task, then record them as run evidence.

## Next matched targets

Start with one deterministic/easy-to-audit task lane and one open-ended generation lane. Compare one-step generation against Self-Refine under the same model/configuration. After mechanism and metric parity are demonstrated, expand across the remaining official tasks rather than generalizing from a single benchmark.
