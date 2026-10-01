# Noetrium Research OS



<!-- readme-nav:start -->
<p align="center">
  <strong>English</strong> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (Brasil)</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.ru.md">Русский</a>
</p>
<!-- readme-nav:end -->



<!-- readme-locale:en -->

<!-- readme-source-sha256:e4ac697d165fedf70f3d0e02e15570ece04e987707d79ce090c61e27d72a944f -->

<p align="center">
  <strong>Research infrastructure for attributable, recoverable, evidence-preserving AI-agent experiments.</strong><br>
  Compose research programs at the top. Keep one authority for every truth underneath.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="examples/README.md">Example</a> ·
  <a href="docs/architecture/PLATFORM_ARCHITECTURE.md">Architecture</a> ·
  <a href="docs/INDEX.md">Docs</a> ·
  <a href="#verification">Verification</a>
</p>

<p align="center">
  <a href="https://www.python.org/"><img alt="Python >=3.11" src="https://img.shields.io/badge/Python-%3E%3D3.11-3776AB?logo=python&logoColor=white"></a>
  <a href="pyproject.toml"><img alt="Version 0.44.0" src="https://img.shields.io/badge/version-0.44.0-blue"></a>
  <a href="docs/architecture/PLATFORM_ARCHITECTURE.md"><img alt="Contract-driven architecture" src="https://img.shields.io/badge/architecture-contract--driven-6f42c1"></a>
  <a href="LICENSE"><img alt="Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-green"></a>
</p>

<!-- readme-section:overview -->

## Overview

Noetrium is a <strong>Research Operating System for AI-agent research</strong>. It is not another agent loop, workflow DSL, benchmark harness, or provider SDK. Its job is to make large research programs composable while keeping execution truth, scientific identity, effects, artifacts, resources, and evidence under explicit owners.

The end-state model is intentionally simple:

> <strong>Research OS composes research. Research Programs describe scientific semantics. MachineExecutor + Machine Journal accept scientific execution truth. Each domain system owns one authority. Platform kernel primitives are shared once. Composition wires systems together but never creates a second truth.</strong>

That model is designed for the point where a research repository stops being one script and becomes a matrix of papers, methods, benchmarks, environments, models, trials, resources, interruptions, retries, revisions, and publication evidence.

The normal project execution path is intentionally small:

~~~python
from noetrium import api

with api.open_project(".") as research:
    report = research.run()
~~~

`open_project()` loads the frozen project portfolio and revision immediately, but materializes the physical execution plane lazily on the first execution/control action. The same project object exposes run, inspect, pause, drain, interrupt, resume, retry, cancel, checkpoint, reconcile, migrate, commit, diff, branch and tag operations. Provider/resource mechanics remain below this surface.

Noetrium separates five concerns that are often collapsed into one framework:

| Concern | Noetrium boundary |
| --- | --- |
| Research authoring | <code>noetrium.api</code>, Research OS, portfolios, graphs, studies, programs and explicit bindings |
| Scientific execution | Program interpreters propose work; <code>MachineExecutor</code> accepts transitions into the Machine Journal |
| Domain truth | Experimentation, resource, artifact, data, model, participant, environment and other authorities own their own facts |
| Reusable mechanisms | canonical identity, content addressing, durability, CAS/fencing, leases, checkpoints and other platform primitives |
| Observation | telemetry, diagnostics, projections and forensics observe authority; they do not replace it |

The dependency direction is one-way:

<strong>research intent -> explicit composition -> frozen identity -> admitted execution -> authoritative transition/effect/evidence -> recovery, replay, inspection and verification.</strong>

Noetrium owns the reusable research substrate: canonical identities, revision/binding truth, durable machine transitions, recovery boundaries, resource admission, effect certainty, artifacts, evidence, provenance, observability and governance. Downstream projects own the scientific novelty and concrete paper content: MethodPrograms, prompts, memory semantics, benchmark builders/assets, task policies, experiment hypotheses, statistical interpretation and claims. Noetrium does not require a new upstream benchmark or method implementation when a new paper is added.

A downstream paper should normally change only its top-level ResearchPortfolio/ResearchProgram declaration, concrete MethodPrograms, benchmark builders/assets, Study/Experiment specification, prompts, policies and paper-owned handlers — <strong>not Noetrium internals</strong>. Lower execution, capability, runtime, resource and infrastructure interfaces are consumed only by their adjacent Noetrium layer rather than by downstream research code.

<!-- readme-section:why -->

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

<!-- readme-section:capabilities -->

## Core capabilities

