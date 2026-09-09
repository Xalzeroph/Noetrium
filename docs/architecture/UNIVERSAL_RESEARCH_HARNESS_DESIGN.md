# Noe Universal Research Harness Design

> Status: design proposal for discussion; implementation is intentionally paused
>
> Date: 2026-09-09
>
> Scope: Noe platform, downstream method authoring, experiment execution, agent loops,
> model/environment integration, evidence, evaluation, and publication.

## 1. Executive summary

Noe should be the top-level **reproducible research harness** for the entire
agent-research platform. A downstream researcher should implement a method by
filling a small number of typed nodes and, when necessary, replacing the agent
loop. The platform should provide the rest of the path:

`method -> run -> assignment -> action -> measurement -> evaluation -> artifact`

The harness owns lifecycle, composition, validation, checkpointing, effect
safety, evidence, metrics, plotting integration, and finalization. The method
owns scientific semantics, hypotheses, policies, and method-local state.

The key architectural boundary is:

> Centralize the description and compilation of the system, but keep runtime
> calls typed, direct, scoped, and owned by the correct system.

Noe therefore must not become a global mutable plugin bus or a string-addressed
service locator. It should combine a canonical system registry, a typed
composition graph, a frozen binding plan, direct runtime ports, and separate
durable/observation planes.

## 2. Goals

The harness must make these workflows short and safe:

- create a new research method;
- select or replace model, environment, participant, tool, and evaluator providers;
- choose a standard or custom agent loop;
- define experiments, variants, assignments, and metrics;
- run locally, in Docker, or on a remote execution host;
- recover interrupted work without duplicating external effects;
- produce plots, tables, artifacts, and evidence automatically;
- reproduce a run from its recorded identities and digests;
- expose all downstream contracts from generated, inspectable schemas.

Performance is a first-class goal. Removing downstream ceremony must not mean
repeating qualification, graph resolution, schema generation, or architecture
checks on every decision cycle.

## 3. Non-goals

The harness is not intended to:

- make every scientific method look the same;
- replace domain-specific method logic with a universal workflow language;
- provide a global runtime dictionary of arbitrary services;
- collapse all state, effects, failures, and telemetry into one event log;
- allow an experiment to change its provider graph after execution begins;
- silently retry an external effect whose outcome is UNKNOWN;
- make the platform import downstream scientific types.

## 4. Design principles

1. One authority per durable state, external effect, artifact, and evidence domain.
2. The canonical registry owns topology and system ownership, not runtime behavior.
3. Composition roots choose providers and create typed ports.
4. Runtime consumers use direct immutable port references.
5. Every model-visible request is reconstructable from durable records.
6. Every external effect has intent, certainty, receipt, and reconciliation semantics.
7. Observation failure cannot mutate scientific truth.
8. A Study run freezes the binding plan and all identity-bearing configuration.
9. Workbench mode may be flexible before a run is admitted.
10. Downstream customization happens at declared nodes and typed extension points.
## 5. System model

Noe has several related but non-identical architectural partitions. They must
not be conflated.

### 5.1 Physical package groups

The repository groups implementation by semantic responsibility:

- foundation: kernel, governance, scope, and portfolio;
- infrastructure: lifecycle, resources, and reliability;
- capabilities: model, participant, and environment;
- research: execution and experimentation;
- evidence: data, artifact, and observability;
- product: operator and user-facing control contracts;
- components: reusable method mechanisms;
- orchestration: multi-agent topology and coordination.

These groups are dependency boundaries, not runtime registries.

### 5.2 Canonical system registry

The canonical registry is:

`noetrium_platform/foundation/governance/system_registry/catalog.json`

It currently describes the registered system tree, including 172 system
descriptors and 18 top-level roots. Each descriptor records identity,
parentage, package ownership, declared shape, requirements, provisions,
authority, and downstream surface.

The registry is the single declaration authority for:

- which systems exist;
- which system owns a package surface;
- which system owns a state/effect/artifact domain;
- which systems may depend on which capabilities;
- which public API surface is exposed downstream;
- the topology digest used by generated documentation and run evidence.

The registry is deliberately not a runtime service locator. Its runtime object
supports topology queries, generation, digesting, and observer notification.
It must not be used as `registry.get("model")` to discover a provider during
the hot path.

### 5.3 Three semantic record planes

Noe's record semantics are mechanically distinct:

1. **Durable fact plane**: authoritative facts for replay, reconstruction,
   scientific proof, effect state, checkpoints, and final evidence.
2. **Live interception plane**: current-execution hooks and policy decisions.
   They may influence the current call, but durable or model-visible changes
   require an explicit durable fact.
3. **Side-plane observation**: logs, metrics, traces, diagnostics, and
   projections. These are derived observations and cannot own primary truth.

The command/runtime plane invokes typed ports and causes facts. The durable
truth plane records the authoritative outcome. The observation plane receives
derived signals. A generic event bus must not replace this distinction.

### 5.4 Composition/runtime/event three-plane decision

The accepted composition decision has another three-part distinction:

1. typed capability composition graph for declaration and binding;
2. direct immutable port references for runtime calls;
3. a separate append-only event spine for observations and projections.

This is compatible with the three record planes, but it is not the same
classification. The first describes how systems are assembled; the second
describes what records mean.

## 6. Proposed top-level architecture

```mermaid
flowchart TD
    A["Canonical Registry"] --> B["Profile Composer"]
    B --> C["Frozen BindingPlan"]
    C --> D["Typed Harness Context"]
    D --> E["DIY Nodes and Agent Loop"]
    E --> F["Facts, Evidence, and Observations"]
```

The top-level Harness consists of six cooperating layers:

1. **Registry layer**: canonical identities, ownership, topology, public surfaces.
2. **Profile layer**: selected systems, provider candidates, configuration, and
   method package metadata.
3. **Composition layer**: contract validation and frozen BindingPlan creation.
4. **Runtime layer**: direct typed ports, scopes, lifecycle, scheduling, and
   node execution.
5. **Research layer**: method nodes, agent loops, experiment definitions,
   assignments, evaluation, and plotting.
6. **Evidence layer**: durable facts, effect receipts, checkpoints, artifacts,
   manifests, projections, and publication gates.

The Harness facade is the downstream entry point. It is not a replacement for
the system-specific public facades; it composes them and exposes a smaller
scientific workflow surface.
## 7. Composition contracts

### 7.1 System contract

Every registered system continues to expose the standard shape:

`api + runtime + providers + composition`

The composition surface declares:

- stable system identity;
- owned capabilities and authorities;
- required capabilities;
- scope and lifecycle requirements;
- effect and durability behavior;
- contract and ABI digests;
- provider factory metadata;
- forbidden dependency edges.

The canonical registry remains the authority for system identity and ownership.
Provider selection belongs to the composition profile and BindingPlan.

### 7.2 Capability contract

A capability key is:

`namespace + name + major_version`

A requirement additionally declares:

- cardinality;
- optionality;
- required scope;
- required lifecycle phase;
- required interface/ABI digest;
- effect and failure semantics.

