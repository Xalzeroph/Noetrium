# Noetrium Semantic Breakpoint & Semantic-Loss Audit - 2026-09-28

Status: **live audit, read-only implementation review**
Scope: current node1 working tree at `/data1/agent-research-runtime/agent-research-platform-system`.
Rule: this audit does **not** modify implementation code. Findings are appended as they are verified.

## Baseline

- Git HEAD: `aa60f1947a51157cd9093df554fe6ed5dfa35c37`
- Branch: `main`
- Current tree is dirty and is treated as the implementation under audit.
- `README.md`, `CODE_ARCHITECTURE_MAP.md`, `REPOSITORY_CODE_ARCHITECTURE_MAP.md`, `DATAFLOW_MAP.md`, and `CURRENT_ARCHITECTURE_AUTHORITY.md` were read before source tracing.
- Generated architecture maps are not assumed to represent the latest dirty working tree; live source wins when they diverge.

## Audit objective

Find real semantic breakpoints, information compression, identity loss, lifecycle loss, authority bypass, silent downgrade, disconnected capabilities, failure-provenance loss, and cases where the public Research OS path cannot preserve the semantics expressed at the authoring layer.

## Canonical trace under audit

`noetrium.api/open_project`
-> project loader
-> ResearchOS / ManagedResearchRuntime
-> ResearchGraph
-> Study / Experiment / Trial / Workload
-> MethodRuntimePortInventory
-> UniversalMethodMachine
-> MachineMethodTransitionAuthority
-> MachineExecutor / Machine Journal

Side paths traced with it:
Model, Capability/Effect, Environment, Resource/Lease, Checkpoint/Resume, Failure/Forensics, Evidence/Artifact, child machines, and public receipts/projections.

## Additional audit axis: single universal machine / no semantic dual paths

The target architecture permits multiple backend/provider implementations only when they are interchangeable implementations behind one authority contract and do not create alternate scientific/runtime semantics.

This audit therefore separately flags:
- parallel semantic engines for the same concern;
- optional "fast/direct/embedded/legacy/operational" paths that bypass the canonical machine/authority;
- duplicated state machines or journals for one semantic domain;
- fallback modes that silently change assurance, identity, lifecycle, or recovery semantics;
- code paths where the same authored object lowers to materially different execution semantics depending on composition mode;
- duplicate public/runtime abstractions that compete for the same ownership boundary.

It does **not** flag ordinary storage/provider polymorphism by itself (for example in-memory vs SQLite persistence) when both satisfy the same single authority semantics and are selected explicitly without semantic downgrade.


## Findings

### F-001 - Graph failure metadata is dropped at the Research OS public receipt boundary
Severity: **high**
Status: **verified**
Breakpoint: `ResearchGraphExecutionReport -> ResearchControlReceipt`

Evidence:
- `ResearchGraphNodeResult` carries `failure_type` and `failure_message` for failed nodes in `noetrium_platform/research/execution/graph/api/contracts.py:130-176`.
- `ResearchGraphExecutionReport` preserves the full tuple of node results in `contracts.py:178-224`.
- `_execution_receipt()` in `noetrium_platform/composition/research_os_execution.py:2101-2148` projects the report into only succeeded/failed/blocked/cancelled node-id tuples.
- The resulting `ResearchControlReceipt.payload` contains no per-node failure type, message, attempt identity, failure evidence reference, or causal reference.

Semantic loss:
A failure remains distinguishable inside the graph report but becomes only "node X failed" at the public Research OS surface. This is a real information-loss boundary, not merely missing logging.

Impact:
`api.open_project(".").run()` and later `inspect()` consumers cannot recover even the graph-level error message from the returned receipt. Operators must descend into lower stores/journals, violating the intended top-level inspectability of the Research OS.

### F-002 - ResearchGraph durable failure state truncates exception provenance before the public receipt
Severity: **high**
Status: **verified**
Breakpoint: `worker exception -> durable ResearchGraphNodeExecutionRecord`

Evidence:
- In `noetrium_platform/composition/research_graph.py:671-822`, a caught exception is reduced through `_reportable_failure()` and `describe_exception()` to `type(failure).__name__` plus one safe message.
- The code calls `traceback.print_exception(exc)`, but that traceback is side-plane terminal output only.
- `ResearchGraphNodeExecutionRecord` has only `failure_type` and `failure_message` fields at `noetrium_platform/research/execution/graph/api/state.py:133-145`.
- `ResearchGraphExecutionStorePort.mark_failed()` accepts only those two failure fields at `state.py:618-628`; the SQLite provider persists only those values.

Semantic loss:
Traceback, exception chaining/cause/context, lower-layer failure/evidence identifiers, Machine/Operation/Effect references, and the original exception class provenance are not represented in ResearchGraph durable state. By the time the graph constructs its report, only a normalized type/message pair remains.

Impact:
Even if the public receipt is later widened, the Graph authority currently cannot reconstruct complete failure provenance from its own durable execution record. Full diagnosis depends on separately locating lower Machine Journal/forensic records without an explicit graph-level reference.

### F-003 - Whole-execution INSPECT compresses durable per-node state into state buckets
Severity: **medium-high**
Status: **verified**
Breakpoint: `ResearchGraphExecutionSnapshot -> ResearchControlReceipt(INSPECT)`

Evidence:
- `_active_execution_state()` retrieves the full durable execution snapshot in `noetrium_platform/composition/research_os_execution.py:1123-1153`.
- `_durable_control_receipt()` calls `_states(snapshot)`; `_states()` emits only `state.value -> tuple(node_id)` at lines 1169-1178.
- Per-node `attempt_number`, `attempt_id`, `failure_type`, `failure_message`, blockers and node-control generation are included only when `request.target.node is not None` at lines 1216-1233.
- The public `ResearchOS.inspect()` defaults to no node selection.

Semantic loss:
The full durable snapshot exists, but whole-execution inspection intentionally collapses it. A caller must already identify a node and issue a second node-scoped request to recover even the truncated graph-level diagnostic fields.

Impact:
Top-level inspection is insufficient for failure discovery/triage across a large ResearchGraph. This is especially costly for multi-paper/multi-experiment runs and compounds F-001/F-002.

### F-004 - Verifier-backed trials drop the assignment lifetime before Workload/Environment execution
Severity: **high**
Status: **verified**
Breakpoint: `TrialExecutionRequest.assignment -> ExecutionContext.lifetime_id` in the verifier path

Evidence:
- Normal `WorkloadTrialProvider.run_trial()` constructs `ExecutionContext` with `lifetime_id=request.assignment.assignment_digest` in `noetrium_platform/research/experimentation/lifecycle/study/providers/trial.py:355-371`.
- `_run_verifier_stage()` constructs a second execution context for verifier-backed workloads but omits `lifetime_id` entirely; `ExecutionContext.lifetime_id` therefore defaults to `None`.
- `LifetimeRoutedEnvironmentCapability.session_for()` in `noetrium_platform/composition/environment_capabilities/lifetime.py:88-96` rejects a missing lifetime id.
- `LocalMinecraftLifetimeSessionAuthority` likewise requires a non-empty lifetime id and keys its runtime/session ownership by that identity.
- Assignment cleanup itself exists via `AssignmentLifetimeFinalizingTrialProvider.run_trial(...): finally lifetime.release(request.assignment.assignment_digest)`, so this is not a missing-cleanup finding; it is a propagation break before execution.

Semantic loss:
The same Study assignment has two different runtime-lifetime semantics depending only on whether the task declares a verifier. Normal trials preserve assignment-scoped stateful environment identity; verifier-backed trials lose it before workload execution.

Impact:
A verifier-backed task that uses `environment.act` cannot enter the canonical lifetime-routed Environment path. For Minecraft/stateful environments this fails before meaningful execution instead of sharing the assignment world/session as declared by the Study lifecycle.

### F-005 - The canonical local Environment materializer collapses generic environment.act semantics into Minecraft
Severity: **high**
Status: **verified**
Breakpoint: `ResearchDefinitionKind.ENVIRONMENT -> local Environment capability materialization`

Evidence:
- Public authoring `ResearchProgramBuilder.environment()` in `noetrium_platform/product/research_os.py:1995-2007` accepts a generic ENVIRONMENT definition and generic JSON config; it is not Minecraft-specific.
- The platform contains distinct Environment families for Minecraft, web, GUI, software, text-world and embodied execution under the Environment authority.
- The canonical project path calls only `compose_local_environment_capability_runtime(portfolio, context)` from `LocalResearchExecutionAuthorityMaterializer.materialize()`.
- `_environment_definition()` selects any ENVIRONMENT definition whose config says `required_capability == "environment.act"`, without a typed environment-family discriminator.
- `compose_local_environment_capability_runtime()` then immediately reads `minecraft_version`; absence raises `RuntimeError("Minecraft environment definition requires minecraft_version")`.
- It always constructs `LocalMinecraftLifetimeSessionAuthority` and a provider component whose implementation identity is `minecraft`.

Semantic loss:
The top-level ENVIRONMENT abstraction is wider than the only automatic execution materializer. Generic `environment.act` intent is reinterpreted as Minecraft rather than resolved through the Environment authority to the declared environment family.

Impact:
A downstream ResearchPortfolio can author non-Minecraft environment semantics that survive authoring/identity compilation but cannot reach the canonical `api.open_project(".").run()` local path. This is an execution-semantic coverage break, not merely a missing convenience adapter.

### F-006 - Environment cardinality is collapsed from portfolio/node scope to one global config per local execution plane
Severity: **high**
Status: **verified**
Breakpoint: `multi-program ResearchPortfolio -> _environment_definition(portfolio)`

Evidence:
- `_environment_definition()` scans every program and every ENVIRONMENT definition in the entire portfolio for `required_capability == "environment.act"`.
- It computes config digests for all matches and raises when more than one distinct digest exists: "one local ResearchOS execution plane currently requires one exact environment.act definition identity".
- The resulting single environment runtime is injected once into one global `MethodRuntimePortInventory.capabilities` in `LocalResearchExecutionAuthorityMaterializer.materialize()`.
- The public ResearchPortfolio/ResearchGraph model supports many programs/nodes/experiments with independently frozen semantics.

Semantic loss:
Environment selection is not scoped by ResearchGraph node, Study, assignment, Method, or program. Heterogeneous environment requirements that are distinct and valid at authoring time are collapsed into one portfolio-global physical binding requirement.

Impact:
One ResearchPortfolio cannot execute two papers/Studies needing different `environment.act` configurations through the canonical local path, even when their graph nodes are independent. This breaks the advertised multi-paper/multi-experiment composition semantics at the execution-materialization boundary.

### F-007 - Default durable Method evidence cannot reconstruct the MethodRunResult it claims by run_digest
Severity: **high**
Status: **verified**
Breakpoint: `MethodRunResult -> DirectoryEventMethodEvidence.record_result()`

Evidence:
- `MethodRunResult.run_digest` in `noetrium_platform/research/execution/workflow/api/method_machine.py:943+` commits to status, run/program identity, value, state, events, checkpoint id, interrupt, failure, effect receipts, step/visit counts, evidence status, binding plan digest, runtime binding digest, schema digest, failure code/phase, and diagnostics.
- `MethodEvidencePort` is documented as the authoritative evidence sink.
- The default `DirectoryEventMethodEvidence.record_result()` persists run_id/run_digest/status/program/value/state/events/effect receipts/step counts/evidence status/failure_code/failure_phase.
- It omits at least `failure`, checkpoint identity, interrupt, `binding_plan_digest`, `runtime_binding_digest`, `schema_digest`, and `diagnostics`.
- The file stores the opaque `run_digest` but not the complete field set required to recompute that digest.

Semantic loss:
The durable result evidence is a lossy projection of the authoritative Method result while still carrying the digest of the richer object. After process loss, the persisted evidence cannot reconstruct or independently verify the exact MethodRunResult whose digest it records.

Impact:
Method-level reproducibility and failure diagnosis depend on other stores remaining available. The default evidence artifact alone is not evidence-closed for binding/schema provenance, interrupt/checkpoint state, or full diagnostic/failure semantics.

### F-008 - Canonical Research OS Study execution discards TrialExecutionReceipt provenance after metric projection
Severity: **high**
Status: **verified**
Breakpoint: `TrialExecutionReceipt -> StudyMetricObservation`

Evidence:
- `TrialExecutionReceipt` carries request digest, assignment digest, all MeasurementRecords, `evidence_refs`, optional verifier receipt, and its own `receipt_digest`.
- `StudyResearchReadSnapshot` explicitly models `trial_receipts`, and `TrialMatrixExecutionReport` explicitly models `trial_receipt_digests`, so Trial receipt identity is part of the Experimentation research-result contract.
- In the canonical Research OS adapter `_TrialBoundStudyExecution.execute_bound_variant()` in `noetrium_platform/composition/research_os_experiment_trial_execution.py`, the provider receipt is finalized to a `TrialExecutionReceipt`, then immediately passed to `_observation()`.
- `_observation()` returns only `StudyMetricObservation(assignment, scalar metrics)`.
- `execute_bound_variant()` returns only that observation; it neither returns nor persists the TrialExecutionReceipt.
- Repository-wide search finds no canonical Trial receipt store/append/publish operation on this path; `trial_receipts` is consumed by research-read/query structures but no producer is connected here.

Semantic loss:
Trial-level evidence references, verifier receipt identity, Trial receipt digest, non-scalar measurements, and the exact request-to-receipt provenance are dropped when Experimentation projects the Trial into Study scalar metrics.

Impact:
The canonical Research OS Study report can retain aggregate scientific metrics while losing the exact Trial receipts that justify them. The existing StudyResearchRead/TrialMatrix contracts cannot be populated losslessly from this execution path without a separate producer that is currently absent.

### F-009 - Environment capability mediation creates a process-local shadow Machine Journal instead of using the shared durable Machine authority
Severity: **critical**
Status: **verified**
Breakpoint: `Local Environment capability composition -> CapabilityInvocationPipeline`

Evidence:
- `CapabilityInvocationPipeline` executes capability mediation as a RuntimeProgram through `ResearchProgramHost`; pre/execute/post mediation decisions and events are Machine transitions.
- `CapabilityInvocationPipelineFactory` requires a `MachineJournalPort`.
- The general `AgentTurnSurfaceFactory.bind()` explicitly rejects a missing shared journal and constructs the pipeline with `context.machine_journal`, documenting the intended shared MachineJournal authority.
- The canonical local Environment path in `noetrium_platform/composition/environment_capability_runtime.py` instead constructs `CapabilityInvocationPipelineFactory(InMemoryMachineJournal()).create()`.
- `InMemoryMachineJournal.durability == "process_local"`; all commits disappear on process loss.
- This Environment router is the one injected into the global `MethodRuntimePortInventory.capabilities` by `LocalResearchExecutionAuthorityMaterializer`.

Semantic loss:
Environment capability mediation, although modeled as journal-backed programmable Runtime semantics, is committed to a separate ephemeral Machine Journal rather than the execution's durable shared Machine Journal. Its accepted pre/post policy decisions and mediation history are therefore outside the canonical durable execution cut.

Impact:
After crash/restart, effect-intent SQLite state may survive while the Machine history explaining why an Environment capability was admitted/denied/executed does not. This creates split recovery truth between durable effect state and process-local mediation state, contrary to the single-Machine-Journal authority model.

### F-010 - The canonical Environment capability path bypasses the durable Operation authority
Severity: **critical**
Status: **verified**
Breakpoint: `Environment capability invocation -> KernelOperationDispatcher(OperationExecutor())`

Evidence:
- The platform has a durable Execution Operation authority: `OperationOwner` over `OperationStorePort` / `SQLiteOperationStore`, with lifecycle states, crash classification, effect certainty and reconciliation.
- It also has `DurableKernelOperationDispatcher`, whose purpose is explicitly to bind Kernel invocation mechanics to durable Execution operation truth.
- Repository search finds no composition use of `DurableKernelOperationDispatcher` on the canonical local Environment path.
- `compose_local_environment_capability_runtime()` instead creates `KernelOperationDispatcher(OperationExecutor())` directly.
- That `OperationExecutor()` is constructed with no `OperationFailureSink`; `FailureMaterializer` therefore returns no failure id.
- `CapabilityOperationAdapter.invoke()` calls `dispatcher.require(operation)`; a failed operation raises before `StudyCapabilityRouter` can append the OperationResult to its in-memory operation list.
- The UMM catches the resulting exception and reduces it to Method failure text/code/phase; no durable OperationSnapshot was ever created.

Semantic loss:
The Environment capability flow uses the Operation ABI shape but not the durable Operation authority. Operation lifecycle, durable operation identity/state, failure id, crash classification and authoritative effect-certainty linkage are skipped.

Impact:
A capability failure can become a Method failure without any corresponding durable Operation record. Crash/restart and forensic tooling cannot ask the Operation authority whether that invocation was admitted/running/failed/unknown-effect, even though the platform already defines exactly that authority.

### F-011 - Unqualified operational model fallback is recorded as an assurance gap but does not fail closed before execution
Severity: **high**
Status: **verified**
Breakpoint: `qualified Model binding resolution -> operational fallback -> executable CompiledResearchPlan`

Evidence:
- `PortfolioQualifiedModelResolver.resolve()` first attempts `_qualified_binding()`; when qualified closure is missing it automatically attempts `_operational_binding()`.
- The operational path creates `ProjectModelBinding` with `qualification_certificate_digest=None`, `runtime_qualification_digest=None`, and no runtime canary evidence; `ProjectModelBinding.authority_kind` explicitly reports `"operational"`.
- `project_bound_model_resolution()` still returns `BindingResolution.bound(binding, proof)` for this operational binding.
- `ResearchBindingAuthority._model_bindings()` correctly notices `not binding.qualified` and appends a `ResearchBindingAssuranceGap(domain="model", ...)`.
- `CompiledResearchPlan` preserves those gaps and exposes `binding_assurance_complete = not binding_assurance_gaps`.
- Repository-wide search shows no consumer of `binding_assurance_complete`; `binding_assurance_gaps` is not checked by Research OS composition, admission, or execution after compilation.
- `method_agent_loop_router()` independently repeats the same qualified-first / operational-fallback behavior when materializing the actual Method model loop.