- <strong>Four-root downstream API</strong> — <code>noetrium.api</code> exposes only <code>ResearchPortfolioBuilder</code>, <code>ResearchPortfolio</code>, <code>ResearchOS</code> and <code>open_project</code>. Program/Method/Memory DSL types are reached through those roots; provider, resource, Docker and lifecycle interfaces remain internal owner boundaries.
- <strong>Research OS composition</strong> — one portfolio can describe multiple research programs, studies, experiments, concrete downstream MethodPrograms, concrete downstream Benchmarks, analyses, dependencies, revisions and control operations without adding paper-specific implementations to the platform.
- <strong>One executable program model</strong> — Method (including memory semantics), Runtime, Participant, Environment, Evaluation, Optimization, Experiment and Run semantics converge on <code>ResearchProgram</code> and the same Machine execution kernel.
- <strong>Durable scientific execution</strong> — <code>ProgrammableMachineInterpreter</code> proposes transitions; <code>MachineExecutor</code> commits accepted transitions to the Machine Journal. The journal is the execution truth.
- <strong>Typed Method semantics without a second runtime</strong> — Method-specific authoring can use the internal typed Method facade, which lowers deterministically into <code>ResearchProgram(kind=METHOD)</code>. Method result facades do not own a separate cursor, scheduler, checkpoint engine or transition history.
- <strong>Nested research Machines</strong> — child work runs through the same kernel and is linked to its parent by exact <code>ChildMachineLink</code> / Machine-cut identity rather than hidden callback stacks.
- <strong>Participant and workload compilation</strong> — participant schedules and workload dependency DAGs compile into ordinary ResearchPrograms. Workloads execute through a bounded completion-driven dependency frontier: each completion can immediately unlock and refill eligible dependents while durable Machine state remains scheduling truth.
- <strong>Exact definition binding</strong> — downstream-owned scientific definitions such as Methods, Benchmarks, Metrics and project protocols may carry their concrete implementation directly in the frozen ResearchProgram. Infrastructure requirements such as Model, Environment, Resource and external data/assets resolve through their owning authorities and are frozen before execution. Unknown, ambiguous or drifted bindings fail closed.
- <strong>Durable execution budgets</strong> — steps, wall/working time, turns, messages, model calls, tokens, cost, resource-policy identity and replay level share one crash-durable execution-budget authority.
- <strong>Replay-aware admission</strong> — observational, checkpoint and exact replay claims require different proofs. Exact replay is never inferred from a seed or from a checkpoint alone.
- <strong>Explicit effect certainty</strong> — external actions are mediated through effect intents, receipts and reconciliation. <code>UNKNOWN</code> remains unknown; transport success or failure is not silently converted into scientific certainty.
- <strong>Canonical artifact and evidence ownership</strong> — blobs, artifact catalog entries, references, retention, evidence and provenance use their owning authorities instead of run-local shadow stores.
- <strong>Typed research values</strong> — Artifact, Evidence, Checkpoint, Metric, Selection and Data values cannot be relabeled generic JSON. A value kind is accepted only when its owner authority is available.
- <strong>One recovery truth</strong> — durable recovery is rooted in the Machine Journal and <code>MachineCut</code>. Checkpoint payloads and snapshots are acceleration artifacts tied to that cut, not independent restore authorities.
- <strong>Resource and runtime lifecycle</strong> — admission, shared-host pressure, compute/GPU allocation, endpoints, processes, services, Docker generations, leases, heartbeats and abandoned-owner recovery remain in the physical owner systems below scientific Programs.
- <strong>Content-addressed reuse and single-flight construction</strong> — immutable execution structures and runtime realizations are keyed by exact identity and reused instead of rebuilt. In-process workload/participant/task/model-endpoint/tokenization structures use one-producer single-flight construction; project runtime layers, environment images and other physical realizations reuse content-addressed owner-managed artifacts when their exact identities match.
- <strong>Hierarchical fair scheduling</strong> — execution carries a non-scientific tenant identity through Research OS, Experiment, Workload, child-Machine, environment-capability and model-request paths. Admission prefers tenants and groups with lower active share before grant history, preventing high fan-out from monopolizing shared capacity while remaining work-conserving for a single active tenant.
- <strong>Adaptive shared model serving</strong> — qualified deployments separate the measured safe concurrency ceiling from the preferred operating point. Qualification starts near a computed concurrency derived from model KV geometry and observed request footprint, then searches upward or downward. Runtime admission adapts using normalized service latency, rate-limit responses and vLLM pressure signals such as running/waiting requests, KV-cache usage and preemption.
- <strong>Architecture governance</strong> — generated topology maps, public-contract gates, no-compatibility/no-degradation checks and authority rules reject shadow runtimes and ownership leaks.

### Scientific measurements, derived metrics and analysis

The four-root API carries the full scientific measurement path without exposing Study, MetricEngine or Workbench internals to downstream code. A downstream program declares semantics through the ResearchPortfolioBuilder object reached from noetrium.api:

~~~python
program.metric(
    "task-success",
    value_kind="boolean",
    source_path="diagnostics.success",
    reducer="last",
)

program.metric(
    "latency-mean",
    aggregation="mean",
    record_types=("llm.usage",),
    value_path="latency_ms",
    group_by=("model",),
    unit="ms",
)

program.analysis(
    "latency-comparison",
    depends_on=("derive-latency",),
    value="value",
    group_by=("model",),
    comparison_group="model",
    baseline="control",
    candidate="candidate",
    pair_by="seed",
    inference="paired_compare",
    multiple_comparison="holm",
)
~~~

Capture is typed rather than scalar-only. Supported measurement values are scalar, boolean, categorical, structured, sequence, distribution, matrix, text judgement and artifact-backed content reference. Study measurement projection owns capture and provenance; nontrivial aggregation is deliberately kept out of the capture reducer.

Derived raw-record metrics use the single Experimentation metric engine and support count, sum, mean, min, max, standard deviation, p50, p95, first, last and distinct count, with record/schema filters, predicates, grouping and explicit missing-value policy. Paper-specific formulas remain downstream implementations instead of becoming platform special cases.

Declarative analyses lower through Composition into the standard Research Workbench. Built-in inference includes normal-mean inference, bootstrap mean, group comparison, paired comparison, permutation comparison and one-to-many comparison with Bonferroni, Holm, Benjamini-Hochberg or Benjamini-Yekutieli correction. Every declarative result is tied to an immutable MeasurementCut, frozen AnalysisDefinition, input cut digest, implementation/configuration digest and AnalysisResult digest, so post-hoc analysis can change without silently changing the underlying experiment evidence.

The layer boundary remains strict: Product freezes JSON scientific intent; Experimentation owns capture and derived metrics; Workbench owns statistical inference; Composition performs only the adjacent translation between them. Downstream projects do not import those lower types.

<!-- noetrium-interface-catalog:start -->
### Public interface catalog

Noetrium exposes one high-level Research OS API. Registered lower systems remain internal composition authorities and are listed here only as architecture metadata.

- 31 registered system surfaces; 1 public API module; 4 public root symbols.
- Full machine-readable catalog: noetrium/contracts/downstream_capability_catalog.json
- Full human-readable catalog: docs/architecture/DOWNSTREAM_CAPABILITY_CATALOG.md
- Import rule: downstream code uses only noetrium.api; lower system facades are internal registry material.

| Capability domain | Registered surfaces |
| --- | ---: |
| artifact | 1 |
| data | 3 |
| environment | 6 |
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
| research_os | 1 |
| resource | 2 |
| runtime | 1 |
| scope | 1 |

Author and control research through the same top-level API:

    from noetrium import api
    portfolio = api.ResearchPortfolioBuilder("paper")
    program = portfolio.program("paper")
    research_os = api.open_project(".")

After changing a registry descriptor or public API export, run python scripts/update_generated_docs.py; CI fails on generated-surface or README drift.
<!-- noetrium-interface-catalog:end -->

The catalog is an API map, not an authority registry that downstream code is expected to edit. A system surface declares what it owns, what it must not own, what it requires, what it provides, and which public facade exposes it. Internal implementation packages may be reorganized without turning implementation paths into public contracts.

<!-- readme-section:architecture -->

## Architecture

Noetrium is organized around one rule: <strong>scientific semantics may be modular, but scientific execution has one acceptance path.</strong>

~~~text
Research intent
    |
    v
ResearchPortfolio / ResearchOS
    |
    v
Study / Experiment / bindings / policies
    |
    v
ResearchProgram
    |
    v
ProgrammableMachineInterpreter
    |
    v
MachineExecutor
    |
    v
Machine Journal
    |
    +--> accepted MachineCut
    +--> child Machine links
    +--> effect / evidence / artifact references
~~~

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
        +--> Research OS orchestration
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

