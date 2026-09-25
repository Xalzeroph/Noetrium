# Noetrium System-by-System External Capability Audit
> Classification: research audit / design provenance only.\n> This document is not a platform contract. Production architecture must use native Noetrium vocabulary and must not retain source-project identities.\n\n
> Status: active implementation guide
> Date: 2026-09-18
> Baseline: `d6e34b7b3af5698fda69922a80fc6226e10da1f9`
> Authority rule: external projects contribute proven semantics/design; mature libraries may be used directly behind Noetrium ports; neither may acquire Noetrium scientific authority.

## 1. Audit method

This audit is driven by the source-derived architecture projections rather than directory names alone:

- `CODE_ARCHITECTURE_MAP.md`: platform class graph, associations, constructor edges, imports and authority projection.
- `REPOSITORY_CODE_ARCHITECTURE_MAP.md`: full repository including facades, reproductions, reference code, tooling and tests.
- `DATAFLOW_MAP.md`: scientific execution, capability/effect, evidence/projection and recovery flows.
- `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md`: normative authority classification.

The architecture map contains 16 top-level registry domains. The registry exposes 171 surfaces, but only 21 are authorities. External comparison therefore follows authority ownership rather than pretending every package is an independent system.

Each external capability is classified as one of. Project/harness/application architecture is never adopted through a whole-project adapter:

1. **USE LIBRARY** — depend on a mature library/provider implementation.
2. **ABSORB DESIGN** — reimplement the proven semantic pattern natively under Noetrium authority.
3. **PROVIDER BINDING** — narrow protocol/service/library integration only; never a whole-project architecture wrapper.
4. **RETAIN** — Noetrium has stronger scientific/authority requirements; keep the native subsystem.
5. **DELETE/CONTRACT** — remove duplicate mechanics once a mature library/provider owns them.

## 2. Platform

### Current Noetrium responsibility

Platform/kernel owns canonical immutable values, machine execution primitives and process-local structured-concurrency ownership. Current concurrency includes task groups, cancellation, deadlines, bounded thread/process lanes, serial actors/mailboxes, permits, heartbeat coalescing, topology snapshots and physical-convergence semantics.

### External audit

**AnyIO / Trio — USE LIBRARY selectively.**

Absorb/use:
- cancel scopes;
- deadline propagation;
- task-group lifecycle;
- readiness-style task start;
- async backend portability.

Do not delegate:
- scientific execution identity;
- CPU process physical-convergence semantics;
- Noetrium permit authority;
- serial mailbox ownership;
- heartbeat coalescing/topology receipts.

Target: AnyIO may replace custom async-loop/cancel/deadline provider mechanics behind existing Noetrium concurrency ports. It must not replace the Platform concurrency contract.

**controller-runtime Manager — ABSORB DESIGN.**

Absorb explicit runnable registration, readiness/health separation, lifecycle groups and dependency injection. Do not make Kubernetes manager state a Platform authority.

## 3. Governance

### Current responsibility

Governance owns system/authority topology, release promotion and runtime-relevant policy; repository architecture/algorithm/concurrency/performance analyzers are build-time gates.

### External audit

**Kubernetes Scheme/controller-runtime — ABSORB DESIGN.**
- explicit type/version registration;
- conversion/defaulting boundaries;
- lifecycle health/readiness.

**Bazel analysis/loading model — ABSORB DESIGN.**
- immutable analysis result before execution;
- detect inconsistent dependency graph before effects;
- package-local declarations with derived global graph.

Keep Noetrium source-authority and release evidence. Do not create runtime authorities for static analyzers.

## 4. Scope

### Current responsibility

One strict scientific hierarchy:
`platform → workspace → program → project → study → experiment → run → branch/participant → session → operation`.

### External audit

**OpenFGA — ABSORB DESIGN / REFERENCE only.**

OpenFGA relation tuples are useful for future authorization/policy questions, not for scientific hierarchy truth. Do not replace Scope with a general authorization graph.

Decision: **RETAIN** the small native Scope authority. If access control is added, map Scope identities into an authorization provider rather than merging authorization with scientific identity.

## 5. Portfolio

### Current responsibility

