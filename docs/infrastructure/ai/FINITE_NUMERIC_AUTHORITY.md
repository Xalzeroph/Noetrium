# Finite Numeric Authority

ROLE04 treats every floating-point value that can influence agent control, model qualification, serving identity, persisted recovery, or model-visible request provenance as a finite-domain contract.

IEEE-754 `NaN`, `+Inf`, and `-Inf` are not valid authority values. Python comparisons against `NaN` can evaluate false in both directions, so a check such as `error_rate > limit` is not a safe validator by itself. Non-finite values must be rejected before they can enter a digest, durable record, scheduling decision, qualification decision, or request binding.

## Agent boundaries

Finite validation applies to:

- `AgentGoal.max_seconds`;
- action execution timeouts;
- self-prompter durable scheduling timestamps;
- vision confidence values.

Positive budgets and timeouts must be finite and greater than zero. Durable timestamps must be finite and non-negative. Probability-like confidence values must additionally remain within `[0, 1]`.

## Model and qualification boundaries

Finite validation applies to deployment timeouts and controller intervals, deployment qualification probe timeouts, captured qualification timestamps, GPU power measurements, serving endpoint timeouts, performance samples, qualification policy thresholds, and measured resource envelopes.

Qualification rates are bounded probabilities. Latency/throughput measurements and resource-envelope performance values must be finite, with positive quantities remaining strictly positive. This prevents non-finite measurements from silently satisfying policy comparisons.

## Prompt and request provenance

Prompt sampling parameters are validated when specifications, compiled bundles, body contexts, and persisted request contracts are constructed. Trace timestamps/durations, outcome utilities/rates, and prompt-promotion timestamps are also finite-domain values because they are persisted, summarized, or used for promotion decisions.

Exact request provenance therefore never depends on a JSON serialization of `NaN` or infinity. The same invariant applies whether a value originates from project configuration, a provider measurement, or restored durable state.

## Serving, host evidence, and recovery

Heartbeat timestamps, host inventory timestamps, CPU quota observations, GPU power/fabric measurements, durable recovery timestamps, and model run-state timestamps reject non-finite inputs at their typed construction boundary.

Runtime freshness checks also validate caller-supplied reference time. A valid heartbeat cannot be made incomparable by passing a `NaN` clock value.

## Verification rule

`tests/test_typed_agent_model_finite_numeric_contracts_v1.py` exercises `NaN`, `+Inf`, and `-Inf` across these contracts. Persisted codecs may perform their own validation as defense in depth, but codec validation is not a substitute for an in-memory typed authority that is valid immediately after construction.
