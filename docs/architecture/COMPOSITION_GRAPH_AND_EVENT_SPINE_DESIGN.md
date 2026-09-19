# Composition Graph and Event Spine Design

Status: accepted architecture decision; typed-plan core, first runtime slices,
and the downstream project binding boundary implemented

## Decision

Do not introduce one global runtime bus. The platform will use three distinct
planes:

1. a typed capability composition graph for dependency declaration and
   composition-time binding;
2. direct, immutable port references for runtime calls;
3. a separate event spine for append-only observation and projections.

The word "bus" is therefore reserved for the composition control plane or the
event observation plane. It must not mean a mutable, string-addressed service
locator that every subsystem can query during execution.

This is the only design that simultaneously centralizes system wiring and
keeps ownership, performance, reproducibility, and recursive composition
explicit.

## Why a single universal bus is the wrong abstraction

The proposed requirement contains three different operations:

- a system declares what it provides and needs;
- a composition root chooses concrete providers and assembles a graph;
- a running component invokes a capability or publishes an observation.

Putting all three into one bus creates a hidden dependency container. A call
such as `bus.resolve("logging")` hides the provider, scope, lifecycle,
version, and failure semantics from the caller and from static architecture
checks. A mutable global registry also creates provider collisions, late
startup failures, cross-project contamination, accidental singleton state, and
non-reproducible experiments. A generic message bus has the opposite problem:
it is good at distributing events but cannot express a synchronous typed
dependency such as "this method requires a logging writer with this scope and
these failure-reference semantics".

Centralizing the *wiring description* is valuable. Centralizing the *runtime
semantics of every system* is not.

## The three planes

### 1. Capability composition graph

Every system exposes a declarative contract at its composition surface. The
contract is metadata plus typed factories, not a runtime object bag:

```text
SystemContract =
    identity
  + owned_capabilities
  + required_capabilities
  + scope/lifecycle/effect declarations
  + contract and provider digests

CapabilityKey = namespace + name + major_version

Requirement =
    capability_key
  + cardinality
  + optionality
  + required_scope
  + required_phase

BindingGraph = nodes + typed_edges + configuration_digest
```

The root composition system collects contracts, validates them, chooses one
provider for each required capability, and produces a frozen `BindingPlan`.
Validation is fail-closed and includes:

- exactly one selected provider for every required capability; multiple
  advertisements are rejected unless the composition root records an explicit
  selection;
- no unresolved required requirement;
- no dependency cycle unless the contract explicitly models a lifecycle
  cycle through a dedicated port;
- compatible scope and lifecycle;
- compatible contract major version and schema digest;
- no forbidden parent/child or sibling edge;
- no secret material in the plan, only named secret references;
- stable graph and configuration digest recorded in the run manifest.

The plan is created once at a composition boundary and then frozen. Runtime
code receives the resulting typed port directly. It does not perform dynamic
lookup.

```text
composition root
    -> register contracts and provider factories
    -> validate and freeze BindingPlan
    -> instantiate providers
    -> inject typed ports into parent/child compositions
    -> runtime calls direct ports; no bus lookup
```

This is Dependency Injection plus a Composition Root, with a typed registry
used only as build-time metadata. The registry is an Abstract Factory
catalog; it is not a Service Locator.

### 2. Runtime port plane

The hot path uses ordinary Python object references to the narrowest port. A
method that needs logging receives `LogWriterPort`; a project composition
receives `LoggingSystemPort`; the platform composition may bind the concrete
record/sink/query leaves. Each level sees only the surface it owns.

The parent may create a child composition and expose a facade, but it cannot
reach through the facade into a grandchild implementation. This preserves the
recursive rule:

```text
platform composition
    -> project composition
        -> paper-method composition
            -> method-local ports
```

A project can therefore define its complete local policy in one composition
surface instead of scattering calls to unrelated `build_*` functions through
its runtime code. The centralized graph records the binding; the project
still owns its policy and scientific semantics.

### 3. Event spine

Events solve a different problem: distributing observations after an
authoritative operation. The event spine is an Observer/Pub-Sub boundary with
explicit durability and delivery semantics. An event envelope must carry at
least:

```text
event_type + schema_version + producer_identity
  + run/trace/span identity
  + sequence or causal predecessor
  + source-record/effect/failure references
  + emission timestamp + payload digest
```

