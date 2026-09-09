# Universal Research Harness and Method Machine

Status: implementation baseline for `codex/universal-method-machine-20260909`

## 1. Decision

Noetrium's top-level product is a universal research harness. A downstream
method should express its scientific control logic, model policy, environment
interaction, and evaluation choices at named method nodes. The platform should
provide the surrounding runtime: identity, capability routing, operation
provenance, effect safety, checkpoints, interruption, evidence projection,
recovery boundaries, and experiment integration.

The universal mechanism is a small typed state-machine ABI hosted by the
registered `execution/workflow` system. It is intentionally more general than
the existing workflow DAG: a method graph may contain loops, routes, agent
turns, human interrupts, parallelism implemented by a downstream node, and
arbitrary scientific control logic. Every loop remains bounded by explicit
visit and step limits.

The design borrows useful boundaries from DeepSeek Harness and pi-style agent
runtimes—explicit context, composable control loops, tool/capability calls,
interrupts, and resumable state—without importing their service locator,
provider ownership, or process supervision assumptions.

## 2. Architectural position

The canonical registry remains the topology authority. Noetrium keeps its five
semantic planes and dependency direction:

```text
foundation -> capabilities/evidence -> research -> product
```

`execution/workflow` owns workflow and orchestration semantics. The universal
method machine is an execution service exposed through that system's `api` and
`runtime` segments. It may consume the existing participant method identity,
capability, operation, evidence, scope, and observability contracts; it does
not own their provider truth. Agent cognition is a first-class `AGENT` node
port, so methods can delegate the model/tool/reason/act loop to the platform
without embedding a second loop inside a compute handler.

The four-segment rule remains mandatory:

| Segment | Method-machine responsibility |
| --- | --- |
| `api` | immutable method IR, node ABI, ports, result/checkpoint envelopes |
| `runtime` | deterministic loop execution, dispatch, checkpoint and resume |
| `providers` | durable checkpoint/evidence/capability implementations |
| `composition` | explicit assembly of ports and policy |

There is no global runtime registry and no `require("service.name")` escape
hatch. Dependencies enter through `MethodRuntimeContext` as typed ports.

## 3. The universal ABI

The downstream author implements only a `MethodProgram`:

```python
from noetrium.contracts.systems.execution__workflow import (
    MethodNodeKind, MethodNodeResult, MethodNodeSpec,
    MethodProgramBuilder,
)

program = (
    MethodProgramBuilder(identity, entrypoint="plan")
    .add(MethodNodeSpec("plan", "agent.plan", ("act",), plan))
    .add(MethodNodeSpec(
        "act", "agent.act", ("plan", "finish"),
        decide_next, kind=MethodNodeKind.ROUTE, max_visits=64,
    ))
    .add(MethodNodeSpec("finish", "agent.finish", (), finish,
                        kind=MethodNodeKind.RETURN))
    .build(configuration={"temperature_policy": "frozen"})
)
```

The method function receives a frozen `MethodNodeRequest` containing:

- current node and bounded visit number;
- immutable state and input value;
- the previous node value;
- the run-derived `ExecutionContext`;
- an optional typed `CapabilityPort`.

It returns `MethodNodeResult`, which can contain a value, a state patch, an
explicit route, events, an interrupt, a checkpoint request, and effect
receipts. The method does not construct operation envelopes, trace IDs,
provider identities, or storage records. `MethodProgramBuilder` also exposes
typed `compute`, `capability`, `agent`, `route`, `checkpoint`, `interrupt`, and
`return_node` helpers so common method definitions do not repeat ABI plumbing.

The ABI is intentionally open at the node function boundary. A node can host a
ReAct loop, plan-and-execute, tree search, debate, self-reflection, simulator
control, active data collection, human approval, or a conventional fixed
scientific pipeline. The same host also accepts capability nodes for the common
case where no custom wrapper is needed.

## 4. Method graph versus workflow graph

The existing `WorkflowGraph` remains the right contract for acyclic workflow
orchestration and dependency scheduling. A method graph is a different
semantic object: it is a finite-state control graph and therefore permits
cycles. The method graph records only stable declarative data; Python handlers
are injected behavior and are never used as an accidental configuration
identity.

`MethodGraph.graph_digest` includes entrypoint, node IDs, operation types, edges,
node kinds, capability IDs, effect classes, visit limits, and an implementation
digest for each injected handler when source is available. `MethodProgram.program_digest`
then binds the graph to the exact `MethodProgramIdentity` and frozen configuration.

This separation makes arbitrary control expressible while keeping run identity
reconstructable and comparable.

## 5. Execution protocol

For each node invocation the runtime:

1. derives a child execution context and stable operation ID;
2. validates the node and visit budget;
3. validates declared schemas when a schema port is bound;
4. invokes a capability through `CapabilityPort` when the node is a capability;
5. invokes `MethodAgentLoopPort` when the node is an agent;
6. otherwise calls the downstream node handler;
7. optionally routes the invocation through `OperationDispatchPort`;
8. projects returned effect receipts through the Kernel operation projector;
9. applies the immutable state patch and validates the selected edge;
10. emits method events and persists a checkpoint at the configured interval;
11. returns on `RETURN`, interrupt, failure, wall-clock, or explicit execution limit.