Semantic loss:
Qualification weakness is not completely hidden, but it is demoted from an execution constraint into passive metadata. A required model role can be bound and executed while the compiled plan itself says its binding assurance is incomplete.

Impact:
The canonical `open_project().run()` path does not fail closed on missing qualified-model evidence. A running deployment discovered operationally can replace a qualified closure for execution without an explicit operator/scientific revision choosing weaker assurance.

### F-012 - Method model routing collapses model-role identity across the entire ResearchPortfolio
Severity: **high**
Status: **verified**
Breakpoint: `multi-program Study model roles -> MethodAgentLoopRouter`

Evidence:
- `PortfolioQualifiedModelResolver.method_agent_loop_router()` scans every PROTOCOL definition in every program in the portfolio.
- It stores bindings in `loops: dict[str, MethodModelAgentLoop]` keyed only by `requirement.role`.
- It separately stores `identities[requirement.role]`; if a later Study uses the same role name with a different model/scientific or physical generation, it raises `ValueError("model role ... resolves multiple scientific/physical generations")`.
- The resulting single `MethodAgentLoopRouter` is injected once into the global `MethodRuntimePortInventory.agent_loop`.
- ResearchProgram/Study identities are not part of the router key.

Semantic loss:
A role name that is locally meaningful inside one Study/program is promoted to portfolio-global identity. Program/Study scope is lost before Method runtime routing.

Impact:
Two independent papers in one ResearchPortfolio cannot both use role `agent` while intentionally binding that role to different models or generations. This breaks multi-paper/multi-method composition despite the scientific definitions being separately frozen and graph-isolated.

### F-013 - Optional model roles are allowed by Study binding semantics but are treated as mandatory by Method runtime materialization
Severity: **high**
Status: **verified**
Breakpoint: `ResearchModelRoleRequirement(required=False) -> method_agent_loop_router()`

Evidence:
- `StudyModel.required` and `ResearchModelRoleRequirement.required` explicitly support optional model roles.
- `ResearchBindingAuthority._model_bindings()` and `compile_research_plan()` preserve that semantics: an optional role may have no bound rows and must not create an assurance gap.
- `PortfolioQualifiedModelResolver.method_agent_loop_router()` iterates every model role without checking `requirement.required`.
- It tries `_qualified_binding()`; on missing qualification it calls `_operational_binding()`.
- If the operational binding is also unavailable, that `ResearchBindingRequirementMissing` escapes the router. There is no optional-role catch/filter in the router or its caller.
- `LocalResearchExecutionAuthorityMaterializer.materialize()` calls the router directly while building the one global `MethodRuntimePortInventory`.

Semantic loss:
Optionality is preserved in the scientific binding compiler but lost when the physical Method model runtime is materialized. A model role that the frozen Study explicitly permits to be absent becomes mandatory before any Study execution begins.

Impact:
A valid compiled Study with an unavailable optional model role can fail project runtime materialization and prevent unrelated executable work from starting.

### F-014 - ModelRoleUsage phase semantics are not enforced by the Method model router
Severity: **high**
Status: **verified**
Breakpoint: `ResearchModelRoleRequirement.usage -> MethodAgentLoopRouter`

Evidence:
- `ModelRoleUsage` defines `EXECUTION`, `EVALUATION`, and `BOTH`, with explicit `affects_execution` / `affects_evaluation` predicates.
- Experiment scientific identity separately digests execution model roles and evaluation model roles using those predicates.
- `PortfolioQualifiedModelResolver.method_agent_loop_router()` ignores `requirement.usage` and materializes every Study model role into the Method execution router.
- Repository-wide usage search shows no Method-router/runtime phase gate based on `affects_execution`.
- `MethodAgentLoopRouter.run()` authorizes solely by `request.agent_id`; it has no Study/model-usage context.

Semantic loss:
A role declared evaluation-only is promoted into the execution-time Method agent-loop namespace. The scientific phase boundary encoded in the Study is lost at runtime routing.

Impact:
Evaluation-only model bindings can be invoked from Method execution if a Method node names that role, and they also participate in the portfolio-global role collisions described in F-012. The execution/evaluation separation exists in identity but is not enforced by the runtime capability surface.

### F-015 - Automatic Experiment reconciliation fabricates a retry proof without consulting lower execution/effect authorities
Severity: **critical**
Status: **verified**
Breakpoint: `ResearchOSRuntime.reconcile_node(EXPERIMENTATION) -> CanonicalWorkloadExperimentReconciliation.reconcile()`

Evidence:
- `ResearchOSNodeReconciliationProof` is explicitly documented as a "Lower-authority proof for resolving one uncertain graph attempt" and requires non-empty `evidence_digests`.
- `CanonicalResearchOSRuntime.reconcile_node()` first trusts a terminal lower Machine commit when one exists. If the Experiment Machine has no terminal commit, it delegates to the Experiment runtime reconciliation authority.
- The canonical local materializer registers `CanonicalWorkloadExperimentReconciliation` for every automatic workload trial protocol.
- `CanonicalWorkloadExperimentReconciliation.reconcile()` performs no read of Machine Journal, Method evidence, Trial receipts, EffectIntentJournal, Environment state, durable Operation state, Artifact evidence, or provider reconciliation.
- It constructs `evidence = canonical_digest({closure_digest, protocol_digest, machine_id, attempt_id})` from identities already supplied to it, then returns `ResearchGraphReconciliationDisposition.RETRY` unconditionally.
- The proof's `authority_id` is the literal `"noetrium.auto.workload.reconciliation"`; its sole evidence digest is therefore a self-generated identity digest, not the digest of an independently accepted lower-authority record.
- Research OS accepts that typed proof and calls `resolve_reconciliation(... disposition=RETRY ...)`, making the graph attempt immediately retryable.

Semantic loss:
"Lower authority proved retry-safe" is collapsed into "the reconciliation adapter can deterministically hash the attempt identity." Unknown lower execution/effect state is not represented as indeterminate; it is converted into RETRY.

Impact:
After interruption/crash before an Experiment Machine reaches a terminal commit, ResearchGraph can authorize a retry without proving whether Trial/Method/Environment external effects are complete, pending, unknown, or already consumed. Inner effect mechanisms may later block or reconcile particular calls, but the Research OS recovery authority has already asserted a false stronger fact: that the whole Experiment attempt is retry-safe. This violates the fail-closed reconciliation contract and can hide unresolved lower-state obligations from graph recovery.

### F-016 - UniversalMethodMachine contains two execution-truth modes: Machine-authoritative and process-local
Severity: **critical**
Status: **verified**
Breakpoint: `MethodRuntimeContext.transitions optionality inside UniversalMethodMachine`
Audit dimension: **duplicate semantic implementation + authority split**

Evidence:
- `MethodRuntimeContext.transitions` is optional.
- `UniversalMethodMachine._initial_state()` has two independent state-authority branches:
  - when `runtime.transitions is not None`, it opens authoritative Method state through `MethodTransitionAuthorityPort`;
  - when it is `None`, it constructs and owns a local `_ExecutionState` directly.
- `_commit_authoritative_transition()` and `_commit_authoritative_control()` become no-ops when transitions are absent.
- `_save_checkpoint()` returns `None` when transitions are absent.
- resume is explicitly unavailable in the non-Machine mode, and child Machines are rejected there.
- Nevertheless both modes execute the same MethodProgram and return the same public `MethodRunResult` type.
- `MachineMethodRuntimeBinder` is an external optional binder rather than an invariant of UMM; direct construction of `MethodRuntimeContext` without transitions is supported and extensively tested.

Semantic duplication:
The same Method semantics have two engines of execution truth inside one class:
1. Machine Journal-backed authoritative execution;
2. process-local interpreter-owned execution with no accepted Machine history.

These are not interchangeable storage providers behind one authority contract: they have different resume, checkpoint, child-machine, durability, and accepted-transition semantics.

Impact:
The platform cannot claim one canonical Method execution mechanism while UMM itself remains valid without Machine authority. Any caller that omits the binder silently enters weaker semantics instead of failing closed. This preserves a second implementation mode that can drift from the canonical Machine-backed behavior.

### F-017 - Method node execution has both Operation-ABI and direct-handler paths, and the canonical ResearchOS path currently selects the direct path
Severity: **critical**
Status: **verified**
Breakpoint: `UniversalMethodMachine._invoke_sync/_invoke_async -> runtime.dispatcher optionality`
Audit dimension: **duplicate semantic implementation + canonical bypass**

Evidence:
- `UniversalMethodMachine._invoke_sync()` branches on `runtime.dispatcher`:
  - with a dispatcher, it wraps the node in `MethodNodeOperationAdapter.execute()`, producing an OperationResult and projecting effect receipts;
  - without a dispatcher, it directly calls `_invoke_node_body()` and treats the returned MethodNodeResult as the execution result.
- `_invoke_async()` repeats the same dual-mode structure.
- The two paths therefore differ in Operation identity/result/failure materialization/observation/admission semantics even though they execute the same Method node.
- `CanonicalResearchOSRuntime._execute_method()` creates `MethodRuntimeContext` without `dispatcher` or `async_dispatcher`; `bind_standard_method_runtime()` adds Machine transitions only and does not inject an Operation dispatcher.
- `PortfolioAutomaticTrialProviderResolver.resolve()` calls `compose_method_runtime_bindings(...)` without a dispatcher; that function's dispatcher defaults to `None`.
- Therefore both direct ResearchOS Method nodes and Study/Workload Method execution normally enter the direct-handler branch.
- This contradicts the documented canonical dataflow in which Method node execution crosses the Operation ABI before accepted Machine transition.

Semantic loss:
Operation ABI semantics are optional rather than intrinsic to Method execution. On the current canonical path, Method node invocation has stable Method operation-id strings but no authoritative OperationResult boundary for the node itself.

Impact:
The platform maintains two implementations of the same Method-node execution semantics, and the nominal canonical ResearchOS path chooses the weaker one. Failure/effect/admission behavior can therefore differ depending on whether an outer caller happened to inject a dispatcher. This is incompatible with the required single universal execution machine.

### F-018 - Noetrium maintains two overlapping programmable Machine IR/interpreter stacks: MethodProgram/UMM and ResearchProgram/ProgrammableMachineInterpreter
Severity: **critical**
Status: **verified**
Breakpoint: `MachineKind.METHOD special exclusion from ResearchProgram`
Audit dimension: **multiple universal machines / duplicated control semantics**

Evidence:
- `ResearchProgram` is documented as the "Universal programmable Machine IR for research semantics" and is executed by `ProgrammableMachineInterpreter -> MachineExecutor -> Machine Journal`.
- `PROGRAMMABLE_MACHINE_KINDS` includes Experiment, Run, Runtime, Participant, Memory, Environment, Evaluation, Optimization, Analysis and Publication, but deliberately excludes Method.
- `ResearchProgram.__post_init__()` explicitly rejects `MachineKind.METHOD` with `"Method uses MethodProgram/UMM"`; `ResearchProgramBuilder` repeats that exclusion.
- Method defines a second immutable graph IR (`MethodProgram + MethodGraph + MethodNodeSpec`) and a second interpreter (`UniversalMethodMachine`).
- Both stacks independently implement the same core programmable-machine mechanics:
  - immutable program identity/digest;
  - graph cursor and node routing;
  - per-node visit counts/limits;
  - mutable logical data/state and previous value;
  - node handlers/operations;
  - terminal completion/failure;
  - waiting/interrupt/resume semantics;
  - events;
  - child-machine links;
  - effect/evidence propagation;
  - accepted Machine transitions and Machine Journal integration.
- Method adds typed Agent/Capability/Schema conveniences, but those are semantic node/port specializations layered on top of the same general graph/state/control mechanics rather than a fundamentally different execution-truth problem.
- The two stacks carry different program schemas, interpreter digests, control/result types, checkpoint/interrupt representations and host APIs, so fixes to one do not mechanically apply to the other.

Semantic duplication:
There are two "universal" programmable execution machines. The general ResearchProgram machine is universal for every programmable MachineKind except the one domain with the richest agent semantics, while Method reimplements the programmable graph interpreter separately.

Impact:
Core execution semantics can diverge between Method and every other programmable domain. The already-observed Method-only direct-state/direct-operation modes are examples of divergence that the ResearchProgram path does not need. Under the required single-universal-machine architecture, Method specialization should not require a second graph/interpreter truth engine; otherwise every durability, recovery, routing, checkpoint, effect and child-machine invariant must be maintained twice.

### F-019 - ContextAction external action execution explicitly supports two semantic modes: direct and durable-journal
Severity: **critical**
Status: **verified**
Breakpoint: `ActionExecutionCoordinator.execute_prepared() -> effect_intents optionality`
Audit dimension: **duplicate effect machine + recovery semantic split**

Evidence:
- `WorkflowSurfaceBindingContext.effect_intents` is optional.
- `ContextActionSurfaceFactory` passes that optional value directly into `ContextActionTrialOperations -> SafeEnvironmentActionExecutor -> ActionSafetyAssembly`.
- `ActionSafetyAssembly` constructs `ActionExecutionCoordinator(journal_ops=effect_intents, ...)`.
- `ActionExecutionCoordinator` explicitly documents itself as selecting "direct or durable-journal action flow".
- When `journal_ops is None`, it calls `execute_direct_action()`, which dispatches the provider action and performs immediate result reconciliation without preparing/persisting an EffectIntent.
- When journal operations exist, it uses `JournaledActionExecutor`, which prepares an EffectIntent, records provider result, reconciles existing/prepared effects, records resolved/not-applied state and supports committed recovery.
- `CommittedActionRecovery` is also conditionally absent when journal operations are absent.
- Both paths expose the same `SafeEnvironmentActionExecutor` / `SafeActionExecution` surface despite materially different crash/replay/unknown-effect semantics.

Semantic duplication:
The same Environment action has two external-effect state machines:
1. direct provider execution + immediate reconciliation;
2. durable intent-first execution + recovery/reconciliation lifecycle.

This is not storage polymorphism. The presence of an optional collaborator changes the safety contract and available recovery semantics.

Impact:
Callers can silently enter a weaker action semantics by omitting `effect_intents`. External-effect truth is therefore composition-mode dependent rather than intrinsic to Environment action execution. Under a single universal mechanism, effectful actions should have one authoritative intent/reconciliation machine and fail closed when its authority is unavailable.

### F-020 - Environment external-effect orchestration exists twice above the same EnvironmentSession recovery contract
Severity: **high**
Status: **verified**
Breakpoint: `Environment action -> ContextAction JournaledActionExecutor OR generic CapabilityEffectExecutor`
Audit dimension: **parallel effect implementations with independent identities**

Evidence:
- The generic Method capability path uses `CapabilityEffectExecutor` with `execute_new_capability_effect()` / `resolve_existing_capability_effect()`, backed by `EffectIntentOperationPort`.
- `EnvironmentSessionCapabilityAdapter` adapts the same Environment `DurablePreparedActionSession` contract into that generic capability effect flow via `prepare_action_recovery / execute_prepared_action / reconcile_prepared_action`.
- The ContextAction workflow independently implements Environment effect orchestration through `SafeEnvironmentActionExecutor -> JournaledActionExecutor`, also backed by `EffectIntentOperationPort`, and drives the same prepare/execute/reconcile Environment session contract.
- The two orchestration stacks independently implement:
  - preflight/pending-effect guard;
  - recovery-handle preparation;
  - intent PREPARED;
  - provider execution;
  - result recording;
  - provider reconciliation;
  - reconciled/not-applied/consumed terminalization;
  - replay/committed recovery.
- They do not share one semantic coordinator. They have separate identity builders:
  - ContextAction: `build_action_effect_intent(... intent_namespace="environment-effect")`;
  - generic Capability: `build_capability_effect_intent(... intent_namespace="capability-effect-intent")`.
- `EffectIntent.build()` prefixes the intent id with the namespace and also hashes request/operation identity, so the two routes intentionally produce independent EffectIntent identities for otherwise equivalent physical Environment actions.
- Both ContextAction and agent-turn/generic capability surfaces remain exported composition implementations. The canonical local ResearchOS Environment path currently uses the generic capability route; the ContextAction implementation remains a second complete effect machine.

Semantic duplication:
Environment effect safety is not a single specialization of one generic effect machine. There are two separate orchestration implementations over the same lower Environment recovery protocol, with independently evolved state-transition rules and intent identities.

Impact:
Safety/recovery fixes must be applied twice and may drift. More seriously, the same physical logical action routed once through each surface is not guaranteed to collide in the EffectIntent authority because the two stacks use different semantic identities/namespaces. That weakens the "one external effect -> one authoritative intent lifecycle" invariant even though both use the same underlying EffectIntentJournal abstraction.

### F-021 - Experiment Trial provider identity does not bind the workload/Method runtime that it actually executes
Severity: **critical**
Status: **verified**
Breakpoint: `PortfolioAutomaticTrialProviderResolver -> WorkloadTrialProvider.identity_digest`
Audit dimension: **semantic identity loss + runtime-binding disconnect**

Evidence:
- `PortfolioAutomaticTrialProviderResolver.resolve()` constructs the actual execution chain:
  `MethodProgram -> compose_program_method_runtime_inventory() -> compose_method_runtime_bindings() -> DeclarativeWorkloadMethodCompiler -> WorkloadMethodBinding -> WorkloadGraphBinding -> WorkloadTrialProvider`.
- `DeclarativeWorkloadMethodCompiler.digest` explicitly commits to:
  - exact `MethodProgram.program_digest`;
  - exact resolved Method runtime binding digest;
  - input projection;
  - initial state/projection;
  - resume semantics.
- `MethodRuntimeBindingPlan` itself commits to the selected runtime-port identity digests.
- `WorkloadMethodBinding` owns the Method machine/compiler/result adapter, and `WorkloadGraphBinding` owns that task executor plus scheduling, but neither exposes an identity digest that is consumed by `WorkloadTrialProvider`.
- `WorkloadTrialProvider.__init__()` receives the concrete `workload`, validates only that it provides `execute_one/execute_graph`, then computes `identity_digest` from:
  - literal provider version;
  - protocol identity;
  - task projection identity;
  - measurement projection identity;
  - optional artifact publisher identity.
- The `workload` object, MethodProgram digest, Method compiler digest and Method runtime binding digest are absent from `WorkloadTrialProvider.identity_digest`.
- `ResearchOSExperimentTrialProviderBinding` then treats that provider identity digest as the exact Trial-provider identity, and `ResearchOSExperimentRuntimeBinding` incorporates the resulting adapter identity into its frozen runtime binding.