Logs, metrics, traces, operator dashboards, and diagnostic projections may
subscribe to this plane. They must not silently become the owner of execution
truth, scientific state, failure taxonomy, or effect certainty. If delivery
must survive a process crash, the owning system writes an outbox/evidence
record and the event publisher drains it with explicit acknowledgement and
replay policy. Event delivery failure is reported as a secondary diagnostic;
it is never repaired by dropping the authoritative write.

Commands are not arbitrary events. When a cross-system operation is needed,
use a typed command/query port or a narrow Mediator surface with an explicit
request, response, idempotency key, authorization scope, and error contract.
Do not route commands through a generic event topic and hope that a subscriber
will execute them.

## Recursive graph semantics

The global topology catalog remains the authority for *which systems exist and
who owns what*. The capability graph is a composition artifact constrained by
that topology; it does not replace the catalog.

Each catalog parent constructs a subgraph for its direct children. A project is
not a catalog node: it is an independently versioned composition subject that
may declare only its own local requirements and import selected system offers.

```text
G_platform = compose(platform children)
G_project  = compose(project subject | imported platform offers)
G_method   = compose(method children | imported project ports)
```

An imported capability is a typed boundary value, not a permission to search
the global graph. The parent exports a smaller facade to its parent. The
result is a hierarchy of local graphs whose edges are visible at each
composition boundary while runtime code remains decoupled.

This is the useful part of a "total bus": all requirements and bindings are
inspectable in one generated plan, but no subsystem gains ambient access to
all other subsystems.

## Logging example

The logging migration follows this shape:

```text
platform composition graph
    -> LoggingSystemPort
        -> record/sink/query leaf ports
project composition
    -> SemPaperLoggingSystem (policy adapter)
method/environment internals
    -> LogWriterPort.child(...)
observability event/query projections
    -> read records and correlate failure references
```

`FailureRecorder` remains reliability's failure authority. The logging record
stores `failure_refs`, so a final diagnostic view can correlate the two
authorities without duplicating failure classification. A future composition
graph may centralize the binding of `LoggingSystemPort`, but it must not turn
logging into a global mutable logger or move project policy into the platform.

## Design-pattern mapping

| Need | Pattern | Boundary rule |
| --- | --- | --- |
| Declare requirements/provisions | Ports and Adapters / Dependency Inversion | Contracts live at the owning node |
| Choose implementations once | Composition Root + Abstract Factory | Concrete providers stop at composition |
| Project-specific behavior | Adapter + Strategy | Project wraps a platform port, never a backend |
| Parent export surface | Facade | Expose direct children only |
| Typed cross-system operation | Mediator / Command-Query port | Narrow schemas, explicit errors and idempotency |
| Observation fan-out | Observer / Pub-Sub | Side-plane only; durable delivery semantics |
| Stable wiring record | Immutable Binding Plan | Freeze before the run and hash it |

## Non-negotiable safeguards

- no runtime `resolve(name)` or `get(service)` in production paths;
- no mutable global provider table after composition freeze;
- no `Any`-typed universal capability or catch-all context;
- no ambiguous active capability binding within a scope;
- no provider selection based on hidden import order;
- no event subscriber allowed to decide authoritative execution state;
- no topology descriptor used as a second domain registry;
- no network-wide bus for local in-process calls; remote systems use explicit
  transport adapters and the same typed contract;
- every run records the binding-plan digest, provider identities, host,
  environment, model, prompt, and event schema versions.

## Migration decision for this repository

Do not implement a giant generic bus as the next patch. The typed public
contract/requirement/plan vocabulary lives under
`governance/architecture/api`; its concrete validator lives under
`governance/architecture/runtime`. A composition root may select that
validator and inject the public planner port, but projects must never import
the concrete planner or another system's composition package. This preserves
the dependency direction while leaving runtime modules with direct ports only.

The first bounded migration slice has made host OS routing, server identity
and logging produce frozen plans; environment adapters, generic services and model
service runtime now receive the selected host port directly. A downstream project records
its two imported platform bindings (logging and method composition ports) in a
project-scoped plan without becoming a global system node. Logging, model
serving and project composition still require their wider production-root
migrations.

The architecture gate must enforce that resolution APIs are importable only
from composition modules, that production runtime modules receive direct
ports, and that every declared requirement has a visible binding edge. The
event spine should be extended separately under observability and must retain
the existing separation between observation, reliability, and domain truth.