The default operation key is derived from the frozen program digest, run ID,
node ID, and visit number. Effectful capabilities therefore receive a stable
idempotency key without downstream bookkeeping. A provider may still return an
effect receipt, and the existing effect/reconciliation authorities remain the
only authorities allowed to decide whether an uncertain external effect can be
retried.

The sync and async hosts share the same `MethodProgram` ABI. Async node
handlers and async capability implementations can be awaited by
`run_async`; a native async operation adapter can be supplied later through
`AsyncOperationDispatchPort` without changing method code.

## 6. Checkpoint and resume contract

`MethodCheckpoint` is a content-addressed, immutable envelope containing run ID,
program digest, sequence, current/next node, state, previous value, visit
counts, event lineage, and effect receipts. A
`MethodCheckpointStorePort` is the only required persistence seam. The included
in-memory provider is for tests and local short runs. The JSON provider offers
atomic crash-durable files with monotonic sequence enforcement; production
compositions may replace it with a stronger store while preserving the port.

Resume rejects a checkpoint whose program digest, binding identity, runtime
binding identity, or schema identity differs from the current run. This prevents
a changed method implementation from silently consuming old state. An interrupt stores the continuation edge before returning, so the
next host invocation resumes at the approved next node rather than replaying a
completed effectful node.

The method machine does not pretend that a checkpoint is a complete external
effect reconciliation record. Effect uncertainty remains represented by the
existing operation/effect lifecycle and must be reconciled by its owning
authority.

## 7. Capabilities, models, tools, and environments

Models, tools, environments, memory, datasets, evaluators, and publication
systems are all capabilities from the method's point of view. The method sees
the typed `CapabilityPort`; it does not see a provider object, credential,
socket, process, or ambient registry.

Agent loops are also injected ports. Their normalized request/result carries
method state, goal, continuation checkpoint, events, and effect receipts, so
the existing cognition loop and future agent-loop implementations share the
same UMM execution boundary. Async-only loops implement the companion
`AsyncMethodAgentLoopPort`; continuation checkpoints are stored under a
reserved per-agent state map so multiple agent nodes do not overwrite one
another.

The capability descriptor supplies request/result schemas, effect class, and
determinism. Pure capabilities may be invoked without an idempotency key.
Effectful capabilities receive the derived key and return the normal
`CapabilityResult.effect` receipt. Policy and approval guards remain in the
existing capability invocation pipeline.

This makes common methods short while preserving an escape hatch: a downstream
author can implement a custom node function when the standard capability shape
does not capture the method's semantics.

## 8. Performance and safety defaults

The host is deliberately mechanical. It does not serialize arbitrary handler
objects, copy provider state, or impose a small model-observation limit. State
patches are frozen once per node, operation payloads contain compact digests,
and checkpoint cadence is configurable. The safe defaults are a 10,000-node
run budget, one visit per node unless a
loop node opts into a larger explicit bound, and a checkpoint after every
node. Production compositions may increase checkpoint interval only when
their effect/recovery policy proves that replay is safe. The host also
supports an explicit wall-clock budget and exposes structured failure codes,
phase information, run digests, visit counts, evidence status, and receipts in
`MethodRunResult`.

Performance work must preserve:

- no hidden retry after `UNKNOWN` effect certainty;
- no provider or credential leakage across the public facade;
- no mutation of a frozen run contract;
- no bypass of capability policy or operation observation;
- deterministic program and checkpoint identity.

## 9. Registry and generated surfaces

The canonical registry entry for `execution/workflow` advertises the method
machine through `method.machine`, `method.abi`, and `method.checkpoint` in
addition to `workflow.runtime`. The normal generators then update:

- `noetrium/contracts/downstream_capability_catalog.json`;
- `noetrium/contracts/interface_schema.json`;
- `noetrium/contracts/systems/execution__workflow.py`;
- `docs/architecture/DOWNSTREAM_CAPABILITY_CATALOG.md`.

Downstream imports therefore remain facade-only. Generated schemas expose the
callable signatures and typed fields needed to author a method without making
the downstream project reverse-engineer private implementation modules.

## 10. Acceptance gates

The implementation is complete only when all of the following hold:

1. a pure multi-node method runs through the ordinary Operation ABI;
2. a capability node uses typed descriptor/request/result contracts;
3. effectful capability calls receive stable idempotency keys and receipts;
4. a bounded loop cannot exceed its node visit or run step budget;
5. an interrupt checkpoint resumes at its continuation edge;
6. a changed program digest rejects an old checkpoint;
7. sync and async node handlers share semantic results;
8. generated catalog, interface schema, facade, registry and docs agree;
9. architecture, silent-failure, no-degradation and full test gates pass;
10. the frozen SEM worktree remains byte-for-byte and commit-for-commit
    untouched while this branch is tested.

## 11. Migration path

Existing `ResearchMethodProgram`, `MethodGraphProgram`, and concrete workflow
surfaces remain supported. They can be wrapped as one `MethodNodeSpec` or
adapted incrementally into a `MethodProgram`. No existing experiment or SEM
runner needs to adopt the machine in order for its current contract to remain
valid. New methods should start at the generated facade and use the machine's
typed ports; platform maintainers can later add durable providers and native
async dispatch without changing the downstream node ABI.