A provider offer declares its implementation identity, contract digest,
supported scopes, lifecycle, and evidence obligations.

The composer must fail closed on:

- unresolved required requirements;
- ambiguous providers without explicit profile selection;
- incompatible major versions or ABI/schema digests;
- invalid scope or lifecycle edges;
- forbidden parent/child or sibling dependencies;
- dependency cycles;
- secret values embedded in the plan.

### 7.3 BindingPlan

A BindingPlan is an immutable composition artifact containing:

- profile identity and configuration digest;
- registry topology digest;
- selected provider identities and revisions;
- capability edges;
- interface/ABI/schema digests;
- scope and lifecycle decisions;
- method package identity;
- agent loop identity;
- model/environment selection references;
- plan creation and compiler versions.

The plan is created once at a composition boundary. It is recorded in the
run manifest before model-visible work or external effects begin.

Runtime components receive the resulting typed ports directly. They do not
search the plan, registry, or provider table.

### 7.4 Direct runtime context

The runtime context is a typed, immutable bundle of already-bound ports:

- identity and scope ports;
- model request and prompt ports;
- participant and agent ports;
- environment/session ports;
- workflow and execution ports;
- data, artifact, evaluation, and plotting ports;
- effect, failure, checkpoint, and observability ports.

The context may expose narrow child facades for a node. A node receives only
the ports declared by its contract. A child composition cannot reach through
its facade to an unrelated grandchild implementation.

The context carries cancellation, run identity, trace identity, and immutable
configuration references. It does not expose a universal `Any` bag or a
string-keyed `require()` method.

## 7.5 Universal method runtime: maximum reuse with unrestricted semantics

The Harness must solve two seemingly conflicting requirements:

1. upstream implements almost all repeated engineering work;
2. downstream can express arbitrary agent research methods.

The solution is to separate **mechanism** from **scientific semantics**.

Noe owns the mechanisms: identity, scope, lifecycle, provider binding,
model/tool execution, memory, scheduling, checkpointing, effects, recovery,
evidence, evaluation, artifact handling, and observation.

The downstream method owns the semantics: state meaning, decision policy,
hypothesis, reward, agent interaction strategy, and domain-specific tools.

This produces the following four-layer model:

```text
Harness Kernel
  identity, scope, permissions, effects, checkpoints, recovery, evidence

Execution Fabric
  graph, actor, stream, matrix, external job, and human-loop execution

Research Packs
  single-agent, multi-agent, memory, tools, benchmark, training, and evaluation

Managed Method Program
  downstream scientific state, policy, custom nodes, or custom agent loop
```

### 7.5.1 Harness Kernel

The Kernel is closed and owned entirely by Noe. A method cannot bypass it.
It provides:

- identity and version binding;
- scope and lifecycle ownership;
- direct typed capability ports;
- model requests, prompt compilation, structured output, and function calling;
- tool registration, validation, concurrency, ordering, and error conversion;
- session, transcript, memory, and context transformation;
- checkpoint, replay, interruption, and resume;
- effect intent, receipt, certainty, reconciliation, and UNKNOWN handling;
- measurement, evaluation, artifact, and evidence closure;
- observation, logging, tracing, diagnostics, and status;
- resource allocation, process supervision, and environment sessions.

A custom method can change the algorithm above this boundary, but it cannot
replace the truth, effect, identity, or recovery authority below it.

### 7.5.2 Execution Fabric

The standard research phases are convenience syntax, not the complete semantic
model. The Execution Fabric must support multiple execution forms:

- graph/DAG for branches, loops, conditional transitions, and workflows;
- actor/mailbox for long-lived agents and asynchronous collaboration;
- event/stream for real-time environments and incremental observations;
- matrix/map-reduce for assignments, variants, ablations, and scale-out;
- external-job execution for training, simulation, remote work, and long tasks;
- human-gate execution for approvals, interventions, and interactive research;
- hierarchical execution for planners, workers, delegation, and debate.

Every execution form uses the same Kernel contracts for identity, state,
effects, checkpoints, recovery, and evidence. This prevents the default graph
runner from becoming an artificial limit on method semantics.

### 7.5.3 Research Packs

Research Packs are batteries-included compositions of registered Noe systems.
They are selected during composition and become direct typed bindings in the
compiled plan. They are not runtime service locators.

The initial Pack families are:

- SingleAgentPack;
- MultiAgentPack;
- PlanningPack;
- MemoryPack;
- ToolUsePack;
- InteractivePack;
- StreamingPack;
- RLPack;
- BenchmarkPack;
- TrainingPack;
- DistributedPack.

A Pack automatically assembles the relevant model, environment, participant,
execution, experimentation, data, artifact, observability, reliability,
resource, runtime, component, and orchestration systems. Downstream authors
select a Pack instead of manually wiring dozens of system facades.

A Pack may provide defaults for lifecycle, state persistence, tool execution,
evaluation, plotting, and publication. The downstream method overrides only
the semantic points it actually changes.

### 7.5.4 Managed Method Program

A Managed Method Program is the universal downstream execution boundary. It can
be declarative, callback-based, node-based, graph-based, actor-based, or a
fully custom agent loop.

The program may control:

- method state and state transitions;
- branching, looping, concurrency, and dynamic subtask creation;
- agent prompts, messages, tools, memory, and delegation;
- model-selection policy within the admitted contract;
- reward, evaluation, stopping, and reflection logic;
- child agents and custom execution topology.

The program receives a typed managed context and high-level operations. It
does not need to implement run management, durable writes, effect safety,
checkpoint serialization, or observation plumbing.

A custom loop is therefore free to implement any algorithm while the Kernel
automatically provides its surrounding runtime contract.

### 7.5.5 Progressive authoring levels

The downstream burden is reduced through progressive disclosure:

| Level | Downstream supplies | Noe supplies |
|---|---|---|
| 0 | configuration, prompt, schemas, and provider choices | complete standard loop and research lifecycle |
| 1 | one decision/policy function | state, context, tools, checkpoints, effects, metrics, and finalization |
| 2 | custom nodes, graph, state, and domain tools | execution runtime, scheduling, recovery, evidence, and publication |
| 3 | custom agent loop or execution model | managed Kernel boundary and all cross-cutting guarantees |

Level 0 and Level 1 should be the normal path for new methods. Level 2 and
Level 3 preserve unrestricted research expressiveness without forcing every
downstream project to rebuild platform mechanisms.

### 7.5.6 Universal method ABI

All four levels compile to a common Method ABI:

- method identity and revision;
- declared state schema;
- input and output schemas;
- required capabilities;
- control-flow/execution model;
- node or loop identity;
- effect and concurrency declarations;
- checkpoint and recovery declarations;
- metric and artifact declarations;
- evidence obligations.

Declarative methods compile to an internal research IR. Custom methods provide
the same ABI through a managed adapter. The IR is an optimization and
validation target, not a restriction that every method must expose its
internal algorithm as a fixed DAG.

