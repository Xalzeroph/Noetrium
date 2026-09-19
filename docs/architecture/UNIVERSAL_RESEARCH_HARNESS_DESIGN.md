# Universal Research Harness and Method Machine

> Status: current method-expression design, interpreted through the 2026-09-16 authority-consolidation specification
> Current architecture precedence: `CURRENT_ARCHITECTURE_AUTHORITY.md`

## 1. Decision

Noetrium's top-level product is a universal research harness. A downstream method should express its scientific control logic, model policy, environment interaction, and evaluation choices at named method nodes. The platform should provide the surrounding reusable mechanics: identity, capability routing, operation provenance, effect safety, Machine-backed transition acceptance, checkpoints/recovery, evidence projection, experiment integration, and typed provider boundaries.

The universal method mechanism is a small typed state-machine ABI. It is intentionally more general than an acyclic workflow DAG: a method graph may contain loops, routes, agent turns, human interrupts, bounded parallel composition, and arbitrary scientific control logic. Every loop remains bounded by explicit visit and step limits.

The key authority clarification is:

> **UMM interprets research methods; MachineExecutor + the Machine Journal accept scientific execution truth.**

UMM therefore must not maintain a competing durable execution history. Method checkpoints and progress are recoverable projections/artifacts bound to accepted Machine cuts.

## 2. Architectural position

The canonical system registry remains the topology source. Authority classification follows `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md` and the authority-disposition matrix.

`execution/workflow` owns the typed workflow/method interpretation seam. The universal method machine consumes existing participant identity, capability, operation, evidence, scope, effect, and observability contracts; it does not own provider truth, external-effect certainty, resource placement, or another independent run history.

The public source shape may still use `api`, `runtime`, `providers`, and `composition`, but package shape does not itself confer authority.

There is no global runtime registry and no `require("service.name")` escape hatch. Dependencies enter through typed runtime/composition ports.

## 3. The universal ABI

The downstream author implements a `MethodProgram`:

```python
from noetrium.contracts.systems.execution__workflow import (
    MethodNodeKind,
    MethodNodeResult,
    MethodNodeSpec,
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

A method node receives the typed method request/context and returns `MethodNodeResult`. A result may contain a value, state patch, explicit route, events, interrupt, checkpoint request, or effect references/receipts according to the public ABI.

The method does not construct provider credentials, ambient service lookups, hidden retry state, or a second durable run ledger.

The node boundary remains deliberately open. A node can host a ReAct policy, plan-and-execute step, tree search, debate turn, self-reflection step, simulator control, active data collection action, human approval boundary, or a conventional scientific pipeline stage. Common mechanisms may be reusable upstream components; paper-specific semantics remain downstream.

## 4. Method graph versus workflow graph

`WorkflowGraph` remains appropriate for acyclic dependency orchestration. A method graph is a finite-state scientific control graph and therefore permits cycles.

The method graph records stable declarative data rather than process-local callable identity. `MethodProgram` binds graph structure to exact method identity and frozen configuration so that scientific method identity can be reconstructed independently of a particular worker process.

Changing a handler implementation or configuration in a way that affects scientific semantics must change the corresponding frozen identity/digest. Runtime/provider placement changes are recorded separately through binding/provenance rather than being smuggled into method semantics.

## 5. Execution protocol

For each node invocation, UMM performs the method-level interpretation work: validate node/visit budgets, construct the typed request, call the configured capability or downstream handler, validate the selected edge and result schema, and produce the next method/control fact.

The authoritative path is then:

```text
MethodProgram
    ↓
UMM node interpreter
    ↓
node/control decision
    ↓
MachineMethodTransitionAuthority
    ↓
MachineExecutor
    ↓