Workspace/program/project metadata plus canonical `ProjectManifest`, including capability requirements, method requirements, provider bindings, configuration refs and platform/tool provenance.

### External audit

**Backstage Catalog — ABSORB DESIGN.**
- entity metadata/spec separation;
- ownership/reference conventions;
- generated catalog views.

**Bazel package model — ABSORB DESIGN.**
- package-local ownership;
- immutable finalized package metadata;
- dependency graph derived from local declarations.

Decision: retain `ProjectManifest` because its scientific provenance is stronger. Move author-owned details toward package-local declarations and generate global catalog projections rather than making authors edit central catalogs.

## 6. Runtime

### Current responsibility

Host/process/service/session lifecycle and orchestration. Runtime must not own experiment/model scientific truth.

### External audit

**systemd — ABSORB DESIGN.**
- dependency and ordering are distinct relations;
- construct/validate a lifecycle transaction before mutation;
- explicit service state machine;
- restart/rate-limit policy separated from unit identity;
- readiness notification rather than assuming process-start equals ready.

**controller-runtime — ABSORB DESIGN.**
- desired-vs-observed reconcile loops;
- bounded requeue;
- explicit readiness/liveness.

Decision: retain Noetrium Runtime authority; contract duplicate lifecycle loops into reusable reconcile/transaction primitives. External service/container managers remain providers.

## 7. Resource and Resource Lease

### Current responsibility

Resource inventory, logical requirements, placement, allocation, lease TTL/renew/release and fencing.

### External audit

**Ray placement groups — ABSORB DESIGN; optional narrow scheduler-provider binding.**
- logical bundles;
- PACK/SPREAD/STRICT placement intent;
- child-work capture/isolation;
- physical scheduler decoupled from logical request.

**Kubernetes scheduler/Kueue — ABSORB DESIGN; optional narrow scheduler-provider binding.**
- request vs observed capacity;
- queue/admission separate from binding;
- topology/affinity constraints;
- external scheduler may own physical placement.

Decision: retain one Noetrium lease/fencing authority. Add richer logical placement intents only when required by experiments. Ray/Kubernetes adapters return binding receipts; they do not own scientific resource identity.

## 8. Reliability, Effect and Failure

### Current responsibility

Effect preparation/reconciliation, effect certainty, durable failure facts, recovery policy and evidence/forensics projections.

### External audit

**Temporal — ABSORB DESIGN.**
- workflow history is replayed deterministically;
- Activities own non-deterministic/external effects;
- heartbeat is an Activity-progress signal;
- retry/cancellation policy belongs to effectful Activity execution;
- telemetry emitted during history replay must be replay-safe.

**controller-runtime — ABSORB DESIGN.**
- reconciliation is repeated desired-vs-observed convergence;
- errors/requeue are distinct from successful convergence.

Decision: **RETAIN** Noetrium effect certainty. `UNKNOWN` external effects must remain unretryable until reconciled. Add replay-safe observability and richer reconciliation policy instead of importing Temporal as a second truth store.

## 9. Execution and Operation

### Current responsibility

Command intent, admission, scheduling, operation lifecycle, workflow ancestry, MethodProgram/Machine composition.

### External audit

**Temporal — ABSORB DESIGN.**
- deterministic orchestration vs external Activity;
- explicit cancellation/retry semantics;
- history compatibility.

**systemd transaction model — ABSORB DESIGN.**
- build a proposed dependency/ordering transaction;
- reject cycles/conflicts before executing effects.

**LangGraph — ABSORB DESIGN.**
Do not preserve a whole-project LangGraph adapter in the platform. Absorb graph authoring/transition semantics that are genuinely reusable into native MethodProgram contracts. A downstream project may directly use a library when required, but LangGraph checkpoints/state never become Noetrium execution truth.

Decision: Machine Journal remains the sole scientific transition truth. Workflow/operation systems reference committed Machine cuts.

## 10. Experimentation

### Current responsibility

Study/experiment/run identity, benchmark cuts, assignments, measurement/evaluation, scientific binding, checkpoint policy and resource execution plans.

### External audit

**Inspect AI — ABSORB DESIGN.**
- compact `Task` authoring;
- named model roles;
- required roles;
- `role -> model | model[]`;
- late binding;
- scorer-time model-role resolution;
- post-hoc rescoring with role rebinding;
- message/token/turn/time/working-time/cost limits;
- layered task/eval overrides;
- checkpoint callbacks/trigger UX.