The minimum method-specific semantic surface should be:

```text
MethodState
DecisionPolicy or MethodProgram
ToolDefinitions
EvaluationSpec
```

Everything else should be inherited from the selected Pack and Kernel.

### 7.5.7 What “arbitrary” means

Noe should be semantically universal for any method that declares its state,
capabilities, control flow, and effects. This includes ReAct, planning,
multi-agent, reflection, online learning, RL, streaming, human-in-the-loop,
long-running jobs, distributed execution, and custom state machines.

A method may contain arbitrary code, but only declared and mediated operations
can participate in Noe-certified evidence. Hidden global state, untracked
external effects, silent provider changes, and unrecoverable mutation are not
additional expressive features; they are outside the reproducible research
contract.

The target is therefore:

> Turing-complete method semantics with a finite, auditable, reproducible
> runtime boundary.

### 7.5.8 Automatic cross-cutting implementation

Noe should wrap every Managed Method Program with standard middleware for:

- run and assignment identity;
- scope creation and disposal;
- timing and resource accounting;
- state snapshots and checkpoint scheduling;
- model/tool request recording;
- effect intent and receipt recording;
- failure classification and recovery routing;
- metric collection and artifact registration;
- final evidence and manifest closure.

Middleware runs at declared lifecycle boundaries. It must not introduce a
global lookup on the hot path or require methods to call dozens of low-level
systems manually.



## 8. Harness modes

### 8.1 Workbench mode

Workbench is for method development:

- providers and nodes may be replaced before admission;
- profiles can be rebuilt quickly;
- local inspection and interactive experimentation are supported;
- validation is performed at profile compilation and run admission;
- no active Study may observe a mutable provider graph.

Workbench can support live UI/profile edits, but those edits create a new
candidate profile. They never mutate an already admitted run.

### 8.2 Study mode

Study is the reproducible execution mode:

- the BindingPlan is frozen;
- provider and method identities are immutable;
- model-visible prompt/tool schemas are versioned and recorded;
- run/session/assignment identities are explicit;
- checkpoints are bound to the plan and runtime identity;
- structural changes require a new run or new plan.

The Study boundary is where flexibility becomes scientific evidence.

### 8.3 Profile layering

Profiles may be assembled from:

1. platform defaults;
2. project defaults;
3. method package configuration;
4. experiment/variant configuration;
5. explicit CLI or API overrides.

The effective result is canonicalized before hashing. Equivalent declaration
orders must produce the same profile digest. Secret material is represented by
named references, never copied into the digest payload.
## 9. Downstream authoring model

A downstream method should primarily implement a small typed object:

- method metadata and identity;
- input/state/output schemas;
- method nodes;
- optional custom agent loop;
- metric/evaluation functions;
- optional plot/table renderers.

The platform supplies a standard lifecycle:

`declare -> compose -> admit -> execute -> checkpoint -> measure -> evaluate -> finalize`

A method may replace any node or the whole agent loop while retaining the
platform's evidence and effect contracts.

### 9.1 Node contract

Every node declares:

- stable node identity and revision;
- phase;
- typed input and output schemas;
- required ports;
- scope and concurrency requirements;
- idempotency key policy;
- checkpoint boundary;
- recovery policy;
- durable facts it may emit;
- observations it may publish.

A node returns a typed result or a typed failure outcome. It does not directly
write another system's durable state or bypass effect execution.

### 9.2 Standard research phases

The initial standard graph should provide these replaceable phases:

1. **Author**: define method, experiment, variants, and workload.
2. **Admission**: qualify model/environment/participant and freeze identities.
3. **Plan**: expand assignments and resolve run-scoped resources.
4. **Execute**: run the method or agent loop.
5. **Act**: route external effects through effect-safe execution.
6. **Measure**: collect task and system measurements.
7. **Evaluate**: compute metrics, uncertainty, comparisons, and regressions.
8. **Render**: produce plots, tables, reports, and machine-readable summaries.
9. **Finalize**: close artifact/evidence/hash relationships and publish manifest.

The method may skip irrelevant phases only through an explicit contract. The
omitted phase must still have an evidence policy.

### 9.3 AgentLoopPort

Agent loops are replaceable implementations of one typed port. A loop receives:

- the bound model-request port;
- prompt and context assembly ports;
- tool registry/pipeline port;
- durable transcript or method-state port;
- cancellation and scope;
- checkpoint/evidence writer;
- optional steering/follow-up source.

A loop may be ReAct, planning-based, Pi-style, DSH-style, finite-state, graph
based, or entirely custom. The loop must still preserve:

- reconstructable model requests;
- validated structured output/tool calls;
- durable accepted messages and tool results;
- explicit tool ordering/concurrency;
- cancellation and stop semantics;
- checkpoint and recovery boundaries;
- effect intent and reconciliation;
- final result/evidence closure.

This separates loop freedom from scientific and operational guarantees.

## 10. Agent and tool behavior

The standard agent implementation should offer:

- plain text and structured model output;
- JSON Schema and function/tool calling;
- model request reconstruction;
- context transformation and compaction;
- sequential or bounded parallel tool execution;
- pre-tool guards and post-tool policies;
- steering/follow-up queues;
- cancellation and idle barriers;
- explicit turn stopping policies;
- durable transcript/state adapters.

Structured output is a platform capability. Downstream methods should declare
schemas and consume typed results instead of rebuilding provider-specific
parsing, retry, and validation code.

Tools must declare:

- stable identity and schema;
- execution mode;
- effect classification;
- idempotency/reconciliation behavior;
- required capability scope;
- result/error schema.

A tool failure must become a typed failure/tool-result fact. It must not be
silently returned as successful text.
## 11. Runtime lifecycle

The Harness lifecycle is a rollback-aware state machine:

`declared -> composed -> validated -> admitted -> running -> finalizing -> completed`

Failure transitions are explicit:

`composed -> rejected`
`admitted -> failed`
`running -> interrupted -> resumable`
`finalizing -> evidence_incomplete`

### 11.1 Composition

The composition root:

1. loads the canonical registry and generated public interface metadata;
2. collects profile and method contracts;
3. indexes provider offers by capability and ABI;
4. resolves and validates the graph;
5. creates the immutable BindingPlan;
6. records the plan digest and provider identities.

No model request or external effect is admitted before this boundary.

### 11.2 Admission

Run admission performs the checks whose result must be stable for the run:

- model qualification closure;
- participant binding;
- workflow surface assembly;
- structural environment recovery capability;
- resource and runtime identity;
- evidence and artifact destinations;
- method/profile compatibility.

Successful admission is run-scoped and can be reused inside the run. A failed
proof is never cached as success.

### 11.3 Execution

Execution creates hierarchical scopes:

`Study -> Run -> Assignment -> DecisionCycle -> Effect`

The hot path uses direct ports and run-scoped pinned providers. Decision-cycle
scopes hold temporary registrations and leases only for that cycle.

### 11.4 Teardown and recovery

