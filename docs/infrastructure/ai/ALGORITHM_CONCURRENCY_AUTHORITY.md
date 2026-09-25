# Agent/Model Algorithm and Concurrency Authority

ROLE04 treats algorithm complexity and concurrency topology as release authorities, not advisory lint.

## Concurrency rule

Model qualification must not construct raw thread/process pools. `qualification_index_worker.py` enters through Platform structured concurrency on the `BLOCKING_IO` lane with bounded worker/in-flight capacity.

Qualification map-style work uses caller-scoped task failures: every submitted child is physically joined before the first observed child error is re-raised. Runtime shutdown therefore cannot hide still-running metadata work.

## Avoidable algorithm debt

The owner implementation removes avoidable static/runtime amplification instead of requesting exemptions:

- package receipt decoding uses one decoder per package rather than a syntactically nested singleton comprehension;
- durable recovery keeps every pre/post-step durable write visible in the recovery loop; the effect port is named `run_step` so it cannot be confused with a database `execute` operation while real per-step I/O remains visible to governance;
- qualified-closure loading separates receipt verification, canary loading, and digest-set verification;
- qualification dependency resolution is decomposed into bounded fixed-point, constraint collection, package resolution, and application phases;
- fixed-cardinality numeric/counter validation remains O(1) and does not claim input-size complexity.
## Lower-bound migration candidates

Seven owner symbols intentionally require O(N) work because fail-closed construction or binding must inspect variable-length authority input:

- `DeploymentQualificationApplicationReceipt.__post_init__`: packages, command receipts, and reasons;
- `DeploymentQualificationRuntimeReceipt.__post_init__`: runtime checks and reasons;
- `build_host_inventory_receipt`: observed GPUs and mounts;
- `QualifiedModelEndpointBinding.__post_init__`: every canary evidence digest must be typed, unique, and SHA-256 valid;
- `PersistedQualifiedModelEndpointBinding.binding_for`: every canary bound to the requested deployment/role must be revalidated against route/process/receipt authority;
- `AgentObservation.__post_init__`: immutable observation/evidence JSON and artifact references;
- `ConversationMessage.__post_init__`: every metadata key/value must be validated and frozen.

These are not self-approved. Each O(1) -> O(N) baseline transition requires an exact ROLE00-reviewed `AlgorithmComplexityMigrationApproval` bound to the committed source SHA, source digest, analyzer revision, and analyzer implementation digest.

A changed source SHA or source digest invalidates the prior migration request and requires exact recomputation.

## Validation

Owner validation includes focused qualification/endpoint/recovery/finite-contract tests, exact Algorithm and Concurrency gates, architecture/public-contract/silent-failure/no-degradation gates, and `git diff --check`.

This slice changes no model-serving deployment semantics and requires no GPU, Qwen endpoint, Server1 SEM, or live experiment access.