Noetrium adds exact model revision, provider qualification proof, prompt/config digests, binding evidence, scientific identity and Machine Journal linkage.

**Harbor / Terminal-Bench — ABSORB DESIGN.**
- task owns its local package/config;
- instruction/environment/tests/verifier/artifacts are package-local;
- verifier is first-class;
- verifier can run in an isolated environment;
- only declared artifacts cross the verifier boundary;
- resource/network policy belongs to the task package;
- durable task content identity should supersede ad-hoc directory checksum.

Noetrium keeps method/agent identity outside the benchmark package so one benchmark cut can be reused across methods.

**OpenHands Benchmarks — ABSORB DESIGN.**
- benchmark harness and agent SDK source are independently pinned;
- exact SDK SHA participates in runtime image identity;
- build-content hash invalidates stale images.

Noetrium extends this to paper claim cut, paper-era official code, later code, surrogate implementation, artifact-only release and independent reproduction.

Decision: current declarative `Study`, model-role phase identity, TaskPackage, post-hoc evaluation and checkpoint-trigger work follows the correct direction. Continue simplifying author UX; keep compiler-expanded typed protocol internal.

## 11. Model

### Current responsibility

Logical requirements/roles, exact immutable model identity, prompt/request provenance, qualified deployment binding, serving admission and runtime qualification.

### External audit

**vLLM / SGLang — USE AS SERVING PROVIDERS.**
Do not reproduce inference engines or CUDA/package solvers in core.

**LiteLLM — USE LIBRARY selectively.**
Useful for long-tail provider protocol normalization. Its router/fallback/cooldown semantics must not silently change scientific model identity.

Required Noetrium rule:
- a role first resolves to an explicitly admitted binding set;
- automatic provider fallback may choose only inside that frozen set;
- every actual chosen deployment/model revision emits a binding-selection receipt;
- fallback cause and attempt lineage are evidence;
- an undeclared fallback fails closed.

**Hugging Face tokenizers — USE LIBRARY.**
Tokenizer implementation should be a provider bound to exact tokenizer revision/config identity.

Decision: contract backend-specific dependency/package resolution out of Model core. Qualification should consume provider-produced facts/proofs, not become a package manager.

## 12. Participant

### Current responsibility

Research actor identity/binding/session; method/agent participant kinds; MethodProgram is paper/method semantics.

### External audit

**OpenHands Software Agent SDK — ABSORB DESIGN.**
- conversation/session object;
- typed tool definition/executor;
- MCP tool provider boundary;
- agent server as runtime provider.

**OpenAI Agents SDK — ABSORB DESIGN.**
- compact agent authoring around instructions/tools/guardrails/handoffs/model settings;
- handoff/tool separation;
- explicit parallel tool-call policy.

Decision: do not replace MethodProgram/Machine with an SDK agent loop. Use adapters for reproduction and absorb high-value authoring/tool/session semantics. Paper-specific planning/reflection/memory/search remains downstream until proven cross-paper.

## 13. Environment

### Current responsibility

Provider-independent environment identity/session, observation/action ABI, effect reconciliation, isolation, checkpoint/fork/replay/readiness.

### External audit

**Gymnasium — USE LIBRARY / PROVIDER ABI.**
- reset/step conventions;
- seed semantics;
- termination vs truncation;
- wrappers/vector environment patterns.

**PettingZoo — USE LIBRARY / PROVIDER ABI.**
- explicit multi-agent identities;
- AEC turn selection;
- possible vs active agent sets.

**BrowserGym — USE LIBRARY only when its package is the selected web-environment provider.**
Do not wrap the BrowserGym project architecture or promote browser-specific state into Environment core.

**Harbor sandbox model — ABSORB DESIGN.**
Environment/verifier isolation, network policy and artifact-only crossing are useful provider-independent semantics.

**tau-bench — ABSORB REQUIREMENT, FIX BOUNDARY.**
Its separate agent and user-model configuration proves the need for user simulation, but the user simulator must be a Noetrium Participant, not hidden inside Environment.

