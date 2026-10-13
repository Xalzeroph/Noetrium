# Experiment Reproducibility Contract

Experimentation owns frozen study/run identity, measurement semantics, checkpoint compatibility, artifact finalization, and evidence binding. It does not create an independent execution history.

## Run identity

A run launch manifest binds the exact project/research definition, study and experiment semantics, method implementation, participant topology, execution policy, model/environment requirements, command/configuration, seeds, and composition identities required by the current schema.

Persisted manifest bytes are canonical and versioned. Unknown, missing, extra, unsupported, or noncanonical fields fail closed rather than being silently upgraded into another scientific identity.

## Artifact finalization

Mutable files are not scientific evidence merely because a path exists. Finalization snapshots content into a typed receipt that binds the run, logical artifact identity, generation, digest, size, and authoritative record count where applicable.

The durable seal is the finalization commit point. Once sealed, normal append/publish operations fail closed. Derived indexes may be rebuilt from the authoritative seal; conflicting durable indexes are split truth and are never overwritten automatically.

Verification re-reads authoritative content. A forged receipt, content drift, run mismatch, unfinalized artifact, or non-identical restore fails closed. Byte-identical restore preserves logical artifact identity by design.

## Evidence identity

Evidence manifests bind to the exact run and run-manifest digest. Evidence streams use typed finalized artifact receipts rather than caller-asserted paths, hashes, or record counts. Complete publication verifies every stream against the artifact authority before publication.

Derived analyses and projections identify the immutable measurement/evidence cut they consume. Changing post-hoc analysis does not silently mutate raw experiment evidence.

## Checkpoint transactions

Restore validates run/study/workload identity, component topology, codec/schema identity, payload integrity, execution cut, environment/method generation, and the checkpoint compatibility digest before mutation.

Component preimages are captured before apply. Failed restore rolls back attempted components in reverse order. A successful rollback reports rolled-back certainty; any rollback failure reports unknown state rather than pretending the prior state was restored.

Checkpoint compatibility contains only recovery-relevant facets. Scientific/runtime changes that affect recoverable state invalidate restore; measurement- or analysis-only changes need not invalidate an otherwise compatible checkpoint.

## Lifecycle control

Operator lifecycle commands coordinate the canonical research execution authority. Effectful control operations are prepared before the provider may perform the effect. An interrupted prepared operation remains recovery-required until authoritative reconciliation resolves its physical outcome.

Read-only inspection and evidence queries do not mutate execution state. Resume binds the exact recorded execution and recovery/checkpoint identity.

## Research compilation

Authoring is side-effect free. Research definitions freeze scientific design, benchmark/task cuts, factors, seeds and repetitions, trial budgets, measurements, participant/method/capability requirements, and execution policy without selecting mutable physical providers.

Compilation joins those immutable definitions with exact resolved bindings and produces deterministic experiment assignments. It does not start processes, open sessions, write checkpoints, or execute trials.

Scientific design identity, binding identity, method implementation, execution policy, benchmark cut, assignments, measurements, topology, revision, and replay claims remain distinguishable even when a total plan digest closes over them.

## Measurement and analysis

Measurement records bind their scientific contract and exact project/study/run/assignment/producer/revision lineage. Analysis definitions separately freeze projector, implementation, configuration, filtering, grouping, and comparison semantics over an immutable measurement cut.

This separation allows analysis to evolve without falsely claiming that raw trials were rerun.

## Validation

Changes to persistence, checkpoint, recovery, artifact finalization, or evidence publication require crash/restart and identity-drift tests in addition to the normal success path. Platform validation must use isolated fixtures or explicitly allocated resources and must not depend on private downstream projects or unrelated live workloads.