Every owned resource has an idempotent disposer. Disposal is quiescent and
converges when called repeatedly or concurrently.

A failed node must report whether it:

- produced no durable fact;
- committed a durable fact;
- dispatched an external effect;
- has an UNKNOWN external outcome;
- produced a resumable checkpoint.

Recovery uses the owning system's authority. It never guesses from logs.

## 12. Three planes in a single operation

For an environment action:

1. Command/runtime plane validates and invokes the typed environment/effect port.
2. Durable truth plane records intent, request digest, receipt, certainty,
   reconciliation, and commit consumption.
3. Observation plane publishes timing, traces, diagnostics, and projections.

The observation event may reference the durable fact, but it cannot become the
fact. If observation delivery fails, the action truth remains intact.

For a model request:

1. prompt/context/tool assembly builds the semantic request;
2. canonical request body, prompt, and tool schema are persisted before the
   provider call;
3. the request envelope records identities and content references;
4. the model port dispatches the exact reconstructed request;
5. stream and terminal observations remain separate from durable messages.

Invariant:

`actual model-visible bytes == durable reconstruction bytes`

## 13. Performance design

The harness removes ceremony by moving work to the correct frequency:

| Frequency | Required work |
|---|---|
| Release/source revision | source and architecture gates |
| Run admission | model qualification, participant binding, workflow assembly, structural environment proof |
| Assignment | fresh world/session and participant checkpoint |
| External action | exact request digest, effect intent, receipt, reconciliation, commit consumption |
| Finalization | measurement coverage, artifact/evidence/hash closure |
| Decision cycle | only direct port calls, local policy, scoped leases, and necessary checkpointing |

Performance rules:

- compile and freeze the graph once;
- index providers once, rather than rescanning all offers;
- compute ABI and tool-schema digests once per relevant revision;
- pin qualified providers per run, not globally;
- reuse run-scoped context and model clients;
- keep direct object references on the hot path;
- do not perform release verification inside every run;
- do not use a universal event bus for local calls;
- do not turn observability into synchronous runtime coordination.

A provider replacement or schema change invalidates the relevant plan and
starts a new run. It cannot silently alter a live run.

## 14. Failure, safety, and scientific firewalls

The following rules are mandatory:

- UNKNOWN effect outcomes are not blindly retried;
- post-policy rejection records that an effect may already have happened;
- J_audit and J_eval cannot write materialized method memory;
- observer failures cannot mutate durable truth;
- external effects require intent/certainty/reconciliation;
- checkpoints bind plan, provider, runtime, and schema identities;
- final artifacts require complete evidence/hash closure;
- no hidden import-order provider selection;
- no mutable global provider table after Study admission;
- no arbitrary universal context object;
- no platform imports of downstream scientific types;
- no method imports of concrete environment/server/process management.

## 15. Generated downstream interface

The current generated downstream systems catalog and interface schema are the
foundation for automation. The next Harness layer should add:

- a profile template schema;
- a method/node template;
- an AgentLoopPort template;
- generated typed context hints for each selected capability;
- generated run/evaluation/plotting entry points;
- contract linting before execution;
- a CLI/API that can create a valid method skeleton.

The downstream discovery API remains read-only metadata discovery. It must never
become runtime dependency resolution.

The desired authoring experience is conceptually:

`noe init method`
`noe compose`
`noe run`
`noe evaluate`
`noe render`

The CLI may produce a conventional Python package, but it must ultimately call
the same public contracts and composition root as SDK users.

## 16. DSH and Pi adoption boundary

### 16.1 Adopt from DSH

Adopt the following ideas:

- composition by named profiles;
- plugin/facet-like independent composition units;
- lifecycle ownership and reverse-order disposal;
- setup/activation separated from runtime execution;
- agent loop as a replaceable driver;
- session/transcript as reconstructable source material;
- scoped per-agent and per-run contributions;
- structured event and hook seams;
- bounded parallel tool execution and explicit barriers;
- rollback-aware creation and teardown.

### 16.2 Do not adopt from DSH

Do not adopt:

- a global mutable runtime service locator;
- unconstrained “everything is a plugin” semantics;
- one universal event log for all domain truth;
- runtime patching that changes scientific treatment identity;
- provider dynamism that invalidates a running study.

DSH's profile/lifecycle lessons are useful, but Noe's scientific reproducibility
and authority boundaries remain stronger constraints.

### 16.3 Adopt from Pi

Adopt:

- a small stable Agent contract;
- a separate low-level agent loop;
- context transformation and message conversion boundaries;
- tool execution policy hooks;
- steering/follow-up queues;
- explicit cancellation, idle, and stop barriers;
- support for custom message types with a model-facing conversion layer;
- keeping generic composition separate from the agent package.

### 16.4 Do not adopt from Pi

Pi deliberately leaves permissions, sandboxing, experiment evidence, and
scientific workflow semantics to extensions or applications. Noe must provide
those as platform contracts because they are necessary for research integrity.

Chord's useful lesson is the strongest one: plugin setup declares shape, the
host validates the complete graph, providers activate before consumers, and
resources dispose in reverse dependency order. Stable facades may survive
provider replacement in Workbench, but Study bindings remain frozen.

## 17. Migration from the current preliminary Harness draft

The existing uncommitted Harness draft is a prototype only. Before exposing it
as public API:

1. replace string-keyed runtime service lookup with composition-time typed binding;
2. separate profile metadata from instantiated runtime objects;
3. make the compiled plan immutable and evidence-bearing;
4. make node contracts declare ports, schemas, scope, and recovery;
5. route all durable facts/effects/checkpoints through existing Noe authorities;
6. reuse the existing graph/checkpointer substrate where semantics match;
7. expose the Harness through generated/public facades;
8. add contract, lifecycle, recovery, and performance tests;
9. keep SEM on its frozen branch and validate integration in an isolated fixture.

No preliminary API should be treated as stable until these boundaries are
implemented and registered in the canonical catalog.

## 18. Implementation phases

### Phase A: contract and registry

- register the Harness system and its public shape;
- define profile, capability, BindingPlan, node, and loop contracts;
- extend generated capability/interface schemas;
- add architecture and ownership checks.

### Phase B: composition and runtime

- implement typed profile compilation;
- validate provider graph, scopes, lifecycle, ABI, and forbidden edges;
- instantiate direct runtime ports;
- implement Workbench and Study lifecycle boundaries.

### Phase C: research graph

- standardize author/admission/execute/measure/evaluate/render/finalize nodes;
- connect graph checkpoints and run-scope pinning;
- support custom agent loops through AgentLoopPort;
- add structured output and tool-calling adapters.

### Phase D: automation and developer experience

- add method templates and `noe init`;
- generate selected capability context and schemas;
- add CLI/SDK commands for compose, run, evaluate, and render;
- provide one complete reference research method.

### Phase E: validation and cutover

- run contract and architecture checks;
- run focused unit and integration suites;
- run a non-SEM end-to-end fixture;
- perform SEM conformance only after its frozen experiment is complete;
- commit locally; push only in the final release batch.