Semantic loss:
The frozen Experiment runtime identity proves which Trial-provider shell/projections were selected but not which executable workload, MethodProgram or Method runtime ports are inside that provider.

Impact:
Two materially different Method/workload implementations can produce the same `WorkloadTrialProvider.identity_digest` as long as protocol and projections match. The Research OS runtime binding can therefore remain identity-equal while the actual agent algorithm/model-capability runtime underneath it changes. This breaks exact scientific runtime closure and makes compile-time Study binding versus execution-time Method binding impossible to verify through the Experiment runtime identity alone.

### F-022 - WorkloadGraphBinding is a process-local task scheduler nested inside one Experiment Machine step
Severity: **critical**
Status: **verified**
Breakpoint: `ExperimentProgram.execute_batch handler -> WorkloadTrialProvider -> WorkloadGraphBinding.execute_graph()`
Audit dimension: **duplicate scheduler + recovery-granularity loss + semantic breakpoint**

Evidence:
- `WorkloadMethodBinding` explicitly states that ExperimentProgram/ResearchRunProgram own execution order and recovery through Machine Journal transitions.
- `WorkloadGraphBinding.execute_graph()` nevertheless owns a complete task-graph scheduler in process-local memory:
  - `pending = set(workload.task_ids)`;
  - `results: dict[str, WorkloadTaskResult]`;
  - a `while pending` ready-set loop;
  - dependency blocking;
  - ready-task selection;
  - sequential/TaskGroup parallel execution;
  - failure-scope propagation.
- `WorkloadGraphBinding` has no MachineJournalPort, checkpoint authority, durable cursor, attempt record or accepted task-transition store.
- `WorkloadTrialProvider.run_trial()` invokes `self._workload.execute_graph(...)` as one ordinary call and returns one TrialExecutionReceipt only after the entire assignment graph finishes.
- The outer Experiment ResearchProgram does not commit each workload task/assignment. Its `experiment.execute_batch` handler calls `self._execute_batch(batch)`, waits for all assignments in that batch to finish, and only then returns one `ProgramNodeResult` whose state update advances `batch_cursor` and appends all observations.
- Machine Journal acceptance therefore occurs only after the whole batch handler returns successfully.
- A crash after one or more inner tasks/assignments complete but before the batch handler returns leaves no Experiment Machine commit representing that inner progress.
- F-008 shows Trial receipts are not durably preserved on the canonical Study path, F-015 shows Experiment reconciliation currently returns RETRY without lower-state proof, and F-021 shows the frozen Trial-provider identity does not bind its workload/Method runtime.

Semantic duplication:
Execution order/recovery is split between:
1. the Machine-backed ExperimentProgram batch cursor; and
2. the process-local WorkloadGraphBinding ready-set scheduler inside one Machine node.

The inner scheduler is a second execution machine even though it is not represented as a Machine authority.

Impact:
Experiment recovery granularity is coarser than the scientific workload graph. After a mid-batch crash, already-completed tasks/Methods/effects can exist below an Experiment Machine cut that still says the batch was never accepted. The current automatic reconciliation then authorizes RETRY without reconstructing the inner scheduler state. This directly contradicts the stated ownership that Experiment/Run Machine Journal transitions own workload execution order and recovery.

### F-023 - Canonical local Minecraft execution bypasses the platform EnvironmentInstanceLeaseAuthority and owns a second environment-instance lifecycle
Severity: **critical**
Status: **verified**
Breakpoint: `LocalMinecraftLifetimeSessionAuthority.session_for() -> private runtimes dict`
Audit dimension: **duplicate lifecycle authority + disconnected generic mechanism**

Evidence:
- Platform composition creates one `EnvironmentInstanceLeaseAuthority` over the authoritative Environment catalog plus Resource ownership/leases.
- That authority defines the generic reusable-instance lifecycle: acquire/recover, CLEAN/IN_USE/DIRTY transitions, binding scope, fencing lease, heartbeat renewal, release with cleanliness proof, crash reconciliation and shutdown quarantine.
- `ManagedResourceReconciler` includes that authority as the canonical Environment stage between Docker and endpoint cleanup.
- `ResearchExecutionPool.environment_instance_lease_guard_factory()` exists to renew those Environment instance leases.
- Repository-wide usage shows no Environment runtime/provider actually acquiring `EnvironmentInstanceLeaseAuthority`; outside its construction/reconciler/factory definition, the authority is not consumed by the canonical local Environment path.
- `LocalMinecraftLifetimeSessionAuthority` instead owns `self.runtimes: dict[str, _LifetimeRuntime]` keyed by `lifetime_id`.
- `session_for()` creates a Minecraft branch runtime directly and stores it only in that process-local dictionary.
- `release()` pops the dictionary entry, closes the branch and deletes the workdir.
- The Minecraft lifetime authority receives endpoint allocation and Docker lease authorities, but it does not acquire/register an `EnvironmentInstance`, `EnvironmentBinding`, or `EnvironmentInstanceLeaseHandle`.
- Consequently the platform Environment catalog/lease authority has no record of the live Minecraft assignment generation that the Method is actually using.

Semantic duplication:
Environment instance ownership exists in two implementations:
1. the generic catalog + EnvironmentInstanceLeaseAuthority lifecycle designed as the platform authority;
2. a Minecraft-specific process-local lifetime dictionary plus branch close/delete lifecycle.

The second implementation bypasses the first rather than specializing it.

Impact:
The ResourceReconciler's Environment stage cannot reconcile, dirty, fence or reason about the actual Minecraft generations because they were never admitted to its authority. Docker and endpoint layers may still physically converge after a crash, but Environment-level generation/binding/cleanliness/reuse truth is absent. The generic Environment instance machine therefore exists without governing the canonical Environment execution path, violating the single-authority/single-mechanism requirement.

### F-024 - Experimentation retains an independent Run/Workload checkpoint-and-restore engine whose execution cut is not a Machine cut
Severity: **high**
Status: **verified**
Breakpoint: `research/experimentation/lifecycle/checkpoint -> component restore outside Machine authority`
Audit dimension: **second recovery machine / competing execution-cut model**

Evidence:
- The canonical ResearchOS checkpoint explicitly declares itself non-authoritative and proves lower state with `MachineCut`; `MethodCheckpoint` likewise declares itself a non-authoritative receipt for a verified Machine journal cut.
- Separately, `research/experimentation/lifecycle/checkpoint` exports a complete Run/Workload checkpoint subsystem:
  - `RunCheckpointManifest/Bundle`;
  - `WorkloadCheckpointManifest/Bundle`;
  - `CheckpointCoordinator`;
  - capture/store/publication/recovery;
  - restore with preimage capture and rollback;
  - its own GC/persistence state and recovery errors.
- `WorkloadExecutionCut` is its own task-boundary cursor containing completed task ids, current task id, decision-cycle id and status. It is not `MachineCut` and carries no Machine id, revision or commit id.
- `RunCheckpointManifest` also carries experiment/run/session/decision-cycle identities and participant snapshots but no Machine cut linkage.
- `restore_workload_checkpoint()` validates this independent manifest/binding topology, captures component preimages, then directly invokes `component.restore(payload)` to mutate workload component state.
- `RunCheckpointRestorer` similarly loads its bundle and directly restores participant sessions through participant checkpoint operations.
- Repository-wide production/composition search finds no current canonical ResearchOS consumer of `run_checkpoint_coordinator()` or `workload_checkpoint_coordinator()`; current consumers are primarily tests. The subsystem remains formally exported from the Experimentation lifecycle API.

Semantic duplication:
Noetrium currently has two recovery-cut concepts:
1. authoritative Machine Journal cut with non-authoritative checkpoint projections;
2. an independent Experimentation Run/Workload execution cut capable of restoring component/participant state without proving alignment to a Machine commit.

The second is not merely a payload codec for the first; it owns capture/restore coordination and a separate execution cursor.

Impact:
Although the canonical ResearchOS path currently appears not to use this older/parallel checkpoint engine, the platform still exposes a second valid recovery mechanism with different authority semantics. A caller can restore participant/workload state to a task-boundary cut that the Machine Journal has not accepted, reintroducing split recovery truth. Under the single-universal-machine requirement, component snapshots may remain as payloads, but restore authority/cut ownership cannot remain independent of the Machine cut.

### F-025 - The authoritative forensic FailureEnvelope/FailureRecorder system is not wired into canonical ResearchOS execution
Severity: **critical**
Status: **verified**
Breakpoint: `canonical Operation/Method/Graph failure -> no OperationForensicFailureSink`
Audit dimension: **disconnected authority + semantic provenance loss**

Evidence:
- Reliability defines a rich authoritative failure record, `FailureEnvelope`, containing failure_id, component/operation/invocation identity, taxonomy domain/code/stage, ExecutionContext, cause type/message/chain digest, retryability/recoverability, integrity/comparability/scientific-risk levels, effect certainty, request/effect/state/correlation refs and recommended recovery.
- `FailureRecorder` documents its ledger append as authoritative failure truth; event/index writes are explicitly secondary projections.
- `OperationForensicFailureSink` is the Kernel `OperationFailureSink` adapter that classifies an exception, records it through `FailureRecorder`, and returns the authoritative `failure_id`.
- `build_operation_executor()` exists specifically to compose a Kernel OperationExecutor with failure and observability projections.
- Repository-wide production search finds no canonical construction of `OperationForensicFailureSink` and no production call to `build_operation_executor()`.
- The only direct `FailureRecorder` construction is inside `OperationForensicFailureSink`; the forensic store is otherwise opened by diagnostic/read/rebuild utilities.
- Canonical local Environment currently constructs bare `OperationExecutor()` with no failure sink (F-010).
- Canonical Method node execution normally bypasses Operation dispatch entirely (F-017).
- Service-crash failure handoff is also not wired into ManagedResearchRuntime; `DurableServiceCrashCoordinator` call sites are tests.
- Search of Method workflow, ResearchGraph and ResearchOS composition finds no propagation of `failure_id` from lower execution into their failure records/receipts.

Semantic loss:
The platform has an intended single rich forensic failure authority, but canonical scientific execution normally never materializes failures into it. Instead failures are represented independently as Method strings/codes/phases and Graph type/message fields.

Impact:
The system can capture enough local text to diagnose some failures, but cannot guarantee one durable failure identity that joins Operation, Machine, Method, Experiment, Graph and public ResearchOS inspection. This explains why lower logs can contain useful exception text while top-level receipts have no authoritative causal/evidence reference. The failure authority exists architecturally without governing the main execution path.

### F-026 - Durable Operation, Method and Graph maintain separate failure representations instead of referencing one failure identity
Severity: **high**
Status: **verified**
Breakpoint: `FailureEnvelope -> OperationFailure -> MethodRunResult -> ResearchGraphNodeExecutionRecord`
Audit dimension: **multiple failure truths + identity loss**

Evidence:
- Reliability's authoritative failure type is `FailureEnvelope(failure_id, ...)`.
- Execution's durable Operation authority defines a separate `OperationFailure(kind, code, message, retryable, reconciliation_required)` embedded in `OperationSnapshot`; it has no explicit `failure_id` or forensic-record reference field.
- `DurableKernelOperationDispatcher` handles a failed Kernel OperationResult by constructing that separate OperationFailure. When a forensic `result.failure_id` exists, it places the failure id into the generic `OperationFailure.code` field; otherwise it uses `"OPERATION_FAILED"`.
- Method failure control stores `failure` text plus `failure_code` and `failure_phase`; MethodRunResult has no `failure_id`.
- ResearchGraph durable node state then stores only `failure_type` and `failure_message`.
- ResearchOS public execution receipt drops even those fields (F-001).
- Repository-wide search of the Method/Graph/ResearchOS path finds no explicit lower forensic failure reference carried through these layers.

Semantic duplication:
Failure state is independently re-encoded at multiple layers rather than projected from/referenced to one authoritative failure identity:
1. forensic FailureEnvelope;
2. OperationFailure;
3. Method failure text/code/phase;
4. Graph failure type/message;
5. ResearchOS failed-node ids.

Impact:
Each upward transition can change taxonomy and discard causality. Even when a forensic failure was recorded, higher layers cannot deterministically join back to it. Under the single-authority requirement, layers may retain status projections, but the authoritative failure id/causal reference must remain invariant rather than being repackaged into unrelated local failure schemas.

### F-027 - Scientific Study model bindings and the Method execution model router are resolved independently and never equality-checked
Severity: **critical**
Status: **verified**
Breakpoint: `ResearchBindingAuthority.resolve(study) || method_agent_loop_router(portfolio)`
Audit dimension: **binding semantic disconnect + duplicate resolution authority**

Evidence:
- `LocalResearchExecutionAuthorityMaterializer.materialize()` creates one `PortfolioQualifiedModelResolver`.
- Before any Study closure is compiled, it calls `model_resolver.method_agent_loop_router(portfolio, context)`, which independently materializes every model role by calling `_qualified_binding()` or the operational fallback and builds the concrete physical replica-set-backed `MethodModelAgentLoop` objects.
- The same materializer separately exposes `ResearchBindingAuthority(..., model_resolver)` as the scientific binding authority.
- Later, `ResearchStudyProtocolClosureProvider.resolve()` calls `self._research_bindings.resolve(study)`; this invokes the model resolver again and freezes exact `ResearchModelRoleBinding` rows into the Study/ResearchPlan binding digest.
- `ResearchModelRoleBinding.binding_digest` commits to the exact `ProjectModelBinding.digest()` and binding proof, including deployment generation and provenance.
- `PortfolioAutomaticTrialProviderResolver.resolve(closure)` receives this frozen closure but does not inspect `closure.research_plan` model-role bindings when selecting Method runtime ports. It uses the already-created global `self.runtime_inventory.agent_loop`.
- `compose_method_runtime_bindings()` verifies only that the Method's required agent ids exist in the inventory and incorporates the router identity into a Method runtime binding plan. It does not compare the router's bound model/deployment generation against the Study's frozen `ResearchModelRoleBinding`.
- F-021 further shows the Trial-provider/Experiment runtime identity does not bind that Method runtime digest, so the outer Experiment closure cannot detect the mismatch through provider identity.
- Both resolution passes may often select the same live state, but no invariant requires this; the resolver itself is time-sensitive (qualified candidates are ordered by runtime qualification heartbeat; operational bindings inspect/start current deployment generations).

Semantic loss:
"Noetrium scientifically bound this role to exact model/deployment/proof X" and "Method execution will dispatch this role to physical model/router Y" are separate facts produced by separate resolution passes. The execution path does not prove X == Y.

Impact:
A model deployment/qualification generation can change between or around the two resolutions without changing the frozen Study semantics that the Experiment reports. The platform can therefore execute Method requests through a model binding that is not the binding committed by the scientific ResearchPlan. Under one binding authority, exact model resolution must be performed once (or revalidated against the frozen binding) and the same immutable binding identity must flow into execution.

### F-028 - Frozen participant topology/schedule is identity-only; automatic Trial execution collapses all participants into one MethodProgram
Severity: **critical**
Status: **verified**
Breakpoint: `ResearchStudyDefinition participants -> TrialExecutionRequest.participant_schedule -> WorkloadTrialProvider`
Audit dimension: **semantic loss + multi-agent topology collapse + duplicate/unused participant runtime abstraction**

Evidence:
- Study participant requirements carry role, participant kind, Method id, treatment id, capability/configuration refs and `depends_on_roles`.
- `ResearchBindingAuthority._participant_bindings()` resolves every role to an exact `ProjectParticipantBinding` and proof.
- `compile_research_plan()` preserves those bindings as `ExperimentParticipantSpec`, including `depends_on_roles`.
- `ExperimentParticipantTopology.from_spec()` derives dependency waves; `ParticipantSchedule` freezes those waves and its digest is included in `RunResearchSemanticsReference`.
- `_TrialBoundStudyExecution._request()` carries that frozen participant-schedule identity into every `TrialExecutionRequest`.
- Repository-wide search of the canonical Trial/Workload path finds no consumer of `request.participant_schedule`; `WorkloadTrialProvider` never reads it.
- The same canonical path does not consume `ResearchParticipantBinding`, `ExperimentParticipantSpec`, `BoundParticipants`, or participant sessions during Trial execution.
- `PortfolioAutomaticTrialProviderResolver.resolve()` instead takes only the participant requirements, extracts the set of `method_id` values, requires exactly one unique MethodProgram, and constructs one `DeclarativeWorkloadMethodCompiler` around that program.
- If multiple participant roles reference the same MethodProgram, their roles/dependency waves/treatment-specific participant bindings collapse into that single Method execution.
- If the Study uses multiple MethodPrograms for multiple participants, the resolver rejects it and instructs the paper to author one composite MethodProgram.
- `WorkloadTrialProvider.run_trial()` then executes that one workload/Method for the task graph; no participant role/session/topology is supplied to the Method invocation.

Semantic loss:
The platform can author and scientifically digest an explicit multi-participant topology, but the canonical automatic runtime does not execute that topology. Participant scheduling is retained as identity metadata while runtime semantics are reduced to one MethodProgram per task.

Impact:
A Study can report a participant/topology/schedule digest that did not govern execution. Sequential/dependent participants, user simulators as independent Participants, and multi-agent role-specific runtime state cannot be represented faithfully by the automatic Trial path unless downstream manually collapses them into one composite MethodProgram. That shifts generic participant orchestration back into paper Method code and leaves the platform's Participant binding/session machinery disconnected from the canonical ResearchOS path.

### F-029 - Experimentation owns an independent RunArtifact authority parallel to the platform's canonical Artifact authority
Severity: **critical**
Status: **verified**
Breakpoint: `ResearchOS Experiment report publication -> DirectoryRunArtifactStore`
Audit dimension: **duplicate authority + duplicate content/retention lifecycle**

