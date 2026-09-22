# Noetrium downstream capability catalog

This file is generated from the canonical system registry and public API exports.
Do not edit it manually; run python scripts/update_generated_docs.py.

## How downstream projects use Noetrium

1. Import only the unified noetrium.api surface.
2. Use api.<Symbol> from the Product authoring surface. Lower platform layers are not downstream entrypoints.
3. Use api.search(), api.describe(), api.catalog(), and api.interface_schema() for discovery; do not import noetrium_platform implementation modules.
4. Run python scripts/update_generated_docs.py after changing a registry descriptor or public API export.

Example:

    from noetrium import api

    MethodSpec = api.AgentMethodSpec
    MinecraftBridgePort = api.MinecraftBridgePort

- Registered systems: 30
- Public API modules: 405
- Public symbols: 4361
- Registry digest: e8b5c76efc480dab2647c61ff1a5c4653fa51d1b293e71c966e793578a299846

## Capability domains

| Domain | Systems | API modules | Symbols |
| --- | ---: | ---: | ---: |
| artifact | 1 | 23 | 122 |
| data | 3 | 19 | 122 |
| environment | 6 | 21 | 208 |
| execution | 2 | 37 | 659 |
| experimentation | 1 | 65 | 972 |
| governance | 3 | 34 | 389 |
| model | 1 | 52 | 535 |
| observability | 2 | 0 | 0 |
| operator | 1 | 0 | 0 |
| participant | 1 | 39 | 447 |
| platform | 1 | 6 | 83 |
| portfolio | 1 | 4 | 69 |
| reliability | 3 | 30 | 172 |
| resource | 2 | 19 | 171 |
| runtime | 1 | 49 | 386 |
| scope | 1 | 7 | 26 |

## System surfaces

### artifact

- Package: noetrium_platform.evidence.artifact
- Authority: artifact_identity
- Canonical authority: artifact
- Node kind: authority
- Owns: immutable content identity, references, retention and catalog
- Must not own: mutable business state
- Requires: platform, scope
- Provides: artifact.registry
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact

#### API modules

- noetrium_platform.evidence.artifact.api ?w^~)?t ArchiveMaterializationPort, ArchiveMaterializationRequest, ArtifactAcquisitionPort, ArtifactAcquisitionRequest, ArtifactAcquisitionResult, ArtifactBlobRef, ArtifactBlobStorePort, ArtifactContentIdentity, ArtifactHttpOpener, ArtifactHttpResponse, ArtifactKind, ArtifactQuery, ArtifactRecord, ArtifactReference, ArtifactReferencePort, ArtifactRegistryPort, ArtifactRetention, MaterializedTreeInspectionPort, MultimodalPart
- noetrium_platform.evidence.artifact.api.contracts ?w^~)?t ArtifactContentIdentity
- noetrium_platform.evidence.artifact.catalog.api ?w^~)?t ArtifactKind, ArtifactNotFound, ArtifactQuery, ArtifactRecord, ArtifactRegistryConflict, ArtifactRegistryCorruptionError, ArtifactRegistryPort, ArtifactRetention
- noetrium_platform.evidence.artifact.catalog.api.contracts ?w^~)?t ArtifactKind, ArtifactQuery, ArtifactRecord, ArtifactRetention
- noetrium_platform.evidence.artifact.catalog.api.errors ?w^~)?t ArtifactNotFound, ArtifactRegistryConflict, ArtifactRegistryCorruptionError
- noetrium_platform.evidence.artifact.catalog.api.ports ?w^~)?t ArtifactRegistryPort
- noetrium_platform.evidence.artifact.content.api ?w^~)?t MultimodalPart, ArtifactBlobRef, ArtifactBlobStoreError, ArtifactBlobStorePort, TensorContentRef, TensorContentStorePort, ArtifactAcquisitionError, ArtifactHttpOpener, ArtifactHttpResponse, ArtifactAcquisitionPort, ArtifactAcquisitionRequest, ArtifactAcquisitionResult, ArtifactContentIdentityResolverPort, ArtifactContentIdentityVerificationError, ArtifactStorageBinding, ArtifactStorageBindingConflict, ArtifactStorageBindingCorruptionError, ArtifactStorageBindingNotFound, ArtifactStorageBindingPort, ArtifactStoragePlacementVerifierPort, ArtifactStorageVerificationError, VerifiedArtifactStoragePlacement, ArchiveMaterializationError, ArchiveMaterializationPort, ArchiveMaterializationRequest, ArchiveMaterializationResult, MaterializedTreeInspection, MaterializedTreeInspectionPort
- noetrium_platform.evidence.artifact.content.api.acquisition ?w^~)?t ArtifactAcquisitionError, ArtifactHttpOpener, ArtifactHttpResponse, ArtifactAcquisitionPort, ArtifactAcquisitionRequest, ArtifactAcquisitionResult
- noetrium_platform.evidence.artifact.content.api.blob ?w^~)?t ArtifactBlobRef, ArtifactBlobStoreError, ArtifactBlobStorePort
- noetrium_platform.evidence.artifact.content.api.identity ?w^~)?t ArtifactContentIdentityResolverPort, ArtifactContentIdentityVerificationError
- noetrium_platform.evidence.artifact.content.api.materialization ?w^~)?t ArchiveMaterializationError, ArchiveMaterializationPort, ArchiveMaterializationRequest, ArchiveMaterializationResult, MaterializedTreeInspection, MaterializedTreeInspectionPort
- noetrium_platform.evidence.artifact.content.api.multimodal ?w^~)?t MultimodalPart
- noetrium_platform.evidence.artifact.content.api.storage ?w^~)?t ArtifactStorageBinding, ArtifactStorageBindingConflict, ArtifactStorageBindingCorruptionError, ArtifactStorageBindingNotFound, ArtifactStorageBindingPort, ArtifactStoragePlacementVerifierPort, ArtifactStorageVerificationError, VerifiedArtifactStoragePlacement
- noetrium_platform.evidence.artifact.content.api.tensor ?w^~)?t TensorContentRef, TensorContentStorePort
- noetrium_platform.evidence.artifact.lineage.relation.api ?w^~)?t ArtifactLineageConflict, ArtifactLineageCorruptionError, ArtifactLineageCycle, ArtifactLineageEdge, ArtifactLineageRelationPort
- noetrium_platform.evidence.artifact.lineage.relation.api.contracts ?w^~)?t ArtifactLineageConflict, ArtifactLineageCorruptionError, ArtifactLineageCycle, ArtifactLineageEdge
- noetrium_platform.evidence.artifact.lineage.relation.api.ports ?w^~)?t ArtifactLineageRelationPort
- noetrium_platform.evidence.artifact.reference.api ?w^~)?t ArtifactReference, ArtifactReferenceConflict, ArtifactReferenceCorruptionError, ArtifactReferenceNotFound, ArtifactReferencePort
- noetrium_platform.evidence.artifact.reference.api.contracts ?w^~)?t ArtifactReference, ArtifactReferenceConflict, ArtifactReferenceCorruptionError, ArtifactReferenceNotFound
- noetrium_platform.evidence.artifact.reference.api.ports ?w^~)?t ArtifactReferencePort
- noetrium_platform.evidence.artifact.retention.api ?w^~)?t ArtifactRetentionConflict, ArtifactRetentionCorruptionError, ArtifactRetentionNotFound, ArtifactRetentionPort, ArtifactRetentionState
- noetrium_platform.evidence.artifact.retention.api.contracts ?w^~)?t ArtifactRetentionConflict, ArtifactRetentionCorruptionError, ArtifactRetentionNotFound, ArtifactRetentionState
- noetrium_platform.evidence.artifact.retention.api.ports ?w^~)?t ArtifactRetentionPort

### data

- Package: noetrium_platform.evidence.data
- Authority: data_authority
- Canonical authority: data
- Node kind: authority
- Owns: durable facts, records, datasets, canonical state and projections
- Must not own: immutable artifact content identity
- Requires: artifact, platform, scope
- Provides: dataset.registry, projection.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.data

#### API modules

- noetrium_platform.evidence.data.api ?w^~)?t ResearchDimension, ResearchDimensionKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultQuery, ResearchResultRecord, ResearchResultReference, ResearchSourceDisposition, ResearchSourceSnapshot, source_cut
- noetrium_platform.evidence.data.dataset.api ?w^~)?t DatasetIdentity, DatasetNotFound, DatasetQuery, DatasetRegistryConflict, DatasetRegistryCorruptionError, DatasetRegistryPort, DatasetVersion
- noetrium_platform.evidence.data.dataset.api.contracts ?w^~)?t DatasetIdentity, DatasetQuery, DatasetVersion
- noetrium_platform.evidence.data.dataset.api.errors ?w^~)?t DatasetNotFound, DatasetRegistryConflict, DatasetRegistryCorruptionError
- noetrium_platform.evidence.data.dataset.api.ports ?w^~)?t DatasetRegistryPort
- noetrium_platform.evidence.data.projection.api ?w^~)?t ProjectionCheckpoint, ProjectionCheckpointStorePort, ProjectionCursor, ProjectionReducerPort, ProjectionTail, SemanticProjectionEntry, SemanticProjectionSnapshot, SemanticSourceReference
- noetrium_platform.evidence.data.projection.api.contracts ?w^~)?t ProjectionCheckpoint, ProjectionCheckpointStorePort, ProjectionCursor, ProjectionReducerPort, ProjectionTail
- noetrium_platform.evidence.data.projection.api.semantic ?w^~)?t SemanticProjectionEntry, SemanticProjectionSnapshot, SemanticSourceReference
- noetrium_platform.evidence.data.query.api ?w^~)?t ResearchDimension, ResearchDimensionKind, ResearchQueryGap, ResearchQueryGapKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultPage, ResearchResultQuery, ResearchResultQueryPort, ResearchResultRecord, ResearchResultReference, ResearchResultSourcePort, ResearchSourceCut, ResearchSourceDisposition, ResearchSourceSnapshot, ResearchSourceStatus, SemanticSimilarityMatch, SemanticSimilarityMetric, SemanticSimilarityQuery, SemanticSimilarityQueryPort, SemanticSimilarityResult, source_cut
- noetrium_platform.evidence.data.query.api.contracts ?w^~)?t ResearchDimension, ResearchDimensionKind, ResearchQueryGap, ResearchQueryGapKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultPage, ResearchResultQuery, ResearchResultRecord, ResearchResultReference, ResearchSourceCut, ResearchSourceDisposition, ResearchSourceSnapshot, ResearchSourceStatus
- noetrium_platform.evidence.data.query.api.identity ?w^~)?t input_cut_digest, query_document, record_document, research_query_digest, source_cut
- noetrium_platform.evidence.data.query.api.ports ?w^~)?t ResearchResultQueryPort, ResearchResultSourcePort
- noetrium_platform.evidence.data.query.api.semantic ?w^~)?t SemanticSimilarityMatch, SemanticSimilarityMetric, SemanticSimilarityQuery, SemanticSimilarityQueryPort, SemanticSimilarityResult

### data/fact

- Package: noetrium_platform.evidence.data.fact
- Authority: fact_authority
- Canonical authority: data/fact
- Node kind: authority
- Owns: durable fact envelopes and authoritative fact writes
- Must not own: business-specific state transitions
- Requires: none
- Provides: durable.fact
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__fact

#### API modules

- noetrium_platform.evidence.data.fact.api ?w^~)?t DurableFact, DurableFactConflict, DurableFactCorruptionError, DurableFactNotFound, DurableFactReceipt, DurableFactSinkPort, DurableFactStorePort, FactCriticality, FactDecoderPort, FactSchema, UnknownRequiredFact
- noetrium_platform.evidence.data.fact.api.contracts ?w^~)?t DurableFact, DurableFactConflict, DurableFactCorruptionError, DurableFactNotFound, DurableFactReceipt, DurableFactSinkPort, DurableFactStorePort, FactCriticality, FactDecoderPort, FactSchema, UnknownRequiredFact

### data/state

- Package: noetrium_platform.evidence.data.state
- Authority: state_authority
- Canonical authority: data/state
- Node kind: authority
- Owns: canonical mutable state and state-store contracts
- Must not own: disposable projections
- Requires: platform
- Provides: state.atomic
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__state

#### API modules

- noetrium_platform.evidence.data.state.api ?w^~)?t AggregateValue, AtomicMutation, AtomicStateStorePort, StateBootstrapConflict, StateCorruptionError, StateVersionConflict
- noetrium_platform.evidence.data.state.api.contracts ?w^~)?t AggregateValue, AtomicMutation
- noetrium_platform.evidence.data.state.api.errors ?w^~)?t StateBootstrapConflict, StateCorruptionError, StateVersionConflict
- noetrium_platform.evidence.data.state.api.ports ?w^~)?t AtomicStateStorePort

### environment

- Package: noetrium_platform.capabilities.environment
- Authority: environment_state
- Canonical authority: environment
- Node kind: authority
- Owns: environment specs, bindings, resolution and instances
- Must not own: project semantics and model serving
- Requires: governance/system_registry, platform, reliability, resource, runtime, scope
- Provides: environment.catalog, environment.category, environment.contract, environment.embodied.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment

#### API modules

- noetrium_platform.capabilities.environment.api ?w^~)?t observation_payload, observation_from_payload, effect_receipt_payload, effect_receipt_from_payload, action_result_payload, action_result_from_payload, ExecutionContext, EffectClass, EffectCertainty, EffectReceipt, ActionIdentityViolation, ActionNotApplied, ActionRecoveryRequired, ActionReconciliationDisposition, ActionReconciliationResult, ActionRequest, ActionResult, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, ActionSemanticIdentity, EnvironmentBranchState, EnvironmentBranchStateMismatch, EnvironmentBranchStatePort, EnvironmentRecoverySession, EnvironmentResetPort, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationPort, EnvironmentAssignmentIsolationReceipt, EnvironmentCapabilityUnsupported, EnvironmentCapability, EnvironmentConformanceProbe, EnvironmentProviderConformanceReceipt, verify_environment_provider_conformance, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentProviderPort, EnvironmentSessionDiagnostics, EnvironmentSessionServices, EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort, DurablePreparedActionSession, EnvironmentIdentity, EnvironmentImplementation, EnvironmentSession, Observation, action_request_digest, require_action_recovery_handle_identity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_recovery_handle_reconciliation_identity, StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json_mapping, ActionKind, ActionSpec, EmbodiedActionCommand, EmbodimentKind, EmbodimentSpec, EnvironmentSpec, EpisodeSpec, ExecutionEnvironmentKind, SensorModality, SensorSpec
- noetrium_platform.capabilities.environment.api.action_identity ?w^~)?t ActionIdentityViolation, ActionSemanticIdentity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_action_recovery_handle_identity, require_recovery_handle_reconciliation_identity
- noetrium_platform.capabilities.environment.api.branch_state ?w^~)?t EnvironmentBranchState, EnvironmentBranchStateMismatch, EnvironmentBranchStatePort
- noetrium_platform.capabilities.environment.api.codec ?w^~)?t action_result_from_payload, action_result_payload, effect_receipt_from_payload, effect_receipt_payload, observation_from_payload, observation_payload
- noetrium_platform.capabilities.environment.api.conformance ?w^~)?t EnvironmentConformanceProbe, EnvironmentProviderConformanceReceipt, verify_environment_provider_conformance
- noetrium_platform.capabilities.environment.api.contracts ?w^~)?t ExecutionContext, SystemIdentity, SystemPort, SystemSpec, EffectReceipt, PreparedEffectHandle, EnvironmentIdentity, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationReceipt, EnvironmentAssignmentIsolationPort, Observation, ActionRequest, action_request_digest, ActionResult, ActionReconciliationDisposition, ActionReconciliationResult, DurablePreparedActionSession, EnvironmentSession, EnvironmentImplementation
- noetrium_platform.capabilities.environment.api.errors ?w^~)?t ActionNotApplied, ActionRecoveryRequired, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, EnvironmentCapabilityUnsupported
- noetrium_platform.capabilities.environment.api.interaction ?w^~)?t EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort
- noetrium_platform.capabilities.environment.api.provider ?w^~)?t EnvironmentCapability, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentProviderPort, EnvironmentSessionDiagnostics, EnvironmentSessionServices
- noetrium_platform.capabilities.environment.api.recovery ?w^~)?t EnvironmentRecoverySession
- noetrium_platform.capabilities.environment.api.reset ?w^~)?t EnvironmentResetPort
- noetrium_platform.capabilities.environment.api.state_machine ?w^~)?t StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json_mapping
- noetrium_platform.capabilities.environment.catalog.api ?w^~)?t EnvironmentAssignment, EnvironmentBinding, EnvironmentInstance, EnvironmentOverlay, EnvironmentSpec, EnvironmentTemplate, ExecutionEnvironmentCatalogPort, ExecutionEnvironmentKind, ResolvedEnvironmentSpec
- noetrium_platform.capabilities.environment.catalog.api.contracts ?w^~)?t EnvironmentAssignment, EnvironmentBinding, EnvironmentInstance, EnvironmentOverlay, EnvironmentSpec, EnvironmentTemplate, ExecutionEnvironmentKind, ResolvedEnvironmentSpec
- noetrium_platform.capabilities.environment.catalog.api.ports ?w^~)?t ExecutionEnvironmentCatalogPort
- noetrium_platform.capabilities.environment.category.api ?w^~)?t EnvironmentCategoryCatalogPort, EnvironmentCategoryDescriptor, EnvironmentCategoryId, EnvironmentCategoryStatus, EnvironmentImplementationDescriptor
- noetrium_platform.capabilities.environment.category.api.contracts ?w^~)?t EnvironmentCategoryDescriptor, EnvironmentCategoryId, EnvironmentCategoryStatus, EnvironmentImplementationDescriptor
- noetrium_platform.capabilities.environment.category.api.ports ?w^~)?t EnvironmentCategoryCatalogPort
- noetrium_platform.capabilities.environment.embodied.api ?w^~)?t ActionKind, ActionSpec, EmbodiedActionCommand, EmbodiedCaptureReceipt, EmbodiedCapabilityPort, EmbodiedCheckpointPort, EmbodiedEnvironmentPort, EmbodiedQueryPort, EmbodiedEvent, EmbodiedEventKind, EmbodiedTrajectorySinkPort, EmbodimentKind, EmbodimentSpec, EpisodeSpec, SensorModality, SensorSpec
- noetrium_platform.capabilities.environment.embodied.api.contracts ?w^~)?t ActionKind, ActionSpec, EmbodiedActionCommand, EmbodiedCaptureReceipt, EmbodiedEvent, EmbodiedEventKind, EmbodimentKind, EmbodimentSpec, EpisodeSpec, SensorModality, SensorSpec
- noetrium_platform.capabilities.environment.embodied.api.ports ?w^~)?t EmbodiedCapabilityPort, EmbodiedCheckpointPort, EmbodiedEnvironmentPort, EmbodiedQueryPort, EmbodiedTrajectorySinkPort

### environment/minecraft

- Package: noetrium_platform.capabilities.environment.minecraft
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: Minecraft environment contracts, server-control/world-cut semantics, state projection, bridge providers and readiness adapters
- Must not own: generic environment catalog, process/server supervision, model serving, project method semantics or telemetry storage
- Requires: artifact, environment, reliability, resource, runtime
- Provides: environment.minecraft.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__minecraft

### environment/gui

- Package: noetrium_platform.capabilities.environment.gui
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: desktop and mobile GUI environment contracts and provider adapters
- Must not own: benchmark cases, task scoring, tool capability policy or OS process supervision
- Requires: environment, runtime
- Provides: environment.gui.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__gui

### environment/web

- Package: noetrium_platform.capabilities.environment.web
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: stateful web and browser environment contracts and provider adapters
- Must not own: benchmark cases, task scoring, browser automation policy or model serving
- Requires: environment, runtime
- Provides: environment.web.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__web

### environment/software

- Package: noetrium_platform.capabilities.environment.software
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: repository and software-workspace environment contracts and provider adapters
- Must not own: benchmark scoring, repository policy, model serving or generic process supervision
- Requires: environment, resource, runtime
- Provides: environment.software.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__software

### environment/text_world