## 19. Acceptance criteria

The design is ready for implementation only when:

- a new method can be created without importing concrete platform providers;
- a custom agent loop can run through the same evidence/effect contract;
- the same profile produces the same BindingPlan digest;
- a Study cannot mutate its provider graph after admission;
- runtime calls do not perform string service resolution;
- model-visible requests are reconstructable;
- tool calls and external actions have durable outcomes;
- interruption and resume preserve identity and do not duplicate effects;
- evaluation and rendering produce linked artifacts and evidence;
- observation failure cannot corrupt scientific truth;
- generated downstream schemas describe the public surface;
- performance tests show no per-cycle global graph scan or release gate.

## 20. Decisions for confirmation

Recommended defaults:

1. Plugins are dynamic only during composition/Workbench; Study is frozen.
2. Provide one high-level Harness facade plus system-specific escape-hatch
   facades for advanced users.
3. Standardize lifecycle, schemas, evidence, recovery, and effect semantics;
   leave method algorithms and agent-loop strategy fully DIY.
4. Treat the canonical registry as topology authority and BindingPlan as the
   run-specific provider authority.
5. Keep the event spine observational and keep durable truth domain-owned.

Once these defaults are confirmed, implementation should begin by replacing the
preliminary runtime draft with the typed composition model above.
## 21. Architecture review against large-repository standards

### 21.1 Verdict

The direction in this document is strong, but a facade-only interpretation of
the Universal Research Harness is not the final architecture. The target must
be a **Research Operating Kernel with an open execution model**:

```text
closed research invariants
+ open method semantics
+ pluggable execution fabrics
+ compiled binding plans
+ automatic evidence and recovery
```

This is an evolutionary refinement, not a rewrite of the current Noe
foundation. The registry, package ownership boundaries, five semantic planes,
three composition/runtime/event planes, domain-owned durable truth, and SEM
freeze boundary remain authoritative.

The central rule is:

> Downstream code may be arbitrary at the level of scientific control flow,
> but every interaction with models, tools, environments, durable state,
> artifacts, and external effects must cross a typed Noe boundary.

This gives downstream methods high semantic freedom without exporting the
platform's reliability, reproducibility, and evidence burden to every method
author.

### 21.2 Evaluation criteria

The architecture is judged by the following repository-scale criteria:

1. **Stable core**: invariants and public contracts evolve slowly and have
   explicit compatibility rules.
2. **Extension without core coupling**: providers, packs, loops, and
   evaluators can be added without editing unrelated kernel systems.
3. **Progressive complexity**: the common path is short; advanced users can
   escape to lower-level ports without replacing the kernel.
4. **Predictable lifecycle**: ownership, activation, teardown, cancellation,
   and recovery are explicit.
5. **Reproducible execution**: the admitted run has an immutable identity and
   a reconstructable binding plan.
6. **Operational explainability**: failures identify the boundary, cause,
   certainty, evidence, and next legal action.
7. **Hot-path performance**: composition, validation, and discovery are not
   repeated inside the decision loop.
8. **Conformance over convention**: each adapter and execution fabric is
   tested against contracts rather than trusted because it follows a pattern.

### 21.3 Patterns adopted and their boundaries

| Pattern | Noe adoption | Explicit boundary |
|---|---|---|
| Microkernel / plugin | Provider, pack, facade, and execution-fabric extension at composition time | No global mutable runtime plugin bus |
| Hexagonal architecture | Scientific method depends on typed ports; providers are adapters | Domain ownership cannot be bypassed by an adapter |
| Compiler / IR | Profile and method declarations compile to a canonical Method IR and BindingPlan | IR validates and optimizes; it must not erase arbitrary method semantics |
| Durable workflow | Deterministic orchestration, checkpoints, replayable requests, and recorded activities | Not every external process is replayable; certainty must be explicit |
| Actor model | Optional fabric for stateful, concurrent, long-lived agents | Actor state and ownership remain scoped and evidence-bearing |
| Controller / reconciler | Run admission, assignment, environment, artifact, and evidence closure | Use multiple small controllers, not one monolithic controller |
| CQRS | Separate commands, durable facts, queries, and projections | Do not turn every record into a universal event-sourced log |
| Saga / effect system | Intent, receipt, reconciliation, and UNKNOWN handling for external effects | Never blind-retry an effect with uncertain outcome |
| Dataflow pipeline | Evaluation, metrics, rendering, and observation fan-out | Observation pipelines cannot own primary scientific truth |
| Strategy / Template Method | Replace loops, schedulers, evaluators, and providers under a stable lifecycle | Kernel middleware surrounds the strategy and cannot be skipped |
| Decorator / middleware | Identity, timing, checkpoint, policy, audit, and evidence interception | Middleware cannot silently mutate method semantics |
| Composite | Nested methods, child agents, sub-experiments, and method graphs | Child scopes and evidence lineage are mandatory |

The combination is intentional. No single pattern expresses both arbitrary
agent behavior and research-grade durability.

## 22. Target architecture: Research Operating Kernel

### 22.1 Four architectural layers

The Harness should be implemented as four stable layers rather than as one
large object:

1. **Harness Kernel**: identity, scope, lifecycle, admission, effect safety,
   checkpoint/recovery, evidence, compatibility, and platform invariants.
2. **Execution Fabric**: one of several execution substrates that run a
   method program: graph, agent loop, actor, stream, matrix, external job,
   human gate, or custom fabric.
3. **Research Packs**: batteries-included compositions for common research
   families such as single-agent, multi-agent, planning, memory, tool-use,
   interactive, streaming, RL, benchmark, training, and distributed work.
4. **Managed Method Program**: downstream-owned scientific state, algorithm,
   control flow, hypotheses, policies, and method-specific claims.

The Kernel is closed with respect to safety and evidence invariants. The
Method Program is open with respect to scientific semantics. Packs are
convenience and composition units, not a second authority.

### 22.2 Control, data, and observation planes

Noe's existing three composition/runtime/event planes should be formalized in
the familiar control-plane/data-plane/observation-plane vocabulary without
replacing the existing five semantic ownership planes:

| Noe plane | Responsibility | Performance rule |
|---|---|---|
| Control plane | Registry, profile, dependency resolution, admission, compilation, freezing, and reconciliation | May be relatively rich and slow; never runs per decision cycle |
| Data plane | Direct typed ports, method execution, model/tool/environment calls, and scoped state transitions | Must use pre-bound references and bounded middleware |
| Observation plane | Event spine, telemetry, projections, metrics, evaluation inputs, and diagnostics | May fan out and fail independently; cannot mutate primary truth |

```mermaid
flowchart TD
    A["Registry and Profile"] --> B["Compile and Admit"]
    B --> C["Frozen BindingPlan"]
    C --> D["Execution Fabric"]
    D --> E["Managed Method Program"]
    D --> F["Domain Facts and Effects"]
    D --> G["Observation and Projections"]
```