## 14. Data, Data Fact and Data State

### Current responsibility

Durable research facts/state, immutable dataset/source cuts, provider-neutral query federation and pinned-cut completeness semantics.

### External audit

**Apache Arrow — USE LIBRARY.**
Canonical high-volume tabular interchange.

**DuckDB / DataFusion / Polars — USE LIBRARY providers.**
Analytics/query execution, joins, aggregates, projections and scans are not Noetrium authority.

Decision: retain source-cut/query federation contracts; do not grow a custom SQL/columnar engine. Query providers return derived results bound to exact input cuts.

## 15. Artifact

### Current responsibility

Immutable content identity, artifact metadata/lineage, verified physical placement and CAS generation.

### External audit

**fsspec — USE LIBRARY provider.**
Unify filesystem/object-store transport mechanics instead of creating one bespoke storage implementation per backend.

**DVC / MLflow artifact stores — ABSORB DESIGN.**
If a specific storage library component is reused, bind that library narrowly behind Artifact ports; do not import either project's metadata/control plane.
Remote/path resolution, cache/materialization and artifact repository UX are useful; their metadata stores do not become Noetrium scientific authority.

Decision: retain content digest and placement-generation authority. Provider access is replaceable; every authoritative binding still requires byte/content verification.

## 16. Observability

### Current responsibility

Operational logs, metrics, events, tracing/context, status/diagnostic projections; scientific evidence remains separate.

### External audit

**OpenTelemetry Python SDK / Collector — USE LIBRARY provider.**
- TracerProvider/SpanProcessor/exporters;
- MeterProvider/MetricReader/exporters;
- batching/export/backend routing;
- context propagation standards.

Decision: Noetrium retains semantic metric/event definitions, scientific correlation refs and evidence linkage. OTel owns operational transport/export mechanics only. Replay-time instrumentation must be suppressible/replay-safe.

## 17. Operator

### Current responsibility

CLI/application/product surfaces over authorities: project workflow, run control, forensics, diagnostics, queries and release tooling.

### External audit

**kubectl/controller client patterns — ABSORB DESIGN.**
- command tree translates user intent to typed API requests;
- no product command owns domain truth;
- discovery/output formatting are projections.

**Typer/Click/Rich — library candidates, not automatic migrations.**
Argparse is already stable and dependency-free. Replace it only where a declarative command schema demonstrably removes duplicate parser/handler wiring; do not add dependencies for aesthetics.

Decision: consolidate duplicated CLI declarations around one typed command registry, then generate argparse/other frontends if useful.

## 18. Cross-system priority queue

### P0 — completed scientific-correctness tranche

1. **DONE** — model binding-set and actual-selection receipts prevent hidden provider fallback/model drift.
2. **DONE** — user simulator is an explicit Participant, never hidden Environment state.
3. **DONE** — replay-aware observability prevents replay from emitting historical telemetry as fresh execution.
4. **DONE** — verifier isolation/artifact boundary exposes only declared artifacts/evidence and requires isolation evidence for separate verification.

The next implementation tranche therefore starts at P1 instead of creating another competing P0 mechanism.

### P1 — native absorption of mature implementation lessons

1. structured cancellation/convergence semantics without importing another runtime authority;
2. operational metric export semantics rewritten behind native Noetrium metric contracts;
3. remote artifact byte-access and verification semantics rewritten behind native Artifact contracts;
4. columnar/query execution may use mature libraries privately, while source cuts and result identity stay native;
5. tokenization mechanics may use mature libraries privately, while tokenizer identity stays native;
6. model-serving mechanics may use qualified engines privately, while deployment/binding identity stays native.

Named provider surfaces are not part of the target architecture.

### P2 — design absorption

1. systemd-style validated lifecycle transactions.
2. controller-runtime desired/observed reconcile contracts.
3. Ray/Kubernetes resource-bundle placement design absorption, with narrow scheduler protocol bindings only where external execution is required.
4. Backstage/Bazel package-local project metadata design absorption.
5. OpenHands/OpenAI Agents compact participant authoring design absorption.

## 19. Non-negotiable rejection rules

An external capability is rejected or wrapped more narrowly when it would:

- introduce a second writer for an existing Noetrium authority;
- silently select a different model/provider/runtime;
- mutate scientific identity during retry/fallback;
- hide a participant inside an environment;
- treat checkpoint/cache/projection as primary truth;
- merge evaluator-private information into method memory;
- replace exact source/paper lineage with one coarse version string;
- make operational telemetry authoritative scientific evidence;
- make a benchmark package own the method being evaluated.

## 20. Implementation rule

For every system change, the commit must state:

1. external project/library inspected;
2. semantic capability being absorbed or library being used;
3. authority that remains in Noetrium;
4. duplicated Noetrium mechanics deleted/contracted;
5. identity/evidence behavior preserved or strengthened;
6. focused tests proving the boundary.

This document is the implementation queue, not a license to add integrations indiscriminately. A system is changed only when the external capability materially improves correctness, generality, maintainability or downstream research speed.


## 21. Implementation progress

### Model P0 — explicit admitted binding sets and actual-selection receipts

Implemented after the Model external audit:

- `ProjectModelBindingSet` freezes the complete qualified binding choice set for
  one requirement/role/protocol.
- `ModelBindingSelectionReceipt` records the binding actually used for one
  request attempt and chains later attempts to predecessor evidence.
- selection outside the frozen set fails closed;
- later attempts require both predecessor receipt identity and causal evidence;
- `ProjectModelResponse` can bind the selection receipt to the exact request and
  binding;
- the existing single-binding path stays unchanged and remains the default;
- no automatic fallback/router was introduced.

This absorbs the useful routing/fallback *evidence semantics* seen in mature
model-routing libraries without delegating scientific model identity or
selection authority to them.


### Observability P0 — replay-safe operational emission

Implemented after the Temporal/Restate replay audit:

- observation emission has a context-local mode: `live`, `replay`, or
  `projection-rebuild`;
- replay and projection rebuild reconstruct already-accepted facts and therefore
  suppress fresh structured events, logs, and metrics by default;
- the scope is observation-plane only and never mutates Machine/Journal truth;
- recovery/reconciliation remains ordinary live execution and stays observable;
- nested scopes restore the previous mode deterministically.

This absorbs replay-aware instrumentation semantics without importing another
workflow runtime or granting observability execution authority.


### Experimentation P0 — verifier execution is an artifact-only platform boundary

Implemented after source-level Harbor/Terminal-Bench comparison:

- a task-declared verifier can no longer be satisfied by a trial provider directly
  returning final measurements;
- verifier-backed trials first return a typed execution-stage receipt containing
  only execution evidence and task-declared artifact references;
- core Study runtime derives the verifier request itself from the frozen trial
  request and TaskPackage;
- the verifier request contains the minimum scientific identity required to emit
  valid MeasurementRecord values, but no execution environment, participant
  session, work directory, method state, or arbitrary provider internals;
- undeclared artifacts and missing required artifacts fail closed before verifier
  execution;
- separate-verifier mode still requires isolation evidence;
- the final TrialExecutionReceipt is constructed only after verifier output is
  rebound to the exact trial request, package, measurement protocol, and artifact
  handoff.

This absorbs Harbor's agent/verifier separation without importing Harbor runtime
authority. Artifact identity remains owned by Artifact, measurement semantics by
Experimentation, and scientific execution truth by the Machine Journal.


### Artifact P1 correction — native placement verification only

A short-lived experiment introduced a source-named storage provider surface.
That implementation was removed after the project-design absorption rule was
tightened. The retained design lesson is provider-neutral: physical bytes must
be streamed and verified before an Artifact placement/generation binding is
accepted. Production code must express this through native Artifact contracts.


### Observability P1 correction — native operational export semantics

A short-lived experiment introduced a source-named telemetry provider surface.
That implementation was removed. The retained design lessons are native:
validated instrument definitions, bounded metric dimensions, replay-safe
emission, resource-scoped exporter lifecycle, batching/backpressure, and strict
separation between operational telemetry and scientific evidence.



## Research-audit handling rule

External names in this file are provenance for design research only. They must
not be copied into production module names, public symbols, examples, canonical
architecture, persisted scientific schemas, or platform operation identities.
Promotion requires rewriting the useful invariant into native Noetrium
terminology and deleting any temporary project-shaped bridge.
