# Model Serving OS — Round 11

## Frozen role-to-model assignment

Each LLM role maps to exactly one qualified deployment in `RoleModelManifest`. This is not failover routing. There is no ordered backup list. If the assigned deployment is unavailable, the run pauses/fails into exact recovery rather than silently switching model quality or semantics.

## Qualification becomes a deployment certificate

A `QualificationCertificate` binds:

- exact `ModelStackSpec` digest;
- target host inventory fingerprint;
- qualified roles;
- measured resource envelope;
- qualification evidence digest.

The resource envelope records measured peak GPU/host memory, maximum qualified concurrency and latency/throughput bounds. Placement therefore uses measured target-host evidence rather than optimistic model-size guesses.

Durable host-inventory, runtime-qualification, and runtime-canary evidence is bound inside its checksummed document to the exact runtime-manifest digest that owns it. Directory placement alone is not authority: copying otherwise valid evidence into another manifest namespace must fail closed, and identical evidence publication is immutable/idempotent rather than overwriteable.

Qualification interpretation also freezes its package-index lookup views: the package and `(package, index)` indexes are immutable mappings over captured `DeploymentCapabilityFacts`, so backend/package selection cannot be changed by mutating an internal index after the facts digest is bound.

Persisted host inventory and resource-delta evidence is immutable and fail-closed. Each evidence document is checksum-protected, bound inside the document to the exact runtime-manifest digest, and decoded through exact schema/type/range invariants. Rebinding a valid receipt under another manifest path, recomputing a checksum over malformed typed facts, changing the phase identity, or overwriting an existing manifest/phase evidence identity is rejected. The embedded runtime snapshot is a frozen typed `RuntimeInventory` value rather than a mutable nested mapping, so a digested receipt cannot be mutated in memory after validation.

## Backpressure, not degradation

`ModelAdmissionController` caps concurrent requests at the qualified concurrency. Saturation waits or times out. It never reduces context, output tokens, precision, tensor parallelism, prompt content or model size.

The endpoint boundary accepts only a typed `ModelRequestEnvelope` bound to an exact lowercase deployment-generation digest. Request bodies and JSON responses are converted to structural `Mapping`/tuple authority values before route/admission/canary identity is evaluated, so neither ordinary nor base-class mutation can rewrite in-memory evidence. The HTTP provider materializes a fresh mutable dict/list only immediately before serialization; that transport copy is not serving authority.

## Crash-reconcilable one-click recovery

Recovery now includes `RECONCILE_STUDY` and has a durable attempt record. Before each recovery step the store records the step as running. If the operator process itself dies during a state-changing step:

- interrupted `RESTART_EXACT_MODEL` resumes from `RECONCILE_PROCESS`;
- interrupted `RESUME_STUDY_EXACT` resumes from `RECONCILE_STUDY`;
- verification-only steps may retry the exact same check.

Thus “recovery interrupted while recovering” cannot cause blind duplicate restarts or duplicate Study writers.
