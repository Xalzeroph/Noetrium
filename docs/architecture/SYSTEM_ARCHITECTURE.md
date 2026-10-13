# Noetrium System Architecture

This document is the detailed technical companion to the repository README for Noetrium 1.0. It consolidates the architecture that previously lived across the long-form README and development-era design notes. The current implementation, public contracts, system registry, and executable gates remain authoritative when prose and code disagree.

The core invariant is simple: **immutable research semantics are composed at the top; mutable truth is accepted only by its owning authority; all scientific execution converges on one Machine path.**

## Overview

Noetrium is a research execution platform for AI-agent research. It is not another agent loop, workflow DSL, benchmark harness, or provider SDK. Its job is to make arbitrarily large research programs composable while preserving one static semantic truth and explicit dynamic authorities.

The end-state model is intentionally small:

> <strong>NoetriumUnit is the only persistent semantic carrier. run is the only public execution operation. Immutable Unit/Event truth is projected into execution views; owning Authorities linearize dynamic facts; thin Providers perform authorized physical effects.</strong>

That model is designed for the point where a research repository stops being one script and becomes a matrix of papers, methods, benchmarks, environments, models, trials, resources, interruptions, retries, revisions, and publication evidence.

The normal Python path is intentionally exact:

~~~python
from noetrium import NoetriumUnit, run

ROOT = NoetriumUnit.make_structure(
    "paper",
    traits=("research.portfolio",),
)
report = run(ROOT)
~~~

A filesystem project is only another source for the same root value, so run(".") and run(ROOT) converge on the same internal execution path. Provider, resource, lifecycle, scheduler and authority mechanics remain below this boundary.

Noetrium separates five concerns that are often collapsed into one framework:

| Concern | Noetrium boundary |
| --- | --- |
| Research authoring | <code>noetrium.NoetriumUnit</code>: one recursive, content-addressed carrier for paper semantics, programs, studies, experiments, methods, metrics and explicit references |
| Scientific execution | Program interpreters propose work; <code>MachineExecutor</code> accepts transitions into the Machine Journal |
| Domain truth | Experimentation, resource, artifact, data, model, participant, environment and other authorities own their own facts |
| Reusable mechanisms | canonical identity, content addressing, durability, CAS/fencing, leases, checkpoints and other platform primitives |
| Observation | telemetry, diagnostics, projections and forensics observe authority; they do not replace it |

The dependency direction is one-way:

<strong>research intent -> explicit composition -> frozen identity -> admitted execution -> authoritative transition/effect/evidence -> recovery, replay, inspection and verification.</strong>

Noetrium owns the reusable research substrate: canonical identities, revision/binding truth, durable machine transitions, recovery boundaries, resource admission, effect certainty, artifacts, evidence, provenance, observability and governance. Downstream projects own the scientific novelty and concrete paper content: ordinary Python implementations, prompts, memory semantics, benchmark builders/assets, task policies, experiment hypotheses, statistical interpretation and claims. Noetrium does not require a new upstream benchmark or method implementation when a new paper is added.

A downstream paper should normally change only its recursive <code>NoetriumUnit</code> root and the paper-owned implementations referenced by that root: methods, benchmark builders/assets, Study/Experiment semantics, prompts, policies and handlers — <strong>not Noetrium internals</strong>. Lower execution, capability, runtime, resource and infrastructure interfaces are consumed only by their adjacent Noetrium layer rather than by downstream research code.


## Why Noetrium?

Agent research becomes difficult to trust when orchestration, scientific semantics, provider mechanics and persistence are implemented as one opaque loop. The common failure modes are structural: two runners both believe they own progress, a retry silently repeats an uncertain external effect, a checkpoint diverges from execution history, a scheduler becomes scientific truth, or an updated provider changes a supposedly identical experiment.

Noetrium addresses those failures by making authority explicit and machine-verifiable.

### Where Noetrium fits