Transient endpoint failure uses one circuit-breaker path rather than a separate recovery client. Healthy replicas remain eligible; a cooled single replica waits for the earliest cooldown boundary and admits one half-open recovery request. A successful request clears consecutive-failure state, while a genuinely unhealthy replica remains fail-closed and is recovered by the same lifecycle authority.

Qualification-derived serving tuning is not confused with scientific model drift. Refresh revalidates the current model/runtime source against the topology recorded by the qualification certificate, while measured scheduler tuning such as the qualified vLLM concurrency setting remains derived runtime evidence. Dynamic host pressure therefore does not silently rewrite model identity or tensor topology. When an exact qualified realization can no longer be placed, stale warm realizations may be retired only under Runtime Fabric consumer fencing; the Compute authority then performs the new placement decision.

Platform-materialized vLLM stacks enable prefix caching and chunked prefill through the typed serving policy. Noetrium owns request admission, tenant fairness, replica choice and runtime lifecycle; vLLM continues to own token-level continuous batching and engine-internal scheduling.

Reusable EnvironmentInstances use the same ownership discipline. Provisioning publishes the reusable catalog generation and its binding atomically, while EnvironmentInstance catalog mutation and resource-lease admission/reconciliation share one host-visible coordination fence. A reconciler cannot quarantine the valid midpoint between `IN_USE` publication and lease creation. Physical convergence that is still pending remains fail-closed for that resource dependency but is retried by the long-lived controller instead of being promoted into a fatal controller failure that cancels unrelated research work.

### Binding and admission

Noetrium separates a scientific declaration from the exact owner-system binding that satisfies it.

Definitions have two canonical forms. A downstream scientific definition may carry its concrete implementation directly in the frozen ResearchProgram; this is the normal path for paper-specific Methods, Benchmarks, Metrics and other project-owned semantics. A platform-resolved infrastructure requirement instead resolves through <code>ResearchDefinitionBindingRegistry</code> to an exact owner identity before execution. The binding records the definition identity, owner system, provider identity and exact binding identity. Missing or drifted owner truth fails closed.

The owner-resolution path applies to model-role selection, participant binding, capabilities, environment instances, resource policy and external assets that require an infrastructure authority. The platform does not maintain a catalog of every paper's benchmark or comparison method.

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
| resource policy | declared digest must match the active execution-pool policy |
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
| Research OS | portfolio/revision/graph authoring and control | a duplicate domain authority |
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
from noetrium import api
        |
        v
api.open_project(".")
        |
        v
LoadedProjectResearchOS
        |
        v
ManagedResearchRuntime
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

Regenerate them after architecture-changing edits. Historical design documents remain useful for rationale but do not override the current source, registry, or architecture gates.

<!-- readme-section:downstream -->

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

Use `noetrium.api` as the only supported downstream project-facing surface. Contract generation, reference components, orchestration, and platform composition remain internal aggregation layers behind that entrypoint. `noetrium_platform` is the internal semantic-plane implementation namespace, not a downstream extension API. The platform must not import a downstream project to decide scientific meaning or deployment policy.

<!-- readme-section:quick-start -->

<a id="quick-start"></a>

## Quick start: author, validate and run

### 1. Install Noetrium for platform development

~~~bash
git clone https://github.com/Xalzeroph/noetrium.git
cd noetrium
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
~~~

Run the core checks:

~~~bash
python -m pytest -q
python scripts/architecture_gate.py
python scripts/machine_architecture_gate.py
python scripts/public_contract_audit.py
python scripts/no_degradation_audit.py
~~~

A historical green result proves only the source cut it tested.

### 2. Create a downstream research project

~~~bash
noetrium project create my-paper ./my-paper
cd ./my-paper
~~~

The generated project has one user-owned scientific entrypoint:

~~~text
src/<package>/core.py::build_research()
~~~

It returns a <code>noetrium.api.ResearchPortfolio</code>. Downstream code starts from the public roots returned by <code>noetrium.api</code>; it does not import internal Machine, resource, model, environment or composition packages.

A minimal project core is:

~~~python
from noetrium import api


def _bootstrap():
    return None


def build_research() -> api.ResearchPortfolio:
    portfolio = api.ResearchPortfolioBuilder("my-paper")
    program = portfolio.program("my-paper")
    program.custom_definition("bootstrap", implementation=_bootstrap)
    program.custom_node("root", definitions=("bootstrap",))
    return portfolio.freeze()
~~~

The example is intentionally semantics-neutral. Real projects add their Study/Experiment, method, participant, benchmark, model/environment requirements, measurement and evidence semantics through objects returned by the public authoring surface.

Concrete paper methods and benchmarks stay downstream. The same program can directly freeze project-owned implementations without adding them to Noetrium:

~~~python
from noetrium import api

def build_benchmark():
    return {
        "benchmark_id": "paper-benchmark",
        "tasks": ({"task_id": "t1", "input": {"goal": "..."}, "expected": {}},),
    }

def configure_reference_method(method):
    ...
    return method
def build_research() -> api.ResearchPortfolio:
    portfolio = api.ResearchPortfolioBuilder("paper")
    program = portfolio.program("paper")
    program.benchmark("benchmark.paper", implementation=build_benchmark)
    program.method(
        "method.reference",
        configure_reference_method,
        method_id="reference",
        entrypoint="recall",
    )
    return portfolio.freeze()
~~~

Noetrium executes both through generic platform machinery. It does not need a Benchmark-specific engine, a Baseline engine, or a new upstream code path for each paper.

### 3. Understand where semantics belong

| Concern | Canonical home |
| --- | --- |
| multi-program / multi-study / multi-experiment composition | ResearchPortfolio / ResearchOS |
| Study, Experiment, assignment and measurement semantics | Experimentation declarations |
| executable scientific control flow | ResearchProgram |
| method/agent semantics | Method authoring lowered to ResearchProgram |
| participant topology and schedule | participant declarations compiled to parent/child ResearchPrograms |
| workload dependencies | workload DAG compiled to a Run ResearchProgram |
| context, memory, communication, synchronization, recovery, visibility | Method/Runtime program components |
| model invocation policy | scientific Program/Method; deployment/serving remains Model authority |
| environment interaction policy | scientific Program/Method; instances/sessions remain Environment authority |
| external tools/actions | capability/effect authority |
| budget/replay requirements | Trial/Study policy enforced by ExecutionBudgetAuthority |
| concrete datasets/benchmarks/metrics used by a paper | downstream definitions/implementations frozen in the ResearchProgram |
| model/environment/resource requirements and external assets | exact owner-system definition bindings |
| artifacts/evidence/data | their canonical owner authorities |
| CPU/GPU/process/port/container placement | resource/runtime infrastructure |

The test is simple: if changing a concern changes the research algorithm, it belongs in scientific authoring. If it changes how physical resources or providers implement an already-declared requirement, it belongs below the Program in the owning platform system.

