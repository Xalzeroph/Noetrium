# Noetrium Cohesion, Coupling & Boundary Audit — 2026-09-22

> Source of truth: `/data/hdd3/agent-research-runtime/noetrium-downstream-ux-20260922`
> Audited source cut: `28c55147a0d2ec0e2940ed07223ee5b553390d4e` plus current working-tree changes.
> Scope: physical package boundaries, registry topology, class/reference graph, module import graph, canonical dataflow, authority boundaries, runtime entrypoints.

## 1. Executive conclusion

Noetrium has substantially completed **authority classification**, but it has **not yet completed physical cohesion consolidation**.

The architecture is therefore in an intermediate state:

- durable authority is much more coherent than before;
- topology correctly distinguishes authority/facet/projection/provider/adapter/policy/tool/product surface;
- however, source layout still mechanically treats most topology nodes like miniature systems;
- this creates large amounts of ceremonial package structure, same-authority cycles, and fake boundaries;
- at the same time, nine genuinely different top-level systems form one import SCC, so several true boundaries are not decoupled enough.

The correct next move is **not “merge everything”**. It is:

1. merge or flatten false boundaries inside one canonical authority;
2. retain semantic concepts as modules/types without giving each concept a full system shape;
3. break cross-authority cycles by dependency inversion and composition relocation;
4. reorganize oversized packages internally without inventing new authorities.

## 2. Quantitative evidence

Fresh AST/code-graph generation on the current working tree reports:

- 2,548 Python modules
- 3,210 classes
- 5,612 module import edges
- 3,261 class association edges
- 877 constructor edges
- 142 inheritance edges
- 172 registry nodes
- only 20 direct authorities
- 16 top-level systems

Registry node kinds:

- 82 facets
- 30 projections
- 20 authorities
- 10 providers
- 8 adapters
- 8 policies
- 8 product surfaces
- 6 tools

The key structural smell is the registry/package-shape distribution:

- 170 / 172 nodes declare exactly `api + runtime + providers + composition`
- 1 node declares only `api`
- 1 node declares `api + runtime + composition`

This shape uniformity is not correlated with real responsibility.

Fresh filesystem AST analysis found:

- 2,489 registry-owned Python files
- 191,168 LOC
- 858 files are empty/re-export shells
- shell files are **34.5% of registry-owned Python files**
- shell LOC is only 4.6% of source LOC
- 145 / 172 registry nodes contain at least five such shell files

This is strong evidence of structural ceremony rather than useful separation.

## 3. Root cause: topology has leaked into physical architecture

The current normative architecture already says that a registry node is not automatically an authority and that fine-grained nodes may remain for discoverability. The implementation, however, still gives nearly every topology node a four-plane physical package shape.

That conflates three different things:

1. **authority boundary** — where truth is accepted/mutated;
2. **semantic taxonomy** — how concepts are named/discovered;
3. **physical module boundary** — where code should be separated because it changes independently.

These are not equivalent.

A facet such as `scope/identity` may deserve a registry/documentation entry and public symbols while still being only one module inside the Scope authority package.

## 4. Same-authority fragmentation: merge/flatten candidates

### 4.1 Experimentation

The experimentation family forms an 11-node SCC:

- experimentation
- experimentation/study
- experimentation/experiment
- experimentation/run
- experimentation/run/control
- experimentation/run/identity
- experimentation/run/lifecycle
- experimentation/run/manifest
- experimentation/checkpoint
- experimentation/evaluation
- experimentation/workload

This is the strongest over-splitting signal in the repository.

Especially strong structural coupling:

- experimentation ↔ study
- study → experiment
- run ↔ lifecycle
- run ↔ identity
- run ↔ manifest
- experiment ↔ run
- checkpoint → run/experiment
- workload → experiment/study/workflow

Recommendation:

- keep **Study / Experiment / Run / Workload / Evaluation / Checkpoint** as explicit domain concepts;
- do not keep each as a full miniature four-plane system;
- consolidate shared runtime/composition under the Experimentation authority;
- keep narrow public API modules where independently useful;
- move workload-to-trial execution bridging out of Study definition/runtime and into Experimentation composition/execution adapter space;
- Run identity/lifecycle/manifest/control should be cohesive modules under one Run bounded context, not mutually dependent pseudo-systems.

### 4.2 Model

The model family forms an 8-node SCC:

- model
- model/asset
- model/deployment
- model/request
- model/request/prompt
- model/serving
- model/serving/endpoint
- model/stack

Most of these are legitimate concepts, but their current physical split is too system-like.

Recommendation:

- one Model authority package;
- domain subpackages for request, deployment, serving and asset;
- `request/input`, `request/output`, `catalog/family`, `deployment/closure` become ordinary modules/contracts, not four-plane mini-systems;
- serving endpoint should be a serving facet/interface, not a mutually importing peer system.

### 4.3 Runtime/server

A 6-node SCC exists among:

- runtime/server
- runtime/server/bootstrap
- runtime/server/health
- runtime/server/identity
- runtime/server/lifecycle
- runtime/session

The normative spec already says server/health/identity leaves are facets unless independently stateful.

Recommendation:

- consolidate server identity, health, lifecycle, bootstrap into a cohesive server bounded context;
- retain submodules, but remove independent system-shaped composition/provider scaffolding where it has no independent lifecycle.

### 4.4 Platform, Scope, Portfolio, Artifact

Clear flattening candidates include:

- platform/{identity, configuration, lifecycle}
- scope/{identity, hierarchy, membership, ownership, path, resolution}
- portfolio/{workspace, program, project, membership}
- artifact/{catalog, content, lineage, reference, retention}

Examples of extremely thin nodes:

- artifact/lineage: 20 LOC, 6 modules, 0 top-level definitions
- environment/instance: 20 LOC, 6 modules, 0 definitions
- environment/specification: 20 LOC, 6 modules, 0 definitions
- model/catalog: 20 LOC, 6 modules, 0 definitions
- portfolio/project: 77 LOC, 7 modules, 0 definitions

These should remain semantic facets but not physical pseudo-systems.

### 4.5 Observability

Many observability leaves are projections/providers with 20–100 LOC spread across 6–9 files.

Examples:

- observability/diagnostic
- observability/tracing
- observability/telemetry
- logging/context
- logging/query
- logging/routing
- logging/projection
- diagnostic/query
- diagnostic/correlation
- tracing/context
- tracing/propagation

Recommendation:

- treat observability as a side-plane library with coherent record/context/query/export packages;
- stop creating composition/provider/runtime layers when the leaf only defines a projection or schema;
- logging query/record/sink currently form their own SCC and should be reorganized around write path vs read path rather than nominal nouns.

## 5. Cross-authority coupling: do not merge; break the cycles

At the top level, nine systems form one strongly connected component:

- data
- environment
- execution
- model
- observability
- participant
- reliability
- resource
- runtime

This is the primary decoupling defect.

Important edge counts include:

- execution → participant: 53
- execution → reliability: 28
- execution → environment: 23
- environment → runtime: 17
- reliability → observability: 17
- model → resource: 13
- model → runtime: 13
- runtime → model: 10
- runtime → reliability: 10
- participant → execution: 5
- resource → runtime: 1
- runtime → resource: 5

These systems represent genuinely different change axes and should **not** be merged.

### 5.1 Execution ↔ Participant

Execution legitimately consumes participant contracts. The reverse dependency is the problem.

Current reverse edges come from participant agent runtime modules importing concrete Research Machine programs/hosts.

Recommendation:

- Participant owns participant identity/binding/session ABI only;
- paper/runtime programs belong to Execution or reference composition;
- participant implementations may implement ports but should not import concrete Machine runtime internals;
- use protocol/port contracts or composition-level adapters.

### 5.2 Execution ↔ Environment

Most Execution → Environment imports are concentrated in
`execution/workflow/implementations/context_action`.

This is not generic workflow infrastructure; it is a concrete reusable/reference execution composition.

Recommendation:

- move `context_action` and similarly concrete `agent_turn` workflow implementations out of the generic workflow core;
- place them under reference components / reusable method compositions;
- leave `execution/workflow` with generic MethodProgram authoring, dispatch, machine binding, effect mediation and runtime contracts.

This alone removes a large false dependency from the generic execution system.

### 5.3 Model ↔ Runtime

Model deployment legitimately needs process/service/runtime capabilities.

The reverse dependency comes largely from `infrastructure.lifecycle.launch_control` importing model-serving contracts.

Recommendation:

- runtime must remain generic service/process/session infrastructure;
- model-specific launch control belongs in Model deployment/serving composition;
- runtime exports neutral service/process/heartbeat ports;
- Model binds those ports at composition time.

### 5.4 Resource ↔ Runtime

The cycle is small but architectural:

- resource compute provider invokes runtime process execution for `nvidia-smi`;
- runtime Python lifecycle imports resource directory authority.

Recommendation:

- extract low-level host process/filesystem primitives as private provider utilities beneath authority topology;
- Resource and Runtime both consume those primitives;
- do not create another public authority just to solve the dependency.

### 5.5 Reliability / Observability / Data

Reliability consuming observability is acceptable if observability is a side-plane port.

The dangerous direction is observability becoming coupled back into durable data/domain semantics.

Recommendation:

- observability records should depend on minimal immutable context/envelope contracts;
- correlation/query may consume pinned evidence/data cuts in composition, not make the observability core depend on Data/Participant authorities;
- forensic materialization remains projection-only.

## 6. Packages that are too broad internally

### 6.1 execution/research_program

Approximately:

- 12.3k LOC
- 140 classes
- 24 modules

It is a valid cohesive authority/mechanism family, but the files are mostly flat in one directory.

Recommendation:

keep one authority, reorganize internally into private subpackages such as:

- core program/interpreter/session/host
- child machine
- rules
- domain programs
- runtime modules

Do **not** create new registry authorities for these.

### 6.2 execution/workflow

Approximately 9.7k LOC. Distribution:

- implementations: ~4.0k LOC
- api: ~2.4k
- runtime: ~2.2k
- composition: ~0.8k
- providers: ~0.3k

Nearly half the package is concrete workflow implementation rather than generic workflow infrastructure.

Recommendation:

- move reusable/reference implementations out;
- shrink generic workflow to the universal execution contract.

### 6.3 environment/minecraft

Approximately 10k LOC / 138 classes.

This is large but mostly a legitimate provider bounded context: protocol/actions, server lifecycle integration, world materialization, checkpoint/restore, transport.

Audit concern:

- local action ledger/recovery/checkpoint code must not become a second Environment/Effect/Machine authority;
- provider-local state must remain operational/provider state or projection with authoritative truth committed through Environment/Effect/Machine boundaries.

Do not split Minecraft into many registry systems merely because it is large.

## 7. Recommended physical architecture rule

Replace the implicit rule:

> every registry node gets api/runtime/providers/composition

with:

> physical structure is chosen by responsibility and independent change axis.

Suggested defaults:

- authority: api + runtime, providers/composition only when actually needed
- facet: usually one API/domain module; runtime only when it has real behavior
- projection: query/projector/store modules as needed; no default composition layer
- provider: provider implementation + minimal provider contract; composition only at binding boundary
- adapter: one focused adapter module/package
- policy: pure/declarative module
- tool: move outside runtime authority topology
- product_surface: application/facade package, not authority-shaped internals

Registry topology should describe ownership/discoverability, not generate package ceremony.

## 8. Refactoring priority

### P0 — architecture meta-model

1. Stop requiring four-plane shape for non-authority registry nodes.
2. Add validation that rejects empty/ceremonial role directories.
3. Separate registry topology metadata from physical package-shape metadata.
4. Regenerate downstream facades from symbols/ownership, not from mandatory role packages.

### P1 — same-authority consolidation

1. Experimentation/Run family
2. Runtime/server family
3. Scope + Portfolio leaves
4. Platform leaves
5. Artifact leaves
6. Model thin leaves
7. Observability thin projections

### P1 — break true system cycles

1. move concrete context_action/agent_turn implementations out of generic Workflow
2. remove Participant → concrete Execution Machine imports
3. move model-specific launch control out of generic Runtime
4. eliminate Resource ↔ Runtime low-level host primitive cycle
5. make observability/data dependencies composition-facing and one-way

### P2 — internal cohesion

1. reorganize `execution/machines` internally without new authorities
2. keep Minecraft one provider context while auditing duplicate truth stores
3. reduce generic workflow surface after reference implementations move

## 9. Acceptance criteria for the consolidation

The refactor is complete only when:

- no non-authority node is forced to have empty api/runtime/providers/composition packages;
- shell/re-export file ratio drops materially from the current 34.5%;
- same-canonical-authority SCCs are eliminated or intentionally confined inside one physical bounded context;
- top-level system SCC no longer contains the current nine systems;
- Participant no longer imports concrete Execution Machine implementations;
- Runtime no longer imports Model-domain launch semantics;
- generic Workflow no longer owns concrete reference agent/context-action implementations;
- projections/providers cannot mutate or duplicate authority truth;
- public downstream symbols remain generated and stable at the semantic API level;
- entrypoint reachability audit and full Docker regression pass after the physical consolidation.

## 10. Final assessment

Noetrium is **conceptually more decoupled than its source tree currently looks** because authority consolidation has already removed many false truth owners.

However, physical modularity has lagged behind conceptual authority design.

The dominant problem is therefore two-sided:

- **over-splitting inside one authority**: too many topology facets are materialized as mini-systems;
- **under-decoupling across real authorities**: several genuinely independent systems import one another in cycles.

The next architecture phase should be called **physical cohesion consolidation**, not another authority redesign.

After that consolidation, the original task—connecting every implemented but unreachable subsystem—becomes much safer, because we will be wiring a smaller number of coherent boundaries instead of cementing accidental fragmentation.