- Package: noetrium_platform.capabilities.environment.text_world
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: text-mediated stateful world contracts and provider adapters
- Must not own: dialogue method, benchmark scoring, agent memory or multi-agent topology
- Requires: environment
- Provides: environment.text_world.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__text_world

### execution

- Package: noetrium_platform.research.execution
- Authority: execution_operations
- Canonical authority: execution
- Node kind: authority
- Owns: workflow and operation orchestration contracts
- Must not own: provider storage and domain truth
- Requires: artifact, environment, governance, model, observability, participant, platform, reliability, runtime, scope
- Provides: capability.invocation, capability.registration, method.abi, method.checkpoint, method.machine, research.machine.authoring, research.program, runtime.program, workflow.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution

#### API modules

- noetrium_platform.research.execution.api ?w^~)?t DeploymentStatusIdentity, ExecutionIntentPort, ExecutionIntentReceipt, ExecutionOperationIntent, ExecutableProgramIdentity, ExecutableProgramSourcePublicationPort, PublishedExecutableProgramSource, ProgramExecutionPort, ProgramExecutionRecoveryPort, ProgramExecutionReconciliationDisposition, ProgramExecutionReconciliationResult, ProgramExecutionReceipt, ProgramExecutionRequest, ProgramExecutionStatus, MethodRuntimeBinderPort, MethodEvidenceFactoryPort, require_execution_trial_protocol, ExecutionTrialProtocolPort, ExecutionTrialProtocolKind, AsyncOperationDispatchPort, DecisionCycleIdentity, DecisionCycleIdentityProvider, DecisionCycleResult, EffectIntentOperationPort, EffectReconciliationOutcome, EffectReconciliationVerdict, EvaluationConcern, ExecutionPriority, ExperimentConcern, ExperimentProgramBuilder, MachineEvent, MethodAgentLoopPort, MethodChildMachinePort, MethodMachinePort, MethodObservationPort, MethodProgram, MethodRunResult, MethodRunStatus, MethodRuntimeContext, MethodRuntimePort, MethodRuntimePortInventory, MethodSchemaPort, OperationDispatchPort, ProgramHandlerRegistry, ProgramNodeRequest, ProgramNodeResult, ProgramRule, ProgramRuleSet, ResearchHostOperation, ResearchProgram, ResearchProgramHost, RuleDispatchMode, RunConcern, RuntimeConcern, RuntimeProgramBuilder, TrialCycleExecution, UnhandledEventPolicy, WorkflowSurfaceBindingContext, WorkflowSurfaceFactory, WorkflowSurfaceReuseScope, analyze_method_runtime_requirements, build_rule_handlers, compile_rule_program, core_program_handlers, plan_method_runtime_binding, workflow_surface_id, workflow_surface_reuse_scope, BoundParticipant, BoundParticipants, CapabilityDescriptor, CapabilityPort, CapabilityRequest, CapabilityResult, ParticipantCheckpoint, ParticipantCheckpointOperationsPort, ParticipantCheckpointRef, ParticipantImplementationIdentity, ParticipantResolutionPort, ParticipantRuntimeBinding, ParticipantSessionBinding, ParticipantSessionLifecyclePort, ParticipantSessionRuntimeIdentity, ProjectParticipantBinding, capability_request_digest, ArtifactContentIdentity, ArtifactReference, ArtifactReferencePort, ArtifactRegistryPort, BindingProof, CompositionSubject, ComputeLeaseGuardFactoryPort, ComputeLeaseGuardPort, ComputeRequirement, ComputeSchedulerPort, GpuSharingMode, ProjectCapabilityRequirement, ProjectConfigurationReference, ProjectManifest, ProjectMethodRequirement, ProjectModelBinding, ProjectModelBindingSet, ProjectProviderBinding, ProjectRequirementCardinality, QualifiedModelEndpointBinding, ResearchDimension, ResearchDimensionKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultQuery, ResearchResultRecord, ResearchResultReference, ResearchSourceDisposition, ResearchSourceSnapshot, ScopeIdentity, ScopeKind, ScopeRegistryPort, is_absolute_target_path, source_cut, ActionKind, ActionSpec, AgentGoal, AgentMethodSpec, AgentPhaseSpec, EmbodiedActionCommand, EmbodimentKind, EmbodimentSpec, EnvironmentSpec, ExecutionEnvironmentKind, GuardDecision, GuardVerdict, MethodProgramBuilder, MethodWorkflow, SensorModality, SensorSpec, EnvironmentCapability, EnvironmentProviderPort, ExecutionContext, MethodIdentity, MethodRuntimeIdentity, program_execution_capability_payload
- noetrium_platform.research.execution.api.intent ?w^~)?t ExecutionIntentPort, ExecutionIntentReceipt, ExecutionOperationIntent
- noetrium_platform.research.execution.api.participants ?w^~)?t BoundParticipant, BoundParticipants, CapabilityDescriptor, CapabilityPort, CapabilityRequest, CapabilityResult, ParticipantCheckpoint, ParticipantCheckpointOperationsPort, ParticipantCheckpointRef, ParticipantImplementationIdentity, ParticipantResolutionPort, ParticipantRuntimeBinding, ParticipantSessionBinding, ParticipantSessionLifecyclePort, ParticipantSessionRuntimeIdentity, ProjectParticipantBinding, capability_request_digest
- noetrium_platform.research.execution.api.platform ?w^~)?t ArtifactContentIdentity, ArtifactReference, ArtifactReferencePort, ArtifactRegistryPort, BindingProof, CompositionSubject, ComputeLeaseGuardFactoryPort, ComputeLeaseGuardPort, ComputeRequirement, ComputeSchedulerPort, GpuSharingMode, ProjectCapabilityRequirement, ProjectConfigurationReference, ProjectManifest, ProjectMethodRequirement, ProjectModelBinding, ProjectModelBindingSet, ProjectProviderBinding, ProjectRequirementCardinality, QualifiedModelEndpointBinding, ResearchDimension, ResearchDimensionKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultQuery, ResearchResultRecord, ResearchResultReference, ResearchSourceDisposition, ResearchSourceSnapshot, ScopeIdentity, ScopeKind, ScopeRegistryPort, is_absolute_target_path, source_cut
- noetrium_platform.research.execution.api.program_execution ?w^~)?t ExecutableProgramIdentity, ExecutableProgramSourcePublicationPort, PublishedExecutableProgramSource, ProgramExecutionPort, ProgramExecutionRecoveryPort, ProgramExecutionReconciliationDisposition, ProgramExecutionReconciliationResult, ProgramExecutionReceipt, ProgramExecutionRequest, ProgramExecutionStatus
- noetrium_platform.research.execution.api.program_execution_authoring ?w^~)?t program_execution_capability_payload
- noetrium_platform.research.execution.api.status ?w^~)?t DeploymentStatusIdentity
- noetrium_platform.research.execution.capability.api ?w^~)?t CapabilityInvocationPipelineFactoryPort, CapabilityInvocationPipelinePort, CapabilityLifetime, CapabilityRegistration, CapabilityTypeMismatch, RegistrationConflict, RegistrationHandlePort, RegistrationKey, RegistrationLeasePort, RegistrationScopeFactoryPort, RegistrationScopePort, ScopeDisposed
- noetrium_platform.research.execution.capability.api.invocation ?w^~)?t CapabilityInvocationPipelineFactoryPort, CapabilityInvocationPipelinePort
- noetrium_platform.research.execution.capability.api.registration ?w^~)?t CapabilityLifetime, CapabilityRegistration, CapabilityTypeMismatch, RegistrationConflict, RegistrationHandlePort, RegistrationKey, RegistrationLeasePort, RegistrationScopeFactoryPort, RegistrationScopePort, ScopeDisposed
- noetrium_platform.research.execution.machines.api ?w^~)?t CapabilityMediationDenied, CapabilityMediationRequest, CapabilityMediationResult, CapabilityMediationStage, CapabilityMediationVerdict, CapabilityMediator, CapabilityMediatorRegistry, CapabilityMediatorRegistryPort, CapabilityProgram, CapabilityRuleProgram, CapabilityRuntimeBinding, BatchCapableRegisteredChildResearchMachineExecutor, ChildBatchExecutionMode, ChildResearchMachineBatchExecution, ChildResearchMachineBatchExecutor, ChildResearchMachineBatchItem, ChildResearchMachineBatchPort, ChildResearchMachineBatchMechanicsPort, ChildResearchMachineBatchMechanicsResult, ChildResearchMachineBatchRequest, RegisteredSerialChildResearchBatchMechanics, ThreadPoolChildResearchBatchMechanics, ChildFailurePolicy, ChildResearchBindingFactory, ChildResearchHostRegistry, ChildResearchHostRegistryPort, ChildResearchMachineExecution, ChildResearchMachineExecutor, ChildResearchMachineRequest, CommunicationRuntimeSpec, ContextBlockProgram, ContextBudgetExceeded, ContextProgram, ContextProjection, ContextRenderRequest, ContextRenderResult, ContextRenderer, ContextRendererRegistry, ContextRendererRegistryPort, ContextRuntimeBinding, DomainProgramBuilder, EnvironmentConcern, EnvironmentMachineSpec, EnvironmentProgramBuilder, EvaluationConcern, EvaluationProgramBuilder, ExperimentConcern, ExperimentProgramBuilder, FunctionalModelInvocationRequestFactory, InterventionDecision, InterventionDecider, InterventionDeciderRegistry, InterventionDeciderRegistryPort, InterventionKind, InterventionPolicyRequest, InterventionProgram, InterventionResponse, InterventionRuntimeBinding, InterventionTrigger, LogicalSchedulingCandidate, LogicalSchedulingProgram, LogicalSchedulingRequest, LogicalSchedulingRuntimeBinding, LogicalSchedulingSelection, LogicalSchedulingSelector, LogicalSchedulingSelectorRegistry, LogicalSchedulingSelectorRegistryPort, MachineEvent, MemoryConcern, MemoryPresetSpec, MemoryProgramBuilder, MemoryRecord, ModelInvocationCandidate, ModelInvocationMode, ModelInvocationOutcome, ModelInvocationProgram, ModelInvocationRequestFactoryPort, ModelInvocationRuntime, ModelInvocationRuntimeBinding, ModelResponseSelector, ModelResponseSelectorRegistry, ModelResponseSelectorRegistryPort, ModelSelectionRequest, ObjectiveDirection, OptimizationConcern, OptimizationObjective, OptimizationPresetSpec, OptimizationProgramBuilder, PARTICIPANT_TURN_FACT_KINDS, PARTICIPANT_TURN_FACT_WIRE_SCHEMA, ParticipantConcern, ParticipantMessageKind, ParticipantProgramBuilder, ProgramHandlerRegistry, ProgramHandlerRegistryPort, ProgramNode, ProgramNodeRequest, ProgramNodeResult, ProgramOperationHandler, ProgramRule, ProgramRuleSet, RecoveryAction, RecoveryDecision, RecoveryDecider, RecoveryDeciderRegistry, RecoveryDeciderRegistryPort, RecoveryProgram, RecoveryRequest, RecoveryRuntimeBinding, RecoverySignal, RegisteredChildResearchHost, RegisteredChildResearchMachineExecutor, ResearchHostBindingRestorer, ResearchHostExecution, ResearchHostHandler, ResearchHostOperation, ResearchProgram, ResearchProgramBuilder, ResearchRunProgramBuilder, RuleDispatchMode, RunConcern, RuntimeConcern, RuntimeModule, RuntimeModuleBuilder, RuntimeModuleLink, RuntimeModuleNode, RuntimeProgramBuilder, RuntimeProgramComposer, SynchronizationAction, SynchronizationDecision, SynchronizationDecider, SynchronizationDeciderRegistry, SynchronizationDeciderRegistryPort, SynchronizationMode, SynchronizationPoint, SynchronizationPresetSpec, SynchronizationProgram, SynchronizationRequest, SynchronizationRuntimeBinding, UnhandledEventPolicy, VisibilityDecision, VisibilityDecider, VisibilityDeciderRegistry, VisibilityDeciderRegistryPort, VisibilityDisposition, VisibilityProgram, VisibilityRequest, VisibilityResource, VisibilityRuntimeBinding, VisibilitySubject, build_rule_handlers, capability_mediator_binding_digest, capability_program_from_policy, capability_runtime_module, communication_initial_data, communication_rule_set, compile_communication_runtime_program, compile_context, compile_environment_program, compile_memory_program, compile_optimization_program, compile_rule_program, context_projection_payload, context_renderer_binding_digest, context_runtime_module, context_runtime_operation, environment_initial_data, environment_rule_set, execution_context_from_payload, execution_context_payload, intervention_initial_data, intervention_runtime_module, logical_scheduling_initial_data, logical_scheduling_runtime_module, memory_initial_data, memory_rule_set, model_invocation_runtime_module, optimization_initial_data, optimization_rule_set, participant_turn_initial_data, participant_turn_program, program_handler_binding_digest, recovery_initial_data, recovery_runtime_module, standard_synchronization_decider, synchronization_initial_data, synchronization_program_from_preset, synchronization_runtime_module, visibility_initial_data, visibility_runtime_module, ResearchMachineRunPort, ResearchMachineSessionPort, ResearchProgramHostFactoryPort, ResearchProgramHostPort, capability_runtime_operations, default_memory_handlers, state_machine_environment_handlers, ResearchProgramHost, state_machine_environment_host, default_memory_host
- noetrium_platform.research.execution.machines.api.host_runtime ?w^~)?t ResearchMachineRunPort, ResearchMachineSessionPort, ResearchProgramHostFactoryPort, ResearchProgramHostPort
- noetrium_platform.research.execution.policy.api ?w^~)?t AdmissionBudget, AdmissionIdentity, AdmissionIntent, AdmissionMode, AdmissionRejected, AdmissionTopologySnapshot, ExecutionAdmissionPort, GroupAdmissionSnapshot, LaneAdmissionSnapshot, ResourceAdmissionSnapshot, TenantAdmissionSnapshot, AdmissionSchedulingPolicyPort, ExecutionPriority, SchedulingCandidate
- noetrium_platform.research.execution.policy.api.contracts ?w^~)?t ExecutionPriority, ExecutionLaneKind, ExecutionPermitRejected, AdmissionMode, AdmissionRejected, AdmissionBudget, AdmissionIdentity, AdmissionIntent, GroupAdmissionSnapshot, TenantAdmissionSnapshot, ResourceAdmissionSnapshot, LaneAdmissionSnapshot, AdmissionTopologySnapshot
- noetrium_platform.research.execution.policy.api.ports ?w^~)?t CancellationTokenPort, Deadline, ExecutionLaneKind, ExecutionPermitLeasePort, AdmissionIdentity, AdmissionIntent, AdmissionTopologySnapshot, ExecutionAdmissionPort
- noetrium_platform.research.execution.policy.scheduling.api ?w^~)?t AdmissionSchedulingPolicyPort, ExecutionPriority, SchedulingCandidate
- noetrium_platform.research.execution.policy.scheduling.api.contracts ?w^~)?t ExecutionPriority, SchedulingCandidate
- noetrium_platform.research.execution.policy.scheduling.api.ports ?w^~)?t SchedulingCandidate, AdmissionSchedulingPolicyPort
- noetrium_platform.research.execution.workflow.api ?w^~)?t require_execution_trial_protocol, ExecutionTrialProtocolPort, ExecutionTrialProtocolKind, AgentMethodSpec, AgentPhaseSpec, MethodWorkflow, EffectIntentOperationPort, OperationDispatchPort, OperationExecutionPort, TrialCycleExecution, WorkflowGraph, WorkflowGraphError, WorkflowParticipantRequirementError, WorkflowStep, WorkflowSurfaceBindingContext, WorkflowSurfaceFactory, WorkflowSurfaceReuseScope, workflow_surface_id, workflow_surface_reuse_scope, AsyncMethodAgentLoopPort, AsyncOperationDispatchPort, MethodAgentLoopPort, MethodAgentRequest, MethodAgentResult, MethodAgentTargetHandler, MethodCapabilityTargetHandler, MethodAgentViewHandler, MethodCheckpoint, MethodCheckpointStorePort, MethodEvidenceStatus, MethodExecutionClass, MethodEvidencePort, MethodEvent, MethodGraph, MethodInterrupt, MethodMachinePort, MethodChildMachinePort, MethodNodeHandler, MethodNodeKind, MethodNodeRequest, MethodNodeResult, MethodNodeSpec, MethodObservationPort, MethodProgram, MethodProgramBuilder, MethodRunResult, MethodRunStatus, MethodRuntimeContext, MethodRuntimePort, MethodRuntimeRequirements, MethodSchemaPort, analyze_method_runtime_requirements, MethodRuntimeBindingPlan, MethodRuntimePortInventory, plan_method_runtime_binding, MethodEvidenceFactoryPort, MethodRuntimeBinderPort, require_method_evidence_factory, require_method_runtime_binder
- noetrium_platform.research.execution.workflow.api.authoring ?w^~)?t AgentMethodSpec, AgentPhaseSpec
- noetrium_platform.research.execution.workflow.api.dispatch ?w^~)?t OperationDispatchPort, OperationExecutionPort
- noetrium_platform.research.execution.workflow.api.effect_intents ?w^~)?t EffectIntentOperationPort
- noetrium_platform.research.execution.workflow.api.errors ?w^~)?t WorkflowParticipantRequirementError
- noetrium_platform.research.execution.workflow.api.graph ?w^~)?t WorkflowGraph, WorkflowGraphError, WorkflowStep
- noetrium_platform.research.execution.workflow.api.method_machine ?w^~)?t AsyncMethodAgentLoopPort, AsyncOperationDispatchPort, MethodAgentLoopPort, MethodAgentRequest, MethodAgentResult, MethodCheckpoint, MethodCheckpointStorePort, MethodEvidencePort, MethodEvent, MethodEvidenceStatus, MethodExecutionClass, MethodGraph, MethodInterrupt, MethodNodeHandler, MethodNodeKind, MethodNodeRequest, MethodNodeResult, MethodNodeSpec, MethodObservationPort, MethodProgram, MethodProgramBuilder, MethodChildMachinePort, MethodRunResult, MethodMachinePort, MethodRunStatus, MethodRuntimeContext, MethodRuntimePort, MethodSchemaPort, MethodAuthoritativeState, MethodControlRecord, MethodTransitionAuthorityPort, MethodTransitionRecord
- noetrium_platform.research.execution.workflow.api.runtime_binding ?w^~)?t MethodRuntimeBindingPlan, MethodRuntimePortInventory, plan_method_runtime_binding
- noetrium_platform.research.execution.workflow.api.runtime_requirements ?w^~)?t MethodRuntimeRequirements, analyze_method_runtime_requirements
- noetrium_platform.research.execution.workflow.api.runtime_services ?w^~)?t MethodEvidenceFactoryPort, MethodRuntimeBinderPort, require_method_evidence_factory, require_method_runtime_binder
- noetrium_platform.research.execution.workflow.api.surfaces ?w^~)?t WorkflowSurfaceBindingContext, WorkflowSurfaceFactory, WorkflowSurfaceReuseScope, workflow_surface_reuse_scope, workflow_surface_id
- noetrium_platform.research.execution.workflow.api.trial ?w^~)?t ExecutionTrialProtocolKind, ExecutionTrialProtocolPort, TrialCycleExecution, require_execution_trial_protocol

### execution/operation

- Package: noetrium_platform.research.execution.operation
- Authority: operation_state
- Canonical authority: execution/operation
- Node kind: authority
- Owns: immutable execution command intent plus operation identity, lifecycle and result envelopes
- Must not own: failure taxonomy, recovery authority, provider effects or workflow orchestration
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__operation

#### API modules