### 4. Sync and validate a generated project

When the platform-owned scaffold changes:

~~~bash
noetrium project sync --project .
~~~

Then run:

~~~bash
noetrium project doctor --project .
noetrium project test --project .
~~~

Sync preserves the user-owned scientific core and regenerates only platform-owned shell/test material. Doctor validates the installed platform identity, generated shell, manifest, public import boundary and frozen portfolio.

If a paper needs an additional Python library, declare it normally in the downstream project's `pyproject.toml`; do not install it manually on the host and do not add it to the shared Noetrium base image. The Docker-first launcher resolves the dependency closure against the exact Noetrium control-plane base, writes a digest-bound lock, materializes a content-addressed project runtime layer, and reuses the resulting image by runtime identity. Projects with no additional dependencies stay on the base image. A dependency that conflicts with the platform-owned Python environment fails closed instead of silently replacing platform packages.

~~~toml
[project]
dependencies = [
  "noetrium==0.44.0",
  "networkx==3.5",
]
~~~

The generated `project.dependencies.lock.json` binds the exact Python version and immutable base-image identity. The runtime image identity additionally covers the lock and the canonical project-runtime Docker recipe, so changing the project dependency declaration, base image, lock, or recipe invalidates the cached layer.

### 5. Run and control the project

Python:

~~~python
from noetrium import api

with api.open_project(".") as research:
    report = research.run()
    snapshot = research.inspect()
~~~

Installed CLI:

~~~bash
noetrium run        --project .
noetrium inspect    --project .
noetrium pause      --project .
noetrium drain      --project .
noetrium interrupt  --project .
noetrium resume     --project .
noetrium retry      --project .
noetrium cancel     --project .
noetrium checkpoint --project .
noetrium reconcile  --project .
noetrium migrate    --project .
~~~

On a Docker-first Linux server, use the repository launcher. It performs the host/Docker checks, starts the containerized control plane, projects host identity and the Docker daemon into that control plane, and delegates to the same Research OS lifecycle:

~~~bash
./deploy/noetrium run --project .
~~~

Node-scoped control supplies the program and node identity:

~~~bash
noetrium pause --project . --program <program-id> --node <node-id>
noetrium retry --project . --program <program-id> --node <node-id>
~~~

Node-scoped retry reopens that failed graph node against the durable Research OS revision and recovery state. It does not require deleting checkpoints, clearing journals or rebuilding an unrelated project graph.

Local project execution state lives under:

~~~text
<project>/.noetrium/research-os/
~~~

<code>open_project()</code> loads the frozen project portfolio/revision immediately and materializes the physical execution plane lazily when execution or control first requires it.

### 6. What happens when you call run()

At a high level:

~~~text
portfolio / revision
    -> compile research graph
    -> materialize exact owner prerequisites
    -> resolve content-addressed realizations / single-flight reusable closures
    -> resolve model assets and immutable runtime stack when required
    -> admit compute / endpoint / container resources
    -> bootstrap and qualify the current model runtime when no current proof exists
    -> resolve exact owner bindings
    -> freeze Study / Trial policy
    -> admit budget / replay / resources
    -> compile workload / participant / Method semantics to ResearchPrograms
    -> reuse exact compiled execution structures when identities match
    -> execute through hierarchical fair admission, completion-driven frontiers and the shared Machine kernel
    -> publish effects / artifacts / evidence through owner authorities
    -> aggregate measurements
    -> return a Research OS report
~~~

There is no paper-local runner, hidden participant scheduler, independent workload checkpoint engine or fallback provider path in the canonical execution model.

### 7. Failure and restart behavior

Noetrium distinguishes execution failure from uncertain external effects.

- A failed pure computation may be retried according to policy.
- An external action with uncertain outcome remains <code>UNKNOWN</code> until its effect authority reconciles it.
- Completed child Machines are identified by durable cuts and can be reused after parent recovery.
- Machine recovery is tied to the exact program/binding identity.
- Resource owners use leases/generations/fencing to prevent a stale process or container from silently reclaiming ownership.
- Background resource reconciliation treats unresolved physical convergence as a retryable control-plane state while preserving dependency fences; it does not cancel scientific work merely because one cleanup cycle is incomplete.
- Method failure projection retains the outer operation identity/digest while surfacing the deepest recorded underlying cause when available, so a platform cancellation or provider error is not reduced to an opaque generic failure.
- A replay claim is admitted only at the level the bound authorities can prove.

### 8. Platform execution configuration

Project execution has a deliberately small operator-facing configuration surface. Scientific requirements belong in the frozen research definition; provider/resource mechanics are materialized by the platform owner systems.

A minimal execution config is:

~~~json
{
  "schema": "noetrium.project-execution-config.v1",
  "start_background_controllers": true
}
~~~

Use it with:

~~~bash
noetrium run --project . --config ./execution.json
~~~

or:

~~~python
from noetrium import api

with api.open_project(".", config_path="./execution.json") as research:
    report = research.run()
~~~

Unknown or ambiguous owner truth fails closed rather than selecting a weaker provider implicitly.

<!-- readme-section:containers -->

## Docker-first server deployment and large-scale execution

For Linux server execution, the intended host contract is Docker plus Compose. Host Python is not required for the canonical deployment path; control-plane Python executes inside the bootstrap container.

### 1. Host prerequisites

The ordinary deployment user must be able to run:

~~~bash
docker info
docker compose version
~~~

The canonical launcher never invokes sudo.

GPU hosts must already have a working NVIDIA driver and Docker GPU runtime. Noetrium does not mutate the host driver.

<code>deploy/install_workspace_docker_engine.sh</code> can install Docker binaries into the workspace, but starting that bundled rootful daemon requires host privileges. For an ordinary-user deployment, prefer the rootless manager described below. Rootless Docker still requires <code>dockerd-rootless.sh</code>, RootlessKit, slirp4netns, setuid <code>newuidmap/newgidmap</code>, subordinate UID/GID ranges and enabled unprivileged user namespaces. Noetrium checks these prerequisites and fails closed; it never emulates the privileged UID/GID mapping helpers in user space.

On a shared server, inspect current GPU and host load before launch. Existing foreign workloads are external ownership facts and must not be killed or preempted merely to make room for Noetrium.

### 2. Put mutable deployment state on the data disk

Redirect runtime state away from a small system partition:

~~~bash
export NOETRIUM_DEPLOYMENT_STATE_ROOT=/data/noetrium-runtime
mkdir -p "$NOETRIUM_DEPLOYMENT_STATE_ROOT"
~~~

The launcher uses:

~~~text
$NOETRIUM_DEPLOYMENT_STATE_ROOT/
├── environment-images/
└── reproduction-fleet/
~~~