The registry remains the topology and ownership authority. The BindingPlan is
the authority for one admitted run. Direct ports are the authority for the
hot path. The event spine is an observation transport, not a replacement for
domain-owned durable facts.

### 22.3 Modular monolith first, distributed by fabric

The logical system should remain a modular monolith until a measured scaling
boundary requires a separate process. The 172 registered systems are not 172
mandatory microservices. Splitting every system into a network service would
add latency, failure modes, deployment coupling, and reproducibility concerns
to the method hot path.

Physical distribution remains supported through Execution Fabric adapters,
worker pools, external jobs, and remote providers. The logical contracts must
not depend on whether a provider is local, containerized, or remote.

## 23. Capability facets and Research Packs

### 23.1 Registry systems versus downstream surface

All registered systems must remain useful, but they must not all be presented
as equal-level downstream APIs. The public surface should be generated through
capability facets and packs:

```text
172 registered systems
        -> owned capabilities and typed ports
        -> capability facets
        -> Research Packs
        -> small Harness authoring surface
```

The registry should eventually classify each system or public capability with
metadata equivalent to:

- `harness_role`: kernel, fabric, pack, method, evidence, or advanced escape hatch;
- `exposure`: default, pack-only, advanced, internal, or observation-only;
- `lifecycle`: process, worker, run, assignment, step, or projection scoped;
- `consistency`: durable, transactional, eventually-consistent, or live;
- `effect_class`: pure, recorded, reversible, idempotent, or uncertain;
- `cost_class`: control-plane, setup, per-run, per-assignment, or hot-path;
- `stability`: public, experimental, deprecated, or internal;
- `conformance`: the contract suite required before publication.

This metadata is additive to the canonical registry. It must not create a
second topology authority.

### 23.2 Packs must be composable, not combinatorially explosive

Packs should declare typed provisions and requirements and be composed through
the same dependency graph as systems. A pack may provide defaults, but every
default must be replaceable at a declared seam.

Packs must not encode every possible combination as a new class. Prefer small
orthogonal facets:

```text
AgentLoopFacet + MemoryFacet + ToolFacet + EvaluationFacet
```

The compiler composes these facets into a BindingPlan. A pack becomes a
curated, tested bundle of facets, defaults, policies, and examples.

### 23.3 Public API tiers

The downstream surface should have four intentional tiers:

1. **Quickstart API**: one method definition and one run command.
2. **Research API**: typed method state, capabilities, variants, metrics,
   artifacts, and evaluation.
3. **Fabric API**: custom graph, actor, stream, scheduler, or agent loop.
4. **Kernel escape hatches**: advanced ports for platform authors and unusual
   research infrastructure.

The tier is a usability boundary, not a permission boundary. Advanced users
can reach lower layers, but ordinary method authors should never need to know
the entire registry.

## 24. Method semantics and the universal ABI

### 24.1 The strongest useful semantic model

The method model should be defined as:

```text
Method Program
  = method-owned State
  + typed Capabilities
  + arbitrary Control Flow
  + typed Effects
  + evidence-bearing Claims
```

This is stronger than a fixed `observe -> think -> act -> evaluate` template.
That sequence remains a default AgentPack, but it is not the semantic limit of
Noe.

The method may implement loops, recursion, branching, speculative execution,
multi-agent negotiation, asynchronous streams, curriculum changes, online
learning, external simulators, human gates, or custom schedulers. The kernel
only controls what crosses a platform boundary.

### 24.2 Progressive authoring

The authoring levels are:

- **Level 0**: configuration, prompt, schema, provider, and experiment matrix;
- **Level 1**: one or more policies such as decision, planning, memory, tool
  selection, or evaluation;
- **Level 2**: custom state, nodes, edges, events, child agents, and graph;
- **Level 3**: a complete custom execution fabric or agent loop.

Every level uses the same identity, scope, effect, evidence, and finalization
contracts. Moving to a lower level increases control, not the amount of
generic reliability code the researcher must rewrite.

### 24.3 Effect boundary

All nondeterministic or externally visible operations are typed effects:

```python
observation = ctx.environment.observe(request)
completion = ctx.model.complete(model_request)
receipt = ctx.tools.invoke(tool_call)
checkpoint = ctx.state.save(snapshot)
claim = ctx.evidence.assert_claim(statement, support)
```

Noe automatically adds identity, scope, request digest, provider identity,
timing, policy checks, outcome certainty, receipts, retries where legal,
reconciliation, and evidence lineage. The method supplies intent and consumes
the typed result.

### 24.4 Execution classes

Arbitrary code and replayability cannot be promised simultaneously for every
method. The ABI must declare an execution class:

| Class | Guarantee |
|---|---|
| Deterministic | Replayable from canonical inputs and recorded effects |
| Checkpointable | Recoverable from declared state checkpoints |
| Effect-recorded | External interactions are reconstructable from receipts and evidence |
| Live | Not replayable by default, but boundaries and evidence remain explicit |

The declaration affects admission, available recovery modes, comparison
claims, and publication gates. It does not prohibit a method from using a
less-deterministic substrate; it prevents the platform from making a false
reproducibility claim.

## 25. Method Compiler and frozen execution

### 25.1 Compilation pipeline

The declarative profile and method metadata should compile once into a
canonical intermediate representation:

```text
Method Definition
  -> capability resolution
  -> dependency and policy validation
  -> Method IR
  -> provider and version binding
  -> generated schemas and manifests
  -> BindingPlan
  -> admitted frozen run
```

The compiler must:

- reject missing, ambiguous, incompatible, or cyclic requirements;
- resolve providers and versions against the canonical registry;
- validate effect and execution-class declarations;
- assemble direct typed ports;
- precompute scopes, lifecycle ownership, and teardown order;
- generate the plan digest, interface schema, and run manifest;
- identify required evidence and finalization obligations;
- expose a human-readable explanation of the resulting plan.

The IR is an optimization and validation artifact, not a workflow language
that every method must be forced to use. A custom Level 3 program can be
wrapped by a Managed Method ABI adapter and still receive a compiled binding
plan.

### 25.2 Freeze and reload rules

Workbench may discover, inspect, validate, and reload development generations.
Study admission creates one immutable run generation:

- provider graph is frozen;
- plugin and pack identities are frozen;
- model and environment identities are frozen;
- schemas and policy versions are frozen;
- the BindingPlan digest is persisted;
- teardown and recovery ownership are fixed.

No execution-time string lookup, implicit package installation, provider
replacement, or hidden hot reload is allowed. This preserves the existing
Noe rule that development flexibility ends at Study admission.

## 26. Reconciliation, failure, and recovery architecture

### 26.1 Small controllers

Noe should use independent reconciliation loops for independently owned state:

- run admission controller;
- assignment/environment controller;
- model/provider readiness controller;
- execution supervision controller;
- artifact finalization controller;
- evidence closure controller.

Each controller compares desired and observed state, writes only to its owned
domain, and emits diagnostics or durable facts through the appropriate
boundary. Controllers must be independently testable and must not form a
hidden monolithic workflow.