Evidence:
- The live system registry declares `artifact` as a top-level authority with canonical ownership of "immutable content identity, references, retention and catalog", implemented under `noetrium_platform.evidence.artifact`.
- That canonical Artifact system provides ArtifactRegistry, content/blob identity and lifecycle, references, lineage and retention authorities.
- Experimentation separately exports `RunArtifactStorePort` and `DirectoryRunArtifactStore`, documented as a "crash-safe run-local artifact authority".
- Experimentation's reproducibility contract explicitly states `DirectoryRunArtifactStore.finalize()` is the authority boundary that snapshots a completed artifact and emits the typed authoritative `RunArtifactSnapshotReceipt`.
- `DirectoryRunArtifactStore` independently owns:
  - content snapshot/hash identity;
  - logical seals;
  - generation ledgers;
  - finalized-receipt verification;
  - physical carrier generation;
  - retirement intent;
  - quarantine;
  - GC eligibility/proof and purge.
- Its implementation imports/uses none of the canonical `ArtifactRegistryPort`, ArtifactReference, canonical artifact lineage or retention authorities; repository inspection finds no registration/projection of finalized RunArtifactSnapshotReceipts into the Artifact authority.
- `CanonicalResearchOSRuntime._publish_experiment_report()` binds this run-local store and publishes protocol/observations/aggregates/report-manifest directly through it.
- The returned ResearchOS report reference contains RunArtifact snapshot receipt JSON, not a canonical Artifact authority identity/reference.
- Therefore the canonical ResearchOS Experiment path itself uses the parallel Experimentation artifact truth, not merely legacy/test code.

Semantic duplication:
Two authorities independently own immutable artifact identity and lifecycle:
1. the registered platform Artifact authority;
2. Experimentation's RunArtifactStore authority.

The second is not a provider behind the first; it has its own identity, seal, retention/retirement and GC semantics.

Impact:
Artifact identity/retention/lineage semantics can diverge by execution path. A ResearchOS Experiment report can be scientifically finalized and GC-governed by RunArtifactStore while being unknown to the platform's canonical Artifact registry/lineage/retention authority. Under the single-authority requirement, run-local layout/sealing may remain an implementation detail or carrier provider, but immutable artifact identity, references and retention truth must be owned by one Artifact authority.

### F-030 - Method evidence has no authoritative reference path into Workload/Trial/Experiment evidence
Severity: **high**
Status: **verified**
Breakpoint: `MethodEvidencePort -> WorkloadMethodReceipt -> TrialExecutionReceipt.evidence_refs`
Audit dimension: **evidence provenance break + disconnected evidence authorities**

Evidence:
- Durable declarative Method execution creates a per-task `DirectoryEventMethodEvidence` under the Method workload state root and records Method checkpoints/results there.
- `MethodRunResult` exposes only `evidence_status` as its evidence summary; it carries no authoritative evidence ArtifactReference/store receipt for the files produced by `MethodEvidencePort`.
- `WorkloadMethodBinding.execute()` projects the Method result into `WorkloadMethodReceipt` containing only run_id, program_digest, run_digest, status, step_count and evidence_status.
- The Workload result diagnostics add the Method run/program digests, but no evidence reference or evidence-store identity.
- `DeclarativeExecutionResultAdapter` likewise emits only method_run_digest/method_status/model-call count plus explicitly selected exports.
- Normal `WorkloadTrialProvider.run_trial()` constructs `TrialExecutionReceipt` with only request digest, assignment digest and measurements; its `evidence_refs` therefore remains empty.
- Repository search shows Trial `evidence_refs` are populated on the verifier-artifact path, but not from Method evidence.
- F-008 then drops Trial receipt provenance when projecting to StudyMetricObservation, so the Experiment report cannot recover a Method evidence reference later.
- The Method evidence directory is also not published through the canonical Artifact authority or the Experimentation RunArtifact evidence-bundle path.

Semantic loss:
"Method evidence was complete/incomplete" survives as a status bit, but the identity/location of the evidence that supports that status does not cross the Workload/Trial boundary.

Impact:
A final Study/Experiment result can say a Method run had COMPLETE evidence without carrying an authoritative reference to that evidence. Operators and reproducibility tooling must infer filesystem paths from implementation conventions rather than follow a typed evidence lineage. Under one evidence/artifact authority model, Method evidence should be materialized once into an immutable reference and that reference should survive Trial, Experiment and ResearchOS projections.

### F-031 - Bounded model-panel semantics exist in Study IR but canonical model resolution collapses every role to one member
Severity: **high**
Status: **verified**
Breakpoint: `ResearchModelRoleRequirement.max_bindings/member_index -> PortfolioQualifiedModelResolver.resolve()`
Audit dimension: **authoring/runtime semantic loss + cardinality collapse**

Evidence:
- `ResearchModelRoleRequirement` explicitly documents that a named role "may resolve to a bounded model panel" and carries `max_bindings: int | None`.
- `ResearchBindingAuthority._model_bindings()` is designed for multiple resolutions: it iterates all returned bindings, assigns monotonically increasing `member_index`, and validates `max_bindings`.
- `ResearchModelRoleBinding`, `ExperimentModelRoleSpec`, Experiment identity and evaluation contracts all preserve `(role, member_index)`, so multi-member roles are first-class scientific semantics.
- The canonical local `PortfolioQualifiedModelResolver.resolve()` always returns a tuple containing at most one bound `BindingResolution`.
- `_qualified_binding()` may discover multiple qualified candidates, but:
  - if they represent different model stacks/deployment generations/models/revisions it raises instead of returning a panel;
  - if they represent the same generation it sorts by heartbeat/path and selects only `candidates[0]`.
- The operational fallback similarly builds one `ProjectModelBinding`; multiple running replicas are collapsed into one physical replica set for that one binding, not exposed as multiple scientific model members.
- Consequently canonical `ResearchBindingAuthority` receives at most one bound resolution for a role and `member_index` remains 0.
- `MethodAgentLoopRouter` is also keyed by role only and cannot address `(role, member_index)`.

Semantic loss:
The scientific IR distinguishes "multiple model members in one role/panel" from "multiple physical replicas of one model binding", but canonical local resolution collapses both to one role-level binding.

Impact:
Ensemble/panel/evaluator-jury/multi-model role designs can be authored and digested by the Study model but cannot be faithfully materialized by `open_project().run()`. Downstream would need to encode the panel manually inside one Method/role, again moving generic model cardinality/orchestration out of the platform. A single universal binding mechanism should preserve the IR cardinality rather than exposing a wider scientific contract than the runtime can execute.

### F-032 - ResearchGraphScheduler contains separate process-local and durable execution-state machines
Severity: **high**
Status: **verified**
Breakpoint: `ResearchGraphScheduler.execute() -> execution_store optionality`
Audit dimension: **duplicate scheduler implementation + weaker fallback semantics**

Evidence:
- `ResearchGraphScheduler.execute()` explicitly selects one of two implementations:
  - when `execution_store is None`, an in-process scheduler owns `pending/running/results` dictionaries and a local completion queue;
  - when an execution store is supplied, `_execute_durable()` owns durable node/attempt/control state through `ResearchGraphExecutionStorePort`.
- The process-local branch implements dependency ready-set scheduling and failure/block propagation but has no durable attempt identity, leases, owner generation, retry state, per-node/global control records, reconciliation-required state, active-cut fencing or restart recovery.
- The durable branch implements those semantics through `ResearchGraphNodeExecutionRecord`, attempt records, lease renewal/recovery, control stores, cut state and reconciliation.
- Both modes accept the same `ResearchGraphPlan`, invoke the same `ResearchGraphNodeExecutorPort`, and return the same `ResearchGraphExecutionReport`.
- `bind_research_portfolio_scheduler()` publicly accepts optional `execution_store/execution_id`, so callers can silently select either semantic mode.
- The canonical ResearchOS `ResearchControlAuthority._drive()` does correctly pass its SQLite-backed graph store and therefore currently uses the durable mode.

Semantic duplication:
The same ResearchGraph orchestration semantics have two state machines inside one scheduler: a local ephemeral implementation and a durable authority-backed implementation. They are not merely two storage providers behind one state authority because control, retry, fencing and reconciliation semantics exist only in the durable branch.

Impact:
Canonical ResearchOS currently chooses the stronger branch, but the platform still treats the weaker branch as a valid execution mode. Graph behavior and recoverability therefore depend on whether a caller remembered to inject an execution store. Under the one-mechanism requirement, graph state authority should be intrinsic; an in-memory provider may implement that authority for isolated tests, but it should not switch the scheduler into a different semantic engine.

### F-033 - Reusable Machine constructors silently default to process-local journals instead of durable authority
Severity: **high**
Status: **verified**
Breakpoint: `Machine-backed domain constructor -> omitted journal/state_root -> InMemoryMachineJournal`
Audit dimension: **durability semantic downgrade + caller-owned authority wiring**

Evidence:
- `MachineMethodRuntimeBinder/_bind_machine_method_runtime()` documents that `state_root=None` creates `InMemoryMachineJournal + InMemoryMachineSnapshotStore`; only an explicitly supplied root makes Method execution crash-durable.
- `RuntimeProgramTrialProtocol` accepts `journal=None` and silently creates `InMemoryMachineJournal()`.
- `ExperimentProgramBinding.open_session()` accepts `journal=None` and silently creates `InMemoryMachineJournal()`.
- `StateMachineEnvironmentRuntime` accepts `journal=None` and silently creates `InMemoryMachineJournal()`.
- `AgentMemory.create_default()` accepts `journal=None` and silently creates `InMemoryMachineJournal()`.
- These objects are production execution/runtime classes, not isolated test-only fake implementations.
- The canonical ResearchOS path explicitly supplies durable state for several of them, so the primary top-level path is stronger; however durability is still an opt-in property of the reusable constructors.
- F-009 is the concrete canonical failure mode created by this design pattern: Environment capability mediation actually instantiated a process-local Machine journal.

Semantic issue:
The execution semantics remain on the same Machine interpreter, but the persistence/recovery contract silently changes when an optional argument is omitted. A caller can construct a valid-looking Method/Trial/Experiment/Environment/Memory machine whose accepted history disappears on process loss.

Impact:
Durability is effectively delegated to every composition caller rather than guaranteed by the platform. This creates repeated wiring burden and makes future composition paths prone to shadow process-local histories. Under the requested architecture, durable authority should be the default/intrinsic production binding; process-local journals should require an explicit test/ephemeral provider choice rather than arise from omission.

### F-034 - The public "platform-resolved" ResearchDefinition surface has no generic authority-resolution path
Severity: **critical**
Status: **verified**
Breakpoint: `ResearchProgram platform_resolved definitions -> ResearchOS lowering -> local execution authority materialization`
Audit dimension: **authoring/execution semantic gap + disconnected platform authorities**

Evidence:
- Public/root authoring intentionally supports implementation-free definitions such as `model()`, `environment()`, `benchmark()`, `dataset()`, `protocol()` and `resource_policy()`; tests explicitly call these "platform-resolved requirements".
- The unified-API test freezes a Study containing implementation-free MODEL, ENVIRONMENT, DATASET, PROTOCOL and RESOURCE_POLICY definitions and asserts that every one is `platform_resolved`.
- The corresponding portfolio-binding test verifies only commit/CAS/diff round-trip for that declarative shape; it does not execute it.
- `ResearchOSLoweringCompiler.compile_node()` handles every definition with `implementation is None` uniformly by putting it into `platform_requirements`.
- For non-Experimentation targets, `CanonicalResearchOSRuntime.admit()` rejects any remaining `platform_requirements` as unresolved; there is no generic platform-definition resolver between lowering and admission.
- For Experimentation targets, admission bypasses that generic unresolved-requirement rejection because execution is delegated to a Study closure. However the default `ResearchStudyProtocolClosureProvider._study()` requires exactly one PROTOCOL definition whose `implementation is not None`; an implementation-free PROTOCOL is explicitly rejected. A dedicated test asserts this rejection.
- A test that runs an Experiment node whose source PROTOCOL is config-only succeeds only because it manually injects a custom Experiment closure provider carrying a separately constructed `ResearchStudyDefinition`; that is not the default local `open_project()` authority materializer.
- Production-wide enum-reference search finds no consumer at all for `ResearchDefinitionKind.DATASET`, `ResearchDefinitionKind.BENCHMARK` or `ResearchDefinitionKind.RESOURCE_POLICY` outside their authoring builders. In particular:
  - the platform has a canonical `DatasetRegistryPort`, but ResearchProgram DATASET definitions are never resolved against it;
  - the Resource system owns physical scheduling/admission, but ResearchProgram RESOURCE_POLICY definitions are never translated into a resource-policy/demand binding;
  - top-level BENCHMARK definitions are not resolved into the Study benchmark authority.
- `derive_research_project_manifest()`, the default Study execution-view manifest compiler, consumes Study capability requirements, participant Method requirements and CONFIGURATION definitions; it does not consume top-level DATASET, BENCHMARK or RESOURCE_POLICY definitions.
- MODEL/ENVIRONMENT receive paper-specific/default-local handling elsewhere, demonstrating that the missing generic resolver is not merely a naming issue: resolution coverage is definition-kind-specific and incomplete.

Semantic loss:
The public Research OS authoring model says a definition can be platform-resolved, but there is no single platform authority that turns that declaration into an exact bound runtime/scientific fact. Some kinds have bespoke composition paths, some require downstream implementation despite the flag, and some currently have no execution consumer at all.

Impact:
A ResearchProgram can freeze, commit, diff and expose a scientifically meaningful declarative requirement that the default execution plane cannot materialize. This makes "expressible by the top-level API" strictly broader than "executable through api.open_project(...).run()". It also forces each future definition kind to grow bespoke composition logic. Under the desired architecture, platform-resolved definitions need one canonical typed resolution/binding mechanism that dispatches to the owning authority (Data, Resource, Environment, Model, Experimentation, etc.) and freezes that exact binding into the execution closure before admission.

### F-035 - Program-scoped CHILD_MACHINE definitions affect semantic identity but are never materialized into the Method child-machine runtime
Severity: **critical**
Status: **verified**
Breakpoint: `ResearchProgramBuilder.child_machine_program() -> compose_program_method_runtime_inventory()`
Audit dimension: **semantic identity/runtime disconnect + dead authoring primitive**

Evidence:
- `ResearchProgramBuilder.child_machine_program()` is a first-class public authoring primitive whose docstring says it declares a Program-scoped nested ResearchMachine host and is "auxiliary runtime authority for MethodPrograms in this ResearchProgram".
- `ResearchDefinition.__post_init__()` requires every CHILD_MACHINE definition to carry an exact `ResearchMachineProgramImplementation`.
- `ResearchProgram` explicitly forbids attaching CHILD_MACHINE definitions to individual nodes because they are Program-scoped auxiliary declarations.
- `compile_research_portfolio_graph()` deliberately injects the digest of every Program-scoped CHILD_MACHINE definition into every node semantic digest, so changing a child declaration changes parent node scientific identity.
- A committed test, `test_canonical_runtime_auto_binds_program_scoped_child_machine`, constructs:
  - a parent MethodProgram requiring `MethodRuntimePort.CHILD_MACHINES`;
  - one `builder.child_machine_program("test.child-memory", ...)`;
  - a canonical local ResearchOS run;
  and explicitly expects the child host to be auto-injected and executed.
- The only canonical program-scoped Method runtime composition function is `compose_program_method_runtime_inventory()`, called by both direct ResearchOS Method binding and automatic Study/Workload Trial binding.
- That function does not inspect `ResearchDefinitionKind.CHILD_MACHINE` at all. Its `owned_components` tuple is built only from definitions whose implementation is `ResearchMethodImplementation`, then from `definition.implementation.resolve().components`.
- It creates `ResearchProgramHost` registrations only for those Method-owned components.
- Production-wide enum-reference search shows the only references to `ResearchDefinitionKind.CHILD_MACHINE` outside authoring are ResearchProgram validation and ResearchGraph semantic-digest construction; there is no runtime resolver/materializer for the child definition itself.
- The current dirty-worktree change in `research_child_machine_runtime.py` removes the old `ProgramScopedChildMachineRouter` and merges any already-present base `ChildResearchMachineExecutor` registrations, but still does not materialize CHILD_MACHINE definitions.
- The committed HEAD version has the same fundamental omission: its router only routes between already-created `method.components` hosts and a base child port; it also never resolves Program-scoped CHILD_MACHINE definitions.
- Therefore this is not a transient effect of the current parallel edit.

Semantic loss:
Program-scoped child declarations participate in scientific identity as if they govern execution, but the canonical Method runtime inventory never turns those declarations into executable child hosts. Only child components embedded inside a ResearchMethod configurer are actually registered.

Impact:
A downstream author can declare a child ResearchMachine through the highest-level API, obtain a different frozen program/node digest, and satisfy the intended authoring shape while the Method runtime still reports CHILD_MACHINES missing or cannot resolve the declared host. This also forces nested-Machine semantics back into Method-specific component construction, duplicating what the top-level CHILD_MACHINE primitive claims to own. Under the unified architecture, Program-scoped child definitions must be materialized once by the canonical ResearchProgram binding/compiler into the same `ChildResearchMachineExecutor` and shared Machine Journal used by the parent.

### F-036 - ResearchValueKind is nominal at the execution boundary; the default value plane collapses every kind into one generic Artifact-backed JSON authority
Severity: **high**
Status: **verified**
Breakpoint: `ResearchGraph node result -> publish_research_os_node_outputs() -> ResearchOSImmutableValueAuthority`
Audit dimension: **typed-semantic loss + lower-authority identity collapse**

Evidence:
- `ResearchValueKind` declares six semantically distinct edge kinds: ARTIFACT, EVIDENCE, CHECKPOINT, SELECTION, METRIC and DATA.
- `ResearchOSValueReference` documents itself as a routing envelope in which "the named lower authority remains the value truth".
- `ResearchOSValueRouter` is designed to route kinds to explicit lower authorities and rejects multiple authorities for the same kind.
- The default local ResearchOS composition registers exactly one authority:
  `ResearchOSImmutableValueAuthority(blobs, registry, retention)`.
- That implementation declares `supported_kinds = frozenset(ResearchValueKind)`, so all six semantic kinds resolve to the same authority id, `artifact.catalog+blob.scientific-values`.
- `publish_research_os_node_outputs()` performs no kind-specific validation. For every declared output it takes the node's raw `JsonValue`, freezes it, and sends it directly to the selected value authority.
- `ResearchOSImmutableValueAuthority.publish()` serializes that raw JSON into the Artifact Blob CAS and registers every kind as `ArtifactKind.SCIENTIFIC`; the only kind distinction retained is a metadata string `research_value_kind`.
- There is no requirement that:
  - EVIDENCE values contain an authoritative evidence manifest/reference;
  - CHECKPOINT values contain a MachineCut/checkpoint authority reference;
  - METRIC values satisfy a measurement definition/value contract;
  - SELECTION values satisfy a selection/candidate identity contract;
  - DATA values reference Data/Dataset authority.