Machine Journal commit
```

A returned Python value is not authoritative merely because the handler completed. The accepted method-state transition is authoritative only after the Machine transition authority commits it.

Effectful capability calls remain subject to the shared effect authority. Stable idempotency identity and effect receipts must not be treated as permission to retry an `UNKNOWN` external effect blindly.

Sync and async method handlers share the same scientific ABI. Async execution is an implementation mode, not a second execution authority.

## 6. Checkpoint and resume contract

A method checkpoint is not an independent durable truth history. It is a recovery acceleration artifact tied to an accepted Machine execution cut.

A valid recovery path binds at least the method/program identity, relevant runtime binding, accepted journal position, state digest, and any effect/artifact identities required to make recovery safe.

Resume rejects incompatible program/binding state rather than silently consuming an old checkpoint under changed semantics.

Interrupts are committed wait states or equivalent accepted Machine facts. Recovery resumes from accepted state rather than replaying a completed effectful node merely because local Python control flow was interrupted.

The method layer never substitutes a checkpoint for external-effect reconciliation.

## 7. Capabilities, models, tools, and environments

Models, tools, environments, memory backends, datasets, evaluators, and publication systems are capabilities/providers from the method's point of view. The method consumes typed contracts rather than provider objects, credentials, sockets, processes, or ambient registries.

Pure capabilities may return typed values. Effectful capabilities must preserve effect identity, certainty, receipt, and reconciliation semantics through the owning effect boundary.

Provider-local mutable state is implementation state. It becomes relevant research truth only through an accepted binding, Machine transition, effect record, evidence fact, artifact identity, or other owning authority.

This keeps downstream code short without collapsing provider implementation into method or platform authority.

## 8. Agents

Agent loops are method semantics, not a second platform execution kernel.

A reusable `AgentCognitionLoop`, ReAct loop, Reflexion loop, planner, memory policy, or similar component may be used as a reference method/program composition. Paper reproductions may preserve the original paper semantics exactly while still entering the same Machine/effect/evidence path.

The platform should absorb reusable mechanics discovered during paper reproduction, but must not absorb benchmark scoring, paper-specific prompts, reflection semantics, search policy, skill curriculum, or other scientific claims into generic authority merely to reduce downstream lines of code.

## 9. Performance and safety defaults

The interpreter should remain mechanical and bounded. It must not serialize arbitrary handler objects as scientific identity, copy provider state into the method contract, or impose paper-specific observation limits.

Performance work must preserve:

- no hidden retry after `UNKNOWN` effect certainty;
- no provider or credential leakage through public facades;
- no mutation of frozen run/method bindings;
- no bypass of capability/effect policy;
- deterministic method/program identity;
- Machine-backed acceptance of scientific execution truth;
- explicit resource admission outside Machine transition authority.

Fast paths may pre-bind typed collaborators at run scope, but must not create ambient mutable singletons or bypass frozen provenance.

## 10. Registry and generated surfaces

The canonical registry and owning public API exports drive generated downstream surfaces such as:

- `noetrium/contracts/downstream_capability_catalog.json`;
- `noetrium/contracts/interface_schema.json`;
- typed facades under `noetrium/contracts/systems/`;
- `docs/architecture/DOWNSTREAM_CAPABILITY_CATALOG.md`;
- generated topology/code architecture projections.

Generated discovery is a read-only contract/discoverability boundary. It never becomes a service locator or a second provider-selection authority.

Every generated artifact must be checked against the exact source cut that produced it. Stale generated maps or schemas are release-blocking evidence drift, not harmless documentation lag.

## 11. Acceptance gates

The universal harness is healthy only when all of the following remain true:

1. arbitrary bounded method control graphs execute through the public method ABI;
2. capability nodes use typed descriptor/request/result contracts;
3. effectful operations preserve stable effect identity and certainty/receipt semantics;
4. loops cannot exceed declared node-visit or run-step budgets;
5. interrupts/recovery resume from compatible accepted execution state;
6. changed scientific program identity rejects incompatible recovery state;
7. sync and async handlers preserve the same scientific contract;
8. method-node execution truth is Machine-backed rather than stored in a competing durable ledger;
9. generated catalog, interface schema, registry metadata, node kinds, canonical-authority mappings, facades, and docs agree;
10. architecture, source-completeness, no-degradation, repository-boundary, and targeted semantic tests pass;
11. downstream paper code can remain on public typed contracts and need not reimplement platform lifecycle/effect/evidence/recovery mechanics.

## 12. Method execution end state

`MethodProgram` is the only scientific method execution ABI. Downstream methods and external frameworks compile directly into it; retired whole-method and graph-program interfaces are not compatibility surfaces.

Typed providers remain valid only for capabilities that are genuinely outside method control-flow execution. No provider may own a competing scientific run/checkpoint history. If an external runtime contains scientifically material graph semantics, compile those semantics into UMM nodes and keep Machine/Journal as the sole accepted execution authority.

For current architecture precedence, read `CURRENT_ARCHITECTURE_AUTHORITY.md` before using this design as an implementation specification.