### 26.2 External effects

An external effect follows:

```text
intent -> request record -> provider call -> receipt -> reconciliation -> commit
```

If the result is UNKNOWN, the next action is reconciliation, not blind retry.
Compensation is provider-specific and must not be assumed to be rollback.
This applies equally to model serving, tool calls, simulator actions, remote
jobs, artifact publication, and human approval.

### 26.3 Failure domains

The runtime must distinguish at least:

- method failure;
- provider failure;
- infrastructure failure;
- policy/admission failure;
- evidence/observation failure;
- uncertain external effect;
- finalization failure.

Each failure domain has a different recovery and claim implication. In
particular, observation failure cannot invalidate or mutate a durable fact,
while an evidence closure failure must block a claim-ready publication.

## 27. Performance and operability requirements

The abstraction must disappear from the hot path as far as practical:

1. Compile and validate once per profile or admitted run, not once per step.
2. Inject direct typed references into worker and run scopes.
3. Initialize expensive clients at worker startup or run setup and reuse them
   when their identity and isolation rules permit.
4. Keep request envelopes canonical and avoid repeated schema generation.
5. Use bounded middleware with explicit sampling for non-authoritative traces.
6. Make checkpoints incremental and provider-aware.
7. Do not serialize large method state merely to pass through generic context.
8. Never scan the full registry, resolve strings, or run release gates per
   decision cycle.
9. Benchmark local, container, and remote fabrics separately.
10. Report overhead as part of run evidence when it can affect the method.

The design therefore rejects a universal mutable `HarnessContext` containing
all 172 systems. A context is a scoped, typed capability view generated from a
BindingPlan; it is not a service bag or ambient dependency container.

## 28. Large-repository acceptance gates

Implementation of this architecture is not complete when the facade imports.
It is complete only when the repository has:

- contract tests for every public port and provider adapter;
- conformance suites for every Execution Fabric;
- deterministic replay tests for deterministic methods;
- checkpoint and crash-recovery tests for checkpointable methods;
- failure-injection tests for each failure domain;
- property-based tests for idempotency and reconciliation;
- golden tests for Method IR, BindingPlan, schema, and manifest digests;
- compatibility tests for public schema and API evolution;
- lifecycle tests for activation, cancellation, drain, teardown, and unwind;
- benchmark tests proving no global graph scan or repeated admission work in
  the hot path;
- one complete reference method at each authoring level;
- diagnostic output that explains why a method or run was rejected;
- documentation generated from the same public contract source as validation.

The minimum-method-size metric should be tracked as a product requirement:
adding a new scientific method must require method semantics, not repeated
implementation of model qualification, effect recovery, evidence transport,
artifact closure, or plotting plumbing.

## 29. Final architecture decision

The recommended target is now:

> **Noe Research Operating Kernel + Open Method ABI + Pluggable Execution
> Fabrics + Capability Facets/Research Packs + Compiled BindingPlan.**

Keep:

- the canonical registry as the single topology authority;
- the five semantic ownership planes and strict dependency direction;
- the typed composition graph;
- direct immutable runtime ports;
- the separate observational event spine;
- domain-owned durable truth;
- frozen Study generations;
- explicit external-effect certainty and reconciliation;
- SEM's pinned frozen Noetrium boundary.

Add before large-scale Harness implementation:

1. registry metadata for role, exposure, lifecycle, consistency, effect, cost,
   stability, and conformance;
2. capability facets and Research Packs as the main downstream surface;
3. Method IR and BindingPlan compilation with explainable diagnostics;
4. multiple Execution Fabric contracts instead of a fixed lifecycle graph;
5. managed Level 3 method execution through the same Effect ABI;
6. small reconciliation controllers for run and evidence closure;
7. contract, conformance, replay, recovery, and performance gates.

This is the architecture that best balances the two apparently conflicting
requirements: a new researcher should write very little infrastructure code,
while an expert researcher must still be able to express an arbitrary agent
research method without fighting the framework.

### 29.1 Reference sources for the adopted patterns

The design draws on the following public architectural precedents, adapted to
Noe's stronger scientific-evidence requirements:

- Kubernetes controller and reconciliation model:
  <https://kubernetes.io/docs/concepts/architecture/controller/>
- Temporal deterministic workflow and recorded Activity boundary:
  <https://docs.temporal.io/workflows>
- Ray stateful Actor execution model:
  <https://docs.ray.io/en/latest/ray-core/actors.html>
- OpenTelemetry extensible observation pipelines:
  <https://opentelemetry.io/docs/collector/architecture/>
- DeepSeek Harness profile/plugin lifecycle:
  <https://raw.githubusercontent.com/deepseek-ai/deepseek-harness/refs/heads/master/docs/architecture.md>
- Pi Chord provision/requirement graph and lifecycle ownership:
  <https://github.com/earendil-works/pi/tree/main/packages/chord>
## 30. Universal Method Machine

### 30.1 The generalization that removes most Pack-specific engineering

The Harness should not grow by implementing one runtime package for every
research pattern. The scalable abstraction is a Universal Method Machine: a
small operation algebra, a typed capability model, and a managed program
interpreter.

The intended relationship is:

~~~text
registered systems
  -> capability descriptors
  -> typed operation handlers
  -> compiled Method IR and BindingPlan
  -> Universal Method Machine
  -> arbitrary downstream Method Program
~~~

A Research Pack is then a tested declarative recipe over this machine. It is
not a second runtime, a new source of truth, or a bespoke implementation of
model, tool, memory, evidence, and recovery plumbing.

This is the main mechanism for reducing implementation scale. The platform
still contains domain-specific providers because models, environments, stores,
and schedulers have real differences. What disappears is repeated integration
code around each provider and repeated Pack-specific lifecycle code.

### 30.2 Operation algebra

Every interaction between a Method Program and the platform is normalized to
one of a small number of operation kinds:

| Operation | Meaning | Durable implication |
|---|---|---|
| READ | Read a fact, observation, model context, memory, or resource state | May be replayed or memoized according to its contract |
| COMPUTE | Run method-owned or provider-owned pure computation | No external effect unless declared |
| EFFECT | Invoke a model, tool, environment, remote job, or external system | Requires intent, receipt, certainty, and reconciliation |
| COMMIT | Append or transition an owned durable fact | Only the owning domain may commit |
| OBSERVE | Produce telemetry, metrics, traces, or projections | Side-plane only; cannot become primary truth |
| CHECKPOINT | Persist resumable method or runtime state | Carries scope, lineage, and compatibility identity |
| SPAWN | Create a child method, Agent, assignment, or execution unit | Creates a child scope and evidence lineage |
| WAIT | Wait for a child, event, resource, human gate, or external job | Must be cancellation- and recovery-aware |
| CLAIM | Register a metric, evidence statement, or scientific claim | Must reference supporting facts and artifacts |

The operation algebra is a runtime semantic boundary, not a restriction on
method control flow. A method may issue operations from arbitrary loops,
recursion, branches, coroutines, actor mailboxes, streams, or custom
schedulers.