- noetrium_platform.research.execution.operation.api ?w^~)?t EffectId, IllegalOperationTransition, OperationAdmissionPort, OperationConflict, OperationCorruption, OperationEffectCertainty, OperationEffectProfile, OperationFailure, OperationFailureKind, OperationId, OperationLifecyclePort, OperationRecoveryPort, OperationSnapshot, OperationState, OperationStorePort, OperationSubmissionPort, EffectReconciliationOutcome, EffectReconciliationVerdict, project_effect_reconciliation, TERMINAL_OPERATION_STATES, revise_operation, transition_operation, CommandConflict, CommandCorruption, CommandDeduplicationKey, CommandId, CommandIntentPort, CommandStorePort, ExecutionCommand
- noetrium_platform.research.execution.operation.api.contracts ?w^~)?t EffectId, IllegalOperationTransition, OperationEffectCertainty, OperationEffectProfile, OperationFailure, OperationFailureKind, OperationId, OperationSnapshot, OperationState, TERMINAL_OPERATION_STATES, revise_operation, transition_operation
- noetrium_platform.research.execution.operation.api.ports ?w^~)?t OperationAdmissionPort, OperationConflict, OperationCorruption, OperationLifecyclePort, OperationRecoveryPort, OperationStorePort, OperationSubmissionPort
- noetrium_platform.research.execution.operation.api.reconciliation ?w^~)?t EffectReconciliationOutcome, EffectReconciliationVerdict, project_effect_reconciliation
- noetrium_platform.research.execution.operation.command.api ?w^~)?t CommandConflict, CommandCorruption, CommandDeduplicationKey, CommandId, CommandIntentPort, CommandStorePort, ExecutionCommand
- noetrium_platform.research.execution.operation.command.api.contracts ?w^~)?t CommandDeduplicationKey, CommandId, ExecutionCommand
- noetrium_platform.research.execution.operation.command.api.ports ?w^~)?t CommandConflict, CommandCorruption, CommandIntentPort, CommandStorePort

### experimentation

- Package: noetrium_platform.research.experimentation
- Authority: experimentation_state
- Canonical authority: experimentation
- Node kind: authority
- Owns: study, experiment, run, branch and checkpoint semantics
- Must not own: server/process control and model serving
- Requires: artifact, environment, execution, governance, model, participant, platform, portfolio, resource, scope
- Provides: experiment.catalog, experiment.definition, experiment.resource-policy, experiment.runtime, experiment.workload, research.workbench, run.checkpoint, run.control, run.decision, run.identity, run.lifecycle, run.manifest, study.definition
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation

#### API modules

- noetrium_platform.research.experimentation.api ?w^~)?t ExperimentationCatalogPort, MachineCut, ResearchBindingContribution, ResearchCapabilityBinding, ResearchModelRoleBinding, ResearchModelRoleRequirement, ResearchParticipantBinding, ResearchBindingRequirements, ResearchParticipantRequirement, ResearchRequirementResolution, resolve_research_requirements, TaskVerifierArtifact, TaskVerifierPort, TaskVerifierReceipt, TaskVerifierRequest, TrialProviderPort, TrialMatrixExecutionReport, TrialExecutionRequest, TrialExecutionReceipt, TrialExecutionStageReceipt, ModelRoleUsage, ReplayLevel, AnalysisDefinition, AnalysisResult, PostHocEvaluationDefinition, PostHocEvaluationResult, Study, StudyModel, StudyParticipant, BenchmarkAssignmentMode, BenchmarkCutSpec, BenchmarkTaskSet, BenchmarkSourceKind, BenchmarkSourcePort, BenchmarkSourceResolution, BenchmarkSourceSpec, InMemoryBenchmarkSource, MeasurementContentReference, MeasurementCut, TaskArtifactSpec, TaskDefinition, TaskPackageSpec, TaskVerifierIsolation, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, diff_research_plans, compile_research_plan, ResearchPlanDiff, CompiledResearchPlan, compile_research_method, CompiledExperimentShardPlan, ExperimentBatchPlacement, ExperimentShard, compile_experiment_shard_plan, CompiledExperimentProgram, ExperimentBatch, ExperimentBatchKind, ExperimentProgramBinding, compile_experiment_program, experiment_report_from_data, CompiledResearchCampaign, CompiledResearchCampaignLane, ResearchCampaignCompilationUnit, compile_research_campaign, ResearchCampaignExecutionPort, ResearchCampaignExecutionReport, ResearchCampaignLaneResult, ResearchCampaignLaneState, ResearchCampaignPlan, ResearchCampaignStudy, ResearchCampaignStudyBinding, StudyIntervention, StudyFactorSpec, ResearchStudyDefinition, StudyExecutionPolicy, ResearchRevision, ParticipantSchedule, MeasurementValueKind, MeasurementValue, MeasurementRecord, MeasurementProtocol, MeasurementDefinition, FactorSelection, FactorLevelSpec, ProjectIdentityProjection, ProjectManifestProjection, ProjectRunDefinition, RunControlAction, RunControlPort, RunControlPreparedOperation, RunControlReceipt, RunControlRequest, RunControlTarget, RunEvidenceValidity, RunExecutionOutcome, RunOutcomeProjection, RunScientificValidity, RunTaskOutcome, ActionKind, ActionSpec, AgentGoal, AgentMethodSpec, AgentPhaseSpec, EmbodiedActionCommand, EmbodimentKind, EmbodimentSpec, EnvironmentSpec, ExecutionEnvironmentKind, GuardDecision, GuardVerdict, MethodProgram, MethodProgramBuilder, MethodWorkflow, SensorModality, SensorSpec, TableAggregateStep, TableDeriveStep, TableExpression, TableExpressionKind, TableFilterStep, TableJoinStep, TableProgram, TableProjectStep, TableStepKind, CapabilityDescriptor, CapabilityRequest, EnvironmentCapability, EnvironmentProviderPort, ExecutionContext, MethodIdentity, MethodRuntimeIdentity, AgentStudySpec, AggregationFunction, AggregationSpec, BaselineSpec, DataColumn, DataTable, EvaluationContext, EvaluationStage, FigureCell, FigureKind, FigureOutputFormat, FigurePoint, FigureSeries, FigureSpec, FigureStyle, MissingValuePolicy, MultipleComparisonMethod, SplitStrategy, StudyObservationTableAdapter, RunCheckpointManifest, StudyVariantSpec, VariantKind, StudyProtocol, StudyConcurrencyPolicy, VariantBinding, StudyAssignment, ExperimentPlan
- noetrium_platform.research.experimentation.api.campaign ?w^~)?t CompiledResearchCampaign, CompiledResearchCampaignLane, ResearchCampaignCompilationUnit, ResearchCampaignExecutionPort, ResearchCampaignExecutionReport, ResearchCampaignLaneResult, ResearchCampaignLaneState, ResearchCampaignPlan, ResearchCampaignStudy, ResearchCampaignStudyBinding, compile_research_campaign
- noetrium_platform.research.experimentation.api.catalog ?w^~)?t ExperimentationCatalogPort
- noetrium_platform.research.experimentation.api.construction ?w^~)?t ProjectIdentityProjection, ProjectManifestProjection, ProjectRunDefinition
- noetrium_platform.research.experimentation.api.method_host ?w^~)?t compile_research_method
- noetrium_platform.research.experimentation.api.program ?w^~)?t CompiledExperimentProgram, ExperimentBatch, ExperimentBatchKind, ExperimentProgramBinding, compile_experiment_program, experiment_report_from_data
- noetrium_platform.research.experimentation.api.research_compiler ?w^~)?t CompiledResearchPlan, ResearchPlanDiff, compile_research_plan, resolve_research_requirements, diff_research_plans
- noetrium_platform.research.experimentation.api.sharding ?w^~)?t CompiledExperimentShardPlan, ExperimentBatchPlacement, ExperimentShard, compile_experiment_shard_plan
- noetrium_platform.research.experimentation.lifecycle.api ?w^~)?t TaskVerifierArchiveMaterializationPort, MaterializedTaskVerifierArchive, encode_run_launch_manifest, decode_run_launch_manifest, RunLaunchManifestDecodeError, RUN_LAUNCH_MANIFEST_SCHEMA_VERSION, StudySpec, AgentStudySpec, AnalysisDefinition, AnalysisPlan, AnalysisResult, BenchmarkAssignmentMode, BenchmarkCutSpec, BenchmarkSourceKind, BenchmarkSourcePort, BenchmarkSourceResolution, BenchmarkSourceSpec, BenchmarkTaskSet, BoundStudyExecutionPort, BranchReceipt, CheckpointCapturePolicy, CheckpointTrigger, CheckpointTriggerKind, ComparabilityProof, CompositionPlanReference, ComputeDemand, DecisionCycleRuntimePort, DerivedEvidenceArtifact, DoctorFinding, EVIDENCE_BUNDLE_SCHEMA_VERSION, EvidenceBundleManifest, EvidenceBundlePublisherPort, EvidenceBundleReceipt, EvidenceBundleStatus, EvidenceStreamDescriptor, ExecutionMode, ExperimentComponentBindingPort, ExperimentDefinition, ExperimentLifecycleState, ExperimentModePort, ExperimentModelRoleSpec, ExperimentParticipantSpec, ExperimentParticipantTopology, ExperimentPlan, ExperimentRunExecutionPort, ExperimentRunReport, ExperimentRunResult, ExperimentRunSpec, ExperimentSpec, ExperimentTaskSpec, ExperimentTransition, ExperimentTrialCycleExecutorPort, ExperimentTrialProtocolIdentity, ExperimentTrialProtocolIdentityMismatch, ExperimentUnit, ExperimentUnitExecutorPort, ExperimentUnitKind, ExperimentUnitPlannerPort, ExperimentWorkloadFailure, FactorLevelSpec, FactorSelection, FailureScope, FailureScopeRank, FindingSeverity, InMemoryBenchmarkSource, MeasurementContentReference, MeasurementCut, MeasurementDefinition, MeasurementProtocol, MeasurementRecord, MeasurementValue, MeasurementValueKind, MetricAggregation, MetricDefinition, MetricMissingPolicy, MetricPredicate, MetricReport, MetricValue, ObservationEnvelope, ObservationKind, ObservationSinkPort, PairedEvaluationResult, ParticipantImplementationIdentity, ParticipantSchedule, ParticipantSessionRuntimeIdentity, PostHocEvaluationDefinition, PostHocEvaluationResult, RawRecord, RawRecordStorePort, ReplayLevel, ResearchRevision, ResearchStudyDefinition, ResourceAllocationLeasePort, ResourceAllocationReceipt, ResourcePolicy, RunArtifactFinalizationError, RunArtifactFinalizationPort, RunArtifactKind, RunArtifactSealedError, RunArtifactSnapshotReceipt, RunArtifactStorePort, RunArtifactVerificationError, RunArtifactVerificationPort, RunArtifactWriteActorPort, RunCheckpointBundle, RunCheckpointConflict, RunCheckpointCoordinatorPort, RunCheckpointIntegrityError, RunCheckpointManifest, RunCheckpointResult, RunCheckpointStore, RunCleanupFailure, RunCleanupReport, RunClosed, RunControlAction, RunControlActionFailure, RunControlCheckpointBundlePort, RunControlCheckpointStorePort, RunControlConflict, RunControlError, RunControlEvidencePort, RunControlIntegrityError, RunControlLifecyclePort, RunControlNotFound, RunControlPhase, RunControlPort, RunControlPreparedOperation, RunControlReceipt, RunControlReconciliationPort, RunControlRequest, RunControlStaleRevision, RunControlTarget, RunControlTransitionOutcome, RunCycleExecutionPort, RunCycleExecutorPort, RunDiagnosticsPort, RunEvidenceValidity, RunExecutionOutcome, RunIdentity, RunIdentityProvider, RunLaunchManifest, RunLifetimePort, RunOutcomeProjection, RunParticipantPayload, RunParticipantSnapshotRef, RunRecoveryRequired, RunResearchSemanticsReference, RunRestoreResult, RunRuntimePort, RunScientificValidity, RunSessionFactoryPort, RunSessionPort, RunTaskOutcome, Study, StudyArtifactPublicationPort, StudyAssignment, StudyAssignmentPort, StudyConcurrencyPolicy, StudyExecutionPlan, StudyExecutionPolicy, StudyExecutionUnit, StudyFactorSpec, StudyIntervention, StudyMatrixExecutionReport, StudyMetricAggregate, StudyMetricAggregationPort, StudyMetricObservation, StudyModel, StudyParticipant, StudyProtocol, StudyResearchReadPort, StudyResearchReadSnapshot, StudyVariantSpec, TaskArtifactSpec, TaskDefinition, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskPackageSpec, TaskSetSplit, TaskVerifierArtifact, TaskVerifierIsolation, TaskVerifierPort, TaskVerifierReceipt, TaskVerifierRequest, TrialBudget, TrialExecutionReceipt, TrialExecutionRequest, TrialExecutionStageReceipt, TrialMatrixExecutionReport, TrialMeasurementProjectionPort, TrialProviderPort, TrialTaskProjectionPort, UnitOutcome, UnitOutcomeState, VariantBinding, VariantExecutionProvider, VariantExecutionRequest, VariantKind, WorkloadCheckpointBindingPort, WorkloadCheckpointBundle, WorkloadCheckpointComponentPort, WorkloadCheckpointComponentRef, WorkloadCheckpointCoordinatorPort, WorkloadCheckpointManifest, WorkloadCheckpointPayload, WorkloadCheckpointPublicationPort, WorkloadCheckpointRestoreError, WorkloadCheckpointStore, WorkloadExecutionCut, WorkloadRestoreStateCertainty, attach_cleanup_note, build_comparability_proof, build_workload_checkpoint_manifest, failure_scope_rank, validate_task_graph
- noetrium_platform.research.experimentation.lifecycle.api.manifest_codec ?w^~)?t RUN_LAUNCH_MANIFEST_SCHEMA_VERSION, RunLaunchManifestDecodeError, decode_run_launch_manifest, encode_run_launch_manifest
- noetrium_platform.research.experimentation.lifecycle.checkpoint.api ?w^~)?t CheckpointCapturePolicy, CheckpointTrigger, CheckpointTriggerKind, RunCheckpointBundle, RunCheckpointConflict, RunCheckpointCoordinatorPort, RunCheckpointIntegrityError, RunCheckpointManifest, RunCheckpointResult, RunCheckpointStore, RunParticipantPayload, RunParticipantSnapshotRef, RunRestoreResult, WorkloadCheckpointBindingPort, WorkloadCheckpointBundle, WorkloadCheckpointRestoreError, WorkloadCheckpointComponentPort, WorkloadCheckpointComponentRef, WorkloadCheckpointManifest, WorkloadCheckpointPayload, WorkloadCheckpointStore, WorkloadExecutionCut, WorkloadRestoreStateCertainty, build_workload_checkpoint_manifest, WorkloadCheckpointCoordinatorPort, WorkloadCheckpointPublicationPort
- noetrium_platform.research.experimentation.lifecycle.checkpoint.api.contracts ?w^~)?t RunCheckpointBundle, RunCheckpointConflict, RunCheckpointIntegrityError, RunCheckpointManifest, RunCheckpointStore, RunParticipantPayload, RunParticipantSnapshotRef
- noetrium_platform.research.experimentation.lifecycle.checkpoint.api.policy ?w^~)?t CheckpointCapturePolicy, CheckpointTrigger, CheckpointTriggerKind
- noetrium_platform.research.experimentation.lifecycle.checkpoint.api.ports ?w^~)?t RunCheckpointCoordinatorPort
- noetrium_platform.research.experimentation.lifecycle.checkpoint.api.results ?w^~)?t RunCheckpointResult, RunRestoreResult
- noetrium_platform.research.experimentation.lifecycle.checkpoint.api.workload ?w^~)?t WorkloadCheckpointBindingPort, WorkloadCheckpointRestoreError, WorkloadCheckpointBundle, WorkloadCheckpointComponentPort, WorkloadCheckpointComponentRef, WorkloadCheckpointManifest, WorkloadCheckpointPayload, WorkloadCheckpointStore, WorkloadExecutionCut, WorkloadRestoreStateCertainty, build_workload_checkpoint_manifest
- noetrium_platform.research.experimentation.lifecycle.checkpoint.api.workload_ports ?w^~)?t WorkloadCheckpointCoordinatorPort, WorkloadCheckpointPublicationPort
- noetrium_platform.research.experimentation.lifecycle.evaluation.api ?w^~)?t BranchReceipt, ComparabilityProof, PairedEvaluationResult, build_comparability_proof
- noetrium_platform.research.experimentation.lifecycle.evaluation.api.contracts ?w^~)?t BranchReceipt, ComparabilityProof, PairedEvaluationResult, build_comparability_proof
- noetrium_platform.research.experimentation.lifecycle.experiment.api ?w^~)?t ExperimentComponentBindingPort, AnalysisPlan, DoctorFinding, ExperimentDefinition, ExperimentLifecycleState, ExperimentModePort, ExecutionMode, ExperimentModelRoleSpec, ExperimentParticipantSpec, ExperimentPlan, ExperimentRunReport, ExperimentTransition, ExperimentUnit, ExperimentUnitExecutorPort, ExperimentUnitKind, ExperimentUnitPlannerPort, RawRecordStorePort, RawRecord, MetricAggregation, MetricMissingPolicy, MetricPredicate, MetricDefinition, MetricValue, MetricReport, ExperimentParticipantTopology, ExperimentTrialCycleExecutorPort, ExperimentTaskSpec, ExperimentWorkloadFailure, ExperimentSpec, ExperimentTrialProtocolIdentity, ExperimentTrialProtocolIdentityMismatch, FailureScope, FailureScopeRank, failure_scope_rank, validate_task_graph
- noetrium_platform.research.experimentation.lifecycle.experiment.api.contracts ?w^~)?t ExperimentParticipantSpec, ExperimentModelRoleSpec, ExperimentSpec, AnalysisPlan, DoctorFinding, ExecutionMode, ExperimentDefinition, ExperimentLifecycleState, ExperimentModePort, ExperimentPlan, ExperimentRunReport, ExperimentTransition, ExperimentUnit, ExperimentUnitExecutorPort, ExperimentUnitKind, ExperimentUnitPlannerPort, FindingSeverity, ObservationEnvelope, ObservationKind, ObservationSinkPort, ExperimentDoctorPort, UnitOutcome, UnitOutcomeState, RawRecordStorePort, RawRecord, MetricAggregation, MetricMissingPolicy, MetricPredicate, MetricDefinition, MetricValue, MetricReport
- noetrium_platform.research.experimentation.lifecycle.experiment.api.failure ?w^~)?t ExperimentWorkloadFailure, FailureScope, FailureScopeRank, failure_scope_rank
- noetrium_platform.research.experimentation.lifecycle.experiment.api.ports ?w^~)?t ExperimentComponentBindingPort, ExperimentTrialCycleExecutorPort
- noetrium_platform.research.experimentation.lifecycle.experiment.api.tasks ?w^~)?t ExperimentTaskSpec, validate_task_graph
- noetrium_platform.research.experimentation.lifecycle.experiment.api.topology ?w^~)?t ExperimentParticipantTopology
- noetrium_platform.research.experimentation.lifecycle.experiment.api.trial_protocol ?w^~)?t ExperimentTrialProtocolIdentity, ExperimentTrialProtocolIdentityMismatch
- noetrium_platform.research.experimentation.lifecycle.experiment.resource.api ?w^~)?t ComputeDemand, ModelCapacityMode, ResourceAllocationReceipt, ResourcePolicy, ExperimentResourceBinderPort, ResourceAllocationLeasePort
- noetrium_platform.research.experimentation.lifecycle.experiment.resource.api.contracts ?w^~)?t ComputeDemand, ModelCapacityMode, ResourceAllocationReceipt, ResourcePolicy
- noetrium_platform.research.experimentation.lifecycle.experiment.resource.api.ports ?w^~)?t ExperimentResourceBinderPort, ResourceAllocationLeasePort
- noetrium_platform.research.experimentation.lifecycle.run.api ?w^~)?t RunIdentity, RunIdentityProvider, RunCleanupFailure, RunCleanupReport, RunClosed, RunRecoveryRequired, attach_cleanup_note, RunCycleExecutionPort, RunCycleExecutorPort, RunLifetimePort, CompositionPlanReference, RunLaunchManifest, RunResearchSemanticsReference, DerivedEvidenceArtifact, EVIDENCE_BUNDLE_SCHEMA_VERSION, EvidenceBundleManifest, EvidenceBundleReceipt, EvidenceBundleStatus, EvidenceStreamDescriptor, EvidenceBundlePublisherPort, RunControlAction, RunControlActionFailure, RunControlCheckpointBundlePort, RunControlCheckpointStorePort, RunControlConflict, RunControlError, RunControlEvidencePort, RunControlIntegrityError, RunControlLifecyclePort, RunControlNotFound, RunControlPhase, RunControlPort, RunControlPreparedOperation, RunControlReceipt, RunControlReconciliationPort, RunControlRequest, RunControlStaleRevision, RunControlTarget, RunControlTransitionOutcome, RunEvidenceValidity, RunExecutionOutcome, RunOutcomeProjection, RunScientificValidity, RunTaskOutcome, DecisionCycleRuntimePort, RunArtifactFinalizationError, RunArtifactFinalizationPort, RunArtifactKind, RunArtifactSnapshotReceipt, RunArtifactSealedError, RunArtifactStorePort, RunArtifactVerificationError, RunArtifactVerificationPort, RunArtifactWriteActorPort, RunRuntimePort, RunDiagnosticsPort, RunSessionPort, RunSessionFactoryPort, ExperimentRunSpec, ExperimentRunExecutionPort, ExperimentRunResult
- noetrium_platform.research.experimentation.lifecycle.run.api.artifacts ?w^~)?t RunArtifactFinalizationError, RunArtifactFinalizationPort, RunArtifactKind, RunArtifactSnapshotReceipt, RunArtifactSealedError, RunArtifactStorePort, RunArtifactVerificationError, RunArtifactVerificationPort, RunArtifactWriteActorPort
- noetrium_platform.research.experimentation.lifecycle.run.api.cleanup ?w^~)?t attach_cleanup_note
- noetrium_platform.research.experimentation.lifecycle.run.api.control ?w^~)?t RunIdentity, RunLaunchManifest, RunControlAction, RunControlPhase, RunControlTarget, RunControlRequest, RunControlPreparedOperation, RunExecutionOutcome, RunTaskOutcome, RunEvidenceValidity, RunScientificValidity, RunOutcomeProjection, RunControlReceipt, RunControlTransitionOutcome, RunControlError, RunControlNotFound, RunControlConflict, RunControlStaleRevision, RunControlIntegrityError, RunControlActionFailure, RunControlPort, RunControlCheckpointBundlePort, RunControlCheckpointStorePort, RunControlLifecyclePort, RunControlReconciliationPort, RunControlEvidencePort
- noetrium_platform.research.experimentation.lifecycle.run.api.diagnostics ?w^~)?t RunDiagnosticsPort
- noetrium_platform.research.experimentation.lifecycle.run.api.execution ?w^~)?t ExperimentRunExecutionPort, ExperimentRunResult
- noetrium_platform.research.experimentation.lifecycle.run.api.identity ?w^~)?t RunIdentity
- noetrium_platform.research.experimentation.lifecycle.run.api.identity_ports ?w^~)?t RunIdentityProvider
- noetrium_platform.research.experimentation.lifecycle.run.api.lifecycle ?w^~)?t RunCleanupFailure, RunCleanupReport, RunClosed, RunRecoveryRequired
- noetrium_platform.research.experimentation.lifecycle.run.api.lifecycle_ports ?w^~)?t RunCycleExecutionPort, RunCycleExecutorPort, RunLifetimePort, RunSessionPort, RunSessionFactoryPort
- noetrium_platform.research.experimentation.lifecycle.run.api.manifest ?w^~)?t CompositionPlanReference, RunLaunchManifest, RunResearchSemanticsReference
- noetrium_platform.research.experimentation.lifecycle.run.api.manifest_evidence ?w^~)?t DerivedEvidenceArtifact, EVIDENCE_BUNDLE_SCHEMA_VERSION, EvidenceBundleManifest, EvidenceBundleReceipt, EvidenceBundleStatus, EvidenceStreamDescriptor
- noetrium_platform.research.experimentation.lifecycle.run.api.manifest_ports ?w^~)?t EvidenceBundlePublisherPort
- noetrium_platform.research.experimentation.lifecycle.run.api.ports ?w^~)?t DecisionCycleRuntimePort, RunRuntimePort, RunSessionPort
- noetrium_platform.research.experimentation.lifecycle.run.api.spec ?w^~)?t ExperimentRunSpec
- noetrium_platform.research.experimentation.lifecycle.study.api ?w^~)?t AgentStudySpec, Study, BenchmarkAssignmentMode, StudyModel, StudyParticipant, PostHocEvaluationDefinition, PostHocEvaluationResult, TaskVerifierArtifact, TaskVerifierPort, TaskVerifierReceipt, TaskVerifierRequest, TrialProviderPort, TrialTaskProjectionPort, StudyResearchReadPort, StudyResearchReadSnapshot, TrialMatrixExecutionReport, TrialMeasurementProjectionPort, TrialExecutionRequest, TrialExecutionReceipt, TrialExecutionStageReceipt, ReplayLevel, AnalysisDefinition, AnalysisResult, MeasurementCut, BenchmarkCutSpec, BenchmarkTaskSet, BenchmarkSourceKind, BenchmarkSourcePort, BenchmarkSourceResolution, BenchmarkSourceSpec, InMemoryBenchmarkSource, TaskArtifactSpec, TaskDefinition, TaskPackageSpec, TaskVerifierIsolation, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, StudyIntervention, StudyFactorSpec, ResearchStudyDefinition, StudyExecutionPolicy, ResearchRevision, ParticipantSchedule, FactorSelection, FactorLevelSpec, StudyConcurrencyPolicy, MeasurementContentReference, MeasurementDefinition, MeasurementProtocol, MeasurementRecord, MeasurementValue, MeasurementValueKind, StudyAssignment, StudyExecutionUnit, StudyArtifactPublicationPort, StudyAssignmentPort, StudyMetricAggregate, StudyMatrixExecutionReport, StudyMetricAggregationPort, StudyMetricObservation, StudyProtocol, StudyVariantSpec, VariantKind, StudyExecutionPlan, VariantBinding, VariantExecutionProvider, VariantExecutionRequest, BoundStudyExecutionPort, MaterializedTaskVerifierArchive, TaskVerifierArchiveMaterializationPort
- noetrium_platform.research.experimentation.lifecycle.study.api.analysis ?w^~)?t AnalysisDefinition, AnalysisResult, DatasetVersionProjection, EvidenceManifestProjection, MeasurementCut
- noetrium_platform.research.experimentation.lifecycle.study.api.authoring ?w^~)?t AgentStudySpec, Study, StudyModel, StudyParticipant
- noetrium_platform.research.experimentation.lifecycle.study.api.benchmark ?w^~)?t BenchmarkCutSpec, BenchmarkTaskSet, TaskDefinition, TaskPackageSpec, TaskArtifactSpec, TaskVerifierIsolation, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, BenchmarkSourceKind, BenchmarkSourceSpec, BenchmarkSourceResolution, BenchmarkSourcePort, InMemoryBenchmarkSource
- noetrium_platform.research.experimentation.lifecycle.study.api.contracts ?w^~)?t StudyConcurrencyPolicy, StudyAssignment, StudyExecutionUnit, StudyMatrixExecutionReport, StudyMetricAggregate, StudyMetricObservation, StudyProtocol, StudyVariantSpec, VariantKind
- noetrium_platform.research.experimentation.lifecycle.study.api.design ?w^~)?t BenchmarkAssignmentMode, FactorLevelSpec, FactorSelection, ParticipantSchedule, ResearchRevision, ResearchStudyDefinition, StudyExecutionPolicy, StudyFactorSpec, StudyIntervention
- noetrium_platform.research.experimentation.lifecycle.study.api.evaluation ?w^~)?t PostHocEvaluationDefinition, PostHocEvaluationResult
- noetrium_platform.research.experimentation.lifecycle.study.api.materialization ?w^~)?t MaterializedTaskVerifierArchive, TaskVerifierArchiveMaterializationPort
- noetrium_platform.research.experimentation.lifecycle.study.api.measurement ?w^~)?t MeasurementContentReference, MeasurementDefinition, MeasurementProtocol, MeasurementRecord, MeasurementValue, MeasurementValueKind
- noetrium_platform.research.experimentation.lifecycle.study.api.plan ?w^~)?t StudyExecutionPlan, VariantBinding, VariantExecutionProvider, VariantExecutionRequest
- noetrium_platform.research.experimentation.lifecycle.study.api.ports ?w^~)?t BoundStudyExecutionPort, StudyArtifactPublicationPort, StudyAssignmentPort, StudyMetricAggregationPort
- noetrium_platform.research.experimentation.lifecycle.study.api.research_read ?w^~)?t StudyResearchReadPort, StudyResearchReadSnapshot
- noetrium_platform.research.experimentation.lifecycle.study.api.trial ?w^~)?t TaskVerifierArtifact, TaskVerifierPort, TaskVerifierReceipt, TaskVerifierRequest, TrialExecutionReceipt, TrialExecutionRequest, TrialExecutionStageReceipt, TrialMatrixExecutionReport, TrialMeasurementProjectionPort, TrialProviderPort, TrialTaskProjectionPort
- noetrium_platform.research.experimentation.workbench.api ?w^~)?t TableAggregateStep, TableDeriveStep, TableExecutionReceipt, TableExecutionResult, TableExpression, TableExpressionKind, TableFilterStep, TableJoinStep, TableProgram, TableProgramExecutionPort, TableProjectStep, TableStepKind, AggregationFunction, AggregationSpec, BaselineRegistryPort, BaselineSpec, CandidateProgramExecutionPort, CandidateProgramExecutionReceipt, CandidateProgramExecutionRequest, CandidateProgramExecutionStatus, CandidateProgramIdentity, CandidateProgramMeasurementProjection, CandidateProgramMeasurementProjectionPort, CandidateProgramSourcePublicationPort, candidate_program_capability_payload, DataColumn, DataTable, EvaluationContext, EvaluationStage, FigureCategory, FigureCell, FigureKind, FigureOutputFormat, FigurePoint, FigureRendererPort, FigureSeries, FigureSpec, FigureStyle, GroupComparison, InferenceResult, MetricSummary, MissingValuePolicy, MultipleComparisonMethod, MultipleComparisonResult, PairedComparison, RenderedResearchPackage, ResearchEvaluation, ResearchFigureFactoryPort, ResearchLifecyclePort, ResearchReport, ResearchStatisticsPort, ResearchTablePipelinePort, ReportTableRendererPort, SplitStrategy, TableAnalysisPort, TableReaderPort, TableTransformPort, MeasurementRecordTableAdapter, StudyObservationTableAdapter
- noetrium_platform.research.experimentation.workbench.api.adapters ?w^~)?t MeasurementRecordTableAdapter, StudyObservationTableAdapter
- noetrium_platform.research.experimentation.workbench.api.candidate_program ?w^~)?t CandidateProgramExecutionPort, CandidateProgramExecutionReceipt, CandidateProgramExecutionRequest, CandidateProgramExecutionStatus, CandidateProgramIdentity, CandidateProgramMeasurementProjection, CandidateProgramMeasurementProjectionPort, CandidateProgramSourcePublicationPort, candidate_program_capability_payload
- noetrium_platform.research.experimentation.workbench.api.contracts ?w^~)?t AggregationFunction, AggregationSpec, BaselineRegistryPort, BaselineSpec, DataColumn, DataTable, EvaluationContext, EvaluationStage, FigureCategory, FigureCell, FigureKind, FigureOutputFormat, FigurePoint, FigureRendererPort, FigureSeries, FigureSpec, FigureStyle, GroupComparison, InferenceResult, MetricSummary, MissingValuePolicy, MultipleComparisonMethod, MultipleComparisonResult, PairedComparison, RenderedResearchPackage, ResearchEvaluation, ResearchFigureFactoryPort, ResearchLifecyclePort, ResearchReport, ResearchStatisticsPort, ResearchTablePipelinePort, ReportTableRendererPort, SplitStrategy, TableAnalysisPort, TableReaderPort, TableTransformPort
- noetrium_platform.research.experimentation.workbench.api.table_program ?w^~)?t TableAggregateStep, TableDeriveStep, TableExecutionReceipt, TableExecutionResult, TableExpression, TableExpressionKind, TableFilterStep, TableJoinStep, TableProgram, TableProgramExecutionPort, TableProgramStep, TableProjectStep, TableStepKind
- noetrium_platform.research.experimentation.workload.api ?w^~)?t StaticExperimentTaskProjection, WorkloadCompletionReceipt, WorkloadEvaluation, WorkloadMethodCompilerPort, WorkloadMethodInvocation, WorkloadMethodReceipt, WorkloadMethodResultAdapterPort, WorkloadTaskExecutionPort, WorkloadTaskResult, WorkloadTaskRunError
- noetrium_platform.research.experimentation.workload.api.contracts ?w^~)?t WorkloadCompletionReceipt, StaticExperimentTaskProjection, WorkloadEvaluation, WorkloadMethodInvocation, WorkloadMethodReceipt, WorkloadTaskResult, WorkloadTaskRunError
- noetrium_platform.research.experimentation.workload.api.ports ?w^~)?t WorkloadMethodCompilerPort, WorkloadMethodResultAdapterPort, WorkloadTaskExecutionPort

