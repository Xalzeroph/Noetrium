# Execution authority and recovery contract

ROLE 03 owns execution intent, durable operation state, workflow progress, and the execution/admission consumer projection. It does not own external-effect certainty or the governance system catalog.

## Admission ownership projection

`execution/admission` keeps authority id `admission_decision` and projects the ROLE 01 system-catalog ownership contract exactly as `hierarchical execution quotas, identity-aware admission decisions and lease accounting`. Both `OWNS` and `SystemLeafContract.owns` are consumer projections of that catalog authority; wording drift fails closed rather than creating a second ownership source.

## Operation identity

An effectful `OperationSnapshot` has one immutable external-effect identity before execution:

- `effect_id`
- `effect_request_id`
- `effect_request_digest`
- `effect_profile`

All four fields are durable SQLite identity. An effect-free operation carries none of the three external-effect identifiers. Reusing an `operation_id` with different immutable identity fails closed.

## Reconciliation authority

`OperationOwner.reconcile_effect` accepts only ROLE 02 `EffectReconciliationProof`. Caller-selected certainty enums are not recovery authority.

- `UNKNOWN` preserves uncertainty and does not authorize retry or completion.
- `NOT_APPLIED + NO_EFFECT` authorizes `NOT_EXECUTED` recovery.
- `APPLIED + EFFECT_CONFIRMED` authorizes executed recovery without re-execution.
- `REJECTED + EFFECT_REJECTED` terminates the operation as failed.

Request ID, effect ID, request digest, and verification state must match the durable operation identity exactly.
## Workflow recovery

`WorkflowOperationBinding` freezes the exact operation/effect/request identity at claim time. Workflow recovery compares that binding against durable operation truth before any progress CAS.

Effect-free interrupted steps use `retry_interrupted_effect_free`; they cannot impersonate external-effect reconciliation. Effectful interrupted steps require ROLE 02 proof. An `UNKNOWN` proof leaves the step uncertain and does not advance the workflow version.

A workflow step may enter `completed` only after its bound durable operation is already `COMPLETED`. Stale operation IDs and drifted effect identities fail closed.

## Persistence boundaries

Command, operation, and workflow stores use exact SQLite schemas and explicit short-lived connection closure. Persisted schema drift is corruption, not an implicit migration request.

SQLite first-open setup is race-safe and idempotent without a Python initialization mutex. WAL negotiation, DDL, and schema inspection run outside application authority locks; transient SQLite lock errors use the Platform bounded deadline-retry primitive. Concurrent constructors therefore contend only through SQLite's durable locking authority, and every constructor still revalidates the exact persisted schema.

Workflow binding serialization is versioned by its exact typed shape. Legacy two-field bindings are rejected rather than silently losing effect ancestry.

Tests cover success, read, conflict, corruption/decode failure, rollback, restart, concurrent claim, cancellation, uncertain-effect reconciliation, and stale identity.