Large model caches, world state and scientific outputs should likewise use an explicitly selected data volume.

This variable does **not** relocate the Docker daemon's own image/layer store. Before building on a server with a small system disk, inspect the active daemon storage:

~~~bash
docker info --format '{{.DockerRootDir}}'
~~~

If that path is on a nearly-full system partition, fix the daemon/rootless-Docker data root first. Otherwise image pulls and builds can still consume the system disk even though Noetrium state is on a data volume.

Noetrium can own a user-level rootless Docker daemon entirely on the selected data volume:

~~~bash
export NOETRIUM_DEPLOYMENT_STATE_ROOT=/data/noetrium-runtime
export NOETRIUM_DOCKER_DATA_ROOT=/data/noetrium-runtime/docker
export NOETRIUM_DOCKER_RUNTIME_ROOT=/data/noetrium-runtime/docker-runtime

./deploy/noetrium docker doctor
./deploy/noetrium docker start
eval "$(./deploy/noetrium docker env)"
./deploy/noetrium docker status
./deploy/noetrium doctor
~~~

When <code>NOETRIUM_DOCKER_DATA_ROOT</code> is set, normal deployment doctor/build/run paths verify that the active daemon's actual <code>DockerRootDir</code> equals that canonical path. A variable pointing at a data disk is not accepted as proof that Docker really moved. Stop only the exact user-owned daemon with <code>./deploy/noetrium docker stop</code>.

If <code>docker doctor</code> reports a missing privileged host prerequisite such as <code>newuidmap</code>, an administrator must install or enable that prerequisite once. Do not fall back to a nearly-full system DockerRootDir merely to continue a run.

The current evidence-bound image builder also requires real Git source metadata. It derives the source identity with Git and refuses a dirty checkout before building the qualified wheel/image. A source-only archive with no .git metadata is not currently sufficient for the formal image-build path. When transporting source without GitHub, preserve the repository metadata by copying the complete checkout or by using a verified Git bundle/local transport. Do not invent a source SHA or bypass the clean-source check.

Offline/local Git transport must also preserve tracked executable modes. The canonical
Linux launcher and its shell entrypoints are committed as executable files, so a
verified Git bundle/clone reproduces both source identity and executable bits. Do not
replace the formal server source cut with a filesystem copy that silently strips
Git mode metadata.

### 3. Verify Docker and environment-profile authority

From the repository root:

~~~bash
./deploy/noetrium doctor
./deploy/noetrium env list
./deploy/noetrium env show minecraft
./deploy/noetrium env validate
~~~

The profile authority is <code>deploy/environments/catalog.json</code>. Current reusable categories are text_world, web, minecraft, gui, embodied and software. The central builder does not hard-code that set.
### 4. Build or reuse exact environment images

Build every active default profile:

~~~bash
./deploy/noetrium build
~~~

Or one profile:

~~~bash
./deploy/noetrium env build --profiles minecraft
~~~

The build path is:

~~~text
exact clean source cut
  -> qualified Noetrium distribution/wheel
  -> evidence-bound base image
  -> exact upstream runtime image identities
  -> environment profile image
  -> image-local doctor
  -> provenance/build receipt
~~~

The base image is built from one formally prepared evidence-bound wheel, not from a mutable source-tree copy. Exact source, wheel and runtime identities are recorded and verified.

Profile revisions are immutable. A draining revision requires explicit recovery intent and a retired revision requires explicit historical-recovery intent:

~~~bash
./deploy/noetrium env build --profiles <profile> --allow-draining
./deploy/noetrium env build --profiles <profile> --allow-retired
~~~

### 5. Environment isolation

The invariant is:

> **Share immutable content; isolate all mutable execution state.**

Shared examples include image layers, content-addressed assets, dependency caches and immutable runtime artifacts.

Private per-execution state includes workspace, tmp, runtime state, secrets, process/network namespace, ports, browser profile, world state and application state.

A warm instance returns to a pool only after an explicit cleanliness proof. Otherwise it is destroyed.

The Minecraft profile provides Java 21, Node 22 and the lockfile-pinned Mineflayer runtime. Benchmark servers, worlds, tasks, methods, models and checkpoints stay downstream.

### 6. Plan the repository fleet before execution

Static planning starts no work:

~~~bash
./deploy/noetrium plan
~~~

The repository-fleet planner discovers the platform's reference/validation reproductions, compiles each ResearchProgram and builds one top-level ResearchPortfolio/ResearchGraph without starting work. It reports compile failures, unresolved external-asset requirements, reproduction-closure gaps, materialization readiness, Study requirements and graph identities. Concrete benchmark/method semantics for an independent downstream paper remain in that downstream repository.

Having a directory below <code>research/reproductions/</code> does not by itself make a paper runnable. Execution requires exact closure.

### 7. Materialize owner-authority prerequisites

Emit the machine-readable prerequisite manifest:

~~~bash
./deploy/noetrium requirements
~~~

The canonical repository path uses Noetrium's built-in owner-authority materialization. `preflight` and `run` derive binding requirements from frozen Programs/Studies and ask the actual Model, Environment, Participant, Resource, Artifact/Benchmark and Trial owners to close them. The materializer may compose authority; it may not invent authority.

For Model requirements, the current path is platform-owned end to end: resolve or materialize the declared model asset, freeze its content identity, resolve an engine OCI image and freeze its immutable image identity, materialize one `ModelStackSpec`, obtain compute/endpoint/container admission, start the replica through the shared service/container lifecycle, perform measured qualification plus requirement-aware runtime canaries, and publish the single current qualified-model closure. Downstream code does not select Docker images, GPU ids, ports, service processes or qualification files.

Machine-local or external facts that cannot be inferred uniquely remain explicit repository-operator inputs, for example an externally stored dataset/benchmark asset cut or other external materialization. This operator input closes an external asset requirement; it does not move the benchmark's scientific semantics into Noetrium:

~~~bash
export NOETRIUM_CONTROL_INPUT_ROOT=/data/noetrium-authority-assets
./deploy/noetrium plan --authority-audit \
  --authority-input benchmark.gsm8k.test_jsonl=/data/noetrium-authority-assets/gsm8k/test.jsonl
~~~

When an authority input refers to host data that the Docker control plane must read, `NOETRIUM_CONTROL_INPUT_ROOT` is the allowed read-only host root. Benchmark/materialization code must verify source revision, content digest and task-cut identity; a path string is not authority proof. Stateful audit/runtime output remains under `$NOETRIUM_DEPLOYMENT_STATE_ROOT`, never inside a read-only source checkout.

The automatic materializer never silently substitutes a model, environment, GPU, endpoint, verifier or external asset. A lane whose required owner authority cannot prove exact closure remains `BLOCKED`; unrelated authority-closed lanes may still run. Downstream-owned Method and Benchmark implementations are already part of the frozen scientific definition and are not selected from an upstream paper catalog.