| Project | Primary focus | Noetrium adds |
| --- | --- | --- |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Long-running stateful agent orchestration | Research identity, evidence, recovery, and governance around execution |
| [AutoGen](https://github.com/microsoft/autogen) | Multi-agent applications | Experiment protocol, reproducibility, and release evidence |
| [CrewAI](https://github.com/crewAIInc/crewAI) | Agent teams and event flows | Scientific run identity, lineage, and fail-closed recovery |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | AI-driven software development | General research infrastructure across agents, models, and environments |
| <strong>Noetrium</strong> | Reproducible AI-agent research infrastructure | The research-systems layer itself |

Existing orchestration frameworks can be used inside a downstream method or provider when that is scientifically appropriate. Noetrium does not need to replace them. It supplies the surrounding research identity, execution authority, resource/effect discipline, recovery and evidence closure that remain stable when the orchestration implementation changes.


## Core capabilities

- <strong>Two-symbol downstream API</strong> — <code>noetrium</code> exposes exactly <code>NoetriumUnit</code> and <code>run</code>. Every static paper concept is a schema/role/reference projection over the same recursive Unit; provider, authority, resource, Docker and lifecycle interfaces remain internal owner boundaries.
- <strong>Recursive research composition</strong> — one immutable Unit root can contain any number of programs, studies, experiments, concrete downstream methods, benchmarks, analyses, dependencies and nested research roots without introducing another carrier type.
- <strong>One executable program model</strong> — Method (including memory semantics), Runtime, Participant, Environment, Evaluation, Optimization, Experiment and Run semantics converge on <code>ResearchProgram</code> and the same Machine execution kernel.
- <strong>Durable scientific execution</strong> — <code>ProgrammableMachineInterpreter</code> proposes transitions; <code>MachineExecutor</code> commits accepted transitions to the Machine Journal. The journal is the execution truth.
- <strong>Typed Method semantics without a second runtime</strong> — Method-specific authoring can use the internal typed Method facade, which lowers deterministically into <code>ResearchProgram(kind=METHOD)</code>. Method result facades do not own a separate cursor, scheduler, checkpoint engine or transition history.
- <strong>Nested research Machines</strong> — child work runs through the same kernel and is linked to its parent by exact <code>ChildMachineLink</code> / Machine-cut identity rather than hidden callback stacks.
- <strong>Participant and workload compilation</strong> — participant schedules and workload dependency DAGs compile into ordinary ResearchPrograms. Workloads execute through a bounded completion-driven dependency frontier: each completion can immediately unlock and refill eligible dependents while durable Machine state remains scheduling truth.
- <strong>Exact definition binding</strong> — downstream-owned scientific definitions such as Methods, Benchmarks, Metrics and project protocols may carry their concrete implementation directly in the frozen ResearchProgram. Infrastructure requirements such as Model, Environment and external data/assets resolve through their owning authorities and are frozen before execution. Physical admission policy, placement and runtime realization remain platform-owned. Unknown, ambiguous or drifted bindings fail closed.
- <strong>Durable execution budgets</strong> — steps, wall/working time, turns, messages, model calls, tokens, cost and replay level share one crash-durable execution-budget authority. Physical resource admission is enforced separately by the platform runtime.
- <strong>Replay-aware admission</strong> — observational, checkpoint and exact replay claims require different proofs. Exact replay is never inferred from a seed or from a checkpoint alone.
- <strong>Explicit effect certainty</strong> — external actions are mediated through effect intents, receipts and reconciliation. <code>UNKNOWN</code> remains unknown; transport success or failure is not silently converted into scientific certainty.
- <strong>Controlled causal environments</strong> — observed-state projections, action intents and effect transitions are disjoint NoetriumUnit truth roles; Minecraft's causal world-machine contract specifies the physical/method boundary, conditional minimality claims and exact failure invariants.
- <strong>Canonical artifact and evidence ownership</strong> — blobs, artifact catalog entries, references, retention, evidence and provenance use their owning authorities instead of run-local shadow stores.
- <strong>Typed research values</strong> — Artifact, Evidence, Checkpoint, Metric, Selection and Data values cannot be relabeled generic JSON. A value kind is accepted only when its owner authority is available.
- <strong>One recovery truth</strong> — durable recovery is rooted in the Machine Journal and <code>MachineCut</code>. Checkpoint payloads and snapshots are acceleration artifacts tied to that cut, not independent restore authorities.
- <strong>Resource and runtime lifecycle</strong> — admission, shared-host pressure, compute/GPU allocation, endpoints, processes, services, Docker generations, leases, heartbeats and abandoned-owner recovery remain in the physical owner systems below scientific Programs.
- <strong>Content-addressed reuse and single-flight construction</strong> — immutable execution structures and runtime realizations are keyed by exact identity and reused instead of rebuilt. In-process workload/participant/task/model-endpoint/tokenization structures use one-producer single-flight construction; project runtime layers, environment images and other physical realizations reuse content-addressed owner-managed artifacts when their exact identities match.
- <strong>Hierarchical fair scheduling</strong> — execution carries a non-scientific tenant identity through Research execution, Experiment, Workload, child-Machine, environment-capability and model-request paths. Admission prefers tenants and groups with lower active share before grant history, preventing high fan-out from monopolizing shared capacity while remaining work-conserving for a single active tenant.
- <strong>Adaptive shared model serving</strong> — qualified deployments separate the measured safe concurrency ceiling from the preferred operating point. Qualification starts near a computed concurrency derived from model KV geometry and observed request footprint, then searches upward or downward. Runtime admission adapts using normalized service latency, rate-limit responses and vLLM pressure signals such as running/waiting requests, KV-cache usage and preemption.
- <strong>Architecture governance</strong> — generated topology maps, public-contract gates, no-compatibility/no-degradation checks and authority rules reject shadow runtimes and ownership leaks.

### Scientific measurements, derived metrics and analysis

The Unit API carries the full scientific measurement path without exposing Study, MetricEngine or Workbench internals. Metrics, analyses, evidence obligations and their dependencies are immutable Units/schemas nested in the same research root. Their content identity therefore participates in the root digest exactly like methods, experiments and benchmarks; no second metric/analysis carrier is required.

Capture is typed rather than scalar-only. Supported measurement values are scalar, boolean, categorical, structured, sequence, distribution, matrix, text judgement and artifact-backed content reference. Study measurement projection owns capture and provenance; nontrivial aggregation is deliberately kept out of the capture reducer.

Derived raw-record metrics use the single Experimentation metric engine and support count, sum, mean, min, max, standard deviation, p50, p95, first, last and distinct count, with record/schema filters, predicates, grouping and explicit missing-value policy. Paper-specific formulas remain downstream implementations instead of becoming platform special cases.

Declarative analyses lower through Composition into the standard Research Workbench. Built-in inference includes normal-mean inference, bootstrap mean, group comparison, paired comparison, permutation comparison and one-to-many comparison with Bonferroni, Holm, Benjamini-Hochberg or Benjamini-Yekutieli correction. Every declarative result is tied to an immutable MeasurementCut, frozen AnalysisDefinition, input cut digest, implementation/configuration digest and AnalysisResult digest, so post-hoc analysis can change without silently changing the underlying experiment evidence.

The layer boundary remains strict: Product freezes JSON scientific intent; Experimentation owns capture and derived metrics; Workbench owns statistical inference; Composition performs only the adjacent translation between them. Downstream projects do not import those lower types.

<!-- noetrium-interface-catalog:start -->
### Public interface catalog

Noetrium exposes one semantic value and one execution operation. Registered lower systems remain internal composition authorities and are listed here only as architecture metadata.

- 30 registered system surfaces; 1 cataloged API module; 2 cataloged symbols.
- Full machine-readable catalog: noetrium/contracts/downstream_capability_catalog.json
- Full human-readable catalog: docs/architecture/DOWNSTREAM_CAPABILITY_CATALOG.md
- Import rule: downstream code uses only NoetriumUnit and run from noetrium; lower system facades are internal registry material.

| Capability domain | Registered surfaces |
| --- | ---: |
| artifact | 1 |
| data | 2 |
| environment | 7 |
| execution | 2 |
| experimentation | 1 |
| governance | 3 |
| model | 1 |
| observability | 2 |
| operator | 1 |
| participant | 1 |
| platform | 1 |
| portfolio | 1 |
| reliability | 3 |
| research | 1 |
| resource | 1 |
| runtime | 1 |
| scope | 1 |

Author and control research through the same top-level API:

    from noetrium import NoetriumUnit, run
    method = NoetriumUnit.make_structure(
        "method", traits=("research.method",)
    )
    ROOT = NoetriumUnit.make_structure(
        "paper", traits=("research.portfolio",), members=(method,),
    )
    run(ROOT)

After changing a registry descriptor or public API export, run python scripts/update_generated_docs.py; CI fails on generated-surface or README drift.
<!-- noetrium-interface-catalog:end -->

The catalog is an API map, not an authority registry that downstream code is expected to edit. A system surface declares what it owns, what it must not own, what it requires, what it provides, and which public facade exposes it. Internal implementation packages may be reorganized without turning implementation paths into public contracts.


## Architecture

Noetrium is organized around one rule: <strong>scientific semantics may be modular, but scientific execution has one acceptance path.</strong>

~~~text
recursive content-addressed NoetriumUnit root
    |
    v
pure validation / refinement / compiled projections
    |
    v
Authority admission + generation fencing + single-flight
    |
    +--> MachineExecutor / thin physical Providers
    |
    v
Authority-partitioned causal Event Units
    |
    +--> Declared / Authorized / Observed / Evidenced truth
    +--> disposable SQLite/index/graph/debug projections
    +--> reverse causal cone for replay and root-cause analysis
~~~

There is no global total-order journal. Independent Authority domains may progress concurrently; only explicit causal references and resource conflicts impose order.

**Verifiable execution coverage.** The Machine Journal binds every accepted transition to its executable Unit identity, input, state delta, events, effects and causal links. Read-only coverage Units attest committed journal cuts; recursive child-Machine verification checks each linked Unit lock and immutable MachineCut. The same accepted events can be projected into Metric Definition Units through the shared MetricEngine, including the verified transitive child cut. Coverage remains explicitly scoped to observed and persisted facts: external effects and artifact content must be independently verified by their owning Authorities. See Unit Execution Coverage Theory for assumptions, impossibility bounds and verification requirements.

A domain may provide its own typed authoring vocabulary, but executable semantics converge before state progression. Method is the main example: Method-specific nodes, schemas, evidence obligations and agent/capability semantics are useful authoring concepts, but they lower to <code>ResearchProgram(kind=METHOD)</code> and execute through the same interpreter and Machine journal as other programmable domains.

### One executable IR, many semantic domains

The generic executable program is <code>ResearchProgram</code>. Its <code>MachineKind</code> identifies governance and semantic role; it does not create a separate engine.

Current programmable domains include Method, Runtime, Participant, Environment, Evaluation, Optimization, Experiment, Run, Analysis and Publication. Memory is part of Method semantics rather than a peer runtime. Programs may use bounded transitions, per-node visit limits, capabilities, child Machines, checkpoints, interruption, evidence, artifacts and semantic sidecar state.

The distinction is:

~~~text
kind            = what the Machine represents
program nodes   = what it does
ports/authority = what external facts or effects it may use
journal         = what execution was accepted
~~~

A new research concern should therefore become a new program, policy, handler, capability or owner binding before it becomes a new runtime.

### Method semantics

Method is the Agent Harness semantic aggregate: control flow, agent/model invocation, capability use, context, memory, communication, environment interaction, logical scheduling, synchronization, recovery, intervention, visibility and related paper-variable behavior belong here when they are part of the method.

Noetrium may retain typed Method authoring classes internally because they make these semantics precise. They are not a second executable IR. Method authoring lowers deterministically into <code>ResearchProgram</code>; the Method facade projects generic host execution back into typed Method results and evidence.

That means there is no independent Method cursor, transition authority, checkpoint engine or durable Method scheduler.

### Participant and workload execution

Participant topology is platform-composed rather than hidden inside one composite method. A frozen participant schedule compiles into a parent <code>ResearchProgram(kind=PARTICIPANT)</code>. Each participant role executes as an ordinary child Machine through the same kernel.

~~~text
ParticipantSchedule
    |
    v
parent ResearchProgram
    |
    +--> wave 0 -> child Machine(s)
    |
    +--> wave 1 -> child Machine(s)
    |
    v
parent MachineCut + exact child MachineCut links
~~~

All participant outputs are preserved by role. Measurement may explicitly select a role-specific output; the platform does not guess which participant is the “final” one.

Workload dependency DAGs follow the same rule. They compile into a <code>ResearchProgram(kind=RUN)</code> and execute through one bounded completion-driven frontier. Ready tasks are submitted up to the admitted parallelism; each terminal completion immediately unlocks and refills newly eligible dependents. Deterministic result order and journal-backed Machine state remain authoritative, so there is no fixed-wave head-of-line barrier or process-local scheduler that can diverge from recovery truth.

### Runtime concerns

Runtime concerns such as context projection, communication, model invocation, logical scheduling, synchronization, recovery, intervention and visibility compose into ResearchPrograms or child Machines. They do not receive private journals or component-specific schedulers.

Physical runtime concerns remain below the scientific Machine: processes, services, containers, endpoints, GPU placement, ports and host lifecycle are infrastructure/resource/runtime authorities.

### Runtime Fabric, reuse and performance isolation

Performance optimizations follow the same ownership model rather than creating a second fast-path architecture.

> **Share immutable realization; isolate mutable scientific state.**

Content-addressed model assets/stacks, qualified deployment facts, project runtime layers, environment images, compiled workload/Method execution structures, tokenization results and other immutable closures may be reused when their exact identities match. Assignment, episode, participant, world, browser/session, effect and Machine state remain scoped to their declared scientific lifetime. A warm environment instance is reusable only after its owner proves the required cleanliness state.

Reusable in-process construction uses the platform <code>SingleFlightCache</code> so one exact key has one producer and concurrent followers share the same result or failure. Physical resources remain protected by their durable owner authority, lease generation and fencing; caching never weakens ownership.

Execution scheduling is hierarchical rather than flat:

~~~text
control
  |
  +--> fleet / top-level dispatch
        |
        +--> Research execution orchestration
              |
              +--> Experiment scheduling
                    |
                    +--> Machine / workload execution
                          |
                          +--> model I/O
                          +--> capability / environment I/O
~~~

Domains that may synchronously wait on downstream work use physically independent worker/admission domains so nested execution cannot deadlock by consuming its own child capacity. The same execution tenant identity is propagated through the hierarchy for fair shared-capacity admission without becoming part of scientific identity.

Model serving adds a feedback loop without adding a second batching engine. The qualified deployment records a measured maximum safe concurrency and a preferred operating concurrency. Cold qualification computes its initial probe from model KV-cache geometry, context and the observed request footprint, then searches in both directions rather than serially ramping from one. During execution, the admission window can grow or retreat inside the qualified ceiling. Rate-limit responses cause fast backoff; sustained normalized latency degradation, queued requests, high KV-cache pressure or vLLM preemption can reduce the window before a hard failure. Metrics collection is advisory and fail-open; the qualification certificate remains the hard authority boundary.

Persistent model flows do not own private capacity ledgers in their endpoint pools. Each qualified physical deployment declares its measured model-slot and continuity dimensions in the Universal Resource Authority. A lifetime reservation atomically claims one unit of both dimensions across all logical pools and execution owners; its actual model requests borrow that exact slot through an exclusive child claim rather than consuming a second slot. The dispatch route remains pinned to the claimed deployment, and the Resource Authority rejects releasing the parent claim while any child effect is active. A pool-local flow set is a dispatch/lifecycle projection, never a second source of capacity truth. Unqualified or unproven physical continuation fails closed.

Transient endpoint failure uses one circuit-breaker path rather than a separate recovery client. Healthy replicas remain eligible; a cooled single replica waits for the earliest cooldown boundary and admits one half-open recovery request. A successful request clears consecutive-failure state, while a genuinely unhealthy replica remains fail-closed and is recovered by the same lifecycle authority.

Qualification-derived serving tuning is not confused with scientific model drift. Refresh revalidates the current model/runtime source against the topology recorded by the qualification certificate, while measured scheduler tuning such as the qualified vLLM concurrency setting remains derived runtime evidence. Dynamic host pressure therefore does not silently rewrite model identity or tensor topology. When an exact qualified realization can no longer be placed, stale warm realizations may be retired only under Runtime Fabric consumer fencing; the Compute authority then performs the new placement decision.

Platform-materialized vLLM stacks enable prefix caching and chunked prefill through the typed serving policy. Noetrium owns request admission, tenant fairness, replica choice and runtime lifecycle; vLLM continues to own token-level continuous batching and engine-internal scheduling.

Reusable EnvironmentInstances use the same ownership discipline. Provisioning publishes the reusable catalog generation and its binding atomically, while EnvironmentInstance catalog mutation and resource-lease admission/reconciliation share one host-visible coordination fence. A reconciler cannot quarantine the valid midpoint between `IN_USE` publication and lease creation. Physical convergence that is still pending remains fail-closed for that resource dependency but is retried by the long-lived controller instead of being promoted into a fatal controller failure that cancels unrelated research work.

### Binding and admission

Noetrium separates a scientific declaration from the exact owner-system binding that satisfies it.

Definitions have two canonical forms. A downstream scientific definition may carry its concrete implementation directly in the frozen ResearchProgram; this is the normal path for paper-specific Methods, Benchmarks, Metrics and other project-owned semantics. A platform-resolved infrastructure requirement instead resolves through <code>ResearchDefinitionBindingRegistry</code> to an exact owner identity before execution. The binding records the definition identity, owner system, provider identity and exact binding identity. Missing or drifted owner truth fails closed.

The owner-resolution path applies to model-role selection, participant binding, capabilities, environment instances and external assets that require an infrastructure authority. Physical resource competition, placement, ports, containers, workers and serving concurrency are derived by the platform and are not downstream ResearchDefinitions. The platform does not maintain a catalog of every paper's benchmark or comparison method.

### Execution budgets and replay

Each assignment lifetime receives one durable execution-budget scope. Budget consumption from parent and child Machines is accounted against the same authority rather than separate local counters.

Supported limits include:

| Limit | Enforcement |
| --- | --- |
| steps | consumed at Method node execution |
| wall / working time | checked against the durable scope |
| turns / messages / model calls | reserved before model dispatch |
| tokens | tokenized and reserved before dispatch; provider-observed usage is committed afterward |
| cost | requires a cost-accounting authority; unverified cost fails closed |
| replay level | observational, checkpoint and exact each require the corresponding proof |

A model response that exceeds a hard budget is not silently accepted as a successful scientific step. The usage/effect evidence remains durable while the parent Machine fails according to the execution policy.

### Effects, artifacts and research values

External actions use the canonical capability/effect path:

~~~text
scientific request
    -> capability resolution
    -> effect intent
    -> provider execution
    -> effect receipt / certainty
    -> reconciliation when required
    -> Machine transition references the accepted fact
~~~

Artifact publication follows one canonical content/catalog/reference/retention authority. Run-local directories may be carriers, but they do not own artifact identity.

Research value kinds are also authority-backed. Artifact, Evidence, Checkpoint, Metric, Selection and Data are not interchangeable labels over JSON. If the owner authority for a declared kind is unavailable, admission fails instead of weakening the type.

### Recovery and checkpoints

The Machine Journal is the sole durable execution history. <code>MachineCut</code> identifies an accepted point in that history.

Checkpoints may contain domain payloads, but restore authority does not live in Experimentation, Method or a workload coordinator. Recovery validates the accepted Machine cut and resumes the same program/binding identity. Terminal child cuts can be reused without reinvoking completed handlers.

### Authority model

Noetrium is authority-shaped rather than directory-shaped.

| Layer | Owns | Must not become |
| --- | --- | --- |
| Recursive Unit root | immutable paper/program/method/experiment semantics | a dynamic authority or second carrier |
| Experimentation | Study, Experiment, assignment, measurement semantics | a second execution history |
| ResearchProgram | executable scientific semantics | a private persistence engine |
| MachineExecutor + Machine Journal | accepted transition history | paper-specific scientific meaning |
| Definition/binding authorities | exact owner-system binding facts | late fallback logic |
| Effect authority | external-effect certainty and reconciliation | “retry on exception” heuristics |
| Artifact/data/evidence authorities | canonical content and research facts | run-local shadow stores |
| Resource/runtime authorities | physical admission and lifecycle | paper semantics |
| Composition | wiring exact owners together | durable truth owner |
| Observability | projections and diagnostics | command authority |

### Canonical project path

~~~text
from noetrium import NoetriumUnit, run
        |
        v
recursive content-addressed NoetriumUnit root
        |
        v
run(ROOT) / run(".")
        |
        v
internal research execution projection
        |
        +--> ResearchExecutionPool
        +--> management-plane authorities
        +--> model/runtime/resource services
        |
        v
LocalResearchExecutionAuthorityMaterializer
        |
        +--> exact definition/binding closure
        +--> platform-owned model asset / stack / qualification bootstrap
        +--> Study / Experiment / Trial composition
        +--> participant + workload ResearchPrograms
        +--> Method/runtime child ResearchPrograms
        |
        v
ResearchProgramHost
        |
        v
ProgrammableMachineInterpreter
        |
        v
MachineExecutor -> Machine Journal
~~~

The public API does not ask downstream projects to construct those lower authorities manually.

### Architecture evidence

The live system registry and source are authoritative for the current tree. Source-derived maps are evidence for the exact source cut named in their headers:

~~~text
docs/architecture/DATAFLOW_MAP.md
docs/architecture/CODE_ARCHITECTURE_MAP.md
docs/architecture/CODE_ARCHITECTURE_INDEX.json
~~~

Regenerate them after architecture-changing edits. Git history preserves design rationale; the current source, registry, tests, and maintained v1.0 documentation define the release architecture.


## Platform vs. downstream projects

This repository is an independent upstream platform package. A downstream project should be able to replace or add concrete methods, comparison methods, benchmark suites, task assets, experiment matrices, scientific policies and project-specific integrations without editing platform internals.

```text
noetrium
        │
        ├── install as a dependency, or
        └── fork as a platform baseline
                 │
                 ▼
       downstream research repository
       ├── project-specific MethodPrograms
       ├── benchmark builders and frozen task assets
       ├── experiment composition and scientific policies
       └── project evidence and results
```

| You are changing... | Implement downstream... | Reuse from Noetrium... |
| --- | --- | --- |
| Research or comparison method | concrete MethodProgram, policy, memory semantics, tools and prompts | Universal Method Machine, capability/effect path, lifecycle and evidence |
| Task or benchmark | benchmark builder, frozen task assets, splits, verifier/metric semantics and scientific protocol | generic Benchmark definition, Study/Run identity, artifacts and evidence |
| Project-specific integration | project-owned scientific adapter/handler declared through the public program surface | typed owner contracts, composition, readiness and recovery semantics |
| Multi-agent behavior | topology, node policy, message delivery and coordination rules | participant/workload compilation and run authority |

Use `noetrium` as the only supported downstream project-facing surface. Contract generation, reference components, orchestration, and platform composition remain internal aggregation layers behind that entrypoint. `noetrium_platform` is the internal semantic-plane implementation namespace, not a downstream extension API. The platform must not import a downstream project to decide scientific meaning or deployment policy.



## Design principles

1. <strong>One executable Machine model.</strong> Scientific domains may expose typed authoring vocabularies, but state progression converges on ResearchProgram, ProgrammableMachineInterpreter, MachineExecutor and Machine Journal.
2. <strong>One truth, one authority.</strong> Every durable fact, external-effect certainty, artifact identity, binding, resource lease and accepted transition has one owner.
3. <strong>Composition is wiring, not ownership.</strong> Composition may connect exact owners; it may not grow its own durable truth because a call site is inconvenient.
4. <strong>Programs own paper-variable semantics.</strong> New research should primarily change portfolio/program declarations, policies, handlers, prompts and scientific bindings.
5. <strong>Typed Method authoring is not a second engine.</strong> Method semantics lower to the universal executable IR; Method facades may project typed results but cannot own an independent cursor, scheduler or journal.
6. <strong>Child work uses the same kernel.</strong> Participant roles, runtime concerns, nested methods and other child computations link exact child Machine cuts back to the parent.
7. <strong>Machine Journal is execution truth.</strong> Snapshots and checkpoint payloads accelerate recovery; they do not outrank or replace accepted journal history.
8. <strong>Effects are evidence-bearing.</strong> <code>UNKNOWN</code> remains unknown until the effect owner reconciles it; exceptions do not prove that an irreversible action was not applied.
9. <strong>Bindings are exact and fail closed.</strong> Platform-resolved definitions require an owner-system binding identity before execution; runtime fallback is not scientific equivalence.
10. <strong>Budgets are execution policy, not metadata.</strong> Scientific limits such as steps, time, calls, tokens, cost and replay level are enforced by a durable authority shared across parent and child execution; physical resource admission is a separate platform authority.
11. <strong>Research value kinds are real types.</strong> Artifact, Evidence, Checkpoint, Metric, Selection and Data require their actual owner authorities rather than a generic JSON fallback.
12. <strong>Scientific lifetime is explicit.</strong> Assignment, task, participant, environment and operation lifetimes are frozen and propagated; state sharing and cleanup occur at those boundaries.
13. <strong>Logical scheduling and physical scheduling are different.</strong> Research order, barriers and participant waves may be scientific semantics; CPU/GPU/process/endpoint/container placement is infrastructure.
14. <strong>Observation is not authority.</strong> Logs, traces, metrics, caches, status projections and forensics are rebuildable views.
15. <strong>No compatibility shadow path.</strong> When one stronger implementation replaces another, obsolete execution semantics are deleted rather than kept as a hidden fallback.
16. <strong>Exact scientific and realized identities are part of reproducibility.</strong> Program, revision, binding, model and environment identities are frozen together with the platform-resolved provider, deployment and physical-generation evidence; downstream code does not select those physical realizations.
17. <strong>Downstream owns scientific novelty.</strong> The platform supplies reusable execution, evidence, resource and recovery mechanisms; it does not encode one paper's private claim.
18. <strong>External projects are design inputs, not embedded architectures.</strong> Reuse libraries directly when appropriate, but absorb whole-project ideas into Noetrium's ownership model instead of importing a competing architecture behind adapters.
19. <strong>Architecture invariants are executable.</strong> Source-derived maps, tests and gates must agree with the same source cut.
20. <strong>Performance cannot weaken semantics.</strong> Concurrency, pooling, batching and caching must preserve binding identity, effect certainty, budget enforcement, lifetime and evidence.


## Extending the platform

Before implementing a new subsystem, determine whether the requirement is actually new. Start with the system registry, generated code/dataflow maps and the current owner APIs. Then perform an external-capability audit when mature implementations exist in projects such as Inspect AI, OpenHands, Harbor, tau-bench or other relevant systems. The goal is to absorb stronger design, not to embed another framework as a second architecture.

Use this decision order:

1. If the behavior varies by paper, express it as ResearchProgram/Method configuration, policy, handler or sub-IR.
2. If an existing Noetrium owner already has the semantic responsibility, add the smallest typed provider/port beneath that owner.
3. If several papers repeatedly need the same paper-independent mechanism, lift exactly one reusable implementation into the correct Platform owner.
4. Add a new authority only when the state has genuinely independent canonical truth that cannot belong to an existing owner.
5. Do not add a new Runner/Manager/Controller simply because a call site is inconvenient.

The common internal system shape is:

```text
<system>/
├── api/          contracts, identities and owner-facing ports
├── runtime/      canonical lifecycle/execution semantics
├── providers/    replaceable provider mechanics beneath the owner
└── composition/  adjacent-layer binding only
```

A provider may be replaceable; the authority is not duplicated. Whole external projects should not be nested behind generic adapter layers that preserve their competing ownership model. Third-party libraries can be direct dependencies when their abstraction is already the desired one.

Any extension that touches effects, models, environments, resources or durable state must exercise failure, uncertainty, restart and stale-generation cases—not only the happy path.
