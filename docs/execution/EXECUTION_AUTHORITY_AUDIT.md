# Execution authority audit — Worker 03

Baseline: `e0003c98ffa873a8d25428de8416f028bae99a99` (`origin/master` at worker start).

## Current authority topology

| Subsystem | Owns | Must not own | Current authority / state |
|---|---|---|---|
| admission | atomic permit accounting, wait queue, backpressure | resource allocation, process launch, scientific eligibility | one `Condition`; hierarchical quotas; deterministic scheduling selection cache |
| scheduling | ordering of admissible candidates | permit/resource state | stateless fair-priority + aging policy |
| capability | scoped typed invocation registration and lease lifetime | global DI/service location | typed `CapabilityRegistration[T]` with explicit owner/lifetime |
| command | immutable execution intent identity and request deduplication | operation/effect lifecycle | `CommandIntentOwner` + durable SQLite command store |
| operation | operation identity, lifecycle, cancellation intent, effect-certainty projection | Reliability reconciliation truth | `OperationOwner` + durable SQLite CAS store |
| workflow | immutable DAG identity, step↔operation ancestry, durable progress | scientific success or checkpoint authority | typed DAG/progress owner + durable SQLite CAS store |
| lifecycle | dependency start/stop ordering | component durable truth | deterministic O(V+E) dependency graph traversal |
| runtime/manager | runtime-control write ordering and observation history projection | process/service/model/experiment truth | typed authoritative state + typed hash-chained history projection |

## P0 findings resolved in this renovation

1. Command intent is now a first-class typed durable authority. Full immutable envelope reuse is idempotent; identity or dedup-key drift fails closed.
2. Operation lifecycle is now a first-class durable authority. Callers cannot use a generic transition escape hatch; admission and lifecycle mutations use narrow ports.
3. External-effect uncertainty is explicit. `UNKNOWN_EFFECT` cannot resume execution until reconciliation resolves certainty.
4. Cancellation intent is an orthogonal durable fact. Crash/reconciliation cannot erase it; `NOT_EXECUTED` after cancellation converges to `CANCELLED`, while confirmed `EXECUTED` cannot be retried.
5. Command→operation write ordering is explicit through `ExecutionIntentCoordinator`: command intent is durable first, then the stable operation binding is materialized/replayed.
6. Workflow progress preserves exact step↔operation ancestry. Late completion/failure from a stale operation cannot complete a retried step.
7. Durable Command/Operation/Workflow decoders reject malformed/corrupt rows instead of coercing arbitrary values into apparently valid truth.

## Durable authority boundaries

Command SQLite owns immutable execution request identity. Operation SQLite owns operation lifecycle only and references `CommandId`; it does not duplicate command payload/dedup truth. Workflow SQLite owns DAG progress and operation ancestry only; Experimentation remains checkpoint/scientific-truth authority. Reliability remains effect-reconciliation authority; Operation records only the resolved certainty needed to prevent unsafe retry.

## Concurrency and performance changes

- Admission caches one scheduling decision for the same queue version and 50 ms scheduling bucket, eliminating repeated O(W) rescans by every waiter without changing fairness/aging granularity.
- Fair-priority selection computes effective rank once per candidate.
- Lifecycle dependency ordering uses indegree/children traversal instead of repeated unresolved-node scans.
- SQLite Command/Operation/Workflow stores configure WAL during serialized initialization rather than on every connection; normal connections use bounded busy timeout and FULL synchronous durability.
- All durable mutations use stable identity plus CAS/transaction boundaries; no unbounded in-memory work queue was introduced.

## Observation plane

Runtime history remains a non-authoritative hash-chained projection. Its semantic boundary now uses `RuntimeControlState` / `RuntimeHistoryEntry`; raw JSON mappings are restricted to codec/integrity implementation. History corruption prevents authoritative mutation before write, and post-state/pre-history crash windows remain explicitly repairable by authoritative reconciliation.

## Breaking migration notes

- The current Operation SQLite schema includes durable `cancellation_requested`; an older 17-column operation database is rejected as `OperationCorruption` rather than silently migrated.
- Public capability registration/acquisition is typed. Legacy untyped registry primitives remain concrete-runtime implementation details only, not `RegistrationScopePort` API.
- Generic Operation state mutation is removed; callers must use narrow admission/lifecycle methods.

## Remaining debt / cross-system seams

- Lifecycle start/stop timeout fields are still declarative. Safe hard timeout requires a cancellable TaskGroup/runtime-provider boundary; spawning an unkillable Python thread would worsen failure semantics.
- Effect reconciliation itself remains owned by Reliability. A generic cross-system reconciliation handoff should be reviewed with the Reliability owner rather than duplicated in Execution.
- Workflow durable progress is not a replacement for Experimentation checkpoint authority; cross-system resume integration requires adjacent-owner review.
- Workspace manifest/project SHA metadata was stale relative to actual Git at worker start. ROLE 03 does not own those shared authority files.

## Test taxonomy

Tests remain under the canonical `tests/TEST_SYSTEM.json` taxonomy: typed contracts are L1, component state machines/algorithms L2, explicit compositions L3, durable replay/corruption L4, and concurrency/capacity L5. No alternate taxonomy or shared test-authority file was created by ROLE 03.

## Validation status

Windows deterministic validation covers typed command/operation/workflow contracts, durable SQLite reopen/CAS/corruption/recovery, stale-operation workflow races, cancellation/effect reconciliation, capability lease typing, admission fairness/backpressure, lifecycle ordering, runtime-history reconciliation, architecture gate and algorithm/performance governance. Claim-eligible Linux/BOTH evidence must be produced only from an exact committed SHA after push and server-authority resolution.