### 30.3 Typed capabilities, not an ambient context

A capability is a statically bound, typed view of one or more platform
operations:

~~~text
Capability
  = Descriptor
  + Typed Port
  + Operation Schema
  + Handler
  + Lifecycle
  + Effect Policy
  + Evidence Policy
~~~

The BindingPlan resolves the capability before execution and injects only the
views requested by the Method Program. It does not inject a dictionary
containing all systems.

A generated capability may look like:

~~~python
model = runtime.capabilities.model
environment = runtime.capabilities.environment
memory = runtime.capabilities.memory
~~~

but each attribute is a typed, pre-bound capability handle. It is not a
string lookup, a mutable service bag, or a permission to discover arbitrary
providers during the hot path.

The existing four-segment system shape remains the source of implementation:

- api declares the capability and operation contracts;
- runtime defines deterministic semantic logic;
- providers implement storage, network, model, environment, and other
  concrete handlers;
- composition resolves and binds handlers before admission.

### 30.4 Managed Method Program

The Method Program is the only part that must express the research algorithm.
It owns its state and control flow but not the platform's cross-cutting
machinery.

The minimal managed surface is conceptually:

~~~python
class MethodProgram:
    state_schema: type
    execution_class: ExecutionClass

    async def run(self, runtime: MethodRuntime) -> None:
        ...
~~~

The runtime supplies typed capabilities and structured operations. The method
may use ordinary Python control flow, a generator, coroutine, actor callback,
stream processor, external worker protocol, or another supported program
adapter.

For a lower-level method, the same ABI exposes explicit operations:

~~~python
async for operation in program:
    result = await runtime.execute(operation)
    program.resume(result)
~~~

The two styles are equivalent at the boundary. The first is convenient for
most researchers; the second is useful for interpreters, schedulers, and
custom fabrics.

### 30.5 Universal Handler pipeline

Every operation passes through a compiled handler chain appropriate to its
kind:

~~~text
typed call
  -> scope and identity
  -> authorization and policy
  -> request canonicalization
  -> checkpoint / deduplication
  -> provider handler
  -> receipt or durable commit
  -> reconciliation
  -> evidence linkage
  -> observation
~~~

The handler chain is assembled during composition and frozen at Study
admission. Handlers may be omitted when their contract proves they are
unnecessary, but a method cannot bypass required identity, effect certainty,
ownership, or evidence handlers.

This is the practical form of an algebraic-effect architecture: method code
describes an operation, while the runtime installs the correct handler for
that operation. It centralizes generic behavior without forcing all scientific
algorithms into one workflow template.

### 30.6 Universal semantic core, specialized execution engines

The Universal Method Machine unifies operation semantics, not every physical
implementation. It may select specialized schedulers from the BindingPlan:

- sequential or cooperative coroutine execution;
- structured concurrent execution;
- actor/mailbox execution;
- event-stream execution;
- matrix/batch execution;
- external job execution;
- human-gated execution.

All schedulers consume the same Method Program, operation contracts, scope
rules, effect semantics, and evidence ABI. This prevents Pack proliferation
while preserving performance-specific implementations.

The scheduler is a Strategy; the lifecycle around it is a Template Method; the
operation handlers are typed adapters and Decorators. The Method Program
itself remains the domain-owned algorithm.

### 30.7 Research Packs become recipes

Research Packs should be represented primarily as:

~~~text
Recipe
  = required capabilities
  + default policies
  + execution strategy
  + evidence obligations
  + examples
  + conformance tests
~~~

A recipe may generate a user-friendly API, but it should not copy the
underlying runtime. A new combination of memory, tools, model, and evaluator
should normally require a new recipe document or manifest, not a new runtime
package.

A genuine new Pack implementation is justified only when it introduces a new
execution substrate, resource lifecycle, operation kind, or domain contract
that cannot be expressed by existing capabilities.

### 30.8 Automatic capability lifting

A registered system should be liftable into the universal machine when its
descriptor supplies:

- public typed operations;
- ownership of facts, effects, artifacts, or projections;
- lifecycle and scope;
- consistency and idempotency;
- effect certainty behavior;
- provider identity and version;
- schema and digest rules;
- conformance test reference.

The compiler can then generate:

- capability handles;
- operation schemas;
- downstream interface schemas;
- binding and teardown plans;
- evidence obligations;
- method authoring hints;
- a human-readable plan explanation.

This means the 172 systems can contribute value without requiring 172
handwritten Harness integrations.

## 31. Consequences for Noe implementation

### 31.1 The first implementation target

The first production slice should be the smallest complete machine, not a
catalog of Packs:

1. CapabilityDescriptor and generated capability catalog;
2. OperationKind, request, result, and error contracts;
3. typed CapabilityHandle binding through the existing composition graph;
4. MethodProgram and MethodRuntime ABI;
5. compiled handler pipeline for identity, recording, effect certainty,
   checkpoint, and evidence linkage;
6. one sequential scheduler and one structured-concurrency scheduler;
7. one reference method and one failure/recovery fixture;
8. generated schema and BindingPlan explanation.

Only after this vertical slice is conformance-tested should more schedulers or
recipes be added.

### 31.2 What should not be implemented

The following implementations are explicitly rejected:

- one Pack class for every popular Agent pattern;
- one universal mutable Context holding all registered systems;
- one global operation/event bus that owns every domain fact;
- runtime string lookup of providers;
- a mandatory fixed observe -> think -> act -> evaluate lifecycle;
- a giant DSL that forces all arbitrary method logic into generated nodes;
- automatic inference of scientific meaning from generic runtime events;
- execution-time provider replacement or hidden hot reload;
- a separate topology authority for capability metadata.

### 31.3 Correctness and performance invariant

The Universal Method Machine must satisfy this invariant:

~~~text
same Method Program
+ same admitted BindingPlan
+ same input/effect records
=> same legal replay or explicitly classified non-replayable outcome
~~~

Compilation, discovery, schema generation, and architecture validation occur
before execution or at a declared scope boundary. The hot path uses direct
typed references, bounded handlers, and worker/run-scoped resources.

### 31.4 Migration rule

The preliminary Harness draft is not the target implementation if it uses
string service locators, an ambient all-system context, or runtime discovery.
It should be replaced or reduced to reusable contract fragments.

Existing Noe systems remain the providers and authorities. The Universal
Method Machine is a new orchestration substrate above their public contracts,
not a second domain layer and not a replacement for the registry.

### 31.5 Definition of success

The architecture is successful when a new downstream method can provide:

~~~text
method-owned state
+ method program
+ semantic manifest
~~~

and receive, without handwritten infrastructure integration:

~~~text
model/tool/environment access
+ lifecycle
+ checkpoint/recovery
+ effect receipts
+ experiment identity
+ metrics and artifacts
+ evidence closure
+ generated schema
~~~

An expert can still replace the program and scheduler through the same ABI.
A novice can stay at the recipe or policy level. Both paths produce the same
auditable run boundary.