- Tests confirm that kind enforcement is currently only nominal/routing-level: arbitrary JSON such as `{"candidate_id": "c-1"}` is accepted as SELECTION, and the primary cross-kind invariant tested is merely that reuse cannot relabel DATA as METRIC.
- Repository-wide production/test search finds no dedicated producer contract for `ResearchValueKind.EVIDENCE` or `ResearchValueKind.CHECKPOINT`.

Semantic loss:
The edge kind survives as a label, but the payload's lower semantic authority and schema do not. The default authority becomes the truth for the serialized envelope itself rather than requiring an immutable reference to the actual Evidence/Checkpoint/Metric/Data owner.

Impact:
A node can emit arbitrary JSON while declaring it EVIDENCE or CHECKPOINT and still obtain a valid, retained, reusable ResearchOSValueReference. Downstream nodes see a typed edge name but cannot prove the value is owned by or consistent with the corresponding lower authority. Under the single-authority design, the ResearchOS value plane may use Artifact CAS as a carrier, but each semantic kind should require a typed authoritative reference/proof from its owning subsystem rather than treating the kind as metadata over unrestricted JSON.

### F-037 - StudyExecutionPolicy freezes TrialBudget and ReplayLevel as scientific semantics but canonical execution does not enforce them
Severity: **critical**
Status: **verified**
Breakpoint: `ResearchStudyDefinition.execution_policy -> compiled StudyProtocol/ExperimentProgram -> Trial/Method runtime`
Audit dimension: **scientific policy semantic loss + identity-only guarantees**

Evidence:
- `StudyExecutionPolicy` documents itself as the "Complete execution semantics for one scientific Study" and explicitly states that trial budget, replay guarantee and concurrency are one identity-bearing policy and must not be inferred.
- `ReplayLevel` is not merely descriptive metadata:
  - EXACT claims the bound execution stack can reproduce the same authoritative transition sequence from frozen inputs;
  - CHECKPOINT claims authoritative continuation from accepted durable checkpoints;
  - OBSERVATIONAL claims only evidence auditability without trajectory reproduction.
- Production-wide search shows `replay_level` is consumed only by authoring/validation, `RunResearchSemanticsReference`, manifest encoding and migration identity comparison. No Trial, Method, Machine, model, environment, checkpoint or runtime-admission code validates that the bound stack actually satisfies the declared replay level.
- Therefore EXACT, CHECKPOINT and OBSERVATIONAL select the same execution mechanisms; the system records a stronger or weaker scientific guarantee without proving it.
- `TrialBudget` carries substantive per-trial limits:
  `max_steps`, `max_seconds`, `max_tokens`, `resource_budget_digest`, `max_turns`, `max_messages`, `max_model_calls`, `max_working_seconds`, and `max_cost_usd`.
- `TrialBudget.budget_digest` correctly commits to every one of those fields.
- Yet the research compiler projects a TrialBudget into execution only through `trial_budget.budget_id`:
  - `StudyVariantSpec` receives only `budget_id`;
  - `StudyProtocol.budget_ids` receives only `budget_id`.
- Repository-wide runtime search finds no consumer of the TrialBudget numeric/resource limits.
- The canonical Method runtime still uses an independently configured/default `max_steps` (10,000 in the automatic local paths), not `trial_budget.max_steps`.
- Experiment repetition timeout is taken from `StudyConcurrencyPolicy.repetition_timeout_seconds`, not `TrialBudget.max_seconds/max_working_seconds`.
- Model dispatch is not gated by `TrialBudget.max_tokens/max_model_calls/max_cost_usd`; participant/message/turn execution is not gated by `max_turns/max_messages`; physical Resource admission does not consume `resource_budget_digest`.
- By contrast, `StudyConcurrencyPolicy` is genuinely compiled into Experiment batches and consumed by the runtime, proving that the missing budget/replay enforcement is not because execution policies are intended to be identity-only.

Semantic loss:
The frozen scientific identity commits to exact replay and resource/interaction limits that do not govern the actual execution. Only the budget's name/id survives into the executable protocol.

Impact:
Two Studies with different max_steps/tokens/cost/model-call/replay guarantees produce different scientific policy digests but can execute identically, and a run may exceed its declared budget while still producing an ordinary Trial/Experiment result. More seriously, a run may claim ReplayLevel.EXACT without any admission proof that model/environment/effect/checkpoint bindings provide exact replay. Under the unified architecture, StudyExecutionPolicy must compile into one enforceable runtime policy object whose limits are consumed by the relevant Method/Model/Participant/Resource authorities and whose replay guarantee is proven before execution.

### F-038 - Study factor/treatment interventions collapse to identity labels; canonical Trial execution does not apply or prove executable intervention semantics
Severity: **critical**
Status: **verified**
Breakpoint: `FactorLevelSpec.value -> FactorSelection -> TrialExecutionRequest -> ExecutionContext.condition_selections -> Method`
Audit dimension: **treatment semantic loss + identity/runtime disconnect**

Evidence:
- `FactorLevelSpec` contains the actual scientific level payload in `value: JsonValue`, plus `level_id` and `control`; its `level_digest` commits to the exact value.
- During Study compilation, `_factor_selections()` converts each selected level into `FactorSelection(factor_id, level_id, level_digest)`.
- `FactorSelection` has no `value` field. The exact intervention payload is therefore no longer available as typed runtime data after selection; only its id and digest remain.
- `StudyIntervention` stores only the tuple of FactorSelection rows and an intervention digest.
- `VariantBinding` similarly stores only `intervention_digest`, provider id, ablation policy id and comparator role; it contains no executable intervention/configuration delta.
- `_TrialBoundStudyExecution._request()` carries the StudyIntervention into `TrialExecutionRequest`, but production-wide search shows `intervention_spec` is consumed only by `WorkloadTrialProvider`.
- `WorkloadTrialProvider.run_trial()` does not apply a factor-level value to the Method/runtime/model/environment. It converts the selections only into:
  `ExecutionContext.condition_selections = ((factor_id, level_id), ...)`.
- `ResearchMethodCall`, the paper-facing Method call object, exposes only `condition_id` and `condition_selections: tuple[(factor_id, level_id)]`; it cannot read the original FactorLevelSpec.value through the canonical context.
- `DeclarativeWorkloadMethodCompiler.compile()` uses the same frozen MethodProgram, MethodRuntimeBindings, input projection and initial-state projection for every variant. It receives no intervention object and performs no per-variant reconfiguration.
- Study participant requirements separately carry `treatment_id`. That id participates in ProjectManifest method requirements and ResearchPlan identity/proof, but runtime-wide search shows no Trial/Workload/Method execution consumer of `treatment_id`.
- The automatic Trial resolver reduces participant requirements to the set of unique `method_id` values and builds one `DeclarativeWorkloadMethodCompiler` for that MethodProgram; it does not select a different executable binding by treatment_id.
- F-028 already establishes that participant/treatment-specific participant bindings are not consumed by the canonical Trial runtime.
- A paper Method can manually branch on the exposed factor/level names, so this does not prove every current downstream treatment executes identically. But that behavior is paper-specific convention, not a platform-applied or platform-verifiable intervention binding.

Semantic loss:
The scientific Study freezes exact factor-level values and treatment identities, but canonical execution preserves only nominal condition labels. There is no authoritative operation that says "apply intervention X/value V to runtime component Y" and no receipt proving that application.

Impact:
A multi-treatment Study can produce distinct variant/intervention digests while all variants still use the same MethodProgram/runtime binding unless downstream Method code manually interprets the condition labels. For SEM's treatment matrix this means the Experiment layer itself cannot prove that the four treatment semantics were actually applied. Under the unified architecture, selected factor levels/treatments need one typed immutable intervention binding that carries the exact value/config delta to its owning semantic authority and emits an execution proof that survives Trial/Experiment provenance.

### F-039 - Study assignment seeds are frozen as scientific identity but are not propagated into Method/model/environment randomness; the generic EnvironmentAssignmentIdentity seed path is disconnected
Severity: **critical**
Status: **verified**
Breakpoint: `StudyAssignment.seed -> TrialExecutionRequest -> ExecutionContext / Environment assignment / model request`
Audit dimension: **randomization semantic loss + disconnected seed authority**

Evidence:
- `StudyAssignment` carries an explicit `seed: str`, validates it as required, and commits it into `assignment_digest`.
- Study protocol compilation also commits the seed schedule into `seed_schedule_digest`; Experiment batches order assignments using `assignment.seed`.
- `ExecutionContext`, the context propagated into Method/model/capability/environment operations, has no seed field.
- Canonical `WorkloadTrialProvider.run_trial()` creates an ExecutionContext containing run/study/condition/lifetime/task identities but does not copy `request.assignment.seed` into any runtime field.
- Production-wide exact search for `assignment.seed` finds only:
  - Experiment assignment ordering;
  - serialization of StudyMetricObservation;
  - construction of MeasurementRecord.logical_time.
  It is not consumed by Method compilation/execution, model request generation, capability routing, or Environment session creation.
- Model serving/composition has no bridge from Study assignment seed to decoding/sampling seed.
- The Environment API already defines `EnvironmentAssignmentIdentity` with an explicit `seed` field and includes that seed in its authoritative assignment digest, showing the intended provider-neutral semantic exists.
- Minecraft also implements `MinecraftBranchAssignmentIsolation` over that generic identity.
- However production-wide search finds no construction/use of `EnvironmentAssignmentIdentity` by canonical ResearchOS/Trial composition and no consumer of `MinecraftBranchAssignmentIsolationFactory` outside its own module.
- Canonical local Minecraft lifetime composition instead derives a runtime key from `ExecutionContext.lifetime_id` and constructs a server with a fixed world seed:
  `level_seed="NOETRIUM_SEM_FIXED_WORLD_V1"`.
- Because `lifetime_id = assignment_digest`, changing the Study seed does create a distinct assignment lifetime/branch identity, but it does not seed the physical world, Method RNG, model sampling, or another declared stochastic source.
- Thus assignment seed currently distinguishes scientific identities and isolated lifetimes without governing the stochastic mechanisms whose variation it is intended to control.

Semantic loss:
"Noetrium Study assignment uses seed S" survives in protocol/report identity, but there is no canonical seed-binding operation that fans S out to the stochastic authorities participating in that trial, nor a receipt proving which authorities consumed it.

Impact:
Repetitions/seeds can be reported as distinct experimental samples while the execution stack may use the same fixed Environment world and uncontrolled/default model/Method randomness. Conversely uncontrolled randomness can vary even when the same assignment seed is replayed. For SEM's repeated treatment/task matrix this weakens both reproducibility and interpretation of between-repetition variation. Under the unified architecture, one immutable trial-randomness binding should derive named sub-seeds from the Study assignment seed, bind them to Method/model/environment/participant stochastic authorities, and persist proof of the exact seed map used.
### F-040 - Generic Runtime concern machines exist but the canonical automatic Method runtime does not compose or expose them
Severity: **critical**
Status: **verified**
Breakpoint: `RuntimeProgram concern modules -> automatic Method runtime inventory`
Audit dimension: **disconnected generic mechanisms + semantic duplication forced downstream**

Evidence:
- Noetrium implements first-class ResearchProgram/Machine semantics for reusable runtime concerns:
  - context;
  - communication;
  - logical scheduling;
  - synchronization;
  - recovery;
  - intervention;
  - visibility;
  - model invocation.
- Each concern has its own typed RuntimeModule/ResearchProgram compiler, state/rules/handlers and Machine-backed execution semantics.
- Production-wide caller search finds no external composition consumer for the corresponding concern compilers/modules/hosts; their public constructors are defined/exported but are not assembled by the canonical local ResearchOS automatic execution plane.
- `MethodRuntimePort`, the immutable Method ABI visible to MethodProgram, exposes only:
  `AGENT_LOOP`, `CAPABILITIES`, `CHILD_MACHINES`, and `SCHEMAS`.
- Therefore the automatic Study/Workload -> Method path has no direct canonical port through which a Method can consume the platform communication, logical-scheduling, synchronization, recovery, intervention or visibility machines.
- F-028 shows participant topology/schedule is frozen but not executed.
- The complete `communication_program` and `synchronization_program` implementations are not automatically instantiated from that participant topology/schedule.
- F-035 shows the intended escape hatch for reusable nested ResearchMachines (Program-scoped CHILD_MACHINE) is itself not materialized into the canonical Method child-machine runtime.
- As a result, a downstream paper that needs these generic concerns must currently implement/compose them inside Method-specific logic or manually construct lower-level RuntimeProgram hosts, despite the platform already containing generic implementations.

Semantic issue:
Noetrium has reusable generic machines for these concerns, but the strongest top-level execution path does not bind them into the one Method runtime aggregate. The functionality therefore exists beside the canonical path rather than underneath it.

Impact:
Generic mechanics can be reimplemented paper by paper, creating exactly the duplicate semantic implementations the platform is meant to eliminate. Multi-agent communication/synchronization is especially affected: Study participant topology may claim one causal structure while execution uses downstream ad-hoc messaging or none at all. Under the single-universal-machine architecture, these concern modules should be composable through one canonical ResearchMachine/Method runtime mechanism, automatically bound from frozen paper semantics rather than requiring bespoke lower-level composition.

### F-041 - Canonical automatic Trial execution cannot materialize verifier-backed benchmark tasks
Severity: **critical**
Status: **verified**
Breakpoint: `TaskPackageSpec.verifier_requirement_id -> PortfolioAutomaticTrialProviderResolver`
Audit dimension: **verifier authority disconnect + executable benchmark coverage gap**

Evidence:
- Benchmark tasks can declare:
  - `verifier_requirement_id`;
  - `verifier_isolation` (SHARED or SEPARATE);
  - optional verifier environment requirement;
  - an explicit artifact allowlist.
- `WorkloadTrialProvider._run_verifier_stage()` correctly enforces the artifact allowlist and requires a `TrialVerifierArtifactPublisherPort` before verifier handoff.
- `TrialVerifierOrchestrator.finalize()` correctly requires a `TaskVerifierPort` when the frozen task package declares a verifier.
- `TaskVerifierRequest` is a strong artifact-only isolation contract: it carries frozen scientific identity plus declared ArtifactReferences and explicitly excludes execution environment/session/workdir/Method state.
- `TaskVerifierReceipt` additionally requires isolation evidence when `TaskVerifierIsolation.SEPARATE` is declared.
- Composition already implements `ResearchExecutionVerifierArtifactPublisher`, backed by the canonical Artifact content authorities.
- However production-wide search finds no consumer/materialization of that publisher.
- `PortfolioAutomaticTrialProviderResolver.resolve()`, the canonical local `open_project().run()` path for Study workload execution, constructs `WorkloadTrialProvider(...)` without `artifact_publisher`.
- The same resolver returns `ResearchOSExperimentTrialProviderBinding(provider_identity, provider, provider.identity_digest)` without a verifier or verifier identity.
- No production implementation of `TaskVerifierPort.verify()` is registered/materialized by the default local execution authority.
- Therefore a verifier-backed task first fails at the provider stage because verifier artifact publication authority is absent; even if that were supplied manually, the default Experiment binding still has no verifier authority and orchestration would fail.
- F-004 additionally shows the verifier-backed workload stage currently drops assignment lifetime_id before execution.

Semantic issue:
The verifier isolation contract is well specified, but the canonical execution materializer does not connect any verifier execution authority or the already-implemented artifact handoff publisher to that contract.

Impact:
Benchmarks whose correctness depends on isolated verification cannot run through the default ResearchOS automatic Trial path even though the top-level Study/benchmark semantics support them. Downstream must manually construct lower-level Trial provider/verifier bindings, creating a second bespoke execution path. Under the unified architecture, verifier requirement resolution must be part of the same canonical platform-definition/binding mechanism as Method/Model/Environment, with isolation environment, artifact handoff and verifier identity frozen before Trial admission.

### F-042 - Verifier-backed workloads switch to a separate single-node Trial engine instead of preserving the universal WorkloadGraph semantics
Severity: **high**
Status: **verified**
Breakpoint: `WorkloadTrialProvider.run_trial() -> verifier_tasks -> _run_verifier_stage()`
Audit dimension: **dual Trial implementation + workload-DAG semantic collapse**

Evidence:
- The normal Workload Trial path executes `request.assignment.workload` through `WorkloadGraphBinding.execute_graph()`, which supports an explicit multi-node task graph with dependency edges.
- Benchmark `TaskDefinition` attaches package/verifier requirements per task, so verifier semantics are task-local rather than inherently single-Trial/single-node.
- `WorkloadTrialProvider.run_trial()` detects verifier-backed tasks and switches away from the normal graph path into the dedicated `_run_verifier_stage()` path.
- `_run_verifier_stage()` immediately requires `len(verifier_tasks) == 1`.
- It then additionally requires `len(request.task_definitions) == 1` and raises that the provider "currently requires a single-node assignment workload".
- It calls `self._workload.execute_one(task, context)` rather than the universal graph executor.
- `TrialVerifierOrchestrator.finalize()` independently rejects more than one verifier-backed task with the message that multi-verifier workload graphs would require per-node verifier receipts.
- Thus the same TrialProvider surface has two materially different workload execution engines:
  1. non-verifier: universal task graph execution;
  2. verifier-backed: one hard-coded single task execution followed by one verifier handoff.
- F-004 shows this special verifier path also already diverges in assignment lifetime propagation.
- F-041 shows the default local materializer does not currently supply verifier/publisher authorities at all; F-042 remains a separate structural limitation that would still exist after those authorities are connected.

Semantic duplication:
Verifier semantics are implemented by replacing the universal WorkloadGraph execution mechanism with a specialized one-task path rather than decorating each relevant graph node with the same artifact/verifier boundary.