The launcher still exposes `NOETRIUM_FLEET_AUTHORITY_MATERIALIZER=module:factory` as an advanced repository-operator hook in this source cut. It is **not** the canonical downstream project API and must not encode paper semantics or create shadow Model, Environment, Resource, Execution, Effect or Journal authorities. New platform composition should prefer the built-in owner path.

### 8. Preflight the complete execution closure

~~~bash
./deploy/noetrium preflight
~~~

Preflight resolves exact authority closure, filters the authority-closed runnable subgraph, and performs admission without creating an execution cut or starting tasks. Source/materialization blockers and owner-authority gaps are reported per lane and do not abort unrelated lanes.

If no lane currently closes, preflight returns a structured <code>no-runnable-lanes</code> report instead of asking the operator to wire providers manually. Do not bypass blocked lanes with a paper-local runner.

### 9. Execute

~~~bash
./deploy/noetrium run
~~~

Unless <code>NOETRIUM_SKIP_ENVIRONMENT_BUILD=1</code> is intentionally set, the launcher builds/reuses active environment profiles first.

The real execution path is:

~~~text
./deploy/noetrium run
  -> host Docker/Compose doctor
  -> containerized control-plane bootstrap
  -> exact environment image build/reuse
  -> reproduction discovery
  -> ResearchPortfolio + ResearchGraph compile
  -> authority materialization
  -> whole-graph admission
  -> ManagedResearchRuntime
  -> ResearchGraphScheduler
  -> experiment/model/environment/provider execution
  -> Machine / Operation / Effect / Evidence authorities
  -> durable result/evidence closure
~~~

### 10. Large-scale scheduling and shared-host behavior

ResearchGraph scheduling is dependency-aware:

~~~text
pending
  -> dependency frontier
  -> ready set
  -> concurrent submission
  -> terminal result
  -> downstream unlock or BLOCKED propagation
~~~

Repository execution is also lane-fault-isolated before graph admission. Benchmark
or reproduction-closure failure in one paper does not abort unrelated papers.
Noetrium independently materializes every exact lane, compiles the closed subset
into the runnable ResearchPortfolio, and retains content-addressed BLOCKED records
for the rest. A lane with an externally selected benchmark split must match that
split exactly; a Study that owns its split internally may materialize its own
canonical split without inventing an external selection.

Bound reproduction ResearchProgram identities are content-addressed by the exact
execution-binding digest rather than by embedding free-form binding labels. This
keeps program IDs valid, deterministic and collision-resistant across arbitrary
paper-owned binding names.

Durable scheduling adds attempt identities, leases, retry timing, per-node control and reconciliation-required states.

ResearchExecutionPool separates control, fleet/top-level dispatch, orchestration, experiment, Machine, model-I/O and capability-I/O concerns. Parent domains that synchronously wait on child work do not share the same blocking worker pool, preventing nested admission deadlock. Workload domains share one CPU worker provider and one residual-capacity reservation ledger so separate gates cannot spend the same RAM/PID/FD/storage headroom concurrently.

Execution tenants propagate from the project/portfolio root through Experiment, Trial, Workload, child-Machine, environment-capability and model-request execution. Fair admission considers current tenant and group in-flight share before historical grant order. This prevents a paper with thousands of ready episodes from starving a paper with a small frontier, while a single active paper can still consume otherwise idle capacity.

Model requests add an engine-pressure feedback loop on top of the same fair admission. Qualified deployments bind a hard safe concurrency ceiling and a preferred operating point derived from measured performance. The runtime window adapts within that envelope using completion behavior, rate-limit responses and normalized engine pressure. For vLLM, the pressure projection includes running/waiting requests, KV-cache usage, preemption and prefix-cache counters. Prefix affinity and pooled HTTP transport preserve locality and connection reuse; vLLM itself remains responsible for continuous token batching.

Lease heartbeats run through the independent control domain. Compute/GPU, endpoint, EnvironmentInstance and Docker-container fencing can therefore continue while workloads are quiescing.

On a shared host, use currently idle residual capacity while respecting pre-existing external workloads. Pressure blocks new admission; it does not normally kill already admitted Noetrium work.

### 11. GPU, endpoint and Docker ownership

Papers declare requirements; Platform resource authorities select physical identities.

Endpoint lifecycle is:

~~~text
candidate
  -> OS binding validation
  -> atomic reservation
  -> lease/fencing generation
  -> exact binding proof
  -> heartbeat
  -> physical convergence
  -> release/reuse
~~~

Compute/GPU ownership follows the same authority principle.

Containerized model services use the shared exact service lifecycle and the same Docker-container lease authority used by the physical resource layer. Model authority owns model identity, stack, deployment and qualification semantics; service authority owns start/readiness/stop/reconciliation; container authority owns the physical Docker generation, fencing and recovery. Model code does not own a private Docker lifecycle.

Docker-managed containers are generation-bound and reconciled against physical daemon state. A stopped exact-generation container may be parked and resumed through the container authority, but mutable scientific state is never inferred from container survival. Container convergence must be proven before dependent environment, endpoint or compute ownership is released.
### 12. Shutdown, crash and restart semantics

Normal ManagedResearchRuntime shutdown detaches the project consumer without treating reusable physical runtime as project-owned garbage:

~~~text
quiesce project/background submission
  -> quiesce experiment, capability and model I/O for this consumer
  -> flush durable Machine / effect / evidence state
  -> release project-scoped guards and heartbeat ownership
  -> detach the Runtime Fabric consumer lease
  -> close project-local observability and execution pools
  -> release managed-runtime interprocess lock LAST
~~~

Exact model services, qualified deployments, reusable environment realizations and their physical containers may remain warm when their durable owner state is still valid. Terminal retirement and pressure reclamation are separate owner-authority operations: they first prove exclusive Runtime Fabric consumer conditions, stop or retire the physical generation, and only then release dependent endpoint/compute ownership. A normal project close does not masquerade as terminal physical GC.

If a retirement or reconciliation stage cannot prove convergence, later dependent resources remain fenced. `EndpointPhysicalConvergencePending` and equivalent physical-pending states therefore block unsafe lower-resource release, but the long-lived resource controller retries them rather than failing the whole controller task.

After SIGKILL, SSH loss or a crashed prior controller, the next exclusive managed runtime performs startup reconciliation before admitting new work. A stopped durable realization is adopted only after its exact generation and current physical placement are re-proved; lost capacity, stale generations and expired ownership are fenced and replanned through the canonical resource authorities rather than revived blindly.