### governance

- Package: noetrium_platform.foundation.governance
- Authority: none
- Canonical authority: none
- Node kind: facet
- Owns: architecture, quality, release and system topology rules
- Must not own: domain execution
- Requires: governance/system_registry, platform, scope
- Provides: architecture.audit, governance.evolution, quality.audit
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance

#### API modules

- noetrium_platform.foundation.governance.analysis.algorithm.api.contracts ?w^~)?t AlgorithmBaselineApproval, AlgorithmComplexityMigrationApproval, AlgorithmDiff, AlgorithmGovernanceApprovalSet, AlgorithmFinding, AlgorithmGateReport, AlgorithmLanguage, AlgorithmMetrics, AlgorithmPriority, AlgorithmSnapshot, AlgorithmSymbol, FileAnalysis, LanguageCoverage, SourceDocument, SymbolDelta
- noetrium_platform.foundation.governance.analysis.algorithm.api.ports ?w^~)?t AlgorithmSnapshotStorePort, FileAnalysisCachePort, LanguageAnalyzerPort, SourceInventoryPort
- noetrium_platform.foundation.governance.analysis.api ?w^~)?t algorithm, concurrency, performance
- noetrium_platform.foundation.governance.analysis.concurrency.api.contracts ?w^~)?t ConcurrencyLanguage, ConcurrencyPriority, ConcurrencyFinding, ConcurrencyMetrics, ConcurrencyHotspot, ConcurrencyCoverage, ConcurrencySnapshot, ConcurrencyDocument, ConcurrencyFileAnalysis, ConcurrencyBaseline, ConcurrencyGateReport
- noetrium_platform.foundation.governance.analysis.concurrency.api.ports ?w^~)?t ConcurrencyBaseline, ConcurrencyDocument, ConcurrencyFileAnalysis, ConcurrencyLanguage, ConcurrencySnapshot, ConcurrencySourceInventoryPort, ConcurrencyLanguageAnalyzerPort, ConcurrencySnapshotStorePort
- noetrium_platform.foundation.governance.analysis.performance.api.contracts ?w^~)?t PerformanceLanguage, PerformancePriority, PerformanceFinding, PerformanceMetrics, PerformanceHotspot, PerformanceCoverage, PerformanceSnapshot, PerformanceBaseline, PerformanceGateReport, PerformanceDocument, PerformanceFileAnalysis
- noetrium_platform.foundation.governance.analysis.performance.api.ports ?w^~)?t PerformanceBaseline, PerformanceDocument, PerformanceFileAnalysis, PerformanceLanguage, PerformanceSnapshot, PerformanceSourceInventoryPort, PerformanceLanguageAnalyzerPort, PerformanceSnapshotStorePort
- noetrium_platform.foundation.governance.api ?w^~)?t PLATFORM_SCOPE, PathFlavor, ScopeIdentity, ScopeKind, ScopePathPort, ScopeRegistryPort, is_absolute_target_path, scope_from_data, scope_to_data, BindingDiagnostic, BindingDiagnosticCode, BindingDiagnosticReference, BindingDiagnosticReferenceKind, BindingDiagnosticSeverity, BindingPlan, BindingProof, BindingRemediationCategory, BindingResolution, CapabilityCompositionPlannerPort, CapabilityOffer, CapabilityRequirement, CompositionContract, CompositionIdentity, CompositionSubject, EXCEPTION_DESCRIPTOR_V1, ExecutionQualificationPort, GovernanceBaselineApproval, GovernanceBaselineApprovalSet, GovernanceBaselineLane, HOST_OPERATING_SYSTEM_ROUTE_V1, LOGGING_SYSTEM_V1, LOG_QUERY_V1, LOG_SINK_V1, METHOD_COMPOSITION_PORTS_V1, QualificationEvidence, QualificationKind, ReleasePinStorePort, RepositorySourceBlob, RepositorySourceFailure, RepositorySourceFailureKind, RepositorySourceIncompleteError, RepositorySourceIndexPort, RepositorySourcePort, RepositorySourceSnapshot, RequirementAddress, SERVER_CONNECTION_FACTORY_V1, SERVER_FILE_TRANSFER_FACTORY_V1, SystemDescriptor, SystemIdentity, SystemRegistryChange, SystemRegistryPort, governance_baseline_semantic_digest, interface_contract_digest, repository_source_scope_digest, repository_source_scope_text_digest, require_production_qualification, system_catalog, ComponentDescriptor, component_catalog
- noetrium_platform.foundation.governance.api.baseline_authority ?w^~)?t GovernanceBaselineApproval, GovernanceBaselineApprovalSet, GovernanceBaselineLane, governance_baseline_semantic_digest
- noetrium_platform.foundation.governance.api.repository_source ?w^~)?t RepositorySourceBlob, RepositorySourceFailure, RepositorySourceFailureKind, RepositorySourceIncompleteError, RepositorySourceIndexPort, RepositorySourcePort, RepositorySourceSnapshot, repository_source_scope_digest, repository_source_scope_text_digest
- noetrium_platform.foundation.governance.architecture.api ?w^~)?t AmbiguousCapabilityProvider, BindingDiagnostic, BindingDiagnosticCode, BindingDiagnosticReference, BindingDiagnosticReferenceKind, BindingDiagnosticSeverity, BindingEdge, BindingPlan, BindingProof, BindingRemediationCategory, BindingResolution, BindingResolutionState, BindingResolverPort, CapabilityBindingError, CapabilityCompositionPlannerPort, CapabilityDependencyCycle, CapabilityInterfaceMismatch, CapabilityKey, CapabilityOffer, CapabilityRequirement, CompositionContract, CompositionContractError, CompositionIdentity, CompositionSubject, CompositionSubjectKind, CompositionTopologyError, MissingCapabilityProvider, ProviderSelection, ProviderIngressContractError, ProviderIngressProtocol, ProviderIngressViolation, ProviderImplementationIdentity, ProviderIngressBoundary, ProviderQualificationIdentity, ProviderRevision, ProviderRevisionKind, provider_implementation_from_repository_source, RequirementAddress, RequirementCardinality, interface_contract_digest, ConsensusQualificationPort, ExecutionQualificationPort, IsolationQualificationPort, QualificationEvidence, QualificationKind, WorkerAttestationQualificationPort, require_production_qualification, SemanticBoundaryClaim, SemanticBoundaryClaimError, SemanticBoundaryClassification, SemanticBoundaryEvidence, SemanticStateAuthorityKind, validate_semantic_boundary_claim, EXCEPTION_DESCRIPTOR_V1, HOST_OPERATING_SYSTEM_ROUTE_V1, LOGGING_SYSTEM_V1, LOG_QUERY_V1, LOG_SINK_V1, METHOD_COMPOSITION_PORTS_V1, SERVER_CONNECTION_FACTORY_V1, SERVER_FILE_TRANSFER_FACTORY_V1
- noetrium_platform.foundation.governance.architecture.api.capabilities ?w^~)?t EXCEPTION_DESCRIPTOR_V1, HOST_OPERATING_SYSTEM_ROUTE_V1, LOG_QUERY_V1, LOG_SINK_V1, LOGGING_SYSTEM_V1, METHOD_COMPOSITION_PORTS_V1, SERVER_CONNECTION_FACTORY_V1, SERVER_FILE_TRANSFER_FACTORY_V1
- noetrium_platform.foundation.governance.architecture.api.capability_composition ?w^~)?t AmbiguousCapabilityProvider, BindingDiagnostic, BindingDiagnosticCode, BindingDiagnosticReference, BindingDiagnosticReferenceKind, BindingDiagnosticSeverity, BindingEdge, BindingPlan, BindingProof, BindingRemediationCategory, BindingResolution, BindingResolutionState, BindingResolverPort, CapabilityBindingError, CapabilityCompositionPlannerPort, CapabilityDependencyCycle, CapabilityInterfaceMismatch, CapabilityKey, CapabilityOffer, CapabilityRequirement, CompositionContract, CompositionContractError, CompositionIdentity, CompositionSubject, CompositionSubjectKind, CompositionTopologyError, MissingCapabilityProvider, ProviderSelection, RequirementAddress, RequirementCardinality, interface_contract_digest
- noetrium_platform.foundation.governance.architecture.api.execution_qualification ?w^~)?t ConsensusQualificationPort, ExecutionQualificationPort, IsolationQualificationPort, QualificationEvidence, QualificationKind, WorkerAttestationQualificationPort, require_production_qualification
- noetrium_platform.foundation.governance.architecture.api.provider_ingress ?w^~)?t ProviderImplementationIdentity, ProviderIngressBoundary, ProviderIngressContractError, ProviderIngressProtocol, ProviderIngressViolation, ProviderQualificationIdentity, ProviderRevision, ProviderRevisionKind, provider_implementation_from_repository_source
- noetrium_platform.foundation.governance.architecture.api.semantic_boundary ?w^~)?t SemanticBoundaryClaim, SemanticBoundaryClaimError, SemanticBoundaryClassification, SemanticBoundaryEvidence, SemanticStateAuthorityKind, validate_semantic_boundary_claim
- noetrium_platform.foundation.governance.architecture.gating.api ?w^~)?t GateCompositionPort, GateFinding, GatePort, GateReport, GateRequest, GateSeverity
- noetrium_platform.foundation.governance.architecture.gating.api.contracts ?w^~)?t GateFinding, GateReport, GateRequest, GateSeverity
- noetrium_platform.foundation.governance.architecture.gating.api.ports ?w^~)?t GateCompositionPort, GatePort
- noetrium_platform.foundation.governance.architecture.gating.quality.api ?w^~)?t BANNED_RUNTIME_IDENTIFIERS, DegradationFinding, FORBIDDEN_ENABLED_CONFIG_KEYS, FORBIDDEN_NONEMPTY_CONFIG_KEYS, SilentFailureFinding
- noetrium_platform.foundation.governance.architecture.gating.quality.api.contracts ?w^~)?t BANNED_RUNTIME_IDENTIFIERS, DegradationFinding, FORBIDDEN_ENABLED_CONFIG_KEYS, FORBIDDEN_NONEMPTY_CONFIG_KEYS, SilentFailureFinding
- noetrium_platform.foundation.governance.architecture.repository_boundary.api ?w^~)?t DownstreamImportKind, DownstreamImportObservation, DownstreamProjectImportReport, RepositoryBoundaryReport, RepositoryBoundaryViolation, RepositoryBoundaryAuditor
- noetrium_platform.foundation.governance.architecture.repository_boundary.api.contracts ?w^~)?t DownstreamImportKind, DownstreamImportObservation, DownstreamProjectImportReport, RepositoryBoundaryReport, RepositoryBoundaryViolation, RepositoryBoundaryAuditor
- noetrium_platform.foundation.governance.evolution.api ?w^~)?t DiscoveryReport, DriftKind, EvolutionAssessment, EvolutionProposal, EvolutionStage, EvolutionStateStorePort, EvolutionTransition, ImprovementSignal, ObservationOutcome, SignalKind, SystemEvolutionPort, TopologyDrift, TopologyObservation
- noetrium_platform.foundation.governance.evolution.api.contracts ?w^~)?t DiscoveryReport, DriftKind, EvolutionAssessment, EvolutionProposal, EvolutionStage, EvolutionTransition, ImprovementSignal, ObservationOutcome, SignalKind, TopologyDrift, TopologyObservation
- noetrium_platform.foundation.governance.evolution.api.ports ?w^~)?t EvolutionStateStorePort, SystemEvolutionPort