Impact:
A benchmark task DAG cannot mix ordinary and verifier-backed nodes or contain multiple isolated verifier stages through the canonical Trial engine. Downstream must flatten the benchmark or build another bespoke Trial provider. Under the one-universal-machine requirement, verifier handoff should be a per-task/per-node capability of the same WorkloadGraph state machine, with verifier receipts/evidence attached to node results rather than a separate single-node execution mode.

### F-043 - ResearchOS cross-node values use a ResearchGraph cut digest as a fake RUN scope identity
Severity: **medium-high**
Status: **verified**
Breakpoint: `ResearchOSValueSubject.execution_cut_id -> ScopeIdentity(ScopeKind.RUN, execution_cut_id)`
Audit dimension: **scope identity semantic drift**

Evidence:
- `ResearchOSValueSubject.execution_cut_id` is required to be a SHA-256 cut identity and is populated from the prepared/source ResearchGraph cut id.
- The default `ResearchOSImmutableValueAuthority._scope()` unconditionally maps that value to:
  `ScopeIdentity(ScopeKind.RUN, subject.execution_cut_id)`.
- Foundation Scope semantics define a strict hierarchy in which RUN is the child of EXPERIMENT and represents the scientific run scope.
- Experimentation's own Run identity follows that contract: its `scope` property is `ScopeIdentity(ScopeKind.RUN, self.run_id)`.
- A ResearchGraph cut digest is a revision/execution-cut identity, not a scientific run id and is not registered through the Experiment -> Run scope hierarchy.
- The value authority does not validate/register this synthetic scope through ScopeRegistry before publishing Artifact references.
- Therefore Artifact references for ResearchOS cross-node values are catalogued under RUN-kind identities that are not actual scientific runs.

Semantic loss:
ScopeKind.RUN is being reused as a convenient namespace for graph cuts, collapsing two distinct identities: scientific run and ResearchGraph execution cut.

Impact:
Artifact/reference/retention/query code that reasons by ScopeKind can treat graph-cut values as run-scoped evidence even though they have no corresponding Experiment Run scope. Cross-source queries and lineage joins cannot reliably relate such values to the real Study/Experiment/Run hierarchy. The value plane needs either an explicit execution-cut scope kind/authority or a mapping to the actual owning run scope plus cut metadata; it should not overload RUN with a digest from another identity domain.

## Audit completion gate

The semantic-breakpoint audit pass is complete across the canonical ResearchOS dataflow and all registered top-level systems. The audit covered authoring/lowering, ResearchGraph, Experimentation, Method/Machine, Model, Capability/Effect, Environment, Resource, Participant, Memory/Context, verifier isolation, Artifact/Evidence/Data, Failure/Forensics, Scope, Observability, revision/reuse/reconciliation, and a repository-wide duplicate/fallback/compatibility/cardinality sweep.

Verified findings before remediation: **43**.

From this point forward implementation changes are remediation only. Every completed remediation is appended below as a FIX record; a finding is not considered fixed merely because code was edited.

## Remediation log

### FIX-F004 - Verifier Trial now preserves assignment lifetime
Status: **fixed**
Implementation:
- Updated `WorkloadTrialProvider._run_verifier_stage()` so its `ExecutionContext.lifetime_id` is exactly `request.assignment.assignment_digest`, matching the ordinary Workload Trial path.
- No new verifier-specific lifetime mode was introduced; both paths now use the same assignment-owned lifetime identity.

Validation:
- The edited module compiles successfully in the canonical Noetrium Docker image using an in-memory `compile(..., "exec")` check.
- A targeted invariant check in the same image confirms the verifier context binds `lifetime_id=request.assignment.assignment_digest`.

Effect:
- Stateful Environment capabilities can now resolve the same assignment session/world from verifier-backed workloads.
- Assignment finalization releases the same lifetime key that execution used.

### FIX-F001 - RUN receipt preserves graph-level failure metadata
Status: **fixed**
Implementation:
- Extended `ResearchOSExecution._execution_receipt()` with a canonical `node_results` projection for every ResearchGraphNodeResult.
- Each row preserves graph_node_id, semantic_digest, state, failure_type, failure_message and blockers.
- ResearchOS remains a projection only; it does not create a second failure authority.

Validation:
- The edited module compiles in the canonical Docker image using `compile(..., "exec")`.
- Targeted invariant checks confirm the public execution receipt contains per-node failure type/message and blocker metadata.

Effect:
- `api.open_project(...).run()` no longer collapses graph failures to failed-node IDs alone.

### FIX-F003 - Whole-execution INSPECT now exposes durable per-node state
Status: **fixed**
Implementation:
- Extended `_durable_control_receipt()` to include a `nodes` tuple for the complete durable snapshot, not only state buckets.
- Each row carries state, attempt_number, attempt_id, failure_type/message, blockers, node control phase and control generation.
- Node-scoped INSPECT remains available but is no longer required to discover basic failure provenance.

Validation:
- The edited module compiles in the canonical Docker image.
- Targeted invariant checks confirm the whole-execution receipt includes per-node attempt/failure/control fields.

Effect:
- Operators can discover which nodes failed, why, on which attempt, and under which control state from one top-level INSPECT response.

### FIX-F007 - Durable Method result evidence is field-complete for MethodRunResult
Status: **fixed**
Implementation:
- Upgraded the default result evidence schema to `noetrium.method-evidence.result.v2`.
- Persisted checkpoint_id, interrupt identity/payload, full failure text, binding_plan_digest, runtime_binding_digest, schema_digest and diagnostics in addition to the fields already present.
- The persisted field set now covers every semantic field committed by `MethodRunResult.run_digest`.

Validation:
- The provider module compiles in the canonical Docker image.
- Targeted invariant checks confirm every previously omitted run-digest field is present in the durable result payload.

Effect:
- The default Method evidence file no longer carries an opaque run_digest while omitting the binding/checkpoint/interrupt/failure/diagnostic material needed to reconstruct its semantic result.

### FIX-F011 - Canonical scientific model binding is now qualified-only and fail-closed
Status: **fixed**
Implementation:
- Removed the operational model-binding fallback from `PortfolioQualifiedModelResolver`; the canonical resolver now returns only proof-backed qualified bindings.
- Removed the corresponding operational fallback from Method agent-loop materialization.
- `ResearchStudyProtocolClosureProvider` now rejects any non-empty binding assurance gap before compiling an executable Experiment closure.
- Required model roles without qualified closure therefore remain unresolved rather than silently executing against a merely running deployment.

Validation:
- The local execution-authority and Study-closure modules import successfully in the canonical Docker image.
- Targeted invariants confirm `_operational_binding` no longer exists and the closure has an explicit `binding_assurance_complete` gate.

Effect:
- Missing qualification is an execution blocker, not a weaker alternate success mode.

### FIX-F013 - Optional model roles remain optional during Method runtime materialization
Status: **fixed**
Implementation:
- Method agent-loop materialization now skips an unavailable model role when `requirement.required == False`.
- Required execution roles still fail closed when the qualified binding is unavailable.

Validation:
- The execution-authority module imports successfully and targeted invariants confirm the optional-role skip branch.

Effect:
- A valid Study no longer fails project materialization merely because an optional model role is absent.

### FIX-F014 - Evaluation-only model roles are excluded from Method execution routing
Status: **fixed**
Implementation:
- `method_agent_loop_router()` now admits only requirements whose `ModelRoleUsage.affects_execution` is true.
- EVALUATION-only roles no longer become callable Method agent-loop identities.

Validation:
- Module import succeeds in the canonical Docker image.
- Targeted invariant confirms the execution-usage filter is present before binding materialization.

Effect:
- The Study execution/evaluation phase boundary is now enforced at the actual Method model capability surface.

### FIX-F015 - Experiment reconciliation is fail-closed without lower-authority proof
Status: **fixed**
Implementation:
- Removed the synthetic retry-evidence digest and unconditional RETRY result from `CanonicalWorkloadExperimentReconciliation`.
- When no terminal lower Machine commit or independent Trial/Method/Effect proof exists, the reconciler now raises `ResearchOSReconciliationIndeterminate`.
- The ResearchGraph therefore remains in RECOVERY_REQUIRED instead of being marked retry-safe.

Validation:
- The local execution-authority module imports successfully in the canonical Docker image.
- Targeted invariant checks confirm the reconciler contains no RETRY disposition and explicitly returns the indeterminate path.

Effect:
- Unknown Experiment state is no longer converted into a fabricated lower-authority retry proof.

### FIX-F021 - Trial provider identity now closes over the executable workload/Method runtime
Status: **fixed**
Implementation:
- Added a stable `identity_digest` to `UniversalMethodMachine` that commits its semantic execution controls.
- Strengthened `MethodMachinePort` and the universal `WorkloadExecutionPort` with explicit identity digests.
- `WorkloadMethodBinding.identity_digest` now commits the Method machine, declarative compiler and result-adapter identities; the compiler digest already commits the exact MethodProgram and resolved Method runtime binding.
- `WorkloadGraphBinding.identity_digest` commits its bound task executor plus graph-scheduling semantics.
- `WorkloadTrialProvider` now requires that workload identity and includes it in provider identity (`workload-trial-provider.v4`).

Validation:
- All modified execution/workload/provider modules import successfully in the canonical Docker image.
- Construction-time validation now rejects a workload/Method executor without stable identity instead of silently freezing only the provider shell.

Effect:
- Changing the MethodProgram, Method runtime binding, Method machine limits, result projection or workload graph executor necessarily changes the Trial-provider identity and therefore the frozen Experiment runtime binding.

### F-044 - ManagedObservability is constructed and persisted but is not wired into canonical Method/Experiment execution
Severity: **high**
Status: **verified**
Breakpoint: `ManagedResearchRuntime.observability -> MethodRuntimeBindings / Experiment observation sinks`
Audit dimension: **disconnected side-plane authority + lost execution telemetry**

Evidence:
- `build_local_managed_research_runtime()` always builds one durable `ManagedObservability` bundle containing:
  - SQLite-backed telemetry;
  - file-backed raw observation lake behind `RegistryBoundRawObservationGateway`;
  - durable structured logging.
- `ManagedResearchRuntime` stores that bundle and closes it during ordered shutdown.
- Composition already contains typed adapters intended to project canonical scientific execution into this observability plane:
  - `RawLakeMethodObservationSink`;
  - `LakeBackedExperimentObservationLedger`;
  - `LakeBackedRawRecordStore`.
- Production-wide constructor search finds no canonical construction of `RawLakeMethodObservationSink`, `LakeBackedExperimentObservationLedger` or `LakeBackedRawRecordStore`.
- `MethodRuntimeBindings` explicitly has an optional `observation: MethodObservationPort` field.
- `UniversalMethodMachine._publish_events()` publishes MethodEvents only when `runtime.observation is not None`; otherwise it silently returns.
- The canonical local automatic Method composition does not pass an observation sink into `compose_method_runtime_bindings()`.
- Experimentation also defines `ObservationSinkPort` / `RawRecordStorePort`, but ResearchOS Experiment execution does not receive the ManagedObservability raw gateway or bind the Lake-backed adapters.
- ManagedResearchRuntime's observability object is therefore currently owned and durable but not connected to the canonical ResearchOS scientific execution path.

Semantic loss:
The platform possesses a durable observability authority, while Method/Experiment execution can complete without emitting its semantic events/records into that authority. Observability becomes an idle managed service rather than a projection of authoritative execution.

Impact:
Operational dashboards/telemetry/raw-event queries cannot reconstruct Method/Experiment activity from the managed observability plane even though the runtime advertises and persists that plane. This also leaves future debugging vulnerable to ad-hoc local logs instead of one canonical side-plane projection. Under the single-mechanism model, scientific truth should remain Machine/Operation/etc., but all canonical Method/Experiment transitions/events should be projected automatically into the one managed observability system with replay-safe/idempotent semantics.

## Audit closure

Status: **semantic audit complete; remediation started after this point**

Coverage completed:
- public ResearchOS authoring/revision/control surface;
- ResearchPortfolio/ResearchGraph lowering, scheduling, migration, reuse, retry and reconciliation;
- Study/Experiment/Trial/Workload/measurement/aggregation semantics;
- MethodProgram/UMM/Machine Journal/Operation/effect/failure paths;
- Model scientific binding, deployment, replica, GPU and endpoint binding;
- Environment/Minecraft capability, lifetime, Docker, endpoint, process and recovery lifecycles;
- Participant topology, multi-agent scheduling, child machines, communication/synchronization/runtime concerns;
- Artifact/Evidence/Data/value-plane lineage and retention;
- checkpoint/resume/replay/budget/intervention/seed semantics;
- verifier isolation and artifact-only handoff;
- managed observability/telemetry/logging projection;
- Scope/Portfolio/Governance authority boundaries;
- repository-wide final sweep for process-local fallbacks, direct/durable dual modes, compatibility fallbacks, shadow authorities, first-element collapses and direct physical-resource bypasses.

Final audit count at closure: **44 verified findings**.

Non-findings explicitly checked:
- Scope uses one canonical registry authority; capability-registration scopes are a different execution concern.
- Portfolio catalog/revision DAG remain within one Portfolio authority and do not own scientific payload/execution truth.
- Governance is metadata/audit/policy only and does not own Machine/Operation execution.
- Model physical GPU/endpoint placement reuses the shared Compute/Endpoint authorities.
- Canonical local Minecraft uses shared Docker/Endpoint authorities and crash-durable bridge recovery.
- Verifier handoff itself is artifact-only and exact-request-bound; the verifier problems are the separately recorded Trial-engine/lifetime/materialization issues.
- ResearchOS/Method checkpoints on the canonical path are projections of Machine cuts; the duplicate independent Experimentation checkpoint engine is recorded separately.
- ResearchGraph's first-element program access is guarded by exactly-one admission on the canonical path.

## Remediation log

Each verified finding is updated here only after implementation repair and validation. Fixes must remove the weaker/duplicate semantic path rather than merely add another compatibility branch.

### Fix F-001 - RESOLVED in current working tree

- Current `StrictResearchOSControl._execution_receipt()` now publishes a `node_results` tuple for every graph node, including graph-node id, semantic digest, state, failure type/message and blockers.
- This preserves the failure metadata already present in `ResearchGraphExecutionReport` at the public ResearchOS receipt boundary instead of reducing failures to node ids only.
- The target file already contained this repair from concurrent work when remediation started; no competing rewrite was applied.
- Validation: `python3 -m py_compile noetrium_platform/composition/research_os_execution.py noetrium_platform/product/research_os.py` passes.

### Fix F-003 - RESOLVED in current working tree

- Current `StrictResearchOSControl._durable_control_receipt()` now emits whole-execution `nodes` rows for every durable graph node, including attempt number/id, failure type/message, blockers and node-control phase/generation.
- Whole-execution `inspect()` therefore no longer requires the caller to know the failed node in advance to recover per-node graph diagnostics.
- The target file already contained this repair from concurrent work when remediation started; no competing rewrite was applied.
- Validation: the same targeted `py_compile` passes and direct source inspection confirms `nodes` is present unconditionally in the durable receipt payload.

### Fix F-002 - RESOLVED

- Added one typed `ResearchGraphFailureProvenance` projection instead of adding another independent failure authority. It preserves safe qualified exception identity, error digest, redacted traceback frames, causal chain, lower forensic `failure_id` when available, evidence refs and lower Operation/Effect/Machine/result references.
- FAILED `ResearchGraphNodeResult` now requires typed failure provenance; the previous valid type/message-only failure result path is removed.
- Durable `ResearchGraphNodeExecutionRecord` and `ResearchGraphAttemptRecord` carry the same typed provenance projection.
- `SQLiteResearchGraphExecutionStore` schema is advanced directly from v3 to v4 (no compatibility branch/migration fallback) and persists one content-verified provenance JSON on both node and attempt records. Retry/new-attempt reset paths clear the prior provenance together with prior failure metadata.
- `ResearchGraphScheduler` now captures safe traceback/cause/lower refs at the exception boundary and reuses the durable record's exact provenance when reconstructing reports.
- ResearchOS whole-execution inspect, node inspect and execution `node_results` now expose that same provenance payload instead of re-encoding another failure schema.
- Validation:
  - targeted Python compilation passes for Graph API/state/SQLite/scheduler/ResearchOS and affected fixtures;
  - Docker Python 3.12 SQLite lifecycle round-trip wrote and reread identical node/attempt provenance digest: `031d8d015c44a958c17c424d92c7d3c05423cdcf0dbf4b79584dd6d625868ea5`;
  - Docker semantic probe verified nested cause, lower failure id, evidence ref, operation ref and traceback preservation and verified FAILED results reject missing provenance;
  - targeted `git diff --check` passes.
- The node1 Noetrium image does not contain pytest, so no pytest result is claimed here.

### Fix F-004 - RESOLVED in current working tree

- The verifier-backed Workload stage now constructs `ExecutionContext` with the same scientific lifetime as the normal workload path: `lifetime_id=request.assignment.assignment_digest`.
- Stateful Environment/Capability routing therefore sees one assignment-scoped lifetime regardless of whether the task uses a verifier.
- Assignment-finalizing cleanup continues to release that exact digest, so creation/use/release now share one lifetime identity instead of releasing a key the verifier path never used.
- This repair was already present in concurrent work when F-004 remediation was reached; no competing rewrite was applied.
- Validation: targeted `py_compile` and `git diff --check` pass for `research/experimentation/lifecycle/study/providers/trial.py`, and direct source inspection confirms the verifier-stage context carries the assignment digest.

### Fix F-007 - RESOLVED in current working tree

- `DirectoryEventMethodEvidence.record_result()` now writes `noetrium.method-evidence.result.v2` with every semantic field committed by `MethodRunResult.run_digest`: value/state/events, checkpoint id, interrupt, failure, effect receipts, step/visit counts, evidence status, binding-plan/runtime-binding/schema digests, failure code/phase and diagnostics.
- The durable evidence artifact therefore no longer carries an opaque richer `run_digest` while omitting fields required to verify that digest.
- This repair was already present in concurrent work when F-007 remediation was reached; no competing rewrite was applied.
- Validation: targeted `py_compile` and `git diff --check` pass for `research/execution/workflow/providers/method_evidence.py`; direct comparison against `MethodRunResult.__post_init__()` confirms every run-digest input field is persisted.

### Fix F-011 - RESOLVED in current working tree