Machine Journals, checkpoints, artifacts, evidence, immutable assets and recovery-required workspaces are durable recovery carriers, not ephemeral leaks. They follow retention/GC policy rather than crash cleanup.

### 13. Bootstrap-container crash handling

<code>deploy/build-environments.sh</code> runs control-plane Python inside a bootstrap container connected to the active host Docker daemon.

Bootstrap containers carry exact host owner identity: PID, boot id and process-start generation. Normal EXIT/HUP/INT/TERM performs cleanup. A later launcher removes only orphan bootstrap containers whose exact owner generation is proven gone. Docker <code>--rm</code> is treated as an optimization, not proof of physical convergence.

### 14. Upstream versus downstream

Keep reusable execution machinery upstream: Research OS/Machine substrate, resource admission and leases, process/service/container lifecycle, generic environment profiles/providers, model-serving mechanics, artifacts/evidence/data authorities, generic experiment/recovery mechanisms and deployment tooling.

Keep scientific novelty downstream: concrete MethodPrograms, comparison methods, memory semantics, prompts/policies, benchmark builders and task assets, task success criteria, paper worlds/assets, paper model selection, experiment hypotheses/matrices and claim interpretation.

Move a mechanism upstream only when it is genuinely reusable across papers and can be expressed without importing one paper's scientific claim into Platform authority.

### 15. Before adding a Runner, Manager, Controller or adapter

Check <code>noetrium.api</code>, the system registry and generated architecture map first.

If the need is paper-variable, prefer Program/sub-IR/policy/handler. If it is physical/provider mechanics, extend the owning typed provider. If an authority already exists, reuse it.

Do not add a second durable history, scheduler, lease registry, checkpoint authority, Docker owner or resource allocator.

### 16. Current execution model

The canonical source path uses one executable ResearchProgram/Machine model across Method, Runtime, Participant, workload, optimization and other programmable research domains.

| Area | Canonical behavior |
| --- | --- |
| Research OS authoring/control | portfolio/program DAGs, immutable revisions, node-scoped control, retry/reconcile/migrate and lazy physical-plane materialization |
| Scientific execution | ResearchProgram -> ProgrammableMachineInterpreter -> MachineExecutor -> Machine Journal |
| Method execution | typed Method semantics lower deterministically to ResearchProgram(kind=METHOD); Method facades project typed results but own no second transition engine |
| Participant execution | frozen participant schedules compile to parent ResearchPrograms; roles execute as child Machines with exact child-cut links |
| Workload execution | dependency DAGs compile to journal-backed Run ResearchPrograms and execute through a bounded completion-driven frontier with immediate dependent refill; no process-local scheduler owns recovery truth |
| Model runtime | declared model requirements resolve to exact assets and an immutable ModelStack; compute/endpoint/container placement, replica startup, measured safe/preferred concurrency qualification, topology-stable qualified refresh, circuit-breaker recovery, prefix-aware pooled transport, adaptive admission from latency/rate-limit/vLLM pressure, qualified closure and durable request/effect evidence are platform-owned |
| Capability/effect runtime | one capability/effect intent/receipt/reconciliation path with explicit certainty |
| Environment runtime | exact environment/session identity, assignment-scoped lifetime, atomic reusable-instance provisioning, catalog/lease admission fencing, deterministic seed derivation when required, and owner-managed provider mechanics |
| Budget/replay | one durable assignment-lifetime authority for steps, time, calls, messages, tokens, cost, resource-policy identity and replay proof |
| Artifact/evidence/data | canonical owner authorities; no run-local identity shadow store |
| Resource/runtime lifecycle | shared-host admission, compute/GPU allocation, endpoints, Docker/process/service generations, leases, heartbeats, cleanup and abandoned-owner recovery |

The normal project path is:

~~~python
from noetrium import api

with api.open_project(".") as research:
    report = research.run()
~~~

Downstream code should not manually construct model, environment, resource, Docker, Machine or evidence authorities. Frozen requirements resolve through their canonical owners. If an exact binding or proof cannot be established, execution fails closed.

<!-- readme-section:repository-layout -->

## Repository layout

| Path | Responsibility |
| --- | --- |
| `noetrium/` | supported downstream package boundary: generated public API and live `ResearchOS`/`open_project` wrapper |
| `noetrium_platform/product/` | Research OS/operator product semantics; highest internal product layer |
| `noetrium_platform/research/` | Method, Machine, Experimentation, workload and scientific execution semantics |
| `noetrium_platform/capabilities/` | Model, Environment, Participant and capability owner systems/providers |
| `noetrium_platform/evidence/` | Artifact, data, provenance and evidence authorities |
| `noetrium_platform/infrastructure/` | process/service/session/container/resource durability and physical lifecycle |
| `noetrium_platform/foundation/` | shared kernel, governance, portfolio/scope and irreducible mechanisms |
| `components/` | reusable component contracts/reference implementations retained outside the internal semantic plane |
| `orchestration/` | reusable orchestration contracts/runtime where they remain independent of paper semantics |
| `research/` | repository-owned benchmark/reproduction definitions and fleet composition; not part of the published downstream API |
| `sdk/` | SDK-facing support assets/tools where applicable |
| `configs/` | versioned configuration examples and non-secret templates |
| `deploy/` | canonical Docker-first server launcher, environment profiles, Compose/bootstrap assets and rootless-Docker helpers |
| `docs/` | architecture, generated source maps, infrastructure, governance, status and history |
| `scripts/` | generation, architecture gates, audits, release evidence and maintenance entrypoints |
| `tests/` | platform/unit/integration/regression contracts |
| `tests_runtime_harness/` | shared test-only runtime harness code |
| `LICENSE` / `NOTICE` / `THIRD_PARTY_NOTICES.md` | Apache-2.0 and third-party license notices |

Treat `noetrium/` as the supported downstream package boundary. Project-specific code stays downstream, and internal implementation details under `noetrium_platform/` may change behind the public contracts.

<!-- readme-section:testing -->

<a id="verification"></a>

## Testing and verification

Run verification against the exact source cut you intend to use. Do not treat a historical green report, generated map or release manifest as proof for a later dirty tree.

Core regression and architecture checks include:

```bash
python -m pytest -q
python scripts/architecture_gate.py
python scripts/machine_architecture_gate.py
python scripts/platform_repository_boundary.py
python scripts/no_compatibility_surface_gate.py
python scripts/public_contract_audit.py
python scripts/no_degradation_audit.py
python scripts/check_readme_i18n.py
```

Use `python scripts/update_generated_docs.py` after changing registry descriptors, public exports or architecture-generating inputs; generated architecture/catalog drift is a source failure, not documentation trivia. For release evidence, use `python scripts/verify_release_evidence.py` and validate that the source, manifests, authority bindings and recorded evidence all name the same revision.