### governance/release

- Package: noetrium_platform.foundation.governance.release
- Authority: release_authority
- Canonical authority: governance/release
- Node kind: authority
- Owns: release identities, manifests, verification and promotion semantics
- Must not own: runtime process state
- Requires: none
- Provides: release.freeze
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__release

#### API modules

- noetrium_platform.foundation.governance.release.api ?w^~)?t ActiveReleasePin, ActiveReleasePinned, FileDigest, ReleaseConsumerQuiescence, ReleaseConsumerQuiescenceProbe, ReleaseManifest, ReleaseQualityEvidence, ReleaseRegressionEvidence, ReleasePinStorePort, ReleaseQualityEvidencePort, ReleaseRegressionPort, ReleaseQuiescenceProof, ReleaseVerificationEvidence, ReleaseVerificationIntegrityError, ReleaseVerificationReport, ReleaseVerifierPort, ReleaseVerificationEvidencePort, ReleaseQuiescenceProofProvider
- noetrium_platform.foundation.governance.release.api.contracts ?w^~)?t ActiveReleasePin, ActiveReleasePinned, FileDigest, ReleaseConsumerQuiescence, ReleaseManifest, ReleaseQuiescenceProof, ReleaseRegressionEvidence, ReleaseVerificationEvidence, ReleaseVerificationReport, ReleaseVerificationIntegrityError
- noetrium_platform.foundation.governance.release.api.ports ?w^~)?t ReleaseConsumerQuiescenceProbe, ReleasePinStorePort, ReleaseQualityEvidencePort, ReleaseRegressionPort, ReleaseQuiescenceProofProvider, ReleaseVerificationEvidencePort, ReleaseVerifierPort

### governance/system_registry

- Package: noetrium_platform.foundation.governance.system_registry
- Authority: system_topology
- Canonical authority: governance/system_registry
- Node kind: authority
- Owns: recursive system topology and ownership declarations
- Must not own: runtime orchestration
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__system_registry

#### API modules

- noetrium_platform.foundation.governance.system_registry.api ?w^~)?t AuthorityDescriptor, ComponentDescriptor, DownstreamSurfaceMode, SYSTEM_CATALOG, SystemDescriptor, SystemIdentity, SystemLayer, SystemNodeKind, SystemRegistryChange, SystemRegistryObserver, SystemRegistryPort, TopologySourceAudit, audit_system_topology_source, component_catalog, system_catalog, LayerDescriptor, LayerHierarchy, SideplaneDescriptor, layer_hierarchy
- noetrium_platform.foundation.governance.system_registry.api.contracts ?w^~)?t AuthorityDescriptor, DownstreamSurfaceMode, SYSTEM_PLANES, SystemDescriptor, SystemIdentity, SystemNodeKind, SystemRegistryChange, SystemLayer
- noetrium_platform.foundation.governance.system_registry.api.hierarchy ?w^~)?t LAYER_HIERARCHY_SCHEMA, LayerDescriptor, LayerHierarchy, SideplaneDescriptor, layer_hierarchy
- noetrium_platform.foundation.governance.system_registry.api.ports ?w^~)?t SystemRegistryObserver, SystemRegistryPort
- noetrium_platform.foundation.governance.system_registry.api.topology ?w^~)?t ComponentDescriptor, SYSTEM_CATALOG, TopologySourceAudit, audit_system_topology_source, component_catalog, system_catalog

### model

- Package: noetrium_platform.capabilities.model
- Authority: model_identity
- Canonical authority: model
- Node kind: authority
- Owns: model assets, stacks, assignments, deployments and serving identity
- Must not own: process lifecycle implementation and experiment semantics
- Requires: artifact, environment, platform, resource, runtime, scope
- Provides: model.asset, model.asset-acquisition, model.assignment, model.deployment, model.deployment-control, model.qualification, model.request, model.serving
- Downstream surface: public
- Facade: noetrium.contracts.systems.model

#### API modules

- noetrium_platform.capabilities.model.api ?w^~)?t ModelRequestContextExceeded, ModelRequestTokenBudget, ModelRequestTokenizationIdentity, ModelRequestTokenizationPort, ModelRequestTokenizationProviderPort, EmbeddingInput, MultimodalMethodSpec, MultimodalRequest, MultimodalRequestCodecPort, MultimodalResponse, EmbeddingOutput, EmbeddingVector, ModelCapabilityInput, ModelCapabilityInvocation, ModelCapabilityOutput, ModelCapabilityResponse, NamedScalar, ProjectModelStreamingCapabilityProviderPort, ProjectModelStreamingCapabilityClientPort, ModelCapabilityStreamTerminal, ModelCapabilityStreamSession, ModelCapabilityStreamDisposition, ModelCapabilityStreamChunk, PolicyActionProbability, PolicyInferenceInput, PolicyInferenceOutput, RankedCandidate, RankingCandidate, RankingInput, RankingOutput, ProjectModelCapabilityClientPort, ProjectModelCapabilityProviderPort, ScoredCandidate, ScoringCandidate, ScoringInput, ScoringOutput, StructuredGenerationOutput, StructuredGenerationInput, StructuredGenerationDecoderPort, ValueInferenceInput, ValueInferenceOutput, ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateProposal, ModelUpdateSource, PreparedModelRevision, ModelAuthorities, ModelBindingSelectionReceipt, ModelBindingDiagnostic, ModelBindingDiagnosticCode, ModelBindingDiagnosticSeverity, ModelCapabilityRequirement, ModelProjectBindingError, ModelProjectDefinition, MultimodalInferenceOutput, MultimodalInferenceInput, MultimodalContent, ModelRequirementContribution, ModelProviderProfile, ProjectModelBinding, ProjectModelBindingSet, ProjectModelClientPort, ProjectModelProviderPort, ProjectModelRequest, ProjectModelResponse, ModelRequestRecorderPort, ModelEndpointDispatchPoolPort, ModelEndpointPort, ModelEndpointRequest, QualifiedModelEndpointBinding
- noetrium_platform.capabilities.model.api.authorities ?w^~)?t ModelAuthorities
- noetrium_platform.capabilities.model.api.capability ?w^~)?t EmbeddingInput, EmbeddingOutput, EmbeddingVector, ModelCapabilityInput, ModelCapabilityInvocation, ModelCapabilityOutput, ModelCapabilityResponse, NamedScalar, ProjectModelStreamingCapabilityProviderPort, ProjectModelStreamingCapabilityClientPort, ModelCapabilityStreamTerminal, ModelCapabilityStreamSession, ModelCapabilityStreamDisposition, ModelCapabilityStreamChunk, PolicyActionProbability, PolicyInferenceInput, PolicyInferenceOutput, RankedCandidate, RankingCandidate, RankingInput, RankingOutput, ProjectModelCapabilityClientPort, ProjectModelCapabilityProviderPort, ScoredCandidate, ScoringCandidate, ScoringInput, ScoringOutput, StructuredGenerationOutput, StructuredGenerationDecoderPort, ValueInferenceInput, ValueInferenceOutput
- noetrium_platform.capabilities.model.api.multimodal ?w^~)?t MultimodalMethodSpec, MultimodalPart, MultimodalRequest, MultimodalRequestCodecPort, MultimodalResponse
- noetrium_platform.capabilities.model.api.project ?w^~)?t ModelBindingSelectionReceipt, ModelBindingDiagnostic, ModelBindingDiagnosticCode, ModelBindingDiagnosticSeverity, ModelCapabilityRequirement, ModelProjectBindingError, ModelProjectDefinition, MultimodalInferenceOutput, MultimodalInferenceInput, MultimodalContent, ModelRequirementContribution, ModelProviderProfile, ProjectModelBinding, ProjectModelBindingSet, ProjectModelClientPort, ProjectModelProviderPort, ProjectModelRequest, ProjectModelResponse, StructuredGenerationInput
- noetrium_platform.capabilities.model.api.tokenization ?w^~)?t ModelRequestContextExceeded, ModelRequestTokenBudget, ModelRequestTokenizationIdentity, ModelRequestTokenizationPort, ModelRequestTokenizationProviderPort
- noetrium_platform.capabilities.model.asset.api.contracts ?w^~)?t ManagedModelAsset, ModelAcquisitionReceipt, ModelAssetMode, ModelAssetOrigin, ModelAssetStats, ModelAssetUsage, ModelConfigSummary, ModelSourceSpec, ModelStoragePoolStatus
- noetrium_platform.capabilities.model.asset.api.ports ?w^~)?t ModelAssetLookupPort, ModelAssetManagementPort, ModelAssetStoragePort, ModelAssetUsagePort, ModelSourceBackend
- noetrium_platform.capabilities.model.assignment.api.contracts ?w^~)?t ModelAssignment, ResolvedModelAssignment
- noetrium_platform.capabilities.model.assignment.api.ports ?w^~)?t ModelAssignmentPort
- noetrium_platform.capabilities.model.catalog.api ?w^~)?t ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateProposal, ModelUpdateSource, PreparedModelRevision
- noetrium_platform.capabilities.model.catalog.revision.api ?w^~)?t ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateProposal, PreparedModelRevision, ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateSource
- noetrium_platform.capabilities.model.catalog.revision.api.contracts ?w^~)?t ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateProposal, PreparedModelRevision
- noetrium_platform.capabilities.model.catalog.revision.api.update ?w^~)?t ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateSource
- noetrium_platform.capabilities.model.deployment.api.contracts ?w^~)?t ModelControlSnapshot, ModelControllerPhase, ModelControllerState, ModelDeploymentLogs, ModelDeploymentSelector, ModelDeploymentSpec, ModelDeploymentStatus, ModelDesiredState, ModelEnvironmentUsage, ModelGpuAllocation, ModelGpuConflict, ModelGpuProcessBinding, ModelLogTail, ModelReconcileCycle, ModelRuntimeState
- noetrium_platform.capabilities.model.deployment.api.ports ?w^~)?t ModelControllerStatePort, ModelControllerStopPort, ModelDeploymentCatalogPort, ModelDeploymentLogPort, ModelDeploymentRuntimePort, ModelFleetRuntimePort, ModelReconcileControllerPort, ModelResourceViewPort, ModelServiceRuntimeFactoryPort
- noetrium_platform.capabilities.model.qualification.api.qualification ?w^~)?t BackendCandidatePlan, CandidateDecision, DeploymentQualificationApplicationPort, DeploymentQualificationApplicationReceipt, DeploymentQualificationApplicationRequest, DeploymentQualificationApplicationStorePort, DeploymentQualificationRuntimePort, DeploymentQualificationRuntimeReceipt, DeploymentQualificationRuntimeRequest, DeploymentQualificationRuntimeStorePort, CudaFacts, DEFAULT_DEPLOYMENT_PROBE_TIMEOUT_SECONDS, DEFAULT_PACKAGE_INDEX_URL, native_cuda_runtime_package_names, DeploymentCapabilityFacts, DeploymentCapabilityProbePort, DeploymentQualificationPlan, DeploymentQualificationEvidenceRecord, DeploymentQualificationEvidenceStorePort, DeploymentQualificationPort, DeploymentQualificationRequest, GpuCapabilityFacts, GpuFabricFacts, HostExecutionFacts, InstallPackage, ModelArtifactFacts, OperatingSystemFacts, PackageArtifactFacts, PackageDependencyNodeFacts, PackageIndexFacts, PythonRuntimeFacts, StorageCapabilityFacts, QualificationCommandReceipt, QualificationMaterializationStatus, QualificationPackageInstallerPort, DeploymentRuntimeQualificationStatus, QualificationRuntimeProbePort, RuntimeCheckReceipt
- noetrium_platform.capabilities.model.request.api ?w^~)?t ExecutionContext, ImmutableModelIdentity, ModelRequestEnvelope, ModelRequestLedgerPort, ModelRequestRecorderPort, ReconstructedModelRequest, PromptSelectionPort
- noetrium_platform.capabilities.model.request.api.contracts ?w^~)?t ModelRequestEnvelope, ModelRequestLedgerPort, ModelRequestRecorderPort, ReconstructedModelRequest
- noetrium_platform.capabilities.model.request.prompt.api ?w^~)?t ActivePromptEvidenceReadPort, ActivePromptVerificationEvidence, PromptVerificationIntegrityError, PromptTraceDescriptor, PromptTraceObserverFailure, PromptTraceObserverFailureSink, PromptTraceObserverPort, PromptTracePoint, PromptTraceStage, PromptTraceSummary, PromptBoundRequest, PromptBodyContext, PromptDynamicBlock, PromptRequestBindingPort, PromptRequestBodyBuilder, PromptSelectionIdentity, PromptSelectionPort
- noetrium_platform.capabilities.model.request.prompt.api.request ?w^~)?t PromptBoundRequest, PromptBodyContext, PromptDynamicBlock, PromptRequestBindingPort, PromptRequestBodyBuilder
- noetrium_platform.capabilities.model.request.prompt.api.selection ?w^~)?t PromptSelectionIdentity, PromptSelectionPort
- noetrium_platform.capabilities.model.request.prompt.api.trace ?w^~)?t PromptTraceDescriptor, PromptTraceObserverFailure, PromptTraceObserverFailureSink, PromptTraceObserverPort, PromptTracePoint, PromptTraceStage, PromptTraceSummary
- noetrium_platform.capabilities.model.request.prompt.api.verification ?w^~)?t ActivePromptEvidenceReadPort, ActivePromptVerificationEvidence, PromptVerificationIntegrityError
- noetrium_platform.capabilities.model.serving.api ?w^~)?t CPUInventory, CPUNode, DeploymentPlacement, GpuPlacementPolicyPort, DurableRecoveryAttempt, DurableRecoveryObserverFailureSink, DurableRecoveryObserverPort, DurableRecoveryPhase, DurableRecoveryStorePort, FrozenDeploymentIdentity, FrozenDeploymentSet, FrozenRoleAssignment, GPUFabricLink, GPUInventory, HostInventory, HostInventoryEvidenceStorePort, HostInventoryProvider, HostInventoryReceipt, HostLimits, HostResourceDelta, MemoryInventory, ModelAdmissionClosed, ModelAdmissionLeasePort, ModelAdmissionPort, ModelAdmissionRegistryPort, ModelAdmissionTimeout, ModelPhase, ModelRunState, ModelSupervisorStateStorePort, MountInventory, PerformanceSample, QualificationCertificate, QualificationDecision, QualificationEvidence, QualificationPolicy, ResourceQualificationMeasurements, QualifiedDeploymentManifest, RecoveryObserverFailure, RecoveryPlan, RecoveryResumeDecision, RecoveryStep, ResourceEnvelope, RoleCanaryResult, RoleModelAssignment, RoleModelManifest, RuntimeCanaryContract, RuntimeCanaryEvidence, RuntimeCanaryEvidenceStorePort, RuntimeCanaryProbe, RuntimeInventory, RuntimeQualificationEvidenceStorePort, RuntimeQualificationPublication, RuntimeQualificationPublisherPort, RuntimeQualificationReceipt, ServiceHeartbeat, begin_recovery_step, build_host_inventory_receipt, build_runtime_qualification_receipt, compare_host_inventory_receipts, complete_recovery_step, decide_resume, evaluate_qualification, evaluate_runtime_canary_contract, fail_recovery_step, new_recovery_attempt, recovery_plan_digest, succeed_recovery, AsyncJsonHttpTransportPort, ModelEndpointFactoryPort, AdaptiveModelEndpointPoolPort, ModelEndpointDispatchPoolPort, ModelEndpointPort, ModelEndpointRequest, QualifiedModelClosurePublication, QualifiedModelClosurePublicationReceipt, QualifiedModelEndpointBinding, QualifiedModelEndpointBindingPort, QualifiedModelEndpointReplicaSet, ModelEndpointResponse, ModelEndpointRoute
- noetrium_platform.capabilities.model.serving.api.admission ?w^~)?t ModelAdmissionClosed, ModelAdmissionLeasePort, ModelAdmissionPort, ModelAdmissionRegistryPort, ModelAdmissionTimeout
- noetrium_platform.capabilities.model.serving.api.deployment ?w^~)?t FrozenDeploymentIdentity, FrozenDeploymentSet, FrozenRoleAssignment, RuntimeQualificationPublication, RuntimeQualificationPublisherPort
- noetrium_platform.capabilities.model.serving.api.host_verification ?w^~)?t HostInventoryReceipt, HostResourceDelta, build_host_inventory_receipt, compare_host_inventory_receipts
- noetrium_platform.capabilities.model.serving.api.host_verification_ports ?w^~)?t HostInventoryEvidenceStorePort, HostInventoryProvider
- noetrium_platform.capabilities.model.serving.api.inventory ?w^~)?t CPUNode, CPUInventory, GPUInventory, GPUFabricLink, MemoryInventory, MountInventory, RuntimeInventory, HostLimits, HostInventory
- noetrium_platform.capabilities.model.serving.api.placement ?w^~)?t DeploymentPlacement, GpuPlacementPolicyPort
- noetrium_platform.capabilities.model.serving.api.qualification ?w^~)?t RoleCanaryResult, PerformanceSample, ResourceQualificationMeasurements, QualificationEvidence, QualificationPolicy, QualificationDecision, evaluate_qualification
- noetrium_platform.capabilities.model.serving.api.qualified_deployment ?w^~)?t DeploymentPlacement, ModelStackSpec, ResourceEnvelope, QualificationCertificate, RoleModelAssignment, RoleModelManifest, QualifiedDeploymentManifest
- noetrium_platform.capabilities.model.serving.api.recovery ?w^~)?t RecoveryPlan, RecoveryStep
- noetrium_platform.capabilities.model.serving.api.recovery_observer ?w^~)?t DurableRecoveryObserverFailureSink, DurableRecoveryObserverPort, RecoveryObserverFailure
- noetrium_platform.capabilities.model.serving.api.recovery_ports ?w^~)?t DurableRecoveryStorePort
- noetrium_platform.capabilities.model.serving.api.recovery_state ?w^~)?t DurableRecoveryAttempt, DurableRecoveryPhase, RecoveryResumeDecision, begin_recovery_step, complete_recovery_step, decide_resume, fail_recovery_step, new_recovery_attempt, recovery_plan_digest, succeed_recovery
- noetrium_platform.capabilities.model.serving.api.runtime_canary ?w^~)?t RuntimeCanaryContract, RuntimeCanaryEvidence, RuntimeCanaryProbe, evaluate_runtime_canary_contract
- noetrium_platform.capabilities.model.serving.api.runtime_canary_ports ?w^~)?t RuntimeCanaryEvidenceStorePort
- noetrium_platform.capabilities.model.serving.api.runtime_qualification ?w^~)?t RuntimeQualificationReceipt, build_runtime_qualification_receipt
- noetrium_platform.capabilities.model.serving.api.runtime_qualification_ports ?w^~)?t RuntimeQualificationEvidenceStorePort
- noetrium_platform.capabilities.model.serving.api.state ?w^~)?t ImmutableModelIdentity, ModelPhase, ModelRunState
- noetrium_platform.capabilities.model.serving.api.supervisor_ports ?w^~)?t ModelSupervisorStateStorePort
- noetrium_platform.capabilities.model.serving.endpoint.api ?w^~)?t AsyncJsonHttpTransportPort, JsonHttpResponse, ModelEndpointError, ModelEndpointObserverPort, ModelEndpointFactoryPort, ModelEndpointPort, ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute, QualifiedModelClosurePublication, AdaptiveModelEndpointPoolPort, ModelEndpointDispatchPoolPort, ModelEndpointDispatchResult, ModelEndpointPoolSnapshot, ModelEndpointReplicaSelectionCandidate, ModelEndpointReplicaSelectionPolicyPort, ModelEndpointReplicaSnapshot, OperationalModelEndpointReplica, OperationalModelEndpointReplicaSet, OperationalModelServingInventory, QualifiedModelEndpointReplicaBindingPort, QualifiedModelEndpointReplicaSet, QualifiedModelClosurePublicationReceipt, QualifiedModelEndpointBinding, QualifiedModelEndpointBindingPort
- noetrium_platform.capabilities.model.serving.endpoint.api.contracts ?w^~)?t JsonHttpResponse, ModelEndpointError, ModelEndpointObserverPort, ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute
- noetrium_platform.capabilities.model.serving.endpoint.api.operational_inventory ?w^~)?t OperationalModelServingInventory
- noetrium_platform.capabilities.model.serving.endpoint.api.ports ?w^~)?t AsyncJsonHttpTransportPort, ModelEndpointFactoryPort, ModelEndpointPort
- noetrium_platform.capabilities.model.serving.endpoint.api.publication ?w^~)?t QualifiedModelClosurePublication, QualifiedModelClosurePublicationReceipt
- noetrium_platform.capabilities.model.serving.endpoint.api.qualification ?w^~)?t QualifiedModelEndpointBinding, QualifiedModelEndpointBindingPort
- noetrium_platform.capabilities.model.serving.endpoint.api.replica ?w^~)?t AdaptiveModelEndpointPoolPort, ModelEndpointDispatchPoolPort, ModelEndpointDispatchResult, ModelEndpointPoolSnapshot, ModelEndpointReplicaSelectionCandidate, ModelEndpointReplicaSelectionPolicyPort, ModelEndpointReplicaSnapshot, OperationalModelEndpointReplica, OperationalModelEndpointReplicaSet, QualifiedModelEndpointReplicaBindingPort, QualifiedModelEndpointReplicaSet
- noetrium_platform.capabilities.model.stack.api ?w^~)?t ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
- noetrium_platform.capabilities.model.stack.api.stack ?w^~)?t ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity

### observability

- Package: noetrium_platform.evidence.observability
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: logs, telemetry, traces, status and observation projections
- Must not own: durable state/failure authority
- Requires: governance, platform
- Provides: logging.observation, logging.routing, status.read-model, telemetry.metrics
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability

### observability/logging/storage

- Package: noetrium_platform.evidence.observability.logging.storage
- Authority: none
- Canonical authority: none
- Node kind: provider
- Owns: durable or volatile log storage backends
- Must not own: log schema policy
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__storage

### operator

- Package: noetrium_platform.product.operator
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: human-facing query, command, maintenance and incident surfaces
- Must not own: domain authority and business state
- Requires: environment, execution, experimentation, governance, model, observability, platform, portfolio, reliability, resource, runtime, scope
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator

### participant

- Package: noetrium_platform.capabilities.participant
- Authority: participant_state
- Canonical authority: participant
- Node kind: authority
- Owns: participant definitions, bindings, sessions, capabilities, agent specializations and participant-facing contracts
- Must not own: server/process supervision and scientific truth
- Requires: artifact, data, governance, platform, reliability
- Provides: agent.contract, capability.contract, method.contract, method.runtime, participant.definition, participant.runtime.abi, participant.session
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant

#### API modules

- noetrium_platform.capabilities.participant.agent.api ?w^~)?t project_action_history, AgentActionHistoryProjectionReceipt, AgentActionHistoryProjection, AGENT_ACTION_HISTORY_VIEW_SCHEMA, AgentIdentity, AgentSession, AgentSnapshot, AgentTurnRequest, AgentTurnResult, AgentImplementation, AgentActionExecutorPort, AgentActionSequence, AgentActionStep, AgentActionSummary, AgentCognitionError, AgentCompletionDecision, AgentCompletionDisposition, AgentCompletionPort, AgentDiagnosticsPort, AgentEvidencePort, AgentGoal, AgentLoopCheckpoint, AgentLoopResult, AgentLoopTerminationReason, AgentMemoryContext, AgentModeDecision, AgentModeDisposition, AgentMemoryPort, AgentObservation, AgentObservationPort, AgentPlannerPort, AgentPlanningRequest, AgentProgressPort, AgentReactiveModePort, AgentReceiptCheckpoint, AgentSafetyDecision, AgentSafetyDisposition, AgentSafetySupervisorPort, AgentSkillCatalogPort, AgentSkillDescription, AgentSkillRecord, AgentSkillSelection, AgentStepReceipt, action_summary_payload
- noetrium_platform.capabilities.participant.agent.api.cognition ?w^~)?t AgentActionSequence, AgentActionStep, AgentActionSummary, AgentCognitionError, AgentGoal, AgentLoopCheckpoint, AgentLoopResult, AgentLoopTerminationReason, AgentMemoryContext, AgentModeDecision, AgentModeDisposition, AgentObservation, AgentPlanningRequest, AgentReceiptCheckpoint, AgentSafetyDecision, AgentSafetyDisposition, AgentSkillDescription, AgentSkillRecord, AgentSkillSelection, AgentStepReceipt, action_summary_payload
- noetrium_platform.capabilities.participant.agent.api.cognition_ports ?w^~)?t AgentActionExecutorPort, AgentCompletionPort, AgentDiagnosticsPort, AgentEvidencePort, AgentMemoryPort, AgentObservationPort, AgentPlannerPort, AgentProgressPort, AgentReactiveModePort, AgentSafetySupervisorPort, AgentSkillCatalogPort
- noetrium_platform.capabilities.participant.agent.api.completion ?w^~)?t AgentCompletionDecision, AgentCompletionDisposition
- noetrium_platform.capabilities.participant.agent.api.contracts ?w^~)?t CapabilityPort, ExecutionContext, AgentIdentity, AgentSnapshot, AgentTurnRequest, AgentTurnResult, AgentSession, AgentImplementation
- noetrium_platform.capabilities.participant.agent.api.model_view ?w^~)?t AGENT_ACTION_HISTORY_VIEW_SCHEMA, AgentActionHistoryProjection, AgentActionHistoryProjectionReceipt, project_action_history
- noetrium_platform.capabilities.participant.api ?w^~)?t PARTICIPANT_MESSAGE_ROUTE_SCHEMA, ParticipantMessageFactBinding, ParticipantMessageKind, ParticipantMessageRecipientReceipt, ParticipantMessageRouteReceipt, ParticipantMessageRouteRequest, ParticipantMessageRouterPort, participant_message_content_digest, AgentProjectDefinition, MethodProjectDefinition, method_program_identity_for_requirement, method_program_identity_for_runtime_binding, require_method_program_runtime_binding, ArchitectureChangeKind, ParticipantArchitectureChange, ParticipantArchitectureComponent, ParticipantArchitectureRevision, ParticipantArchitectureTransition, ParticipantBindingDiagnostic, ParticipantBindingDiagnosticCode, ParticipantBindingDiagnosticSeverity, ParticipantMessageSchedule, ParticipantMessageScheduleEntry, ParticipantProjectBindingError, ParticipantProviderProfile, ParticipantRequirement, ParticipantRequirementContribution, ParticipantRevisionAuthorityPort, ParticipantRevisionAuthoritySnapshot, ParticipantRevisionCommit, ParticipantRevisionConflictError, ParticipantRevisionEvidence, ParticipantRevisionEvidenceKind, ParticipantRevisionIntegrityError, ParticipantRevisionProposal, ParticipantRevisionStateError, ParticipantRevisionValue, ParticipantStateCompatibility, ParticipantStateRevision, ParticipantStateTransition, ParticipantTransitionValue, PreparedParticipantRevision, ParticipantTopology, ParticipantTopologyChange, ParticipantTopologyMember, ParticipantTopologyTransition, ProjectParticipantBinding, ProjectParticipantProviderPort, TopologyChangeKind, MethodRuntimeIdentity, AGENT_ACTION_HISTORY_VIEW_SCHEMA, AgentActionHistoryProjectionReceipt, AgentGoal, AgentMemoryContext, AgentMemoryPort, AgentObservation, AgentSkillDescription, AgentStepReceipt, BoundParticipant, BoundParticipants, CapabilityDescriptor, CapabilityEffectReconciliationResult, CapabilityPolicySet, CapabilityPort, CapabilityRequest, CapabilityResult, GuardVerdict, MethodIdentity, MethodProgramIdentity, ParticipantCheckpoint, ParticipantCheckpointRuntimePort, ParticipantLifecycleAdapterRegistry, ParticipantRuntimeBinding, ParticipantRuntimeHandle, ParticipantSessionBinding, capability_effect_request_id, capability_request_digest, participant_operation_type, participant_operation_verb, project_action_history, ParticipantSessionRuntimeIdentity, AgentTurnResult, AgentSession, AgentIdentity, ParticipantCheckpointOperationsPort, ParticipantCheckpointRef, ParticipantImplementationIdentity, ParticipantResolutionPort, ParticipantSessionLifecyclePort, GuardDecision
- noetrium_platform.capabilities.participant.api.messaging ?w^~)?t PARTICIPANT_MESSAGE_ROUTE_SCHEMA, ParticipantMessageFactBinding, ParticipantMessageKind, ParticipantMessageRecipientReceipt, ParticipantMessageRouteReceipt, ParticipantMessageRouteRequest, ParticipantMessageRouterPort, participant_message_content_digest
- noetrium_platform.capabilities.participant.api.project ?w^~)?t AgentProjectDefinition, MethodProjectDefinition, method_program_identity_for_requirement, method_program_identity_for_runtime_binding, require_method_program_runtime_binding, ParticipantBindingDiagnostic, ParticipantBindingDiagnosticCode, ParticipantBindingDiagnosticSeverity, ParticipantProjectBindingError, ParticipantProviderProfile, ParticipantRequirementContribution, ParticipantRequirement, ProjectParticipantBinding, ProjectParticipantProviderPort
- noetrium_platform.capabilities.participant.api.revision ?w^~)?t ParticipantRevisionAuthorityPort, ParticipantRevisionAuthoritySnapshot, ParticipantRevisionCommit, ParticipantRevisionConflictError, ParticipantRevisionEvidence, ParticipantRevisionEvidenceKind, ParticipantRevisionIntegrityError, ParticipantRevisionProposal, ParticipantRevisionStateError, ParticipantRevisionValue, ParticipantStateCompatibility, ParticipantStateRevision, ParticipantStateTransition, ParticipantTransitionValue, PreparedParticipantRevision
- noetrium_platform.capabilities.participant.api.topology ?w^~)?t ArchitectureChangeKind, ParticipantArchitectureChange, ParticipantArchitectureComponent, ParticipantArchitectureRevision, ParticipantArchitectureTransition, ParticipantMessageSchedule, ParticipantMessageScheduleEntry, ParticipantTopology, ParticipantTopologyChange, ParticipantTopologyMember, ParticipantTopologyTransition, TopologyChangeKind
- noetrium_platform.capabilities.participant.binding.api ?w^~)?t ParticipantBindingResolverPort, ParticipantConfigurationResolverPort, ParticipantImplementationRegistration, ParticipantImplementationResolverPort, ParticipantRuntimeEndpointFactory, ParticipantSessionRuntimeRegistration, ParticipantSessionRuntimeResolverPort
- noetrium_platform.capabilities.participant.binding.api.contracts ?w^~)?t ParticipantBindingResolverPort, ParticipantConfigurationResolverPort, ParticipantImplementationResolverPort, ParticipantImplementationRegistration, ParticipantRuntimeEndpointFactory, ParticipantSessionRuntimeResolverPort, ParticipantSessionRuntimeRegistration
- noetrium_platform.capabilities.participant.capability.api ?w^~)?t CapabilityApprovalDenied, CapabilityApprovalPort, CapabilityCarrierTransportPort, CapabilityDescriptor, CapabilityEffectReconciliationResult, CapabilityExportSession, CapabilityGuardPort, CapabilityInputCarrier, CapabilityOutputCarrier, CapabilityPolicyDenied, CapabilityPolicySet, CapabilityPort, CapabilityPostPolicyPort, CapabilityPostPolicyViolation, CapabilityProviderImplementation, CapabilityProviderIdentity, CapabilityProviderSession, CapabilityRequest, CapabilityResult, CapabilitySelectionReference, CapabilitySelectionView, DurablePreparedCapabilitySession, GuardDecision, GuardVerdict, TypedCapabilityCarrierCodec, TypedCarrierReference, capability_effect_request_id, capability_request_digest, decode_typed_capability_input, decode_typed_capability_result, make_typed_capability_request, make_typed_capability_result, materialize_capability_selection_view, require_pure_typed_descriptor
- noetrium_platform.capabilities.participant.capability.api.contracts ?w^~)?t EffectReconciliationDisposition, PreparedEffectHandle, EffectClass, EffectReceipt, ExecutionContext, CapabilityProviderIdentity, CapabilityDescriptor, CapabilityRequest, capability_effect_request_id, capability_request_digest, CapabilityResult, CapabilityEffectReconciliationResult, DurablePreparedCapabilitySession, CapabilityPort, CapabilityExportSession, CapabilityProviderSession, CapabilityProviderImplementation
- noetrium_platform.capabilities.participant.capability.api.policy ?w^~)?t CapabilityApprovalDenied, CapabilityApprovalPort, CapabilityGuardPort, CapabilityPolicyDenied, CapabilityPolicySet, CapabilityPostPolicyPort, CapabilityPostPolicyViolation, GuardDecision, GuardVerdict
- noetrium_platform.capabilities.participant.capability.api.selection ?w^~)?t CapabilitySelectionReference, CapabilitySelectionView, materialize_capability_selection_view
- noetrium_platform.capabilities.participant.capability.api.typed ?w^~)?t CapabilityCarrierTransportPort, CapabilityInputCarrier, CapabilityOutputCarrier, TypedCapabilityCarrierCodec, TypedCarrierReference, decode_typed_capability_input, decode_typed_capability_result, make_typed_capability_request, make_typed_capability_result, require_pure_typed_descriptor
- noetrium_platform.capabilities.participant.core.api ?w^~)?t BoundParticipant, BoundParticipants, PARTICIPANT_OPERATION_VERBS, ParticipantCheckpoint, ParticipantCheckpointIdentityMismatch, ParticipantCheckpointOperationsPort, ParticipantCheckpointRef, ParticipantCheckpointRuntimePort, ParticipantConfigurationArtifact, ParticipantIdentityMismatch, ParticipantImplementationIdentity, ParticipantImplementationInventory, ParticipantLifecycleAdapter, ParticipantLifecycleAdapterRegistry, ParticipantOperationContractError, ParticipantResolutionPort, ParticipantResolverPort, ParticipantRuntimeBinding, ParticipantRuntimeBindingManifest, ParticipantRuntimeEndpoint, ParticipantRuntimeHandle, ParticipantRuntimeInventory, ParticipantSessionBinding, ParticipantSessionLifecyclePort, ParticipantSessionRuntime, ParticipantSessionRuntimeIdentity, participant_operation_type, participant_operation_verb, validate_participant_kind
- noetrium_platform.capabilities.participant.core.api.bound ?w^~)?t BoundParticipant, BoundParticipants, ParticipantSessionBinding
- noetrium_platform.capabilities.participant.core.api.checkpoint ?w^~)?t ParticipantCheckpoint, ParticipantCheckpointIdentityMismatch, ParticipantCheckpointRef
- noetrium_platform.capabilities.participant.core.api.contracts ?w^~)?t ParticipantConfigurationArtifact, ParticipantImplementationIdentity, ParticipantRuntimeBinding, ParticipantSessionRuntimeIdentity
- noetrium_platform.capabilities.participant.core.api.frozen_manifests ?w^~)?t ParticipantImplementationInventory, ParticipantRuntimeBindingManifest, ParticipantRuntimeInventory
- noetrium_platform.capabilities.participant.core.api.lifecycle ?w^~)?t ParticipantIdentityMismatch, ParticipantLifecycleAdapter, ParticipantLifecycleAdapterRegistry
- noetrium_platform.capabilities.participant.core.api.runtime ?w^~)?t ParticipantResolverPort, ParticipantRuntimeEndpoint, ParticipantRuntimeHandle, ParticipantSessionRuntime
- noetrium_platform.capabilities.participant.core.api.runtime_operations ?w^~)?t PARTICIPANT_OPERATION_VERBS, ParticipantOperationContractError, participant_operation_type, participant_operation_verb, validate_participant_kind
- noetrium_platform.capabilities.participant.core.api.runtime_ports ?w^~)?t ParticipantCheckpointOperationsPort, ParticipantCheckpointRuntimePort, ParticipantResolutionPort, ParticipantSessionLifecyclePort
- noetrium_platform.capabilities.participant.definition.api ?w^~)?t ParticipantConfigurationArtifact, ParticipantImplementationCatalogPort, ParticipantImplementationFactory, ParticipantImplementationIdentity, RegisteredParticipantImplementation
- noetrium_platform.capabilities.participant.definition.api.contracts ?w^~)?t ParticipantImplementationFactory, RegisteredParticipantImplementation
- noetrium_platform.capabilities.participant.definition.api.ports ?w^~)?t ParticipantImplementationCatalogPort
- noetrium_platform.capabilities.participant.method.api ?w^~)?t IdempotentTaskCompletionSession, MethodIdentity, MethodCompositionPorts, MethodEndpointFactoryPort, MethodEndpointPort, MethodImplementation, MethodObservation, MethodProgramIdentity, MethodProgramIdentityMismatch, MethodObservationDeliveryError, MethodObservationOutboxFactoryPort, MethodObservationOutboxPort, MethodObservationSink, MethodRuntimeBinding, MethodRuntimeIdentity, MethodServices, MethodSession, MethodSessionRuntime, MethodSystemBinding, MethodSnapshot, MethodTaskCompletionReceipt, MethodTaskOutcome, RecallRequest, RecallResult, TaskCompletionReconciliationSession, TaskCompletionSafetyCapabilityMissing
- noetrium_platform.capabilities.participant.method.api.binding ?w^~)?t MethodSystemBinding
- noetrium_platform.capabilities.participant.method.api.contracts ?w^~)?t ExecutionContext, MethodIdentity, MethodProgramIdentity, MethodProgramIdentityMismatch, MethodSnapshot, RecallRequest, RecallResult, MethodTaskOutcome, MethodTaskCompletionReceipt, IdempotentTaskCompletionSession, TaskCompletionReconciliationSession, MethodSession
- noetrium_platform.capabilities.participant.method.api.errors ?w^~)?t TaskCompletionSafetyCapabilityMissing
- noetrium_platform.capabilities.participant.method.api.observability ?w^~)?t ExecutionContext, MethodObservation, MethodObservationDeliveryError, MethodObservationSink, MethodObservationOutboxPort, MethodObservationOutboxFactoryPort, MethodServices
- noetrium_platform.capabilities.participant.method.api.ports ?w^~)?t MethodCompositionPorts, MethodEndpointFactoryPort, MethodEndpointPort, MethodImplementation, MethodRuntimeBinding, MethodRuntimeIdentity, MethodSessionRuntime
- noetrium_platform.capabilities.participant.session.api ?w^~)?t ParticipantCheckpointRuntimePort, ParticipantRuntimeEndpoint, ParticipantSessionLifecyclePort, ParticipantSessionRuntime, ParticipantSessionRuntimeCatalogPort, ParticipantSessionRuntimeFactory, ParticipantSessionRuntimeIdentity, RegisteredParticipantSessionRuntime
- noetrium_platform.capabilities.participant.session.api.contracts ?w^~)?t ParticipantSessionRuntimeFactory, RegisteredParticipantSessionRuntime
- noetrium_platform.capabilities.participant.session.api.ports ?w^~)?t ParticipantSessionRuntimeCatalogPort