- `PortfolioQualifiedModelResolver.resolve()` no longer has an operational-deployment fallback. Missing qualified closure now produces a blocking `model.qualification_missing` binding diagnostic.
- `ResearchStudyProtocolClosureProvider.resolve()` additionally rejects any frozen Study binding with incomplete assurance before compiling the executable Experiment closure.
- The previous passive-assurance metadata path is therefore removed from canonical scientific execution.
- Validation: no `_operational_binding` path remains in the local execution materializer; targeted `py_compile` and `git diff --check` pass.

### Fix F-012 - RESOLVED in current working tree

- Method model routing is now materialized per frozen Study closure and cached by `closure.closure_digest`, rather than once per portfolio keyed only by role text.
- Independent Studies/papers may therefore reuse a local role name such as `agent` without sharing one portfolio-global model-generation namespace.
- Validation: the only production `method_agent_loop_router()` consumer passes the exact closure; targeted compile/diff checks pass.

### Fix F-013 - RESOLVED in current working tree

- Closure-scoped model materialization now checks frozen rows per role; an absent optional role (`required=False`) is skipped, while an absent required execution role fails closed.
- Optional Study model semantics therefore survive into Method runtime materialization.
- Validation: source branch at `_materialize_method_agent_loop_router()` explicitly distinguishes required and optional roles; targeted compile/diff checks pass.

### Fix F-014 - RESOLVED in current working tree

- `_materialize_method_agent_loop_router()` now filters model roles with `requirement.usage.affects_execution` before exposing them to Method execution.
- Evaluation-only bindings are no longer promoted into the Method agent-loop namespace.
- Validation: direct source inspection plus targeted compile/diff checks pass.

### Fix F-015 - RESOLVED in current working tree

- `CanonicalWorkloadExperimentReconciliation.reconcile()` no longer manufactures an identity hash and returns `RETRY`.
- When no terminal lower Machine commit or independent lower Trial/Method/Effect proof exists, it now raises `ResearchOSReconciliationIndeterminate` and therefore preserves uncertainty instead of asserting retry safety.
- Validation: direct source inspection confirms there is no RETRY return/evidence fabrication path; targeted compile/diff checks pass.

### Fix F-027 - RESOLVED in current working tree

- Method model runtime is now built from the frozen Study closure rather than a portfolio-global pre-resolution.
- For every execution role, the runtime resolver revalidates the live qualified authority against the exact frozen `ProjectModelBinding.digest()` and separately checks model/deployment generation/model-stack/qualification/runtime-qualification identity before opening the replica set.
- Scientific model binding X and physical Method dispatch binding Y therefore must be identical or execution fails closed.
- Validation: direct source inspection confirms both digest-level and qualified-endpoint field-level equality checks; targeted compile/diff checks pass.

### Fix F-021 - RESOLVED in current working tree

- `WorkloadMethodBinding.identity_digest` now commits to the exact Method machine identity, `DeclarativeWorkloadMethodCompiler.digest`, and result-adapter identity.
- The compiler digest itself commits to MethodProgram, resolved Method runtime binding, task/input projection, initial-state projection and resume semantics.
- `WorkloadGraphBinding.identity_digest` commits to that task executor identity, and `WorkloadTrialProvider.identity_digest` now commits to the WorkloadGraph identity.
- The Experiment Trial-provider binding therefore freezes the executable workload/Method/runtime underneath the provider instead of only the protocol/projection shell.
- This repair was already present in concurrent work when F-021 remediation was reached; no competing rewrite was applied.
- Validation: targeted `py_compile` and `git diff --check` pass across workload operation/graph/trial provider files; direct digest-chain inspection confirms the identity closure reaches MethodProgram and resolved runtime binding.

### Fix F-016 - RESOLVED

- UniversalMethodMachine no longer supports a process-local execution-truth mode. `runtime.transitions` is mandatory at execution admission and missing Machine authority fails closed.
- The local `_ExecutionState` bootstrap branch, no-op checkpoint branch, no-op accepted-transition branch and no-op control-transition branch were removed; Method state now always opens/commits/checkpoints through `MethodTransitionAuthorityPort`.
- `MachineMethodRuntimeBinder` no longer imports or constructs `InMemoryMachineJournal` / `InMemoryMachineSnapshotStore`. A durable `state_root` is mandatory and binding always uses `DirectoryMachineJournal` plus `DirectoryMachineSnapshotStore`.
- The runtime binder protocol, standard binding helper and declarative workload runtime now require an explicit durable state root; both canonical ResearchOS Method paths already supply one.
- Executable Docker/Python 3.12 probe verified that an unbound UMM fails closed and the same Method succeeds after durable Machine binding while creating a durable Machine journal: `F016_F017_EXECUTION_OK`.
- Combined targeted `py_compile` and `git diff --check` pass.

### Fix F-017 - RESOLVED

- UniversalMethodMachine no longer has the direct-handler execution branch. Synchronous nodes always enter `MethodNodeOperationAdapter.execute()`; asynchronous nodes require an async-capable Operation dispatcher and fail closed otherwise.
- Method admission now also requires `runtime.dispatcher`, so omitting the Operation boundary cannot silently select weaker semantics.
- Added one standard Method Operation dispatcher composition function and injected it into both canonical paths:
  - direct ResearchOS Method execution;
  - Study/Workload declarative Method execution.
- `compose_method_runtime_bindings()` now requires an explicit dispatcher instead of defaulting to `None`.
- `_invoke_node_body()` remains only the handler implementation invoked from inside the Operation boundary; it is no longer a competing execution path.
- Executable Docker/Python 3.12 probe passed together with F-016: `F016_F017_EXECUTION_OK`.
- Combined `git diff --check` passes.
- Scope note: the standard dispatcher is currently the Kernel Operation ABI. Durable Operation lifecycle ownership (`OperationOwner` / SQLite operation state) is a separate unresolved authority issue covered by F-010/F-026; this fix removes the Method direct bypass without claiming that those later findings are resolved.

### Fix F-019 - RESOLVED

- Removed the direct external-action semantic mode instead of retaining it behind a dormant branch; `action_execution_direct.py` is deleted and has no remaining imports.
- `ActionExecutionCoordinator` now always owns one `JournaledActionExecutor`; `EffectIntentOperationPort` is mandatory and `execute_prepared()` has no direct-provider bypass.
- Tightened the complete ContextAction safety chain so one durable intent is intrinsic rather than optional:
  - `ActionSafetyAssembly`, preparation, slot guard, authorization, capability preflight, public safe-action facade and ContextAction trial operations all require EffectIntent authority;
  - `PreparedSafeAction.intent`, `ActionSafetyPermit.intent_id` and journal durability are mandatory;
  - committed recovery is always composed;
  - trial-commit recording no longer has a no-op branch when the journal is missing.
- `ContextActionSurfaceFactory` explicitly fails closed if the generic workflow binding context lacks EffectIntent authority.
- Production Environment composition already creates `EffectIntentOperations` from the durable SQLite effect-intent journal.
- Validation:
  - all touched ContextAction production modules pass `py_compile`;
  - no direct-action / optional-journal production branches remain in the ContextAction package;
  - `git diff --check` passes;
  - Docker/Python 3.12 fail-closed probe passed and confirmed the deleted direct implementation is not importable: `F019_FAIL_CLOSED_OK`.

### Fix F-009 - RESOLVED

- Removed the process-local `InMemoryMachineJournal` from canonical local Environment capability mediation.
- `CapabilityInvocationPipelineFactory` now binds to `DirectoryMachineJournal(context.state_root / "machine-state" / "program-journal")`.
- This is the same canonical program-Machine Journal root already used by `CanonicalResearchOSNodeRuntime` and Study child-machine composition, rather than a new Environment-owned side journal.
- Environment mediation transitions therefore survive process loss and participate in the same Machine Journal authority used by the surrounding ResearchOS execution plane.
- Validation: the Environment composition module passes `py_compile` and `git diff --check`; source audit confirms no `InMemoryMachineJournal` remains on this path.

### Fix F-025 - RESOLVED

- The canonical operation boundary is now built with OperationForensicFailureSink backed by the managed ForensicStore.
- Kernel Operation failures therefore materialize through FailureRecorder into the authoritative forensic failure system instead of remaining local exception strings.
- Both automatic Method execution and Environment capability execution use the managed durable dispatcher, so their operation failures pass through the same forensic authority.
- Validation: source closure confirms no canonical Environment/automatic Method construction of a bare OperationExecutor remains; targeted py_compile and git diff --check pass.

### Fix F-026 - RESOLVED

- Durable OperationFailure already carries the forensic failure_id; the remaining upper-layer loss was removed by preserving exactly that id rather than copying FailureEnvelope content.
- Kernel OperationFailure now exposes result.failure_id directly.
- MethodControlRecord and MethodRunResult now carry failure_id; Method run_digest commits to it, Machine control events/commands persist it, and Method evidence records it.
- UMM exception handling walks the exception/cause chain only to recover the existing lower-authority failure_id and propagates that single reference through control/result state.
- WorkloadMethodReceipt and Workload diagnostics now carry the same failure_id, and direct ResearchOS Method failure exceptions expose it so ResearchGraphFailureProvenance can retain the same authoritative reference.
- Validation: all touched files pass py_compile and git diff --check; Docker/Python 3.12 executable probe passed: F026_METHOD_FAILURE_REF_OK failure-authority-123.
### Fix F-010 - RESOLVED

- Promoted Operation lifecycle ownership into the managed runtime instead of leaving Environment on a bare Kernel dispatcher:
  - one `ManagedOperationRuntime` owns SQLite command intent, SQLite Operation lifecycle, operation forensics and the durable dispatcher;
  - `ManagedResearchRuntime` owns/closes this runtime;
  - project ResearchOS, Study/Workload Method execution and Environment capability execution all consume the same `managed_runtime.operation_runtime.dispatcher`.
- Extended the workflow Operation ABI with typed `OperationEffectBinding` so an effectful invocation must freeze its `OperationEffectProfile`, effect id, request id and request digest before provider execution.
- A plain `KernelOperationDispatcher` now fails closed if an effect binding is supplied; only the durable Operation boundary may execute an externally effectful Operation.
- `DurableKernelOperationDispatcher` now owns the complete command/Operation lifecycle:
  - deterministic command materialization and semantic deduplication;
  - CREATED -> QUEUED -> ADMITTED -> RUNNING;
  - crash recovery;
  - terminal replay prevention;
  - pre-execution effect identity;
  - confirmed effect completion;
  - effectful failure or unmatched/unresolved receipt -> durable `UNKNOWN_EFFECT` plus `DurableOperationRecoveryRequired`.
- Command-store semantic equality no longer treats submission timestamp metadata as command identity.
- `CapabilityOperationAdapter` now maps the already-authoritative `CapabilityDescriptor.effect_class` into the Operation effect profile and reuses `capability_effect_request_id()` / `capability_request_digest()` for the Operation effect identity. PURE capability results carrying an external-effect receipt fail closed.
- The Method-node outer Operation remains a coordination Operation; nested capability receipts remain lineage on the Method result, while the inner capability Operation owns physical-effect certainty. This avoids double-owning one external effect.
- Validation:
  - targeted production modules pass `py_compile`;
  - combined `git diff --check` passes;
  - durable SQLite lifecycle/reopen probe passed: `F010_DURABLE_OPERATION_OK`;
  - real `CapabilityOperationAdapter` effect-binding probe passed: `F010_CAPABILITY_BINDING_OK`;
  - production scan shows direct `KernelOperationDispatcher` construction only inside `ManagedOperationRuntime` as the backend wrapped by the durable dispatcher; canonical Environment/Method consumers use the managed durable authority.

### Fix F-032 - RESOLVED in current working tree

- `ResearchGraphScheduler.execute()` now has one implementation path and unconditionally enters `_execute_durable()`.
- The process-local pending/running/results scheduler implementation has been removed; Graph execution always requires the durable graph state/control/attempt authority.
- Validation: `research_graph.py` passes `py_compile` and `git diff --check`; source inspection finds no `execution_store is None` semantic branch.
### Fix F-033 - RESOLVED

- Removed every production `journal=None -> InMemoryMachineJournal()` fallback identified by the audit.
- `StateMachineEnvironmentRuntime`, `AgentMemory.create_default`, `RuntimeProgramTrialProtocol`, and `ExperimentProgramBinding.open_session/execute` now require an explicit `MachineJournalPort`.
- Their public composition helpers (`compose_state_machine_environment`, agent-turn Trial protocol, context-action Trial protocol) also require the journal instead of silently selecting weaker durability.
- Canonical ResearchOS Experiment execution already supplies its shared durable `DirectoryMachineJournal`, so production behavior remains on one Machine authority.
- Validation: all touched modules pass `py_compile` and `git diff --check`; repository search across Research Execution/Experimentation finds no remaining `InMemoryMachineJournal()` fallback.
### Fix F-043 - RESOLVED

- Added explicit `ScopeKind.EXECUTION_CUT` with `PROJECT` as its scope parent.
- ResearchOS cross-node value artifacts now use `ScopeIdentity(EXECUTION_CUT, execution_cut_id)` instead of overloading scientific `RUN`.
- Their immutable retention declaration/checks now use `ArtifactRetention.PROJECT`, matching revision/cut lifetime rather than run lifetime.
- Validation: Scope and ResearchOS value-authority modules pass `py_compile` and `git diff --check`.
### Fix F-035 - RESOLVED

- compose_program_method_runtime_inventory() now materializes Program-scoped ResearchDefinitionKind.CHILD_MACHINE declarations in addition to Method-owned components.
- Each child declaration is resolved through the existing exact resolve_machine_program_implementation() path, so program digest, MachineKind and operation implementation identities are revalidated before execution.
- Declared child hosts are registered into the same ChildResearchHostRegistry/ChildResearchMachineExecutor used by Method-owned components and share the same MachineJournalPort.
- Host-id collision checks cover Method-owned components and Program-scoped child declarations together; base child registrations remain merged into the same registry.
- A concurrent ProgramScopedCapabilityPort change briefly introduced an effective_base initialization regression; it was repaired without reverting that change, and no-child paths now return the program-scoped effective inventory.
- Validation: py_compile and git diff --check pass; Docker/Python 3.12 direct runtime binding test passed with F035_DIRECT_BIND_OK.
### Fix F-044 - RESOLVED

- Rebuilt `RawLakeMethodObservationSink` on the current `MethodObservationPort.publish(MethodEvent, ExecutionContext)` ABI and bound it to the managed `RegistryBoundRawObservationGateway` under system `execution`.
- Method raw event ids are deterministic over the accepted execution context + MethodEvent, so retries/replay project through append-once semantics instead of creating a second event history.
- Direct ResearchOS Method execution receives the managed Method observation sink from the project execution plane; automatic Study/Workload Method execution receives the same managed raw gateway from `ResearchExecutionContext.runtime.observability`.
- Added typed `ResearchOSExperimentTrialObservationPort` to the canonical Trial->Study bridge. After Trial/verifier finalization and metric projection, the bridge best-effort projects the exact `request_digest`, `receipt_digest`, assignment identity, measurement record digests, evidence refs, verifier receipt digest and scalar Study metrics into the managed raw gateway under system `experimentation`.
- Observation projection is explicitly side-plane: exceptions are suppressed at the Method/Trial projection boundary and cannot mutate Machine/Trial scientific truth.
- The older `LakeBackedExperimentObservationLedger` / `LakeBackedRawRecordStore` remain unselected by production composition; canonical ResearchOS now projects from the actual Trial/Study path rather than reviving that older Experiment engine.
- Validation: all touched observability/ResearchOS composition modules pass `py_compile` and `git diff --check`; production constructor search confirms managed Method/Trial sinks are injected; Docker Python 3.12 probe verified deterministic Method event identity: `method-event:85793352b4b995f5a376bdf5d237ac61943c0c771256ae6bd01325264a778a3e`.
### Fix F-042 - RESOLVED in current working tree

- WorkloadTrialProvider now executes verifier-backed assignments through the same universal WorkloadGraph execute_graph() path as ordinary assignments.
- The separate VerifierStageWorkloadTrialProvider/single-task execute_one() engine was removed.
- After the graph completes, _verifier_stage_from_graph() selects the exact verifier-backed task result from the graph result, validates declared exports, publishes only declared verifier artifacts, and returns the stage receipt for the existing verifier orchestrator.
- Graph-level non-verifier measurements continue to be projected from the complete WorkloadGraphResult, preserving dependency/scheduling semantics.
- Validation: targeted py_compile and git diff --check pass; no VerifierStageWorkloadTrialProvider or _run_verifier_stage symbol remains.

### Fix F-005 - RESOLVED

- Local Environment resolution is now typed and fail-closed. A platform-resolved ENVIRONMENT definition must declare explicit category_id and implementation_id in addition to required_capability.
- The resolver validates that implementation identity against the canonical Environment category catalog, requires category agreement and AVAILABLE status, and dispatches only through a registered local runtime factory. Generic ENVIRONMENT no longer silently means Minecraft.
- The current local factory is explicitly minecraft.mineflayer; unsupported available/contract-only implementations fail closed instead of falling through to Minecraft behavior.
- SEM was updated to declare category_id=minecraft and implementation_id=minecraft.mineflayer explicitly.
- Validation: ambiguous ENVIRONMENT lacking category_id is rejected by Docker/Python 3.12 probe; targeted py_compile and git diff --check pass.

### Fix F-006 - RESOLVED

- Environment capability materialization is now per ResearchProgram rather than one portfolio-global configuration.
- Added ProgramScopedCapabilityPort to the Method runtime binding ABI. The existing ResearchProgram -> Method runtime composition seam resolves the exact capability surface before Method binding, so downstream Method code still receives one ordinary CapabilityPort.
- compose_local_environment_capability_runtime now builds a program_id -> exact Environment runtime table; independent programs may use different Environment definitions without a global identity-equality restriction.
- Assignment lifetime finalization selects the lifetime authority for the exact ResearchProgram before wrapping the Trial provider.
- Validation: Docker/Python 3.12 multi-program binding probe passed: F005_F006_BINDING_OK fe64abdd9c65327850a2a98818db77f8e9b74ace4477c5eea6f8a698a6660edd 09757d5466e59597d769ca340aa5a211339a5ffbc27ace5d21a8d62977704db5; compile/diff gates pass and the old portfolio-global cardinality error path is gone.

### Fix F-023 - RESOLVED