The most important interpretation rule is that different gates prove different things. Unit tests prove local behavior. Architecture gates prove ownership/import/invariant boundaries. Machine gates prove the single-machine authority model. Repository-boundary gates prove upstream/downstream packaging. No-compatibility/no-degradation checks reject shadow paths and silent scientific weakening. A release-quality cut needs the relevant set, not one convenient green test.

The repository uses a hierarchical test taxonomy so every test belongs to an explicit contract level and release evidence can prove what was actually exercised. See `tests/TEST_SYSTEM.json`.

<!-- readme-section:principles -->

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
10. <strong>Budgets are execution policy, not metadata.</strong> Steps, time, calls, tokens, cost, resource policy and replay level are enforced by a durable authority shared across parent and child execution.
11. <strong>Research value kinds are real types.</strong> Artifact, Evidence, Checkpoint, Metric, Selection and Data require their actual owner authorities rather than a generic JSON fallback.
12. <strong>Scientific lifetime is explicit.</strong> Assignment, task, participant, environment and operation lifetimes are frozen and propagated; state sharing and cleanup occur at those boundaries.
13. <strong>Logical scheduling and physical scheduling are different.</strong> Research order, barriers and participant waves may be scientific semantics; CPU/GPU/process/endpoint/container placement is infrastructure.
14. <strong>Observation is not authority.</strong> Logs, traces, metrics, caches, status projections and forensics are rebuildable views.
15. <strong>No compatibility shadow path.</strong> When one stronger implementation replaces another, obsolete execution semantics are deleted rather than kept as a hidden fallback.
16. <strong>Exact source and provider identity are part of reproducibility.</strong> Program, revision, binding, model, environment and resource-policy identity participate in admission and evidence.
17. <strong>Downstream owns scientific novelty.</strong> The platform supplies reusable execution, evidence, resource and recovery mechanisms; it does not encode one paper's private claim.
18. <strong>External projects are design inputs, not embedded architectures.</strong> Reuse libraries directly when appropriate, but absorb whole-project ideas into Noetrium's ownership model instead of importing a competing architecture behind adapters.
19. <strong>Architecture invariants are executable.</strong> Source-derived maps, tests and gates must agree with the same source cut.
20. <strong>Performance cannot weaken semantics.</strong> Concurrency, pooling, batching and caching must preserve binding identity, effect certainty, budget enforcement, lifetime and evidence.

<!-- readme-section:extending -->

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

<!-- readme-section:documentation -->

## Documentation

Start with the documentation index.

### Key references

- [Documentation index](docs/INDEX.md)
- [Examples](examples/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Support](SUPPORT.md)
- [Citation metadata](CITATION.cff)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Platform architecture](docs/architecture/PLATFORM_ARCHITECTURE.md)
- [Detailed system map](docs/architecture/VNEXT_DETAILED_SYSTEM_MAP.md)
- [Architecture migration contract](docs/architecture/FINAL_ARCHITECTURE_MIGRATION_CONTRACT.md)
- [Infrastructure documentation](docs/infrastructure/README.md)
- [Governance documentation](docs/governance/README.md)
- [Current status](docs/status/README.md)
- [Engineering history](docs/history/README.md)

Architecture documents define reusable ownership and contracts; status documents describe the current development tree; history preserves evidence for the state that existed when it was written. For implementation orientation, read `docs/architecture/COMPONENT_LAYERS.md` for the public component tiers and `docs/product/PUBLIC_FACADE_AND_CLI.md` for project authoring, doctor, and test flows.

<!-- readme-section:security -->

## Security and configuration

Noetrium treats identity, credentials, provider effects and evidence as part of the execution boundary rather than incidental application configuration.

- Never commit passwords, private keys, access tokens, runtime secrets or machine-local credentials.
- Keep host-specific paths and secrets in ignored local profiles or environment-bound stores.
- Prefer explicit provider bindings and scoped credentials over ambient global discovery.
- Keep external-effect commands typed, bounded, journaled and attributable to an operation identity.
- Preserve idempotency, receipt and reconciliation information for effectful operations.
- Treat logs, artifacts, traces, prompts and evidence as potentially sensitive research data.
- Fail closed when a credential, provider qualification, revision or authority binding cannot be proven.

<!-- readme-section:contributing -->

## Contributing

Changes should be reviewable by ownership boundary and include the tests and documentation needed to prove them.

### Before opening a pull request

```bash
python -m pytest -q
python scripts/architecture_gate.py
python scripts/check_readme_i18n.py
```

- preserve system ownership and public-contract boundaries
- add or update focused regression coverage
- update owning documentation in the same change set
- avoid unrelated refactors in the same commit
- preserve fail-closed behavior for uncertain external effects
- document intentional semantic or compatibility changes explicitly

[Documentation Change Policy](docs/governance/DOCUMENTATION_CHANGE_POLICY.md)

<!-- readme-section:license -->

## License

Noetrium is licensed under the Apache License, Version 2.0. The authoritative legal text is the root LICENSE file.

Third-party components remain governed by their own licenses; see THIRD_PARTY_NOTICES.md. Independently distributed model weights, datasets or benchmark assets may state separate terms.

[`LICENSE`](LICENSE) · [`NOTICE`](NOTICE) · [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

<!-- readme-section:status -->

## Development status

Noetrium 0.44.0 is the current package baseline.

The platform already contains the core execution shape described in this README: Research OS authoring/control, portfolio and research-graph composition, the universal ResearchProgram/Machine execution path, Study/Experiment/Trial execution, completion-driven experiment/workload scheduling, participant compilation, exact owner binding, content-addressed single-flight reuse of immutable execution structures, hierarchical tenant-aware admission, platform-owned model stack/deployment/qualification materialization with adaptive shared serving, environment/capability integration, durable budget/replay admission, canonical artifact/evidence ownership, resource/runtime lifecycle management and Docker-first execution profiles.

Noetrium remains under active development. APIs and internal package boundaries may evolve as real research workloads expose stronger general abstractions. The project intentionally does not preserve obsolete execution paths merely for compatibility; architectural changes are expected to converge toward a single stronger owner and a single executable semantics.

A capability should be considered usable for scientific work only when the exact source revision, program/binding identity, resource/runtime closure, effect behavior, recovery path and evidence are all validated for that same source cut. Historical green tests, generated maps from an older revision and a dirty working tree are not release evidence.

Noetrium is an infrastructure project, not a hosted agent product, and it does not own downstream scientific claims. Downstream projects own their research questions, methods, prompts, task/benchmark semantics, model/environment requirements, experiment design and interpretation. Noetrium owns the reusable research operating system and the execution/evidence/resource discipline around them.

For publication or production use, pin the exact source revision and generate/verify release evidence for that revision.