### platform

- Package: noetrium_platform.foundation.kernel
- Authority: platform_identity
- Canonical authority: platform
- Node kind: authority
- Owns: platform lifecycle, global identity, composition boundaries
- Must not own: domain business state and child internals
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.platform

#### API modules

- noetrium_platform.foundation.kernel.api ?w^~)?t PlatformIdentity, PlatformManifest, PlatformSystemCatalogPort
- noetrium_platform.foundation.kernel.api.contracts ?w^~)?t PlatformIdentity, PlatformManifest
- noetrium_platform.foundation.kernel.api.ports ?w^~)?t PlatformSystemCatalogPort
- noetrium_platform.foundation.kernel.concurrency.api ?w^~)?t SerialMailboxPolicy, SerialMailboxRejected, CancellationTokenPort, ConcurrencyBudget, ConcurrencyTopologySnapshot, Deadline, ExecutionLaneKind, ExecutionPermitRejected, ExecutionSpec, ExecutorPort, ExecutionPermitLeasePort, ExecutionPermitPort, HeartbeatSchedulerPort, HeartbeatSpec, HeartbeatTopologySnapshot, ScheduledTaskHandlePort, ScheduledTaskSpec, SerialActorPort, SerialLaneTopologySnapshot, StructuredConcurrencyRuntimePort, TaskCancelled, TaskContextPort, TaskDeadlineExceeded, TaskFailurePolicy, TaskFailureScope, TaskGroupPort, TaskGroupTopologySnapshot, TaskHandlePort, TaskState, TaskTopologySnapshot
- noetrium_platform.foundation.kernel.concurrency.api.contracts ?w^~)?t ExecutionLaneKind, SerialMailboxPolicy, TaskFailurePolicy, TaskFailureScope, TaskState, TaskCancelled, TaskDeadlineExceeded, ExecutionPermitRejected, SerialMailboxRejected, ConcurrencyBudget, Deadline, ExecutionSpec, HeartbeatSpec, ScheduledTaskSpec, TaskTopologySnapshot, TaskGroupTopologySnapshot, SerialLaneTopologySnapshot, HeartbeatTopologySnapshot, ConcurrencyTopologySnapshot
- noetrium_platform.foundation.kernel.concurrency.api.ports ?w^~)?t ConcurrencyTopologySnapshot, Deadline, ExecutionLaneKind, ExecutionSpec, HeartbeatSpec, HeartbeatTopologySnapshot, ScheduledTaskSpec, TaskFailurePolicy, TaskGroupTopologySnapshot, TaskState, SerialLaneTopologySnapshot, CancellationTokenPort, ExecutionPermitLeasePort, ExecutionPermitPort, TaskContextPort, TaskHandlePort, ScheduledTaskHandlePort, ExecutorPort, SerialActorPort, TaskGroupPort, HeartbeatSchedulerPort, StructuredConcurrencyRuntimePort, ExecutionAuthorityProviderPort, ExecutorProviderPort, CpuWorkerPoolProviderPort, SerialExecutionLaneProviderPort, SerialExecutionLaneFactoryProviderPort, TimerSchedulerProviderPort

### portfolio

- Package: noetrium_platform.foundation.portfolio
- Authority: portfolio_metadata
- Canonical authority: portfolio
- Node kind: authority
- Owns: workspace/program/project metadata and portfolio organization
- Must not own: study/run execution state
- Requires: platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.portfolio

#### API modules

- noetrium_platform.foundation.portfolio.api ?w^~)?t PROJECT_MANIFEST_SCHEMA, PortfolioCatalogPort, ProgramSpec, ProjectCapabilityRequirement, ProjectConfigurationReference, ProjectIdentity, ProjectManifest, ProjectManifestDecodeError, ProjectManifestFacet, ProjectManifestFacetChange, ProjectManifestFacetDiff, ProjectManifestIdentityFacets, ProjectProviderBinding, ProjectMethodRequirement, ProjectRequirementCardinality, ProjectSpec, ProjectToolProvenance, WorkspaceSpec, decode_project_manifest_bytes, decode_project_manifest_document, diff_project_manifest_facets, encode_project_manifest, project_manifest_document, project_manifest_identity_facets
- noetrium_platform.foundation.portfolio.api.contracts ?w^~)?t PROJECT_MANIFEST_SCHEMA, ProgramSpec, ProjectCapabilityRequirement, ProjectConfigurationReference, ProjectIdentity, ProjectManifest, ProjectManifestDecodeError, ProjectManifestFacet, ProjectManifestFacetChange, ProjectManifestFacetDiff, ProjectManifestIdentityFacets, ProjectProviderBinding, ProjectMethodRequirement, ProjectRequirementCardinality, ProjectSpec, ProjectToolProvenance, WorkspaceSpec, decode_project_manifest_bytes, decode_project_manifest_document, diff_project_manifest_facets, encode_project_manifest, project_manifest_document, project_manifest_identity_facets
- noetrium_platform.foundation.portfolio.api.ports ?w^~)?t PortfolioCatalogPort
- noetrium_platform.foundation.portfolio.project.api.contracts ?w^~)?t PROJECT_MANIFEST_SCHEMA, ProjectCapabilityRequirement, ProjectConfigurationReference, ProjectIdentity, ProjectManifest, ProjectManifestDecodeError, ProjectManifestFacet, ProjectManifestFacetChange, ProjectManifestFacetDiff, ProjectManifestIdentityFacets, ProjectProviderBinding, ProjectMethodRequirement, ProjectRequirementCardinality, ProjectSpec, ProjectToolProvenance, decode_project_manifest_bytes, decode_project_manifest_document, diff_project_manifest_facets, encode_project_manifest, project_manifest_document, project_manifest_identity_facets

### reliability

- Package: noetrium_platform.infrastructure.reliability
- Authority: none
- Canonical authority: none
- Node kind: facet
- Owns: effects, failures, incidents, forensics, diagnosis, reconciliation and recovery
- Must not own: scientific truth and UI projections
- Requires: data, governance, observability, platform, resource, scope
- Provides: diagnostics.causal, forensics.ledger, recovery.execution, recovery.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability

#### API modules

- noetrium_platform.infrastructure.reliability.api ?w^~)?t DEFAULT_FAILURE_CATALOG, DiagnosticEvidencePort, EffectCompletionEvidence, EffectIntent, EffectIntentJournal, EffectIntentPrepareResult, EffectIntentRecord, EffectReconciliationDisposition, EffectReconciliationProof, FailureCatalog, FailureEnvelope, FailureLedgerPort, PendingEffectRecoveryRequired, PreparedEffectHandle
- noetrium_platform.infrastructure.reliability.diagnostics.api ?w^~)?t DiagnosticEvidencePort, DiagnosticIndexSessionPort, DiagnosticObjectRecord, IncidentPattern, IncidentProjectionPort, IncidentProjectionSync, MetricQueryPort, OperationInvocationRecord, StateWriterRecord
- noetrium_platform.infrastructure.reliability.diagnostics.api.incidents ?w^~)?t IncidentPattern, IncidentProjectionPort, IncidentProjectionSync
- noetrium_platform.infrastructure.reliability.diagnostics.api.ports ?w^~)?t DiagnosticEvidencePort, DiagnosticIndexSessionPort, MetricQueryPort, MetricQueryRow
- noetrium_platform.infrastructure.reliability.diagnostics.api.records ?w^~)?t DiagnosticObjectRecord, OperationInvocationRecord, StateWriterRecord, freeze_diagnostic_mapping
- noetrium_platform.infrastructure.reliability.forensics.api ?w^~)?t CRASH_BUNDLE_SCHEMA_VERSION, CrashBundleManifest, CrashBundleVerification, ForensicCriticalWriteLanePort, ForensicEventWriteLanePort, ForensicIndexPort, ForensicIndexReadSessionPort, ForensicLedgerPort, ForensicRuntimeParts, ForensicStorePort, ForensicWriterLeasePort, MutationRecord, VerifiedLedgerCut, VerifiedLedgerSlice
- noetrium_platform.infrastructure.reliability.forensics.api.crash_bundle_contracts ?w^~)?t CrashBundleManifest, CrashBundleVerification
- noetrium_platform.infrastructure.reliability.forensics.api.ledger ?w^~)?t VerifiedLedgerCut, VerifiedLedgerSlice
- noetrium_platform.infrastructure.reliability.forensics.api.mutation ?w^~)?t ExecutionContext, MutationRecord
- noetrium_platform.infrastructure.reliability.forensics.api.ports ?w^~)?t ForensicCriticalWriteLanePort, ForensicEventWriteLanePort, ForensicIndexPort, ForensicIndexReadSessionPort, ForensicLedgerPort, ForensicStorePort, ForensicWriterLeasePort, ForensicWriteActorPort
- noetrium_platform.infrastructure.reliability.forensics.api.runtime_parts ?w^~)?t ForensicRuntimeParts
- noetrium_platform.infrastructure.reliability.recovery.api ?w^~)?t RecoveryActionCode, RecoveryAutomation, RecoveryDecisionReport, RecoveryRecommendation, RecoveryLease, RecoveryLeaseBusy, RecoveryExecutionFactoryPort, RecoveryExecutionPort, RecoveryLeaseReadPort, RecoveryLeaseStatePort, RecoveryLeaseStatusPort
- noetrium_platform.infrastructure.reliability.recovery.api.contracts ?w^~)?t RecoveryActionCode, RecoveryAutomation, RecoveryDecisionReport, RecoveryRecommendation
- noetrium_platform.infrastructure.reliability.recovery.api.lease ?w^~)?t RecoveryLease, RecoveryLeaseBusy
- noetrium_platform.infrastructure.reliability.recovery.api.ports ?w^~)?t RecoveryExecutionFactoryPort, RecoveryExecutionPort, RecoveryLeaseReadPort, RecoveryLeaseStatePort, RecoveryLeaseStatusPort

### reliability/effect

- Package: noetrium_platform.infrastructure.reliability.effect
- Authority: effect_authority
- Canonical authority: reliability/effect
- Node kind: authority
- Owns: external effect intent, outcome certainty and reconciliation state
- Must not own: process/server ownership
- Requires: none
- Provides: effect.journal, effect.safety
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability__effect

#### API modules

- noetrium_platform.infrastructure.reliability.effect.api ?w^~)?t EffectAlreadyConsumed, EffectCompletionEvidence, EffectIntent, EffectIntentConflict, EffectIntentJournal, EffectJournalIntegrityError, EffectIntentPhase, EffectIntentPrepareResult, EffectIntentRecord, EffectRecoveryAnchorMissing, EffectRecoveryRequired, EffectReconciliationDisposition, EffectReconciliationProof, PendingEffectRecoveryRequired, PreparedEffectHandle, consumption_digest, effect_digest, require_effect_receipt_request_digest, consumed_transition, effect_transition, is_authoritatively_resolved, not_applied_transition, prepare_transition, require_consumable_effect, require_not_applied_compatible
- noetrium_platform.infrastructure.reliability.effect.api.contracts ?w^~)?t EffectReconciliationDisposition, EffectReconciliationProof, PreparedEffectHandle, require_effect_receipt_request_digest
- noetrium_platform.infrastructure.reliability.effect.api.journal ?w^~)?t EffectCompletionEvidence, EffectIntent, EffectIntentConflict, EffectIntentJournal, EffectJournalIntegrityError, EffectRecoveryRequired, EffectAlreadyConsumed, PendingEffectRecoveryRequired, EffectRecoveryAnchorMissing, EffectIntentPhase, EffectIntentPrepareResult, EffectIntentRecord, consumption_digest, effect_digest
- noetrium_platform.infrastructure.reliability.effect.api.transitions ?w^~)?t consumed_transition, effect_transition, is_authoritatively_resolved, not_applied_transition, prepare_transition, require_consumable_effect, require_not_applied_compatible

### reliability/failure

- Package: noetrium_platform.infrastructure.reliability.failure
- Authority: failure_authority
- Canonical authority: reliability/failure
- Node kind: authority
- Owns: failure taxonomy, envelopes, fingerprints and semantic versions
- Must not own: diagnostic UI and operator policy
- Requires: none
- Provides: failure.truth
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability__failure

#### API modules

- noetrium_platform.infrastructure.reliability.failure.api ?w^~)?t ClassifiedOperationFailure, DEFAULT_FAILURE_CATALOG, FailureCatalog, FailureEnvelope, FailureCorrelationSource, FailureSpec, OperationFailureReferenceProjection, OperationFailureReferenceProjector, PartialOperationFailureClassifier, RecoveryAction, RiskLevel, build_failure, exception_correlation_refs, build_failure_from_spec, failure_from_dict, FailureLedgerPort, FailureFingerprint, fingerprint_failure
- noetrium_platform.infrastructure.reliability.failure.api.catalog ?w^~)?t FailureCatalog, FailureSpec
- noetrium_platform.infrastructure.reliability.failure.api.classification ?w^~)?t ClassifiedOperationFailure, PartialOperationFailureClassifier
- noetrium_platform.infrastructure.reliability.failure.api.codec ?w^~)?t failure_from_dict
- noetrium_platform.infrastructure.reliability.failure.api.contracts ?w^~)?t ExecutionContext, RiskLevel, RecoveryAction, FailureEnvelope
- noetrium_platform.infrastructure.reliability.failure.api.default_catalog ?w^~)?t DEFAULT_FAILURE_CATALOG
- noetrium_platform.infrastructure.reliability.failure.api.exception_refs ?w^~)?t FailureCorrelationSource, exception_correlation_refs
- noetrium_platform.infrastructure.reliability.failure.api.factory ?w^~)?t build_failure, build_failure_from_spec
- noetrium_platform.infrastructure.reliability.failure.api.fingerprint ?w^~)?t FailureFingerprint, fingerprint_failure
- noetrium_platform.infrastructure.reliability.failure.api.ports ?w^~)?t FailureLedgerPort
- noetrium_platform.infrastructure.reliability.failure.api.references ?w^~)?t OperationFailureReferenceProjection, OperationFailureReferenceProjector

### resource

- Package: noetrium_platform.infrastructure.resources
- Authority: resource_inventory
- Canonical authority: resource
- Node kind: authority
- Owns: resource inventory, compute, directories, leases and allocation/resolution
- Must not own: environment semantics and model deployment truth
- Requires: platform, resource/lease, scope
- Provides: compute.inventory, compute.scheduler, directory.layout, resource.endpoint-allocation, resource.hierarchical-resolution, workspace.storage
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource

#### API modules

- noetrium_platform.infrastructure.resources.allocation.api ?w^~)?t AtomicEndpointReservationPort, DEFAULT_ENDPOINT_LEASE_POLICY, EndpointAllocation, EndpointCandidatePortSourcePort, EndpointAllocationPort, EndpointAllocationRequest, EndpointBindingProof, EndpointAllocationState, EndpointLeaseGuardFactoryPort, EndpointLeaseGuardPort, EndpointLeasePolicy, EndpointProbePort, EndpointProbeResult, EndpointProtocol, EndpointReservationResult, EndpointReservationStatus, NetworkEndpoint
- noetrium_platform.infrastructure.resources.allocation.api.contracts ?w^~)?t EndpointAllocation, EndpointBindingProof, EndpointAllocationRequest, EndpointAllocationState, EndpointLeasePolicy, DEFAULT_ENDPOINT_LEASE_POLICY, EndpointReservationResult, EndpointReservationStatus, EndpointProbeResult, EndpointProtocol, NetworkEndpoint
- noetrium_platform.infrastructure.resources.allocation.api.ports ?w^~)?t AtomicEndpointReservationPort, EndpointCandidatePortSourcePort, EndpointAllocationPort, EndpointLeaseGuardFactoryPort, EndpointLeaseGuardPort, EndpointProbePort
- noetrium_platform.infrastructure.resources.api ?w^~)?t DirectoryLayoutPort, ManagedDirectoryKind, ComputeAllocation, ComputeLeaseGuardFactoryPort, ComputeLeaseGuardPort, ComputePlacementUnavailable, ComputeRequirement, ComputeSchedulerPort, EndpointAllocation, EndpointCandidatePortSourcePort, EndpointAllocationPort, EndpointAllocationRequest, EndpointAllocationState, EndpointBindingProof, EndpointLeaseGuardFactoryPort, EndpointLeaseGuardPort, GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, GpuSharingMode, HierarchicalResourceResolver, ResolutionPolicy, ResourceOwnership, ScopedValue
- noetrium_platform.infrastructure.resources.compute.api ?w^~)?t ComputeAllocation, ComputeCandidatePort, ComputeCluster, ComputeGPU, ComputeHost, ComputePlacementUnavailable, ComputeRequirement, ComputeLeasePolicy, DEFAULT_COMPUTE_LEASE_POLICY, ComputeInventoryPort, ComputeLeaseGuardFactoryPort, ComputeLeaseGuardPort, ComputeSchedulerPort, GpuSharingMode, GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, HostRuntimeObserverPort, HostRuntimeSnapshot, HostRuntimeStatus, CommandProbeError, CommandProbePort, CommandProbeResult
- noetrium_platform.infrastructure.resources.compute.api.contracts ?w^~)?t ComputeAllocation, ComputeCluster, ComputeGPU, ComputeHost, ComputePlacementUnavailable, ComputeRequirement, ComputeLeasePolicy, DEFAULT_COMPUTE_LEASE_POLICY, GpuSharingMode
- noetrium_platform.infrastructure.resources.compute.api.ports ?w^~)?t ComputeCandidatePort, ComputeInventoryPort, ComputeLeaseGuardFactoryPort, ComputeLeaseGuardPort, ComputeSchedulerPort
- noetrium_platform.infrastructure.resources.compute.api.probe ?w^~)?t CommandProbeError, CommandProbePort, CommandProbeResult
- noetrium_platform.infrastructure.resources.compute.api.runtime_status ?w^~)?t GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, HostRuntimeObserverPort, HostRuntimeSnapshot, HostRuntimeStatus
- noetrium_platform.infrastructure.resources.directory.api ?w^~)?t DirectoryCleanupCandidate, DirectoryCleanupPort, DirectoryContentStats, DirectoryEntryStats, DirectoryInspectionPort, DirectoryLayout, DirectoryLayoutPort, DirectoryManagementAuthorities, DirectoryOverview, DirectoryUsage, ManagedDirectoryKind, WorkspaceAllocation, WorkspaceMetadataError, WorkspaceMetadataFailureCode, WorkspaceManagementPort
- noetrium_platform.infrastructure.resources.directory.api.contracts ?w^~)?t DirectoryCleanupCandidate, DirectoryContentStats, DirectoryEntryStats, DirectoryLayout, DirectoryOverview, DirectoryUsage, ManagedDirectoryKind, WorkspaceAllocation, WorkspaceMetadataError, WorkspaceMetadataFailureCode
- noetrium_platform.infrastructure.resources.directory.api.ports ?w^~)?t DirectoryCleanupPort, DirectoryInspectionPort, DirectoryLayoutPort, DirectoryManagementAuthorities, WorkspaceManagementPort
- noetrium_platform.infrastructure.resources.resolution.api ?w^~)?t HierarchicalResourceResolver, ResolutionPolicy, ResolvedValue, ResourceNotResolved, ResourceResolutionConflict, ScopedValue, ResourceResolutionPort, ResourceResolutionRequest, ResolvedResourceBinding
- noetrium_platform.infrastructure.resources.resolution.api.contracts ?w^~)?t ResourceResolutionRequest, ResolvedResourceBinding
- noetrium_platform.infrastructure.resources.resolution.api.ports ?w^~)?t ResourceResolutionPort

