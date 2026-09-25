# Agent Cognition Runtime

This document defines the reusable `participant/agent` cognition runtime boundary. It owns participant-local cognition sequencing and durable cognition state; it does not own environment action semantics, model serving, experiment interpretation, or scientific claim acceptance.

## Phase topology

The cognition runtime is a composition of narrow typed phases:

```text
observe -> context -> reason -> plan -> act -> persist
```

`AgentCognitionLoop` is the coordinator only. Environment observation/evidence, verified-memory retrieval, planner reasoning, skill/safety arbitration, action execution, and durable checkpoint publication remain separate replaceable authorities.
## Phase responsibilities

- **observe** validates `AgentObservation` values and publishes their evidence before later cognition consumes them;
- **context** retrieves verified memory and durable skill records and returns one typed context snapshot;
- **reason** constructs the exact planner-visible `AgentPlanningRequest` and performs one planner call;
- **plan** expands the selected skill and performs safety, reactive-mode, and grounded-completion arbitration;
- **act** executes one typed action step, routes any resulting observation through the observe authority, and records the receipt into memory;
- **persist** publishes the versioned cognition checkpoint and binds terminal results to its digest.

A phase may not silently rediscover another phase's provider or recreate its authority. The coordinator passes typed values between phases rather than generic dictionaries or service-location handles.
## Memory and effect truth

Trusted memory is not equivalent to an accepted command. Effect-bearing memory is trusted only when the corresponding receipt is accepted and either explicitly verified or carries confirmed effect certainty. Sequence-level trusted memory requires that condition for every receipt in the sequence.

A rejected, possible, unknown, or otherwise unverified effect remains trajectory evidence but must not become trusted state merely because an executor returned normally.

## Recovery

The cognition checkpoint is versioned and binds session identity, goal digest, counters, last observation digest, action summaries, and the last receipt. Resume rejects a checkpoint from another goal or session. Persistence failure is a primary cognition failure; the loop does not report a terminal result whose checkpoint was not durably published.

The phase split is semantic rather than cosmetic: recovery and tests can exercise each boundary independently while the top-level loop remains a small orchestration state machine.
## Agent turn JSON boundary

`AgentTurnRequest` and `AgentTurnResult` are immutable participant/execution boundary values, not wrappers around mutable JSON. Task, input, output, and diagnostics are recursively copied into structural `Mapping`/tuple values at construction. All arrays canonicalize to tuples to match the platform `JsonValue` contract, eliminating both ordinary mutation and `dict.__setitem__` / `list.append` base-class bypasses. The public diagnostics contract is `Mapping[str, JsonValue]`, matching the frozen runtime representation; no ABI advertises a mutable `dict` for diagnostic authority.

Caller-owned dictionaries or lists may therefore be mutated after construction without changing an already-issued turn request or result. Direct or nested mutation through the boundary value is rejected. Non-finite numbers, unsupported JSON values, invalid mutable artifact collections, and blank artifact identities fail closed before a turn value can cross the boundary.

## Generic participant runtime typing

The generic participant binding layer no longer advertises resolved endpoints as bare `object`: `ParticipantBindingResolverPort.resolve()` returns a `ParticipantRuntimeHandle`, and the handle plus `BoundParticipant.endpoint` expose the structural `ParticipantRuntimeEndpoint` contract. This keeps the binding/runtime identity join typed without importing Agent, Method, or Capability semantics into participant core.

The session value behind that endpoint remains intentionally opaque at the generic lifecycle bridge because Agent, Method, and Capability sessions have different domain protocols; domain workflows must narrow it to their own session contract before invoking domain behavior. Diagnostics are not opaque: agent diagnostic attributes use `Mapping[str, JsonScalar]`, and method-session diagnostics use `Mapping[str, JsonValue]`, so diagnostic authority is never advertised as a mutable `dict[str, object]`.