- LocalMinecraftLifetimeSessionAuthority no longer treats its process-local runtimes dictionary as environment-instance ownership truth.
- Every assignment branch is registered in the canonical Environment catalog, acquired through EnvironmentInstanceLeaseAuthority, fenced by a Resource lease and kept alive by the shared environment-instance heartbeat guard.
- Physical branch-open failure releases without cleanliness proof, leaving the generation DIRTY. Normal release first proves physical branch/workdir closure, then emits an EnvironmentCleanlinessProof, releases the fenced generation and destroys the catalog instance. The process-local dictionary is now only a live-session cache.
- Environment profile revision/materialization identity is registered once and runtime identity is checked by the canonical catalog before instance admission.
- Validation: Docker/Python 3.12 probe using the real Environment catalog + EnvironmentInstanceLeaseAuthority and controlled Resource lease providers passed: F023_ENV_INSTANCE_LIFECYCLE_OK minecraft:owner-generation:3e0704edd8fce6cf4ac94f80 destroyed. Targeted py_compile and git diff --check pass.
### Fix F-008 - RESOLVED

- Canonical Trial Study execution now requires authoritative publication of every finalized TrialExecutionReceipt before it becomes a Study observation.
- ResearchExecutionTrialReceiptPublisher stores canonical_bytes(receipt) through the shared ResearchExecutionContentAuthorities / Artifact authority as a RUN-retained SCIENTIFIC artifact.
- StudyMetricObservation now carries trial request digest, Trial receipt digest, the immutable ArtifactReference, MeasurementRecord digests, Trial evidence refs and verifier receipt digest; these fields participate in observation_digest.
- ExperimentProgram authoritative state serialization/deserialization preserves those typed references and verifies observation_digest on recovery.
- Observability remains a side-plane only; scientific provenance is now reachable from Experiment Machine state through the Artifact authority.
- Canonical local execution injects the receipt publisher automatically; absence fails closed.
- Validation: py_compile and git diff --check pass; Docker/Python 3.12 end-to-end publication/state round-trip passed: F008_TRIAL_PROVENANCE_ROUNDTRIP_OK.
### Fix F-030 - RESOLVED

- Method evidence now has a typed ArtifactReference path instead of ending at a directory plus evidence_status bit.
- MethodEvidencePort.record_result() may return an ArtifactReference; UniversalMethodMachine records immutable Method truth first and then attaches that reference to MethodRunResult without including it in run_digest, avoiding circular identity.
- Canonical production standard_method_evidence_factory now requires the shared ResearchExecutionContentAuthorities and returns ArtifactBackedMethodEvidenceFactory; directory evidence remains only the durable carrier beneath the canonical Artifact projection.
- ArtifactBackedMethodEvidence publishes a complete canonical Method evidence manifest as a RUN-retained SCIENTIFIC artifact while continuing to persist the local detailed evidence carrier.
- WorkloadMethodReceipt carries evidence_reference; WorkloadMethodBinding projects it from MethodRunResult; WorkloadTrialProvider gathers refs from every executed task and includes them in ordinary TrialExecutionReceipt.evidence_refs.
- Verifier-backed Trial stage receipts merge Method evidence refs with verifier artifact refs, so TrialVerifierOrchestrator preserves both.
- F-008 then carries these Trial evidence refs into the authoritative Experiment observation/Machine state.
- Validation: py_compile and git diff --check pass; Python 3.12 package import gate passes after removing an aggregator-layer circular import; Docker semantic chain test passed: F030_METHOD_EVIDENCE_CHAIN_OK.
### Fix F-018 - RESOLVED

- MethodProgram is now a typed authoring/semantic facade only. It lowers deterministically into the canonical ResearchProgram IR with MachineKind.METHOD.
- ResearchProgram is the one executable IR for Method, Runtime, Participant, Memory, Environment, Evaluation, Optimization, Experiment and Run machines.
- Universal Method semantics that previously existed only in UMM were lifted into the generic Program IR: bounded allowed transitions, per-node max_visits, visit-count projection, checkpoint payload, generic semantic sidecar state, and durable global step-limit termination.
- Generic Program handler exceptions, invalid transitions, per-node visit limits and global step limits now become durable FAILED Machine commits instead of escaping as process-only exceptions.
- Method node handlers are exposed as exact ResearchHostOperation values. Every Method node still crosses the durable Operation dispatcher, but state progression is performed only by ProgrammableMachineInterpreter -> MachineExecutor -> Machine Journal.
- MachineMethodTransitionAuthority, MethodAuthoritativeState, MethodTransitionRecord, MethodControlRecord and MethodTransitionAuthorityPort were deleted rather than retained as compatibility paths.
- MachineMethodRuntimeBinder now constructs ResearchProgramHost directly and binds its journal/snapshot store permanently. MethodRuntimeContext carries only the generic program_host + machine_id pair.
- The Method-specific async state-machine interpreter surface was removed. Async I/O remains a provider/Operation concern; Machine state progression has one synchronous commit authority.
- Method events, effect receipts, interruption/failure metadata and checkpoint payload are losslessly projected into the generic Machine semantic state/commit, while user Method state remains separately typed in generic Program data.
- ResearchHostExecution now exposes visit_counts and step_count so downstream facades consume the generic host receipt rather than private Machine state.
- Validation: all touched generic Machine/Method modules pass py_compile and git diff --check. Docker/Python 3.12 executable smoke passed with F018_SINGLE_UNIVERSAL_MACHINE_OK, including a two-node successful Method and a max_visits failure whose final Machine commit is durably FAILED.
### Fix F-022 - RESOLVED

- The process-local WorkloadGraph pending/ready/results scheduler was deleted.
- Immutable AssignmentWorkload DAGs are compiled deterministically into topological waves, and each wave is one node in a generic ResearchProgram with MachineKind.RUN.
- Machine Journal is now the sole scheduling/recovery truth for Workload progression. Wave handlers execute only their statically assigned task set and never own pending/ready state.
- Independent tasks in one wave retain TaskGroup parallel execution; inter-wave dependency progression is durable generic Machine state.
- Full WorkloadTaskResult values, including Method receipt, evidence ArtifactReference, failure id, completion receipt, diagnostics and exports, now have a canonical JSON codec and are persisted in Machine Program data.
- Failed prerequisites are projected as blocked task results inside the next committed wave. Wider-than-task failures become durable FAILED Machine commits with typed workload_failure semantics.
- bind_workload_graph now requires a persistent state_root. The canonical automatic Trial path binds it under workload-graphs/<closure_digest>; no process-local fallback remains.
- Validation: py_compile and git diff --check pass. Docker/Python 3.12 replay smoke passed with F022_WORKLOAD_MACHINE_REPLAY_OK: a two-wave a/b -> c DAG executed once, produced start + two wave commits, and a second execute_graph call returned the same result from durable Machine state without re-invoking any task.
### Fix F-024 - RESOLVED

- The independent Experimentation Run/Workload checkpoint-and-restore subsystem was deleted rather than retained as a compatibility mechanism.
- Removed the entire research/experimentation/lifecycle/checkpoint package, including DirectoryCheckpointStore, CheckpointCoordinator, Run/Workload checkpoint manifests/bundles, WorkloadExecutionCut, direct component restore, rollback and its separate GC/persistence state.
- Removed all checkpoint subsystem exports from lifecycle.api and the legacy RunCheckpointManifest re-export from experimentation.api.
- Canonical recovery authority remains Machine Journal + MachineCut, with ResearchOS/Method checkpoint objects only as projections of verified Machine cuts.
- Environment-specific snapshot payload support may remain where it is a component payload mechanism, but no Experimentation execution-cut authority remains outside Machine.
- Validation: lifecycle/experimentation API modules pass py_compile, repository search finds no remaining Experimentation Run/Workload checkpoint symbols outside the deleted package, and git diff --check passes.
### Fix F-020 - RESOLVED

- The obsolete ContextAction Environment-effect workflow family was deleted instead of wrapped or retained.
- Removed its independent SafeEnvironmentActionExecutor / JournaledActionExecutor, build_action_effect_intent namespace, prepare/execute/reconcile coordination, action slot guard, recovery coordinator, ContextAction surface and composition helper.
- The only raw EnvironmentSession action bridge is now composition.environment_capabilities.action, which exposes DurablePreparedCapabilitySession semantics to the canonical CapabilityEffectExecutor.
- EffectIntent preparation/result/reconciliation/terminalization therefore has one semantic coordinator and one capability-effect intent identity path for Environment actions.
- Governance architecture rules were updated to remove ContextAction workflow requirements/dispatch authorities and to recognize environment_capabilities.action as the single raw Environment action authority. The obsolete Study checkpoint source-authority rule was also removed with F-024.
- No context_action, ContextAction or environment-effect workflow symbols remain in production Python sources.
- Validation: affected governance modules pass py_compile and git diff --check; repository search confirms the duplicate workflow family is gone.
### Fix F-029 - RESOLVED

- The independent Experimentation RunArtifact authority was removed rather than adapted.
- ResearchOSExperimentRuntimeBinding no longer carries an Artifact-store factory or commits its identity into scientific/runtime binding identity; Artifact publication is platform infrastructure, not Study semantics.
- CanonicalResearchOSNodeRuntime now requires the shared ResearchExecutionContentAuthorities and publishes protocol, observations, aggregates and report manifest directly through the canonical Blob/Catalog/Reference Artifact authority under an execution-cut RUN scope.
- Report references now contain canonical ArtifactReference identity plus catalog content digest/media type/kind/retention; publication is immediately read back and byte-verified.
- Local ResearchOS composition no longer creates a run-artifacts directory, Artifact task group or DirectoryResearchOSExperimentArtifactStoreFactory. The factory module was deleted.
- The RunArtifact API/runtime/composition store, finalization, verification, seal, GC, snapshot-receipt and private evidence-bundle lifecycle were physically deleted, along with the old Study RunArtifact publication helper and all top-level re-exports.
- Repository search finds no RunArtifact authority symbols in production Python. Remaining Run lifecycle code owns only Run identity/lifecycle/spec/execution semantics.
- Validation: all touched ResearchOS/Experimentation modules pass py_compile and git diff --check; compose_local_research_os executes against the shared content authority in Docker/Python 3.12.

### Fix F-036 - RESOLVED

- The nominal all-kinds value authority was replaced by ResearchOSArtifactValueAuthority.
- The default local value plane now advertises exactly one kind: ResearchValueKind.ARTIFACT, which it genuinely owns by materializing immutable JSON into the canonical Artifact Blob/Catalog/Retention authorities.
- Direct use also fails closed unless the subject kind is ARTIFACT.
- DATA, METRIC, EVIDENCE, CHECKPOINT and SELECTION are no longer accepted as labels over arbitrary Artifact-backed JSON. If no real lower-authority adapter is registered for one of those kinds, ResearchOSValueRouter admission raises ResearchOSValueAuthorityMissing.
- This preserves the contract that ResearchOSValueReference is only a routing envelope and that the named lower authority remains truth.
- No backwards-compatibility alias for ResearchOSImmutableValueAuthority remains.
- Validation: py_compile and git diff --check pass. Docker/Python 3.12 semantic smoke passed with F036_VALUE_AUTHORITY_FAIL_CLOSED_OK: ARTIFACT publish/resolve succeeded, while DATA/METRIC/EVIDENCE/CHECKPOINT/SELECTION were all rejected as unsupported.

### Fix F-031 - RESOLVED
- Changed `PortfolioQualifiedModelResolver` to preserve every distinct qualified scientific model member instead of collapsing candidates to one heartbeat-selected binding. Physical replicas remain inside each member authority; distinct model-stack/deployment-generation identities remain separate panel members.
- Scientific cardinality is fail-closed: if qualified members exceed `ResearchModelRoleRequirement.max_bindings`, resolution rejects the ambiguous closure rather than silently selecting a subset.
- Canonical Method runtime now materializes every frozen `(role, member_index)` binding. A single-member role keeps its role id; a multi-member execution role is addressed explicitly as `role#member_index`, so no implicit member-0 or hidden voting policy exists.
- Validation: `py_compile` and `git diff --check` pass for `local_research_execution_authority.py`; Python 3.12 Docker probe produced `F031_PANEL_CARDINALITY_OK ('d1', 'd2')` and verified `max_bindings=1` rejects the same two-member closure.

### Fix F-028 - RESOLVED
- Replaced the single-Method automatic Trial assumption with ScheduledParticipantWorkloadBinding.
- ParticipantSchedule is compiled into one parent ResearchProgram; each role is an ordinary child ResearchProgram Machine using the canonical child-machine ABI and shared ResearchExecutionPool.
- Parent transitions commit ChildMachineLink values; each participant keeps an authoritative MachineCut and canonical Method evidence. No participant scheduler, retry ledger, checkpoint authority, or worker pool exists outside the universal Machine path.
- WorkloadTaskResult now preserves role-sorted participant receipts and exports all role outputs under exports.participants.<role> without guessing a final participant.
- Validation: Python compile/diff-check passed; Python 3.12 Docker probe printed F028_MULTI_PARTICIPANT_DURABLE_OK and confirmed two distinct child cuts plus a stable parent cut; re-execution reused terminal cuts and did not invoke Method handlers again.

### Fix F-038 - RESOLVED
- Exact factor intervention payloads now survive into ExecutionContext.intervention_values and the public ResearchMethodCall surface; participant role/kind/treatment_id are frozen into participant_context and child Machine identity.
- Canonical multi-participant execution no longer collapses treatment identity to labels only.
- Validation: Python compile/diff-check passed; Docker runtime probe verified exact intervention payload and treatment identity are visible inside Method execution.

### Fix F-039 - RESOLVED
- Study assignment_seed now drives one canonical ExecutionContext.random_seed(namespace) derivation used by model sampling and environment assignment.
- Minecraft no longer uses a fixed world seed; its assignment-level world seed is derived from the Study assignment seed and frozen into the branch manifest/server spec.
- Validation: Docker runtime probe printed F038_F039_CONTEXT_SEED_OK; same assignment seed produced the same environment seed, different assignment seed produced a different seed, and model call ordinals produced distinct deterministic sampling seeds.

### Fix F-034 - RESOLVED
- Added one immutable ResearchDefinitionBindingRegistry as the canonical platform-resolution authority for implementation-free ResearchDefinition values. Owner systems materialize exact bindings once before preflight; lowering now distinguishes paper implementations, proven platform bindings, and genuinely unresolved requirements.
- Binding identity/provenance is frozen into lowering and runtime admission digests and is reused unchanged by RUN, RESUME, RETRY, MIGRATE, CHECKPOINT and RECONCILE paths.
- Local owner materialization reuses existing Environment, Data, Resource, Model, Participant, Benchmark and Experimentation authorities; missing owner facts remain fail-closed rather than becoming config-only pseudo-bindings.
- Validation: composition-wide py_compile/diff-check passed; Docker preflight probe printed F034_DEFINITION_AUTHORITY_PREFLIGHT_OK and proved the same revision is admitted with an exact platform binding and rejected when that binding authority is absent.

### Fix F-041 - RESOLVED
- Canonical Trial benchmark/verifier materialization now uses the same ResearchDefinition binding authority for platform-resolved definitions and the immutable implementation resolver for paper-owned definitions; no separate verifier execution path exists.
- ResearchProgramBuilder.verifier() now permits an implementation-free verifier requirement. WorkloadTrialProvider receives the canonical verifier artifact publisher and exact verifier identity, while TrialVerifierOrchestrator still enforces artifact-only handoff and declared isolation evidence.
- Validation: Docker probe printed F041_PLATFORM_VERIFIER_CANONICAL_OK; platform verifier materialization, missing-binding fail-closed, artifact allowlist handoff, measurement production and separate-isolation evidence all executed successfully.

### Fix F-037 - RESOLVED
- Added one crash-durable SQLiteExecutionBudgetAuthority shared by Trial, Method nodes and model calls. Trial opens one assignment-lifetime scope before execution and freezes the admission digest into ExecutionContext.
- max_steps, max_seconds/max_working_seconds, max_turns, max_messages, max_model_calls, max_tokens and max_cost_usd are enforced by the same durable ledger. Model requests reserve token/call/message budget before dispatch, are capped by exact tokenization, then commit provider-observed actual usage; post-response violations fail the parent Machine while preserving the model effect receipt/evidence.
- resource_budget_digest must equal the active ResearchExecutionPool resource policy digest. ReplayLevel.OBSERVATIONAL uses evidence-only proof, CHECKPOINT requires durable Machine-journal proof, and EXACT requires an explicit owner-system exact-replay proof. max_cost_usd fails closed unless a cost-accounting authority identity is bound.
- Validation: Python compile/diff-check passed. Docker probe printed F037_SHARED_BUDGET_TOKEN_REPLAY_OK and proved idempotent step charges, token capping, global cross-child model-call enforcement, concurrent reservation exclusion, resource mismatch rejection, exact-without-proof rejection and cost-without-authority rejection. A second Docker probe printed F037_COST_EXACT_POSITIVE_OK and proved exact/cost positive admission plus cumulative cost limit enforcement.

### Fix F-040 - RESOLVED
- Canonical Method runtime now consumes runtime concerns only through the universal ResearchProgram/child-Machine path. ResearchMethod runtime/participant/memory/environment/optimization components automatically add CHILD_MACHINES to the frozen Method requirements and compose_program_method_runtime_inventory() registers them as ResearchProgramHost values in the canonical ChildResearchMachineExecutor. No concern-specific Method port or scheduler was added.
- Participant scheduling is already compiled by F-028 into a parent ResearchProgram with child Machines; intervention/seed/recovery/model/evidence mechanics are native ExecutionContext/Machine/authority concerns rather than parallel execution engines. RuntimeModule remains compile-time composition only and owns no journal/state authority.
- Fixed RuntimeProgramTrialProtocol to use the caller-supplied MachineJournalPort instead of the invalid owned_journal name, preserving one journal authority.
- Validation: Docker probe printed F040_RUNTIME_COMPONENT_UNIVERSAL_MACHINE_OK and proved automatic component registration, parent/child durable cuts and terminal-cut replay without reinvoking handlers. A separate RuntimeProgramTrialProtocol Docker probe printed F040_RUNTIME_TRIAL_JOURNAL_OK and proved the runtime program executes on the supplied Machine journal.