### resource/lease

- Package: noetrium_platform.infrastructure.resources.lease
- Authority: resource_lease
- Canonical authority: resource/lease
- Node kind: authority
- Owns: lease identity, acquisition, renewal and release
- Must not own: server lifecycle
- Requires: scope
- Provides: resource.lease
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource__lease

#### API modules

- noetrium_platform.infrastructure.resources.lease.api ?w^~)?t LeaseState, ResourceIdentity, ResourceKind, ResourceLease, ResourceOwner, ResourceOwnership, ResourceLeasePort, ResourceLeaseConflict, ResourceLeaseExpired, ResourceOwnershipConflict, ResourceOwnershipPort
- noetrium_platform.infrastructure.resources.lease.api.contracts ?w^~)?t LeaseState, ResourceIdentity, ResourceKind, ResourceLease, ResourceOwner, ResourceOwnership
- noetrium_platform.infrastructure.resources.lease.api.errors ?w^~)?t ResourceLeaseConflict, ResourceLeaseExpired, ResourceOwnershipConflict
- noetrium_platform.infrastructure.resources.lease.api.ports ?w^~)?t ResourceLeasePort, ResourceOwnershipPort

### runtime

- Package: noetrium_platform.infrastructure.lifecycle
- Authority: runtime_state
- Canonical authority: runtime
- Node kind: authority
- Owns: server, process, service and session orchestration
- Must not own: experiment semantics and model catalog truth
- Requires: artifact, governance, governance/release, platform, resource, scope
- Provides: host.runtime, persistent-session.runtime, process.capture, process.execution, python-environment.execution, python-environment.lifecycle, python-environment.packages, python-environment.registry, runtime.toolchain, server.bootstrap, service.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime

#### API modules

- noetrium_platform.infrastructure.lifecycle.api ?w^~)?t LifecycleComponent, LifecycleEvidence, LifecyclePhase, LifecycleSpec, ServiceLaunchPreflightReport, ServiceEnvironmentPort, ServiceRuntimeFactoryPort, ServiceReadinessProbePort, ServiceProcessLivenessPort, MaterializedServiceEnvironment, ProcessSupervisorPort, EnvironmentCommandResult, ExactServiceRuntimePort, LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError, OperatingSystemRoute, PythonEnvironmentExecutionPort, PythonEnvironmentLookupPort, PythonPackageManagementPort, RuntimeToolchainError, ServiceContractDrift, ServiceHeartbeat, ServiceLaunchContract, ServiceLaunchPreflightPort, ServiceProcessIdentity, ServiceReadyObservation, ServiceReconcileObservation, ServiceStartOutcome, ServiceStopOutcome, parse_java_major, ComputeAllocation, ComputeLeaseGuardFactoryPort, ComputePlacementUnavailable, ComputeRequirement, ComputeSchedulerPort, DirectoryLayoutPort, EndpointAllocation, EndpointCandidatePortSourcePort, EndpointAllocationPort, EndpointAllocationRequest, EndpointAllocationState, EndpointBindingProof, EndpointLeaseGuardFactoryPort, EndpointLeaseGuardPort, GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, HierarchicalResourceResolver, ManagedDirectoryKind, ResolutionPolicy, ResourceOwnership, ScopedValue
- noetrium_platform.infrastructure.lifecycle.api.component ?w^~)?t LifecycleComponent, LifecycleEvidence, LifecyclePhase, LifecycleSpec
- noetrium_platform.infrastructure.lifecycle.api.errors ?w^~)?t FrozenRuntimeIdentityViolation, RuntimeLifecycleError, RuntimeOperationalHealthUnavailable
- noetrium_platform.infrastructure.lifecycle.api.resources ?w^~)?t ComputeAllocation, ComputeLeaseGuardFactoryPort, ComputePlacementUnavailable, ComputeRequirement, ComputeSchedulerPort, DirectoryLayoutPort, EndpointAllocation, EndpointCandidatePortSourcePort, EndpointAllocationPort, EndpointAllocationRequest, EndpointAllocationState, EndpointBindingProof, EndpointLeaseGuardFactoryPort, EndpointLeaseGuardPort, GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, HierarchicalResourceResolver, ManagedDirectoryKind, ResolutionPolicy, ResourceOwnership, ScopedValue
- noetrium_platform.infrastructure.lifecycle.host.api ?w^~)?t HostOperatingSystem, OperatingSystemFamily, OperatingSystemRoute, ServerBootstrapTransactionPort
- noetrium_platform.infrastructure.lifecycle.host.api.contracts ?w^~)?t HostOperatingSystem, OperatingSystemFamily
- noetrium_platform.infrastructure.lifecycle.host.api.ports ?w^~)?t OperatingSystemRoute
- noetrium_platform.infrastructure.lifecycle.host.bootstrap.api ?w^~)?t ServerBootstrapBlocked, ServerBootstrapIdentityConflict, ServerBootstrapPhase, ServerBootstrapState, ServerBootstrapStateConflict, ServerBootstrapStatePort, ServerBootstrapTransactionPort, ServerBootstrapTransactionReport
- noetrium_platform.infrastructure.lifecycle.host.bootstrap.api.contracts ?w^~)?t ServerBootstrapBlocked, ServerBootstrapIdentityConflict, ServerBootstrapPhase, ServerBootstrapState, ServerBootstrapStateConflict, ServerBootstrapTransactionReport
- noetrium_platform.infrastructure.lifecycle.host.bootstrap.api.ports ?w^~)?t ServerBootstrapStatePort, ServerBootstrapTransactionPort
- noetrium_platform.infrastructure.lifecycle.process.api ?w^~)?t ByteSegment, CaptureIntegrityError, CaptureManifest, CaptureRotationReceipt, CaptureSyncReceipt, CaptureWriterState, LocalCommandExecutionError, LocalCommandResult, LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError, ProcessByteCapturePort, ProcessCommandResult, ProcessCommandRunnerPort, ProcessExitReceipt, ProcessSupervisorPort, ProcessTerminationPolicy, SupervisedProcessPort
- noetrium_platform.infrastructure.lifecycle.process.api.capture ?w^~)?t ProcessByteCapturePort
- noetrium_platform.infrastructure.lifecycle.process.api.contracts ?w^~)?t CaptureIntegrityError, ByteSegment, CaptureManifest, CaptureWriterState, CaptureRotationReceipt, CaptureSyncReceipt
- noetrium_platform.infrastructure.lifecycle.process.api.local_command ?w^~)?t LocalCommandExecutionError, LocalCommandResult, LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError
- noetrium_platform.infrastructure.lifecycle.process.supervision.api ?w^~)?t ProcessCommandResult, ProcessCommandRunnerPort, ProcessExitReceipt, ProcessSupervisorPort, ProcessTerminationPolicy, SupervisedProcessPort
- noetrium_platform.infrastructure.lifecycle.process.supervision.api.contracts ?w^~)?t ProcessCommandResult, ProcessExitReceipt, ProcessTerminationPolicy
- noetrium_platform.infrastructure.lifecycle.process.supervision.api.ports ?w^~)?t ProcessCommandRunnerPort, ProcessSupervisorPort, SupervisedProcessPort
- noetrium_platform.infrastructure.lifecycle.python.api ?w^~)?t EnvironmentCommandResult, InstalledPythonPackage, EnvironmentCommandRunnerPort, ManagedPythonEnvironment, PythonEnvironmentAuthorities, PythonEnvironmentBackend, PythonEnvironmentCloneResult, PythonEnvironmentExecutionPort, PythonEnvironmentLifecyclePort, PythonEnvironmentLookupPort, PythonEnvironmentOwnership, PythonEnvironmentSpec, PythonEnvironmentState, PythonPackageManagementPort
- noetrium_platform.infrastructure.lifecycle.python.api.contracts ?w^~)?t EnvironmentCommandResult, InstalledPythonPackage, ManagedPythonEnvironment, PythonEnvironmentCloneResult, PythonEnvironmentOwnership, PythonEnvironmentSpec, PythonEnvironmentState
- noetrium_platform.infrastructure.lifecycle.python.api.ports ?w^~)?t EnvironmentCommandRunnerPort, PythonEnvironmentAuthorities, PythonEnvironmentBackend, PythonEnvironmentExecutionPort, PythonEnvironmentLifecyclePort, PythonEnvironmentLookupPort, PythonPackageManagementPort
- noetrium_platform.infrastructure.lifecycle.server.api ?w^~)?t ServerOperationEffect, ServerOperationFinished, ServerOperationJournalPort, ServerOperationKind, ServerOperationRecord, ServerOperationReconciliationRequired, ServerOperationTransitionConflict, ServerMutationBusy, ServerTransportBusy, ServerOperationResolved, ServerOperationResolution, ServerOperationStarted, ServerOperationState, ServerConnectionPort
- noetrium_platform.infrastructure.lifecycle.server.api.operations ?w^~)?t ServerOperationFinished, ServerOperationEffect, ServerOperationJournalPort, ServerOperationKind, ServerOperationStarted, ServerOperationRecord, ServerOperationReconciliationRequired, ServerOperationTransitionConflict, ServerMutationBusy, ServerTransportBusy, ServerOperationResolved, ServerOperationResolution, ServerOperationState
- noetrium_platform.infrastructure.lifecycle.server.health.api ?w^~)?t ServerDiagnosticIssue, ServerDiagnosticProjectorPort, ServerDiagnosticReport, ServerDiagnosticSeverity, ServerDiagnosticStatus, ServerHealthProbePort, ServerHealthReport, ServerRuntimeHealthSpec, ServerSessionDiagnostic
- noetrium_platform.infrastructure.lifecycle.server.health.api.contracts ?w^~)?t ServerDiagnosticIssue, ServerDiagnosticReport, ServerDiagnosticSeverity, ServerDiagnosticStatus, ServerHealthReport, ServerRuntimeHealthSpec, ServerSessionDiagnostic
- noetrium_platform.infrastructure.lifecycle.server.health.api.ports ?w^~)?t ServerDiagnosticProjectorPort, ServerHealthProbePort
- noetrium_platform.infrastructure.lifecycle.server.identity.api ?w^~)?t ServerAuthenticationUnavailable, ServerCommandResult, ServerConnectionFactoryPort, ServerConnectionPort, ServerConnectionProfile, ServerFileTransferFactoryPort, ServerFileTransferPort, ServerFileTransferResult, ServerIdentityConfigurationError, ServerProfileCatalog, ServerProfileCatalogEntry, ServerProfileCatalogError, ServerTransportFailureKind, server_environment_prefix, ServerOperationEffect
- noetrium_platform.infrastructure.lifecycle.server.identity.api.contracts ?w^~)?t ServerAuthenticationUnavailable, ServerCommandResult, ServerConnectionProfile, ServerFileTransferResult, ServerIdentityConfigurationError, ServerProfileCatalog, ServerProfileCatalogEntry, ServerProfileCatalogError, ServerTransportFailureKind, server_environment_prefix
- noetrium_platform.infrastructure.lifecycle.server.identity.api.ports ?w^~)?t ServerConnectionFactoryPort, ServerConnectionPort, ServerFileTransferFactoryPort, ServerFileTransferPort
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api ?w^~)?t ServerReleaseDeploymentError, ServerReleaseLayoutError, ServerReleaseDeploymentPort, ServerReleaseDirectoryPort, ServerRepositorySyncError, ServerRepositorySyncPort, ServerRepositorySyncReceipt, ServerRepositorySyncRequest, ServerRepositoryStatus, ServerRepositoryCommandPort, ServerRepositoryCommandReceipt, ServerRepositoryCommandRequest, ServerReleaseDeploymentReceipt, ServerReleaseDeploymentRequest, ServerReleaseLayout, ServerRemoteProfile, ServerRuntimeLaunchManifestPort, ServerRuntimeLaunchManifestMismatch, ServerSessionPolicyMismatch
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.command ?w^~)?t ServerRepositoryCommandReceipt, ServerRepositoryCommandRequest
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.contracts ?w^~)?t ServerReleaseDeploymentError, ServerReleaseDeploymentReceipt, ServerReleaseDeploymentRequest, ServerReleaseLayout
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.errors ?w^~)?t ServerReleaseLayoutError, ServerRuntimeLaunchManifestMismatch, ServerSessionPolicyMismatch
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.ports ?w^~)?t ServerReleaseDeploymentPort, ServerReleaseDirectoryPort, ServerRepositorySyncPort, ServerRepositoryCommandPort, ServerRuntimeLaunchManifestPort
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.repository ?w^~)?t ServerRepositorySyncError, ServerRepositorySyncReceipt, ServerRepositorySyncRequest, ServerRepositoryStatus
- noetrium_platform.infrastructure.lifecycle.service.api ?w^~)?t CrashClass, CrashDiagnosis, CrashEvidence, classify_crash, MaterializedServiceEnvironment, service_environment_digest, ServiceHeartbeat, ExactServiceRuntimePort, ServiceEnvironmentPort, ServiceLaunchPreflightPort, ServiceLaunchPreflightReport, ServiceProcessLivenessPort, ServiceReadinessProbePort, ServiceRuntimeFactoryPort, ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity, ServiceReadyObservation, ServiceReconcileObservation, ServiceStartOutcome, ServiceStopOutcome
- noetrium_platform.infrastructure.lifecycle.service.api.contracts ?w^~)?t ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity
- noetrium_platform.infrastructure.lifecycle.service.api.crash ?w^~)?t CrashClass, CrashEvidence, CrashDiagnosis, classify_crash
- noetrium_platform.infrastructure.lifecycle.service.api.environment ?w^~)?t MaterializedServiceEnvironment, service_environment_digest
- noetrium_platform.infrastructure.lifecycle.service.api.heartbeat ?w^~)?t ServiceHeartbeat
- noetrium_platform.infrastructure.lifecycle.service.api.ports ?w^~)?t ExactServiceRuntimePort, ServiceEnvironmentPort, ServiceLaunchPreflightReport, ServiceLaunchPreflightPort, ServiceProcessLivenessPort, ServiceReadinessProbePort, ServiceReadyObservation, ServiceReconcileObservation, ServiceRuntimeFactoryPort, ServiceStartOutcome, ServiceStopOutcome
- noetrium_platform.infrastructure.lifecycle.session.api ?w^~)?t PersistentSessionBackendConfig, PersistentSessionBinding, PersistentSessionBindingStorePort, PersistentSessionLaunchManifestPort, PersistentSessionControlPort, PersistentSessionHostPort, PersistentSessionDrift, PersistentSessionReasonCode, PersistentSessionEffectUncertain, PersistentSessionObservation, PersistentSessionObservationState, PersistentSessionReport, PersistentSessionRuntimePort, PersistentSessionSnapshot, PersistentSessionSpec, process_environment_digest, PersistentSessionStatusConfig, PersistentSessionStatusProbePort, ServerSessionPolicy, RuntimeControllerCommand
- noetrium_platform.infrastructure.lifecycle.session.api.binding ?w^~)?t PersistentSessionBinding, PersistentSessionBindingStorePort
- noetrium_platform.infrastructure.lifecycle.session.api.contracts ?w^~)?t PersistentSessionDrift, PersistentSessionReasonCode, PersistentSessionEffectUncertain, PersistentSessionObservation, PersistentSessionObservationState, PersistentSessionReport, PersistentSessionSnapshot, PersistentSessionSpec, process_environment_digest, ServerSessionPolicy
- noetrium_platform.infrastructure.lifecycle.session.api.controller ?w^~)?t PersistentSessionLaunchManifestPort, RuntimeControllerCommand
- noetrium_platform.infrastructure.lifecycle.session.api.ports ?w^~)?t PersistentSessionControlPort, PersistentSessionRuntimePort, PersistentSessionStatusProbePort, PersistentSessionHostPort
- noetrium_platform.infrastructure.lifecycle.session.api.status_config ?w^~)?t PersistentSessionBackendConfig, PersistentSessionStatusConfig
- noetrium_platform.infrastructure.lifecycle.toolchain.api ?w^~)?t JavaRuntimePlatform, JavaRuntimeProvisioningPort, JavaRuntimeProvisioningRequest, JavaRuntimeProvisioningResult, JavaRuntimeReceipt, RuntimeToolchainError, current_java_runtime_platform, parse_java_major
- noetrium_platform.infrastructure.lifecycle.toolchain.api.contracts ?w^~)?t JavaRuntimePlatform, JavaRuntimeProvisioningRequest, JavaRuntimeProvisioningResult, JavaRuntimeReceipt, RuntimeToolchainError, current_java_runtime_platform, parse_java_major
- noetrium_platform.infrastructure.lifecycle.toolchain.api.ports ?w^~)?t JavaRuntimeProvisioningPort

### scope

- Package: noetrium_platform.foundation.scope
- Authority: scope_tree
- Canonical authority: scope
- Node kind: authority
- Owns: generic hierarchical scope identity, ancestry and ownership paths
- Must not own: business metadata and runtime state
- Requires: platform
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope

#### API modules

- noetrium_platform.foundation.scope.api ?w^~)?t PLATFORM_SCOPE, PathFlavor, ScopeIdentity, ScopeKind, ScopeLink, ScopePathPort, ScopeRegistryPort, is_absolute_target_path, require_absolute_target_path, scope_from_data, scope_to_data
- noetrium_platform.foundation.scope.api.codec ?w^~)?t scope_from_data, scope_to_data
- noetrium_platform.foundation.scope.api.contracts ?w^~)?t PLATFORM_SCOPE, ScopeIdentity, ScopeKind, ScopeLink
- noetrium_platform.foundation.scope.api.ports ?w^~)?t ScopeRegistryPort
- noetrium_platform.foundation.scope.path.api ?w^~)?t PathFlavor, ScopePathPort, is_absolute_target_path, require_absolute_target_path
- noetrium_platform.foundation.scope.path.api.contracts ?w^~)?t PathFlavor, is_absolute_target_path, require_absolute_target_path
- noetrium_platform.foundation.scope.path.api.ports ?w^~)?t ScopePathPort

