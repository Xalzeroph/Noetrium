# Noetrium downstream capability catalog

This file is generated from the canonical system registry and public API exports.
Do not edit it manually; run python scripts/update_generated_docs.py.

## How downstream projects use Noetrium

1. Find the capability in noetrium/contracts/downstream_capability_catalog.json.
2. Use its facade_module and import only that generated public facade.
3. Inject the listed ports during composition; do not import noetrium_platform implementation modules.
4. Run python scripts/update_generated_docs.py after changing a registry descriptor or public API export.

Example:

    from noetrium.contracts.systems.environment__minecraft import MinecraftBridgePort
    from noetrium.contracts.systems.participant__agent import AgentMemoryPort

    def compose(bridge: MinecraftBridgePort, memory: AgentMemoryPort) -> None:
        ...

- Registered systems: 172
- Public API modules: 500
- Public symbols: 3659
- Registry digest: c07bdb0976a71d3a2c6102013101a02aa39f61abaa0c4a8104fb0cfc7daa24e7

## Capability domains

| Domain | Systems | API modules | Symbols |
| --- | ---: | ---: | ---: |
| artifact | 7 | 24 | 127 |
| components | 1 | 1 | 49 |
| data | 8 | 20 | 106 |
| environment | 18 | 53 | 444 |
| execution | 7 | 31 | 179 |
| experimentation | 15 | 59 | 576 |
| governance | 13 | 33 | 307 |
| model | 16 | 54 | 476 |
| observability | 27 | 52 | 152 |
| operator | 8 | 10 | 60 |
| orchestration | 1 | 1 | 19 |
| participant | 8 | 39 | 410 |
| platform | 5 | 9 | 89 |
| portfolio | 5 | 7 | 75 |
| reliability | 7 | 31 | 162 |
| resource | 6 | 17 | 114 |
| runtime | 13 | 47 | 282 |
| scope | 7 | 12 | 32 |

## System surfaces

### artifact

- Package: noetrium_platform.evidence.artifact
- Authority: artifact_identity
- Owns: immutable content identity, references, retention and catalog
- Must not own: mutable business state
- Requires: platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact

#### API modules

- noetrium_platform.evidence.artifact.api ?w^~)?t ArtifactContentIdentity, SystemIdentity, SystemSpec, SystemPort
- noetrium_platform.evidence.artifact.api.contracts ?w^~)?t SystemIdentity, SystemPort, SystemSpec, ArtifactContentIdentity
- noetrium_platform.evidence.artifact.api.ports ?w^~)?t SystemPort, SystemSpec

### artifact/catalog

- Package: noetrium_platform.evidence.artifact.catalog
- Authority: artifact_catalog
- Owns: artifact metadata and logical identity catalog
- Must not own: content bytes mutation
- Requires: none
- Provides: artifact.registry
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__catalog

#### API modules

- noetrium_platform.evidence.artifact.catalog.api ?w^~)?t ArtifactKind, ArtifactNotFound, ArtifactQuery, ArtifactRecord, ArtifactRegistryConflict, ArtifactRegistryCorruptionError, ArtifactRegistryPort, ArtifactRetention
- noetrium_platform.evidence.artifact.catalog.api.contracts ?w^~)?t ArtifactKind, ArtifactQuery, ArtifactRecord, ArtifactRetention
- noetrium_platform.evidence.artifact.catalog.api.errors ?w^~)?t ArtifactNotFound, ArtifactRegistryConflict, ArtifactRegistryCorruptionError
- noetrium_platform.evidence.artifact.catalog.api.ports ?w^~)?t ArtifactRegistryPort

### artifact/content

- Package: noetrium_platform.evidence.artifact.content
- Authority: artifact_content
- Owns: immutable content storage and content digest identity
- Must not own: business metadata
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__content

#### API modules

- noetrium_platform.evidence.artifact.content.api ?w^~)?t ArtifactAcquisitionError, ArtifactHttpOpener, ArtifactHttpResponse, ArtifactAcquisitionPort, ArtifactAcquisitionRequest, ArtifactAcquisitionResult, ArtifactContentIdentityResolverPort, ArtifactContentIdentityVerificationError, ArtifactStorageBinding, ArtifactStorageBindingConflict, ArtifactStorageBindingCorruptionError, ArtifactStorageBindingNotFound, ArtifactStorageBindingPort, ArtifactStoragePlacementVerifierPort, ArtifactStorageVerificationError, VerifiedArtifactStoragePlacement, ArchiveMaterializationError, ArchiveMaterializationPort, ArchiveMaterializationRequest, ArchiveMaterializationResult, MaterializedTreeInspection, MaterializedTreeInspectionPort
- noetrium_platform.evidence.artifact.content.api.acquisition ?w^~)?t ArtifactAcquisitionError, ArtifactHttpOpener, ArtifactHttpResponse, ArtifactAcquisitionPort, ArtifactAcquisitionRequest, ArtifactAcquisitionResult
- noetrium_platform.evidence.artifact.content.api.identity ?w^~)?t ArtifactContentIdentityResolverPort, ArtifactContentIdentityVerificationError
- noetrium_platform.evidence.artifact.content.api.materialization ?w^~)?t ArchiveMaterializationError, ArchiveMaterializationPort, ArchiveMaterializationRequest, ArchiveMaterializationResult, MaterializedTreeInspection, MaterializedTreeInspectionPort
- noetrium_platform.evidence.artifact.content.api.storage ?w^~)?t ArtifactStorageBinding, ArtifactStorageBindingConflict, ArtifactStorageBindingCorruptionError, ArtifactStorageBindingNotFound, ArtifactStorageBindingPort, ArtifactStoragePlacementVerifierPort, ArtifactStorageVerificationError, VerifiedArtifactStoragePlacement

### artifact/lineage

- Package: noetrium_platform.evidence.artifact.lineage
- Authority: artifact_lineage
- Owns: artifact lineage and provenance relations
- Must not own: scientific result truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__lineage

### artifact/lineage/relation

- Package: noetrium_platform.evidence.artifact.lineage.relation
- Authority: artifact_lineage_edge
- Owns: immutable artifact lineage edge identity
- Must not own: scientific result semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__lineage__relation

#### API modules

- noetrium_platform.evidence.artifact.lineage.relation.api ?w^~)?t AUTHORITY, CONTRACT, MUST_NOT_OWN, NODE, OWNS, SYSTEM, contract, ArtifactLineageConflict, ArtifactLineageCorruptionError, ArtifactLineageCycle, ArtifactLineageEdge, ArtifactLineageRelationPort
- noetrium_platform.evidence.artifact.lineage.relation.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.evidence.artifact.lineage.relation.api.contracts ?w^~)?t ArtifactLineageConflict, ArtifactLineageCorruptionError, ArtifactLineageCycle, ArtifactLineageEdge
- noetrium_platform.evidence.artifact.lineage.relation.api.ports ?w^~)?t ArtifactLineageRelationPort

### artifact/reference

- Package: noetrium_platform.evidence.artifact.reference
- Authority: artifact_reference
- Owns: references, aliases and cross-system artifact pointers
- Must not own: content mutation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__reference

#### API modules

- noetrium_platform.evidence.artifact.reference.api ?w^~)?t AUTHORITY, CONTRACT, MUST_NOT_OWN, NODE, OWNS, SYSTEM, contract, ArtifactReference, ArtifactReferenceConflict, ArtifactReferenceCorruptionError, ArtifactReferenceNotFound, ArtifactReferencePort
- noetrium_platform.evidence.artifact.reference.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.evidence.artifact.reference.api.contracts ?w^~)?t ArtifactReference, ArtifactReferenceConflict, ArtifactReferenceCorruptionError, ArtifactReferenceNotFound
- noetrium_platform.evidence.artifact.reference.api.ports ?w^~)?t ArtifactReferencePort

### artifact/retention

- Package: noetrium_platform.evidence.artifact.retention
- Authority: artifact_retention
- Owns: retention, pinning and garbage-collection policy
- Must not own: business state semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__retention

#### API modules

- noetrium_platform.evidence.artifact.retention.api ?w^~)?t AUTHORITY, CONTRACT, MUST_NOT_OWN, NODE, OWNS, SYSTEM, contract, ArtifactRetentionConflict, ArtifactRetentionCorruptionError, ArtifactRetentionNotFound, ArtifactRetentionPort, ArtifactRetentionState
- noetrium_platform.evidence.artifact.retention.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.evidence.artifact.retention.api.contracts ?w^~)?t ArtifactRetentionConflict, ArtifactRetentionCorruptionError, ArtifactRetentionNotFound, ArtifactRetentionState
- noetrium_platform.evidence.artifact.retention.api.ports ?w^~)?t ArtifactRetentionPort

### data

- Package: noetrium_platform.evidence.data
- Authority: data_authority
- Owns: durable facts, records, datasets, canonical state and projections
- Must not own: immutable artifact content identity
- Requires: artifact, platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.data

### data/dataset

- Package: noetrium_platform.evidence.data.dataset
- Authority: dataset_authority
- Owns: dataset identity, schema references and lifecycle
- Must not own: dataset physical storage implementation
- Requires: none
- Provides: dataset.registry
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__dataset

#### API modules

- noetrium_platform.evidence.data.dataset.api ?w^~)?t DatasetIdentity, DatasetNotFound, DatasetQuery, DatasetRegistryConflict, DatasetRegistryCorruptionError, DatasetRegistryPort, DatasetVersion
- noetrium_platform.evidence.data.dataset.api.contracts ?w^~)?t DatasetIdentity, DatasetQuery, DatasetVersion
- noetrium_platform.evidence.data.dataset.api.errors ?w^~)?t DatasetNotFound, DatasetRegistryConflict, DatasetRegistryCorruptionError
- noetrium_platform.evidence.data.dataset.api.ports ?w^~)?t DatasetRegistryPort

### data/fact

- Package: noetrium_platform.evidence.data.fact
- Authority: fact_authority
- Owns: durable fact envelopes and authoritative fact writes
- Must not own: business-specific state transitions
- Requires: none
- Provides: durable.fact
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__fact

#### API modules

- noetrium_platform.evidence.data.fact.api ?w^~)?t DurableFact, DurableFactConflict, DurableFactCorruptionError, DurableFactNotFound, DurableFactReceipt, DurableFactSinkPort, DurableFactStorePort, FactCriticality, FactDecoderPort, FactSchema, UnknownRequiredFact
- noetrium_platform.evidence.data.fact.api.contracts ?w^~)?t DurableFact, DurableFactConflict, DurableFactCorruptionError, DurableFactNotFound, DurableFactReceipt, DurableFactSinkPort, DurableFactStorePort, FactCriticality, FactDecoderPort, FactSchema, UnknownRequiredFact

### data/projection

- Package: noetrium_platform.evidence.data.projection
- Authority: projection_authority
- Owns: derived read models and projection lifecycle
- Must not own: source-of-truth mutation
- Requires: none
- Provides: projection.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__projection

#### API modules

- noetrium_platform.evidence.data.projection.api ?w^~)?t ProjectionCheckpoint, ProjectionCheckpointStorePort, ProjectionCursor, ProjectionReducerPort, ProjectionTail
- noetrium_platform.evidence.data.projection.api.contracts ?w^~)?t ProjectionCheckpoint, ProjectionCheckpointStorePort, ProjectionCursor, ProjectionReducerPort, ProjectionTail

### data/query

- Package: noetrium_platform.evidence.data.query
- Authority: query_contracts
- Owns: read query contracts spanning non-authoritative projections
- Must not own: durable writes
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__query

#### API modules

- noetrium_platform.evidence.data.query.api ?w^~)?t ResearchDimension, ResearchDimensionKind, ResearchQueryGap, ResearchQueryGapKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultPage, ResearchResultQuery, ResearchResultQueryPort, ResearchResultRecord, ResearchResultReference, ResearchResultSourcePort, ResearchSourceCut, ResearchSourceDisposition, ResearchSourceSnapshot, ResearchSourceStatus
- noetrium_platform.evidence.data.query.api.contracts ?w^~)?t ResearchDimension, ResearchDimensionKind, ResearchQueryGap, ResearchQueryGapKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultPage, ResearchResultQuery, ResearchResultRecord, ResearchResultReference, ResearchSourceCut, ResearchSourceDisposition, ResearchSourceSnapshot, ResearchSourceStatus
- noetrium_platform.evidence.data.query.api.identity ?w^~)?t input_cut_digest, query_document, record_document, research_query_digest, source_cut
- noetrium_platform.evidence.data.query.api.ports ?w^~)?t ResearchResultQueryPort, ResearchResultSourcePort

### data/query/cross

- Package: noetrium_platform.evidence.data.query.cross
- Authority: cross_query
- Owns: cross-authority read composition and query federation
- Must not own: writes and authority mutation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__query__cross

#### API modules

- noetrium_platform.evidence.data.query.cross.api ?w^~)?t ResearchResultQueryPort, ResearchResultSourcePort
- noetrium_platform.evidence.data.query.cross.api.boundary ?w^~)?t AUTHORITY, MUST_NOT_OWN, NODE, OWNS, SYSTEM

### data/record

- Package: noetrium_platform.evidence.data.record
- Authority: record_authority
- Owns: generic record envelopes and record identity
- Must not own: artifact content bytes
- Requires: none
- Provides: record.plane
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__record

#### API modules

- noetrium_platform.evidence.data.record.api ?w^~)?t ExecutionRecordPlane, RecordPlaneTagged
- noetrium_platform.evidence.data.record.api.contracts ?w^~)?t ExecutionRecordPlane, RecordPlaneTagged

### data/state

- Package: noetrium_platform.evidence.data.state
- Authority: state_authority
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
- Owns: environment specs, bindings, resolution and instances
- Must not own: project semantics and model serving
- Requires: platform, reliability, resource, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment

#### API modules

- noetrium_platform.capabilities.environment.api ?w^~)?t SystemIdentity, SystemSpec, SystemPort, ExecutionContext, EffectClass, EffectCertainty, EffectReceipt, ActionIdentityViolation, ActionNotApplied, ActionRecoveryRequired, ActionReconciliationDisposition, ActionReconciliationResult, ActionRequest, ActionResult, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, ActionSemanticIdentity, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationPort, EnvironmentAssignmentIsolationReceipt, EnvironmentCapabilityUnsupported, EnvironmentCapability, EnvironmentConformanceProbe, EnvironmentProviderConformanceReceipt, verify_environment_provider_conformance, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentProviderPort, EnvironmentSessionDiagnostics, EnvironmentSessionServices, EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort, DurablePreparedActionSession, EnvironmentIdentity, EnvironmentImplementation, EnvironmentSession, Observation, action_request_digest, require_action_recovery_handle_identity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_recovery_handle_reconciliation_identity, JsonScalar, JsonInput, JsonMutableValue, JsonValue, StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json, thaw_json_mapping
- noetrium_platform.capabilities.environment.api.action_identity ?w^~)?t ActionIdentityViolation, ActionSemanticIdentity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_action_recovery_handle_identity, require_recovery_handle_reconciliation_identity
- noetrium_platform.capabilities.environment.api.conformance ?w^~)?t EnvironmentConformanceProbe, EnvironmentProviderConformanceReceipt, verify_environment_provider_conformance
- noetrium_platform.capabilities.environment.api.contracts ?w^~)?t ExecutionContext, JsonInput, JsonValue, SystemIdentity, SystemPort, SystemSpec, canonical_digest, EffectReceipt, PreparedEffectHandle, EnvironmentIdentity, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationReceipt, EnvironmentAssignmentIsolationPort, Observation, ActionRequest, action_request_digest, ActionResult, ActionReconciliationDisposition, ActionReconciliationResult, DurablePreparedActionSession, EnvironmentSession, EnvironmentImplementation
- noetrium_platform.capabilities.environment.api.errors ?w^~)?t ActionNotApplied, ActionRecoveryRequired, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, EnvironmentCapabilityUnsupported
- noetrium_platform.capabilities.environment.api.interaction ?w^~)?t EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort
- noetrium_platform.capabilities.environment.api.ports ?w^~)?t SystemPort, SystemSpec
- noetrium_platform.capabilities.environment.api.provider ?w^~)?t EnvironmentCapability, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentProviderPort, EnvironmentSessionDiagnostics, EnvironmentSessionServices
- noetrium_platform.capabilities.environment.api.state_machine ?w^~)?t JsonScalar, JsonInput, JsonMutableValue, JsonValue, StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json, thaw_json_mapping

### environment/category

- Package: noetrium_platform.capabilities.environment.category
- Authority: environment_category_catalog
- Owns: environment category definitions, category/provider descriptors, compatibility and category fingerprint contracts
- Must not own: environment instance lifecycle, provider execution, project task semantics or vendor-specific runtime state
- Requires: governance/system_registry, platform
- Provides: environment.category
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__category

#### API modules

- noetrium_platform.capabilities.environment.category.api ?w^~)?t EnvironmentCategoryCatalogPort, EnvironmentCategoryDescriptor, EnvironmentCategoryId, EnvironmentCategoryStatus, EnvironmentImplementationDescriptor
- noetrium_platform.capabilities.environment.category.api.contracts ?w^~)?t EnvironmentCategoryDescriptor, EnvironmentCategoryId, EnvironmentCategoryStatus, EnvironmentImplementationDescriptor
- noetrium_platform.capabilities.environment.category.api.ports ?w^~)?t EnvironmentCategoryCatalogPort

### environment/binding

- Package: noetrium_platform.capabilities.environment.binding
- Authority: environment_binding
- Owns: binding environment specs to scopes/runs/participants
- Must not own: artifact storage
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__binding

#### API modules

- noetrium_platform.capabilities.environment.binding.api.boundary ?w^~)?t SystemLeafContract, contract

### environment/catalog

- Package: noetrium_platform.capabilities.environment.catalog
- Authority: environment_catalog
- Owns: environment catalog and versioned definitions
- Must not own: resource capacity
- Requires: none
- Provides: environment.catalog
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__catalog

#### API modules

- noetrium_platform.capabilities.environment.catalog.api ?w^~)?t EnvironmentAssignment, EnvironmentBinding, EnvironmentInstance, EnvironmentOverlay, EnvironmentSpec, EnvironmentTemplate, ExecutionEnvironmentCatalogPort, ExecutionEnvironmentKind, ResolvedEnvironmentSpec
- noetrium_platform.capabilities.environment.catalog.api.contracts ?w^~)?t EnvironmentAssignment, EnvironmentBinding, EnvironmentInstance, EnvironmentOverlay, EnvironmentSpec, EnvironmentTemplate, ExecutionEnvironmentKind, ResolvedEnvironmentSpec
- noetrium_platform.capabilities.environment.catalog.api.ports ?w^~)?t ExecutionEnvironmentCatalogPort

### environment/instance

- Package: noetrium_platform.capabilities.environment.instance
- Authority: environment_instance
- Owns: environment instance identity, readiness and lifecycle
- Must not own: host supervision implementation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__instance

### environment/instance/identity

- Package: noetrium_platform.capabilities.environment.instance.identity
- Authority: environment_instance_identity
- Owns: environment instance identity and provenance
- Must not own: host process lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__instance__identity

#### API modules

- noetrium_platform.capabilities.environment.instance.identity.api.boundary ?w^~)?t SystemLeafContract, contract

### environment/instance/readiness

- Package: noetrium_platform.capabilities.environment.instance.readiness
- Authority: environment_readiness
- Owns: environment readiness observations/contract
- Must not own: authoritative process health
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__instance__readiness

#### API modules

- noetrium_platform.capabilities.environment.instance.readiness.api.boundary ?w^~)?t SystemLeafContract, contract

### environment/minecraft

- Package: noetrium_platform.capabilities.environment.minecraft
- Authority: minecraft_environment
- Owns: Minecraft environment contracts, server-control/world-cut semantics, state projection, bridge providers and readiness adapters
- Must not own: generic environment catalog, process/server supervision, model serving, project method semantics or telemetry storage
- Requires: artifact, environment, reliability, resource, runtime
- Provides: environment.minecraft.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__minecraft

#### API modules

- noetrium_platform.capabilities.environment.minecraft.api ?w^~)?t MINECRAFT_ACTION_TYPES, MINECRAFT_ACTION_SPECS, MINECRAFT_ACTION_SPEC_BY_TYPE, MinecraftActionCategory, MinecraftActionOutcomeStatus, MinecraftActionResultEvidence, MinecraftActionSpec, MinecraftBridgeCommandResult, MinecraftBranchRuntimeFactoryPort, MinecraftBranchRuntimePort, MinecraftBranchRuntimeRequest, MinecraftBranchServerFactoryPort, MinecraftBridgeEnvelope, MinecraftBridgePort, MinecraftDiagnosticsPort, MinecraftBridgeSpec, MinecraftAgentSpec, MinecraftCheckpointPort, MinecraftConsoleCommandResult, MinecraftRconEndpoint, MinecraftServerConsolePort, MinecraftWorldBranch, MinecraftWorldCut, MinecraftWorldCutPort, MinecraftWorldCutMetadataStorePort, MinecraftEndpointSpec, MinecraftEnvironmentSpec, MinecraftJsonValue, MinecraftServerPreparedFiles, MinecraftServerSpec, MinecraftSessionRuntimeIdentity, MinecraftObservationEvent, MinecraftPlannerActionContract, MinecraftWorldQuiescence, MinecraftWorldQuiescencePort, MinecraftReconciliation, MinecraftServerLifecyclePort, MinecraftServerEndpointBindingPort, MinecraftSessionServices, MinecraftExperimentHostPort, MinecraftScenarioProvisioningPort, MinecraftScenarioReceipt, MinecraftScenarioSpec, MinecraftScenarioStep, MinecraftScenarioStepReceipt, MinecraftActionContractError, minecraft_action_catalog, minecraft_action_timeout, validate_minecraft_action, minecraft_response_sha256, minecraft_scenario_from_mapping
- noetrium_platform.capabilities.environment.minecraft.api.action_codec_support ?w^~)?t MinecraftActionCodec, MinecraftActionContractError, allowed, distance, error, integer, item_count, number, position, text
- noetrium_platform.capabilities.environment.minecraft.api.action_codecs ?w^~)?t ACTION_CODECS, MinecraftActionCodec, MinecraftActionContractError, validate_minecraft_action
- noetrium_platform.capabilities.environment.minecraft.api.action_codecs_combat ?w^~)?t CODECS
- noetrium_platform.capabilities.environment.minecraft.api.action_codecs_interaction ?w^~)?t CODECS
- noetrium_platform.capabilities.environment.minecraft.api.action_codecs_navigation ?w^~)?t CODECS
- noetrium_platform.capabilities.environment.minecraft.api.action_codecs_resources ?w^~)?t CODECS
- noetrium_platform.capabilities.environment.minecraft.api.action_codecs_utility ?w^~)?t CODECS
- noetrium_platform.capabilities.environment.minecraft.api.actions ?w^~)?t MinecraftActionContractError, minecraft_action_catalog, minecraft_action_timeout, validate_minecraft_action
- noetrium_platform.capabilities.environment.minecraft.api.contracts ?w^~)?t canonical_digest, EndpointAllocationRequest, is_absolute_target_path, ScopeKind, MinecraftActionCategory, MinecraftActionOutcomeStatus, MinecraftPlannerActionContract, MinecraftActionSpec, MinecraftEndpointSpec, MinecraftAgentSpec, MinecraftBridgeSpec, MinecraftEnvironmentSpec, MinecraftSessionRuntimeIdentity, MinecraftServerSpec, MinecraftServerPreparedFiles, MinecraftRconEndpoint, MinecraftConsoleCommandResult, MinecraftWorldQuiescence, MinecraftWorldCut, MinecraftWorldBranch, MinecraftBranchRuntimeRequest, MinecraftObservationEvent, MinecraftActionResultEvidence, MinecraftBridgeEnvelope
- noetrium_platform.capabilities.environment.minecraft.api.ports ?w^~)?t MinecraftBridgeCommandResult, MinecraftSessionServices, MinecraftBranchRuntimeFactoryPort, MinecraftBranchRuntimePort, MinecraftBranchServerFactoryPort, MinecraftBridgePort, MinecraftDiagnosticsPort, MinecraftCheckpointPort, MinecraftConsoleCommandResult, MinecraftRconEndpoint, MinecraftServerConsolePort, MinecraftScenarioProvisioningPort, MinecraftWorldBranch, MinecraftWorldCut, MinecraftWorldCutMetadataStorePort, MinecraftWorldCutPort, MinecraftExperimentHostPort, MinecraftWorldQuiescence, MinecraftWorldQuiescencePort, MinecraftReconciliation, MinecraftServerLifecyclePort, MinecraftServerEndpointBindingPort
- noetrium_platform.capabilities.environment.minecraft.api.scenario ?w^~)?t MinecraftScenarioReceipt, MinecraftScenarioSpec, MinecraftScenarioStep, MinecraftScenarioStepReceipt, minecraft_response_sha256, minecraft_scenario_from_mapping

### environment/embodied

- Package: noetrium_platform.capabilities.environment.embodied
- Authority: embodied_environment
- Owns: embodied environment contracts, episode/trajectory interaction and provider-facing embodiment metadata
- Must not own: generic environment catalog, experiment semantics, model serving, telemetry storage or vendor SDK internals
- Requires: environment, reliability, resource
- Provides: environment.embodied.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__embodied

#### API modules

- noetrium_platform.capabilities.environment.embodied.api ?w^~)?t ActionKind, ActionSpec, EmbodiedActionCommand, EmbodiedCaptureReceipt, EmbodiedCapabilityPort, EmbodiedCheckpointPort, EmbodiedEnvironmentPort, EmbodiedQueryPort, EmbodiedEvent, EmbodiedEventKind, EmbodiedTrajectorySinkPort, EmbodimentKind, EmbodimentSpec, EpisodeSpec, SensorModality, SensorSpec
- noetrium_platform.capabilities.environment.embodied.api.contracts ?w^~)?t ActionKind, ActionSpec, EmbodiedActionCommand, EmbodiedCaptureReceipt, EmbodiedEvent, EmbodiedEventKind, EmbodimentKind, EmbodimentSpec, EpisodeSpec, SensorModality, SensorSpec
- noetrium_platform.capabilities.environment.embodied.api.ports ?w^~)?t EmbodiedCapabilityPort, EmbodiedCheckpointPort, EmbodiedEnvironmentPort, EmbodiedQueryPort, EmbodiedTrajectorySinkPort

### environment/gui

- Package: noetrium_platform.capabilities.environment.gui
- Authority: gui_environment
- Owns: desktop and mobile GUI environment contracts and provider adapters
- Must not own: benchmark cases, task scoring, tool capability policy or OS process supervision
- Requires: environment, runtime
- Provides: environment.gui.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__gui

#### API modules

- noetrium_platform.capabilities.environment.gui.api ?w^~)?t GuiActionKind, GuiEnvironmentSpec, GuiWorldPort
- noetrium_platform.capabilities.environment.gui.api.contracts ?w^~)?t GuiActionKind, GuiEnvironmentSpec
- noetrium_platform.capabilities.environment.gui.api.ports ?w^~)?t GuiWorldPort

### environment/web

- Package: noetrium_platform.capabilities.environment.web
- Authority: web_environment
- Owns: stateful web and browser environment contracts and provider adapters
- Must not own: benchmark cases, task scoring, browser automation policy or model serving
- Requires: environment, runtime
- Provides: environment.web.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__web

#### API modules

- noetrium_platform.capabilities.environment.web.api ?w^~)?t WebActionKind, WebEnvironmentSpec, WebWorldPort
- noetrium_platform.capabilities.environment.web.api.contracts ?w^~)?t WebActionKind, WebEnvironmentSpec
- noetrium_platform.capabilities.environment.web.api.ports ?w^~)?t WebWorldPort

### environment/software

- Package: noetrium_platform.capabilities.environment.software
- Authority: software_environment
- Owns: repository and software-workspace environment contracts and provider adapters
- Must not own: benchmark scoring, repository policy, model serving or generic process supervision
- Requires: environment, runtime, resource
- Provides: environment.software.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__software

#### API modules

- noetrium_platform.capabilities.environment.software.api ?w^~)?t SoftwareActionKind, SoftwareEnvironmentSpec, SoftwareWorldPort
- noetrium_platform.capabilities.environment.software.api.contracts ?w^~)?t SoftwareActionKind, SoftwareEnvironmentSpec
- noetrium_platform.capabilities.environment.software.api.ports ?w^~)?t SoftwareWorldPort

### environment/text_world

- Package: noetrium_platform.capabilities.environment.text_world
- Authority: text_world_environment
- Owns: text-mediated stateful world contracts and provider adapters
- Must not own: dialogue method, benchmark scoring, agent memory or multi-agent topology
- Requires: environment
- Provides: environment.text_world.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__text_world

#### API modules

- noetrium_platform.capabilities.environment.text_world.api ?w^~)?t TextWorldActionKind, TextWorldEnvironmentSpec, TextWorldPort
- noetrium_platform.capabilities.environment.text_world.api.contracts ?w^~)?t TextWorldActionKind, TextWorldEnvironmentSpec
- noetrium_platform.capabilities.environment.text_world.api.ports ?w^~)?t TextWorldPort

### environment/resolution

- Package: noetrium_platform.capabilities.environment.resolution
- Authority: environment_resolution
- Owns: resolve logical environment requirements to concrete instance plan
- Must not own: process lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__resolution

#### API modules

- noetrium_platform.capabilities.environment.resolution.api.boundary ?w^~)?t SystemLeafContract, contract

### environment/runtime

- Package: noetrium_platform.capabilities.environment.runtime
- Authority: environment_runtime_contract
- Owns: environment runtime adapter contracts
- Must not own: environment catalog authority
- Requires: none
- Provides: environment.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__runtime

#### API modules

- noetrium_platform.capabilities.environment.runtime.api ?w^~)?t ActionIdentityViolation, ActionNotApplied, ActionRecoveryRequired, ActionReconciliationDisposition, ActionReconciliationResult, ActionRequest, ActionResult, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, EnvironmentCapabilityUnsupported, EnvironmentCapability, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentSessionDiagnostics, ActionSemanticIdentity, DurablePreparedActionSession, EnvironmentIdentity, EnvironmentSession, Observation, EnvironmentImplementation, action_request_digest, require_action_recovery_handle_identity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_recovery_handle_reconciliation_identity, EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort, JsonScalar, JsonInput, JsonMutableValue, JsonValue, StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json, thaw_json_mapping
- noetrium_platform.capabilities.environment.runtime.api.action_identity ?w^~)?t ActionIdentityViolation, ActionSemanticIdentity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_action_recovery_handle_identity, require_recovery_handle_reconciliation_identity
- noetrium_platform.capabilities.environment.runtime.api.contracts ?w^~)?t ActionReconciliationDisposition, ActionReconciliationResult, ActionRequest, ActionResult, DurablePreparedActionSession, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationPort, EnvironmentAssignmentIsolationReceipt, EnvironmentIdentity, EnvironmentImplementation, EnvironmentSession, Observation, SystemIdentity, SystemSpec, action_request_digest
- noetrium_platform.capabilities.environment.runtime.api.errors ?w^~)?t ActionNotApplied, ActionRecoveryRequired, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, EnvironmentCapabilityUnsupported
- noetrium_platform.capabilities.environment.runtime.api.state_machine ?w^~)?t JsonScalar, JsonInput, JsonMutableValue, JsonValue, StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json, thaw_json_mapping

### environment/specification

- Package: noetrium_platform.capabilities.environment.specification
- Authority: environment_spec
- Owns: environment definition and immutable spec identity
- Must not own: live host process state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__specification

### environment/specification/digest

- Package: noetrium_platform.capabilities.environment.specification.digest
- Authority: environment_digest
- Owns: exact environment specification identity and digest
- Must not own: resource resolution
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__specification__digest

#### API modules

- noetrium_platform.capabilities.environment.specification.digest.api.boundary ?w^~)?t SystemLeafContract, contract

### environment/specification/schema

- Package: noetrium_platform.capabilities.environment.specification.schema
- Authority: environment_schema
- Owns: environment requirement schema and canonical forms
- Must not own: environment instance lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__specification__schema

#### API modules

- noetrium_platform.capabilities.environment.specification.schema.api.boundary ?w^~)?t SystemLeafContract, contract

### execution

- Package: noetrium_platform.research.execution
- Authority: execution_operations
- Owns: workflow and operation orchestration contracts
- Must not own: provider storage and domain truth
- Requires: environment, governance, model, observability, participant, platform, reliability, runtime, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution

#### API modules

- noetrium_platform.research.execution.api ?w^~)?t DeploymentStatusIdentity, ExecutionIntentPort, ExecutionIntentReceipt, ExecutionOperationIntent
- noetrium_platform.research.execution.api.intent ?w^~)?t ExecutionIntentPort, ExecutionIntentReceipt, ExecutionOperationIntent
- noetrium_platform.research.execution.api.status ?w^~)?t DeploymentStatusIdentity

### execution/admission

- Package: noetrium_platform.research.execution.admission
- Authority: admission_decision
- Owns: hierarchical execution quotas, identity-aware admission decisions and lease accounting
- Must not own: scheduling order/fairness, executor lifecycle or model/environment truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__admission

#### API modules

- noetrium_platform.research.execution.admission.api ?w^~)?t AdmissionBudget, AdmissionIdentity, AdmissionIntent, AdmissionMode, AdmissionRejected, AdmissionTopologySnapshot, CONTRACT, ExecutionAdmissionPort, GroupAdmissionSnapshot, LaneAdmissionSnapshot, ResourceAdmissionSnapshot, TenantAdmissionSnapshot, contract
- noetrium_platform.research.execution.admission.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.research.execution.admission.api.contracts ?w^~)?t ExecutionPriority, ExecutionLaneKind, ExecutionPermitRejected, AdmissionMode, AdmissionRejected, AdmissionBudget, AdmissionIdentity, AdmissionIntent, GroupAdmissionSnapshot, TenantAdmissionSnapshot, ResourceAdmissionSnapshot, LaneAdmissionSnapshot, AdmissionTopologySnapshot
- noetrium_platform.research.execution.admission.api.ports ?w^~)?t CancellationTokenPort, Deadline, ExecutionLaneKind, ExecutionPermitLeasePort, AdmissionIdentity, AdmissionIntent, AdmissionTopologySnapshot, ExecutionAdmissionPort

### execution/capability

- Package: noetrium_platform.research.execution.capability
- Authority: capability_catalog
- Owns: capability declarations and invocation contracts
- Must not own: provider implementation
- Requires: none
- Provides: capability.invocation, capability.registration
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__capability

#### API modules

- noetrium_platform.research.execution.capability.api ?w^~)?t CapabilityInvocationPipelineFactoryPort, CapabilityInvocationPipelinePort, CapabilityLifetime, CapabilityRegistration, CapabilityTypeMismatch, RegistrationConflict, RegistrationHandlePort, RegistrationKey, RegistrationLeasePort, RegistrationScopeFactoryPort, RegistrationScopePort, ScopeDisposed
- noetrium_platform.research.execution.capability.api.invocation ?w^~)?t CapabilityInvocationPipelineFactoryPort, CapabilityInvocationPipelinePort
- noetrium_platform.research.execution.capability.api.registration ?w^~)?t CapabilityLifetime, CapabilityRegistration, CapabilityTypeMismatch, RegistrationConflict, RegistrationHandlePort, RegistrationKey, RegistrationLeasePort, RegistrationScopeFactoryPort, RegistrationScopePort, ScopeDisposed

### execution/command

- Package: noetrium_platform.research.execution.command
- Authority: command_intent
- Owns: typed execution commands and command routing
- Must not own: human UI and provider-specific control
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__command

#### API modules

- noetrium_platform.research.execution.command.api ?w^~)?t CONTRACT, CommandConflict, CommandCorruption, CommandDeduplicationKey, CommandId, CommandIntentPort, CommandStorePort, ExecutionCommand, contract
- noetrium_platform.research.execution.command.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.research.execution.command.api.contracts ?w^~)?t CommandDeduplicationKey, CommandId, ExecutionCommand
- noetrium_platform.research.execution.command.api.ports ?w^~)?t CommandConflict, CommandCorruption, CommandIntentPort, CommandStorePort

### execution/operation

- Package: noetrium_platform.research.execution.operation
- Authority: operation_state
- Owns: operation identity, lifecycle and result envelopes
- Must not own: failure taxonomy and recovery authority
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__operation

#### API modules

- noetrium_platform.research.execution.operation.api ?w^~)?t CONTRACT, EffectId, IllegalOperationTransition, OperationAdmissionPort, OperationConflict, OperationCorruption, OperationEffectCertainty, OperationEffectProfile, OperationFailure, OperationFailureKind, OperationId, OperationLifecyclePort, OperationRecoveryPort, OperationSnapshot, OperationState, OperationStorePort, OperationSubmissionPort, EffectReconciliationOutcome, EffectReconciliationVerdict, project_effect_reconciliation, TERMINAL_OPERATION_STATES, contract, revise_operation, transition_operation
- noetrium_platform.research.execution.operation.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.research.execution.operation.api.contracts ?w^~)?t EffectId, IllegalOperationTransition, OperationEffectCertainty, OperationEffectProfile, OperationFailure, OperationFailureKind, OperationId, OperationSnapshot, OperationState, TERMINAL_OPERATION_STATES, revise_operation, transition_operation
- noetrium_platform.research.execution.operation.api.ports ?w^~)?t OperationAdmissionPort, OperationConflict, OperationCorruption, OperationLifecyclePort, OperationRecoveryPort, OperationStorePort, OperationSubmissionPort
- noetrium_platform.research.execution.operation.api.reconciliation ?w^~)?t EffectReconciliationOutcome, EffectReconciliationVerdict, project_effect_reconciliation

### execution/scheduling

- Package: noetrium_platform.research.execution.scheduling
- Authority: schedule_intent
- Owns: priority, aging, fairness and deterministic scheduling order
- Must not own: live resource/admission state, quotas or executor lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__scheduling

#### API modules

- noetrium_platform.research.execution.scheduling.api ?w^~)?t AdmissionSchedulingPolicyPort, CONTRACT, ExecutionPriority, SchedulingCandidate, contract
- noetrium_platform.research.execution.scheduling.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.research.execution.scheduling.api.contracts ?w^~)?t ExecutionPriority, SchedulingCandidate
- noetrium_platform.research.execution.scheduling.api.ports ?w^~)?t SchedulingCandidate, AdmissionSchedulingPolicyPort

### execution/workflow

- Package: noetrium_platform.research.execution.workflow
- Authority: workflow_state
- Owns: workflow definitions and orchestration semantics
- Must not own: process supervision
- Requires: none
- Provides: workflow.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__workflow

#### API modules

- noetrium_platform.research.execution.workflow.api ?w^~)?t EffectIntentOperationPort, OperationDispatchPort, OperationExecutionPort, TrialCycleExecution, WorkflowGraph, WorkflowGraphError, WorkflowOperationBinding, WorkflowParticipantRequirementError, WorkflowProgress, WorkflowProgressConflict, WorkflowProgressCorruption, WorkflowProgressStorePort, WorkflowRunId, WorkflowStep, WorkflowSurfaceBindingContext, WorkflowSurfaceFactory, workflow_surface_id
- noetrium_platform.research.execution.workflow.api.dispatch ?w^~)?t OperationDispatchPort, OperationExecutionPort
- noetrium_platform.research.execution.workflow.api.effect_intents ?w^~)?t EffectIntentOperationPort
- noetrium_platform.research.execution.workflow.api.errors ?w^~)?t WorkflowParticipantRequirementError
- noetrium_platform.research.execution.workflow.api.graph ?w^~)?t WorkflowGraph, WorkflowGraphError, WorkflowStep
- noetrium_platform.research.execution.workflow.api.progress ?w^~)?t WorkflowOperationBinding, WorkflowProgress, WorkflowProgressConflict, WorkflowProgressCorruption, WorkflowProgressStorePort, WorkflowRunId
- noetrium_platform.research.execution.workflow.api.surfaces ?w^~)?t WorkflowSurfaceBindingContext, WorkflowSurfaceFactory, workflow_surface_id
- noetrium_platform.research.execution.workflow.api.trial ?w^~)?t TrialCycleExecution

### experimentation

- Package: noetrium_platform.research.experimentation
- Authority: experimentation_state
- Owns: study, experiment, run, branch and checkpoint semantics
- Must not own: server/process control and model serving
- Requires: environment, execution, participant, platform, portfolio, scope, governance, model
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation

#### API modules

- noetrium_platform.research.experimentation.api ?w^~)?t ResearchBindingContribution, ResearchCapabilityBinding, ResearchModelBinding, ResearchParticipantBinding, ResearchBindingRequirements, ResearchParticipantRequirement, ResearchRequirementResolution, resolve_research_requirements, TrialProviderPort, TrialMatrixExecutionReport, TrialExecutionRequest, TrialExecutionReceipt, ReplayLevel, AnalysisDefinition, AnalysisResult, BenchmarkTaskSet, BenchmarkSourceKind, BenchmarkSourcePort, BenchmarkSourceResolution, BenchmarkSourceSpec, InMemoryBenchmarkSource, MeasurementContentReference, MeasurementCut, TaskDefinition, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, diff_research_plans, compile_research_plan, ResearchPlanDiff, CompiledResearchPlan, ResearchMethodHost, ResearchMethodHostPort, ExperimentPlanExecutionPort, ExperimentRunner, ExperimentRunnerPort, StudyIntervention, StudyFactorSpec, ResearchStudyDefinition, ResearchRevision, ParticipantSchedule, MeasurementValueKind, MeasurementValue, MeasurementRecord, MeasurementProtocol, MeasurementDefinition, FactorSelection, FactorLevelSpec, ProjectIdentityProjection, ProjectManifestProjection, ProjectRunDefinition, RunControlAction, RunControlPort, RunControlRecordKind, RunControlReceipt, RunControlReceiptReference, RunControlRequest, RunControlTarget, RunEvidenceValidity, RunExecutionOutcome, RunOutcomeProjection, RunScientificValidity, RunTaskOutcome
- noetrium_platform.research.experimentation.api.construction ?w^~)?t ProjectIdentityProjection, ProjectManifestProjection, ProjectRunDefinition
- noetrium_platform.research.experimentation.api.method_host ?w^~)?t ResearchMethodHost, ResearchMethodHostPort
- noetrium_platform.research.experimentation.api.research_compiler ?w^~)?t CompiledResearchPlan, ResearchPlanDiff, compile_research_plan, resolve_research_requirements, diff_research_plans
- noetrium_platform.research.experimentation.api.runner ?w^~)?t ExperimentPlanExecutionPort, ExperimentRunner, ExperimentRunnerPort

### experimentation/branch

- Package: noetrium_platform.research.experimentation.branch
- Authority: branch_state
- Owns: run branching and branch lineage
- Must not own: generic artifact lineage
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__branch

#### API modules

- noetrium_platform.research.experimentation.branch.api.boundary ?w^~)?t SystemLeafContract, contract

### experimentation/catalog

- Package: noetrium_platform.research.experimentation.catalog
- Authority: experiment_catalog_view
- Owns: typed experiment catalog views, implementation candidates, slot health and catalog publication/query contracts
- Must not own: experiment execution, study measurement truth, run lifecycle or benchmark implementation runtime
- Requires: experimentation/experiment, experimentation/run/identity, experimentation/study, scope
- Provides: experiment.catalog
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__catalog

#### API modules

- noetrium_platform.research.experimentation.catalog.api ?w^~)?t ExperimentationCatalogPort
- noetrium_platform.research.experimentation.catalog.api.ports ?w^~)?t ExperimentationCatalogPort

### experimentation/checkpoint

- Package: noetrium_platform.research.experimentation.checkpoint
- Authority: checkpoint_state
- Owns: checkpoint identity, binding and lifecycle
- Must not own: artifact content storage
- Requires: none
- Provides: run.checkpoint
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__checkpoint

#### API modules

- noetrium_platform.research.experimentation.checkpoint.api ?w^~)?t CheckpointedWorkloadBatchResult, RunCheckpointBundle, RunCheckpointConflict, RunCheckpointCoordinatorPort, RunCheckpointIntegrityError, RunCheckpointManifest, RunCheckpointResult, RunCheckpointStore, RunParticipantPayload, RunParticipantSnapshotRef, RunRestoreResult, WorkloadCheckpointBindingPort, WorkloadCheckpointBundle, WorkloadCheckpointRestoreError, WorkloadCheckpointComponentPort, WorkloadCheckpointComponentRef, WorkloadCheckpointManifest, WorkloadCheckpointPayload, WorkloadCheckpointStore, WorkloadExecutionCut, WorkloadRestoreStateCertainty, build_workload_checkpoint_manifest, WorkloadCheckpointCoordinatorPort, WorkloadCheckpointPublicationPort, WorkloadCheckpointedBatchExecutorPort
- noetrium_platform.research.experimentation.checkpoint.api.contracts ?w^~)?t RunCheckpointBundle, RunCheckpointConflict, RunCheckpointIntegrityError, RunCheckpointManifest, RunCheckpointStore, RunParticipantPayload, RunParticipantSnapshotRef
- noetrium_platform.research.experimentation.checkpoint.api.ports ?w^~)?t RunCheckpointCoordinatorPort
- noetrium_platform.research.experimentation.checkpoint.api.results ?w^~)?t RunCheckpointResult, RunRestoreResult
- noetrium_platform.research.experimentation.checkpoint.api.workload ?w^~)?t WorkloadCheckpointBindingPort, WorkloadCheckpointRestoreError, WorkloadCheckpointBundle, WorkloadCheckpointComponentPort, WorkloadCheckpointComponentRef, WorkloadCheckpointManifest, WorkloadCheckpointPayload, WorkloadCheckpointStore, WorkloadExecutionCut, WorkloadRestoreStateCertainty, build_workload_checkpoint_manifest
- noetrium_platform.research.experimentation.checkpoint.api.workload_ports ?w^~)?t CheckpointedWorkloadBatchResult, WorkloadCheckpointCoordinatorPort, WorkloadCheckpointPublicationPort, WorkloadCheckpointedBatchExecutorPort

### experimentation/evaluation

- Package: noetrium_platform.research.experimentation.evaluation
- Authority: experiment_evaluation
- Owns: evaluation contracts, execution-neutral evaluators and evaluation composition
- Must not own: experiment execution lifecycle or scientific claim acceptance
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__evaluation

#### API modules

- noetrium_platform.research.experimentation.evaluation.api ?w^~)?t BranchReceipt, ComparabilityProof, PairedEvaluationResult, build_comparability_proof
- noetrium_platform.research.experimentation.evaluation.api.contracts ?w^~)?t BranchReceipt, ComparabilityProof, PairedEvaluationResult, build_comparability_proof

### experimentation/experiment

- Package: noetrium_platform.research.experimentation.experiment
- Authority: experiment_state
- Owns: experiment definitions, variants and experiment lifecycle
- Must not own: runtime process state
- Requires: none
- Provides: experiment.definition, experiment.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__experiment

#### API modules

- noetrium_platform.research.experimentation.experiment.api ?w^~)?t ExperimentComponentBindingPort, AnalysisPlan, DoctorFinding, ExperimentDefinition, ExperimentLifecycleState, ExperimentModePort, ExecutionMode, ExperimentParticipantSpec, ExperimentPlan, ExperimentRunReport, ExperimentTransition, ExperimentUnit, ExperimentUnitExecutorPort, ExperimentUnitKind, ExperimentUnitPlannerPort, RawRecordStorePort, RawRecord, MetricAggregation, MetricMissingPolicy, MetricPredicate, MetricDefinition, MetricValue, MetricReport, ExperimentParticipantTopology, ExperimentTrialCycleExecutorPort, ExperimentTrialProtocol, ExperimentTaskSpec, ExperimentWorkloadFailure, ExperimentSpec, ExperimentTrialProtocolIdentity, ExperimentTrialProtocolIdentityMismatch, FailureScope, FailureScopeRank, failure_scope_rank, validate_task_graph
- noetrium_platform.research.experimentation.experiment.api.contracts ?w^~)?t ExperimentParticipantSpec, ExperimentSpec, AnalysisPlan, DoctorFinding, ExecutionMode, ExperimentDefinition, ExperimentLifecycleState, ExperimentModePort, ExperimentPlan, ExperimentRunReport, ExperimentTransition, ExperimentUnit, ExperimentUnitExecutorPort, ExperimentUnitKind, ExperimentUnitPlannerPort, FindingSeverity, ObservationEnvelope, ObservationKind, ObservationSinkPort, ExperimentDoctorPort, UnitOutcome, UnitOutcomeState, RawRecordStorePort, RawRecord, MetricAggregation, MetricMissingPolicy, MetricPredicate, MetricDefinition, MetricValue, MetricReport
- noetrium_platform.research.experimentation.experiment.api.failure ?w^~)?t ExperimentWorkloadFailure, FailureScope, FailureScopeRank, failure_scope_rank
- noetrium_platform.research.experimentation.experiment.api.ports ?w^~)?t ExperimentComponentBindingPort, ExperimentTrialCycleExecutorPort
- noetrium_platform.research.experimentation.experiment.api.tasks ?w^~)?t ExperimentTaskSpec, validate_task_graph
- noetrium_platform.research.experimentation.experiment.api.topology ?w^~)?t ExperimentParticipantTopology
- noetrium_platform.research.experimentation.experiment.api.trial_protocol ?w^~)?t ExperimentTrialProtocol, ExperimentTrialProtocolIdentity, ExperimentTrialProtocolIdentityMismatch

### experimentation/run

- Package: noetrium_platform.research.experimentation.run
- Authority: run_state
- Owns: run identity, frozen run contract and run lifecycle
- Must not own: server supervision internals
- Requires: none
- Provides: run.lifecycle, run.decision
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run

#### API modules

- noetrium_platform.research.experimentation.run.api ?w^~)?t DecisionCycleCoordinatorPort, RunArtifactFinalizationError, RunArtifactFinalizationPort, RunArtifactKind, RunArtifactSnapshotReceipt, RunArtifactSealedError, RunArtifactStorePort, RunArtifactVerificationError, RunArtifactVerificationPort, RunArtifactWriteActorPort, RunCoordinatorPort, RunDiagnosticsPort, RunSessionPort, ExperimentRunSpec, ExperimentRunExecutionPort, ExperimentRunResult
- noetrium_platform.research.experimentation.run.api.artifacts ?w^~)?t RunArtifactFinalizationError, RunArtifactFinalizationPort, RunArtifactKind, RunArtifactSnapshotReceipt, RunArtifactSealedError, RunArtifactStorePort, RunArtifactVerificationError, RunArtifactVerificationPort, RunArtifactWriteActorPort
- noetrium_platform.research.experimentation.run.api.diagnostics ?w^~)?t RunDiagnosticsPort
- noetrium_platform.research.experimentation.run.api.execution ?w^~)?t ExperimentRunExecutionPort, ExperimentRunResult
- noetrium_platform.research.experimentation.run.api.ports ?w^~)?t DecisionCycleCoordinatorPort, RunCoordinatorPort, RunSessionPort
- noetrium_platform.research.experimentation.run.api.spec ?w^~)?t ExperimentRunSpec

### experimentation/run/control

- Package: noetrium_platform.research.experimentation.run.control
- Authority: run_control
- Owns: durable generic run lifecycle control authority and fenced control generations
- Must not own: operator product intents, server supervision internals or duplicate run manifest/checkpoint truth
- Requires: execution, execution/operation, experimentation/checkpoint, experimentation/run, experimentation/run/identity, experimentation/run/lifecycle, experimentation/run/manifest, platform
- Provides: run.control
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run__control

#### API modules

- noetrium_platform.research.experimentation.run.control.api ?w^~)?t RunControlAction, RunControlActionFailure, RunControlCheckpointBundlePort, RunControlCheckpointStorePort, RunControlConflict, RunControlError, RunControlEventReceipt, RunControlEvidencePort, RunControlIntegrityError, RunControlLedgerPort, RunControlLifecyclePort, RunControlNotFound, RunControlPhase, RunControlProjection, RunControlRecordKind, RunControlPort, RunControlReceipt, RunControlReceiptReference, RunControlReconciliationPort, RunControlRequest, RunControlStaleGeneration, RunControlTarget, RunControlTransitionOutcome, RunEvidenceValidity, RunExecutionOutcome, RunOutcomeProjection, RunScientificValidity, RunTaskOutcome
- noetrium_platform.research.experimentation.run.control.api.contracts ?w^~)?t RunControlAction, RunControlPhase, RunControlRecordKind, RunControlTarget, RunControlRequest, RunControlOperationIntent, RunControlPreparedOperation, RunControlEventReceipt, RunControlProjection, RunControlReceiptReference, RunControlReceipt, RunControlTransitionOutcome, RunControlPreparation, RunControlError, RunControlNotFound, RunControlConflict, RunControlStaleGeneration, RunControlIntegrityError, RunControlActionFailure, RunControlPort, RunControlLedgerPort, RunControlCheckpointBundlePort, RunControlCheckpointStorePort, RunControlLifecyclePort, RunControlReconciliationPort, RunControlEvidencePort

### experimentation/run/identity

- Package: noetrium_platform.research.experimentation.run.identity
- Authority: run_identity
- Owns: run identity, immutable manifest and parent links
- Must not own: live execution state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run__identity

#### API modules

- noetrium_platform.research.experimentation.run.identity.api ?w^~)?t RunIdentity, RunIdentityProvider
- noetrium_platform.research.experimentation.run.identity.api.contracts ?w^~)?t RunIdentity
- noetrium_platform.research.experimentation.run.identity.api.ports ?w^~)?t RunIdentityProvider

### experimentation/run/lifecycle

- Package: noetrium_platform.research.experimentation.run.lifecycle
- Authority: run_lifecycle
- Owns: run lifecycle state and transitions
- Must not own: runtime server lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run__lifecycle

#### API modules

- noetrium_platform.research.experimentation.run.lifecycle.api ?w^~)?t attach_cleanup_note, RunCleanupFailure, RunCleanupReport, RunClosed, RunRecoveryRequired, RunCycleExecutionPort, RunCycleExecutorPort, RunSessionFactoryPort, RunSessionPort
- noetrium_platform.research.experimentation.run.lifecycle.api.cleanup ?w^~)?t attach_cleanup_note
- noetrium_platform.research.experimentation.run.lifecycle.api.contracts ?w^~)?t RunCleanupFailure, RunCleanupReport, RunClosed, RunRecoveryRequired
- noetrium_platform.research.experimentation.run.lifecycle.api.ports ?w^~)?t RunCycleExecutionPort, RunCycleExecutorPort, RunSessionFactoryPort, RunSessionPort

### experimentation/run/manifest

- Package: noetrium_platform.research.experimentation.run.manifest
- Authority: run_manifest
- Owns: frozen run contract and exact dependencies
- Must not own: runtime mutable state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run__manifest

#### API modules

- noetrium_platform.research.experimentation.run.manifest.api ?w^~)?t CompositionPlanReference, DerivedEvidenceArtifact, EVIDENCE_BUNDLE_SCHEMA_VERSION, EvidenceBundleManifest, EvidenceBundlePublisherPort, EvidenceBundleReceipt, EvidenceBundleStatus, EvidenceStreamDescriptor, RunLaunchManifest, RunResearchSemanticsReference
- noetrium_platform.research.experimentation.run.manifest.api.contracts ?w^~)?t CompositionPlanReference, RunLaunchManifest, RunResearchSemanticsReference
- noetrium_platform.research.experimentation.run.manifest.api.evidence ?w^~)?t DerivedEvidenceArtifact, EVIDENCE_BUNDLE_SCHEMA_VERSION, EvidenceBundleManifest, EvidenceBundleReceipt, EvidenceBundleStatus, EvidenceStreamDescriptor
- noetrium_platform.research.experimentation.run.manifest.api.evidence_ports ?w^~)?t EvidenceBundlePublisherPort

### experimentation/study

- Package: noetrium_platform.research.experimentation.study
- Authority: study_state
- Owns: study definitions, hypotheses and study lifecycle
- Must not own: method implementation internals
- Requires: artifact
- Provides: study.definition
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__study

#### API modules

- noetrium_platform.research.experimentation.study.api ?w^~)?t TrialProviderPort, StudyResearchReadPort, StudyResearchReadSnapshot, TrialMatrixExecutionReport, TrialExecutionRequest, TrialExecutionReceipt, ReplayLevel, AnalysisDefinition, AnalysisResult, MeasurementCut, BenchmarkTaskSet, BenchmarkSourceKind, BenchmarkSourcePort, BenchmarkSourceResolution, BenchmarkSourceSpec, InMemoryBenchmarkSource, TaskDefinition, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, StudyIntervention, StudyFactorSpec, ResearchStudyDefinition, ResearchRevision, ParticipantSchedule, FactorSelection, FactorLevelSpec, StudyConcurrencyPolicy, MeasurementContentReference, MeasurementDefinition, MeasurementProtocol, MeasurementRecord, MeasurementValue, MeasurementValueKind, StudyAssignment, StudyExecutionUnit, StudyArtifactPublicationPort, StudyAssignmentPort, StudyMetricAggregate, StudyMatrixExecutionReport, StudyMetricAggregationPort, StudyMatrixExecutionPort, StudyMetricObservation, StudyProtocol, StudyVariantSpec, StudyUnitExecutionPort, StudyVariantExecutionPort, BoundStudyVariantExecutionPort, VariantKind, ExperimentPlan, VariantBinding, VariantExecutionProvider, VariantExecutionReceipt, VariantExecutionRequest, BoundStudyUnitExecutionPort
- noetrium_platform.research.experimentation.study.api.analysis ?w^~)?t AnalysisDefinition, AnalysisResult, DatasetVersionProjection, EvidenceManifestProjection, MeasurementCut
- noetrium_platform.research.experimentation.study.api.benchmark ?w^~)?t BenchmarkTaskSet, TaskDefinition, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, BenchmarkSourceKind, BenchmarkSourceSpec, BenchmarkSourceResolution, BenchmarkSourcePort, InMemoryBenchmarkSource
- noetrium_platform.research.experimentation.study.api.contracts ?w^~)?t StudyConcurrencyPolicy, StudyAssignment, StudyExecutionUnit, StudyMatrixExecutionReport, StudyMetricAggregate, StudyMetricObservation, StudyProtocol, StudyVariantSpec, VariantKind
- noetrium_platform.research.experimentation.study.api.design ?w^~)?t FactorLevelSpec, FactorSelection, ParticipantSchedule, ResearchRevision, ResearchStudyDefinition, StudyFactorSpec, StudyIntervention
- noetrium_platform.research.experimentation.study.api.measurement ?w^~)?t MeasurementContentReference, MeasurementDefinition, MeasurementProtocol, MeasurementRecord, MeasurementValue, MeasurementValueKind
- noetrium_platform.research.experimentation.study.api.plan ?w^~)?t ExperimentPlan, VariantBinding, VariantExecutionProvider, VariantExecutionReceipt, VariantExecutionRequest
- noetrium_platform.research.experimentation.study.api.ports ?w^~)?t StudyArtifactPublicationPort, StudyAssignmentPort, BoundStudyUnitExecutionPort, StudyMetricAggregationPort, StudyMatrixExecutionPort, StudyUnitExecutionPort, StudyVariantExecutionPort, BoundStudyVariantExecutionPort
- noetrium_platform.research.experimentation.study.api.research_read ?w^~)?t StudyResearchReadPort, StudyResearchReadSnapshot
- noetrium_platform.research.experimentation.study.api.trial ?w^~)?t TrialExecutionReceipt, TrialExecutionRequest, TrialMatrixExecutionReport, TrialProviderPort

### experimentation/variant

- Package: noetrium_platform.research.experimentation.variant
- Authority: variant_state
- Owns: experiment variants, assignments and comparison semantics
- Must not own: model deployment internals
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__variant

#### API modules

- noetrium_platform.research.experimentation.variant.api.boundary ?w^~)?t SystemLeafContract, contract

### experimentation/workbench

- Package: noetrium_platform.research.experimentation.workbench
- Authority: research_analysis_publication
- Owns: typed research analysis tables, deterministic statistics/evaluation workflow and report/figure publication semantics
- Must not own: experiment execution lifecycle, measurement truth, method semantics or vendor-specific scientific backends
- Requires: experimentation/study
- Provides: research.workbench
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__workbench

#### API modules

- noetrium_platform.research.experimentation.workbench.api ?w^~)?t AggregationFunction, AggregationSpec, BaselineRegistryPort, BaselineSpec, DataColumn, DataTable, EvaluationContext, EvaluationStage, FigureCategory, FigureCell, FigureKind, FigureOutputFormat, FigurePoint, FigureRendererPort, FigureSeries, FigureSpec, FigureStyle, GroupComparison, InferenceResult, MetricSummary, MissingValuePolicy, MultipleComparisonMethod, MultipleComparisonResult, PairedComparison, RenderedResearchPackage, ResearchEvaluation, ResearchFigureFactoryPort, ResearchLifecyclePort, ResearchReport, ResearchStatisticsPort, ResearchTablePipelinePort, ReportTableRendererPort, SplitStrategy, TableAnalysisPort, TableReaderPort, TableTransformPort, MeasurementRecordTableAdapter, StudyObservationTableAdapter
- noetrium_platform.research.experimentation.workbench.api.adapters ?w^~)?t MeasurementRecordTableAdapter, StudyObservationTableAdapter
- noetrium_platform.research.experimentation.workbench.api.contracts ?w^~)?t AggregationFunction, AggregationSpec, BaselineRegistryPort, BaselineSpec, DataColumn, DataTable, EvaluationContext, EvaluationStage, FigureCategory, FigureCell, FigureKind, FigureOutputFormat, FigurePoint, FigureRendererPort, FigureSeries, FigureSpec, FigureStyle, GroupComparison, InferenceResult, MetricSummary, MissingValuePolicy, MultipleComparisonMethod, MultipleComparisonResult, PairedComparison, RenderedResearchPackage, ResearchEvaluation, ResearchFigureFactoryPort, ResearchLifecyclePort, ResearchReport, ResearchStatisticsPort, ResearchTablePipelinePort, ReportTableRendererPort, SplitStrategy, TableAnalysisPort, TableReaderPort, TableTransformPort

### experimentation/workload

- Package: noetrium_platform.research.experimentation.workload
- Authority: experiment_workload_execution_contract
- Owns: generic experiment task-runner contracts, workload context, task handles/results and checkpointable workload execution semantics
- Must not own: experiment definition truth, environment provider internals, participant method semantics or run durability authority
- Requires: environment/runtime, experimentation/experiment, experimentation/run, participant/method, platform
- Provides: experiment.workload
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__workload

#### API modules

- noetrium_platform.research.experimentation.workload.api ?w^~)?t WorkloadActionAdapterPort, WorkloadBatchCloseError, WorkloadBatchResult, WorkloadBatchBindingPort, WorkloadBatchExecutorPort, WorkloadBoundaryPort, WorkloadCompletionPort, WorkloadCompletionReceipt, WorkloadDecision, WorkloadDiagnosticsPort, WorkloadExecutionCutObserverPort, WorkloadEnvironmentPort, WorkloadEvidencePort, WorkloadFailurePolicyPort, WorkloadPlannerPort, WorkloadStatePort, WorkloadTaskResult, WorkloadTaskRunnerPort, WorkloadTaskRunError
- noetrium_platform.research.experimentation.workload.api.contracts ?w^~)?t WorkloadBatchCloseError, WorkloadBatchResult, WorkloadCompletionReceipt, WorkloadDecision, WorkloadTaskResult, WorkloadTaskRunError
- noetrium_platform.research.experimentation.workload.api.ports ?w^~)?t WorkloadActionAdapterPort, WorkloadBatchBindingPort, WorkloadBatchExecutorPort, WorkloadBoundaryPort, WorkloadCompletionPort, WorkloadDiagnosticsPort, WorkloadExecutionCutObserverPort, WorkloadEnvironmentPort, WorkloadEvidencePort, WorkloadFailurePolicyPort, WorkloadPlannerPort, WorkloadStatePort, WorkloadTaskRunnerPort

### governance

- Package: noetrium_platform.foundation.governance
- Authority: governance_policy
- Owns: architecture, quality, release and system topology rules
- Must not own: domain execution
- Requires: platform
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance

#### API modules

- noetrium_platform.foundation.governance.api ?w^~)?t GovernanceBaselineApproval, GovernanceBaselineApprovalSet, GovernanceBaselineLane, governance_baseline_semantic_digest, RepositorySourceBlob, RepositorySourceFailure, RepositorySourceFailureKind, RepositorySourceIncompleteError, RepositorySourceIndexPort, RepositorySourcePort, RepositorySourceSnapshot, repository_source_scope_digest, repository_source_scope_text_digest
- noetrium_platform.foundation.governance.api.baseline_authority ?w^~)?t GovernanceBaselineApproval, GovernanceBaselineApprovalSet, GovernanceBaselineLane, governance_baseline_semantic_digest
- noetrium_platform.foundation.governance.api.repository_source ?w^~)?t RepositorySourceBlob, RepositorySourceFailure, RepositorySourceFailureKind, RepositorySourceIncompleteError, RepositorySourceIndexPort, RepositorySourcePort, RepositorySourceSnapshot, repository_source_scope_digest, repository_source_scope_text_digest

### governance/algorithm

- Package: noetrium_platform.foundation.governance.algorithm
- Authority: algorithm_governance
- Owns: repository-wide algorithm inventory, complexity baselines and regression gates
- Must not own: runtime execution or scientific result semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__algorithm

#### API modules

- noetrium_platform.foundation.governance.algorithm.api.contracts ?w^~)?t AlgorithmBaselineApproval, AlgorithmComplexityMigrationApproval, AlgorithmDiff, AlgorithmGovernanceApprovalSet, AlgorithmFinding, AlgorithmGateReport, AlgorithmLanguage, AlgorithmMetrics, AlgorithmPriority, AlgorithmSnapshot, AlgorithmSymbol, FileAnalysis, LanguageCoverage, SourceDocument, SymbolDelta
- noetrium_platform.foundation.governance.algorithm.api.ports ?w^~)?t AlgorithmSnapshotStorePort, FileAnalysisCachePort, LanguageAnalyzerPort, SourceInventoryPort

### governance/architecture

- Package: noetrium_platform.foundation.governance.architecture
- Authority: architecture_policy
- Owns: architecture rules, dependencies and invariants
- Must not own: business state
- Requires: scope
- Provides: architecture.audit
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__architecture

#### API modules

- noetrium_platform.foundation.governance.architecture.api ?w^~)?t AmbiguousCapabilityProvider, BindingDiagnostic, BindingDiagnosticCode, BindingDiagnosticReference, BindingDiagnosticReferenceKind, BindingDiagnosticSeverity, BindingEdge, BindingPlan, BindingProof, BindingRemediationCategory, BindingResolution, BindingResolutionState, BindingResolverPort, CapabilityBindingError, CapabilityCompositionPlannerPort, CapabilityDependencyCycle, CapabilityInterfaceMismatch, CapabilityKey, CapabilityOffer, CapabilityRequirement, CompositionContract, CompositionContractError, CompositionIdentity, CompositionSubject, CompositionSubjectKind, CompositionTopologyError, MissingCapabilityProvider, ProviderSelection, ProviderIngressContractError, ProviderIngressProtocol, ProviderIngressViolation, ProviderImplementationIdentity, ProviderIngressBoundary, ProviderQualificationIdentity, ProviderRevision, ProviderRevisionKind, provider_implementation_from_repository_source, RequirementAddress, RequirementCardinality, interface_contract_digest, SemanticBoundaryClaim, SemanticBoundaryClaimError, SemanticBoundaryClassification, SemanticBoundaryEvidence, SemanticStateAuthorityKind, validate_semantic_boundary_claim
- noetrium_platform.foundation.governance.architecture.api.capabilities ?w^~)?t EXCEPTION_DESCRIPTOR_V1, HOST_OPERATING_SYSTEM_ROUTE_V1, LOG_QUERY_V1, LOG_SINK_V1, LOGGING_SYSTEM_V1, METHOD_COMPOSITION_PORTS_V1, SERVER_CONNECTION_FACTORY_V1, SERVER_FILE_TRANSFER_FACTORY_V1
- noetrium_platform.foundation.governance.architecture.api.capability_composition ?w^~)?t AmbiguousCapabilityProvider, BindingDiagnostic, BindingDiagnosticCode, BindingDiagnosticReference, BindingDiagnosticReferenceKind, BindingDiagnosticSeverity, BindingEdge, BindingPlan, BindingProof, BindingRemediationCategory, BindingResolution, BindingResolutionState, BindingResolverPort, CapabilityBindingError, CapabilityCompositionPlannerPort, CapabilityDependencyCycle, CapabilityInterfaceMismatch, CapabilityKey, CapabilityOffer, CapabilityRequirement, CompositionContract, CompositionContractError, CompositionIdentity, CompositionSubject, CompositionSubjectKind, CompositionTopologyError, MissingCapabilityProvider, ProviderSelection, RequirementAddress, RequirementCardinality, interface_contract_digest
- noetrium_platform.foundation.governance.architecture.api.provider_ingress ?w^~)?t ProviderImplementationIdentity, ProviderIngressBoundary, ProviderIngressContractError, ProviderIngressProtocol, ProviderIngressViolation, ProviderQualificationIdentity, ProviderRevision, ProviderRevisionKind, provider_implementation_from_repository_source
- noetrium_platform.foundation.governance.architecture.api.semantic_boundary ?w^~)?t SemanticBoundaryClaim, SemanticBoundaryClaimError, SemanticBoundaryClassification, SemanticBoundaryEvidence, SemanticStateAuthorityKind, validate_semantic_boundary_claim

### governance/concurrency

- Package: noetrium_platform.foundation.governance.concurrency
- Authority: concurrency_governance
- Owns: repository-wide concurrency topology findings, reviewed debt baselines and concurrency regression gates
- Must not own: runtime task scheduling or mutable execution state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__concurrency

#### API modules

- noetrium_platform.foundation.governance.concurrency.api.contracts ?w^~)?t ConcurrencyLanguage, ConcurrencyPriority, ConcurrencyFinding, ConcurrencyMetrics, ConcurrencyHotspot, ConcurrencyCoverage, ConcurrencySnapshot, ConcurrencyDocument, ConcurrencyFileAnalysis, ConcurrencyBaseline, ConcurrencyGateReport
- noetrium_platform.foundation.governance.concurrency.api.ports ?w^~)?t ConcurrencyBaseline, ConcurrencyDocument, ConcurrencyFileAnalysis, ConcurrencyLanguage, ConcurrencySnapshot, ConcurrencySourceInventoryPort, ConcurrencyLanguageAnalyzerPort, ConcurrencySnapshotStorePort

### governance/gate

- Package: noetrium_platform.foundation.governance.gate
- Authority: gate_policy
- Owns: recursive gate contracts and composition semantics
- Must not own: business state, runtime execution or scientific acceptance
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__gate

#### API modules

- noetrium_platform.foundation.governance.gate.api ?w^~)?t GateCompositionPort, GateFinding, GatePort, GateReport, GateRequest, GateSeverity
- noetrium_platform.foundation.governance.gate.api.contracts ?w^~)?t GateFinding, GateReport, GateRequest, GateSeverity
- noetrium_platform.foundation.governance.gate.api.ports ?w^~)?t GateCompositionPort, GatePort

### governance/performance

- Package: noetrium_platform.foundation.governance.performance
- Authority: performance_governance
- Owns: repository-wide performance hotspots, reviewed debt baselines and performance regression gates
- Must not own: runtime resource scheduling or business execution
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__performance

#### API modules

- noetrium_platform.foundation.governance.performance.api.contracts ?w^~)?t PerformanceLanguage, PerformancePriority, PerformanceFinding, PerformanceMetrics, PerformanceHotspot, PerformanceCoverage, PerformanceSnapshot, PerformanceBaseline, PerformanceGateReport, PerformanceDocument, PerformanceFileAnalysis
- noetrium_platform.foundation.governance.performance.api.ports ?w^~)?t PerformanceBaseline, PerformanceDocument, PerformanceFileAnalysis, PerformanceLanguage, PerformanceSnapshot, PerformanceSourceInventoryPort, PerformanceLanguageAnalyzerPort, PerformanceSnapshotStorePort

### governance/quality

- Package: noetrium_platform.foundation.governance.quality
- Authority: quality_policy
- Owns: quality gates, audits and invariants as descriptive policy
- Must not own: runtime business control
- Requires: none
- Provides: quality.audit
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__quality

#### API modules

- noetrium_platform.foundation.governance.quality.api ?w^~)?t BANNED_RUNTIME_IDENTIFIERS, DegradationFinding, FORBIDDEN_ENABLED_CONFIG_KEYS, FORBIDDEN_NONEMPTY_CONFIG_KEYS, SilentFailureFinding
- noetrium_platform.foundation.governance.quality.api.contracts ?w^~)?t BANNED_RUNTIME_IDENTIFIERS, DegradationFinding, FORBIDDEN_ENABLED_CONFIG_KEYS, FORBIDDEN_NONEMPTY_CONFIG_KEYS, SilentFailureFinding

### governance/release

- Package: noetrium_platform.foundation.governance.release
- Authority: release_authority
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

### governance/repository_boundary

- Package: noetrium_platform.foundation.governance.repository_boundary
- Authority: upstream_repository_boundary
- Owns: enforce reusable upstream repository/package/release boundary
- Must not own: downstream project scientific or deployment policy
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__repository_boundary

#### API modules

- noetrium_platform.foundation.governance.repository_boundary.api ?w^~)?t DownstreamImportKind, DownstreamImportObservation, DownstreamProjectImportReport, RepositoryBoundaryReport, RepositoryBoundaryViolation, RepositoryBoundaryAuditor
- noetrium_platform.foundation.governance.repository_boundary.api.contracts ?w^~)?t DownstreamImportKind, DownstreamImportObservation, DownstreamProjectImportReport, RepositoryBoundaryReport, RepositoryBoundaryViolation, RepositoryBoundaryAuditor

### governance/schema

- Package: noetrium_platform.foundation.governance.schema
- Authority: schema_authority
- Owns: schema/version declarations for contracts and records
- Must not own: domain state mutation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__schema

#### API modules

- noetrium_platform.foundation.governance.schema.api.boundary ?w^~)?t SystemLeafContract, contract

### governance/security

- Package: noetrium_platform.foundation.governance.security
- Authority: security_policy
- Owns: security/redaction/classification policy
- Must not own: scientific method semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__security

#### API modules

- noetrium_platform.foundation.governance.security.api.boundary ?w^~)?t SystemLeafContract, contract

### governance/system_registry

- Package: noetrium_platform.foundation.governance.system_registry
- Authority: system_topology
- Owns: recursive system topology and ownership declarations
- Must not own: runtime orchestration
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__system_registry

#### API modules

- noetrium_platform.foundation.governance.system_registry.api ?w^~)?t AuthorityDescriptor, DownstreamSurfaceMode, SYSTEM_CATALOG, SystemDescriptor, SystemIdentity, SystemLayer, SystemRegistryChange, SystemRegistryObserver, SystemRegistryPort, TopologySourceAudit, audit_system_topology_source, system_catalog
- noetrium_platform.foundation.governance.system_registry.api.contracts ?w^~)?t AuthorityDescriptor, DownstreamSurfaceMode, STANDARD_SYSTEM_SHAPE, SystemDescriptor, SystemIdentity, SystemRegistryChange, SystemLayer
- noetrium_platform.foundation.governance.system_registry.api.ports ?w^~)?t SystemRegistryObserver, SystemRegistryPort
- noetrium_platform.foundation.governance.system_registry.api.topology ?w^~)?t SYSTEM_CATALOG, TopologySourceAudit, audit_system_topology_source, system_catalog

### governance/evolution

- Package: noetrium_platform.foundation.governance.evolution
- Authority: system_evolution
- Owns: topology-driven discovery, drift detection and improvement proposals
- Must not own: domain state, external effects and direct runtime mutation
- Requires: governance/system_registry, observability
- Provides: governance.evolution
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__evolution

#### API modules

- noetrium_platform.foundation.governance.evolution.api ?w^~)?t DiscoveryReport, DriftKind, EvolutionAssessment, EvolutionProposal, EvolutionStage, EvolutionStateStorePort, EvolutionTransition, ImprovementSignal, ObservationOutcome, SignalKind, SystemEvolutionPort, TopologyDrift, TopologyObservation
- noetrium_platform.foundation.governance.evolution.api.contracts ?w^~)?t DiscoveryReport, DriftKind, EvolutionAssessment, EvolutionProposal, EvolutionStage, EvolutionTransition, ImprovementSignal, ObservationOutcome, SignalKind, TopologyDrift, TopologyObservation
- noetrium_platform.foundation.governance.evolution.api.ports ?w^~)?t EvolutionStateStorePort, SystemEvolutionPort

### model

- Package: noetrium_platform.capabilities.model
- Authority: model_identity
- Owns: model assets, stacks, assignments, deployments and serving identity
- Must not own: process lifecycle implementation and experiment semantics
- Requires: environment, platform, resource, runtime, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model

#### API modules

- noetrium_platform.capabilities.model.api ?w^~)?t EmbeddingInput, MultimodalMethodSpec, MultimodalPart, MultimodalRequest, MultimodalRequestCodecPort, MultimodalResponse, EmbeddingOutput, EmbeddingVector, ModelCapabilityInput, ModelCapabilityInvocation, ModelCapabilityOutput, ModelCapabilityResponse, NamedScalar, ProjectModelStreamingCapabilityProviderPort, ProjectModelStreamingCapabilityClientPort, ModelCapabilityStreamTerminal, ModelCapabilityStreamSession, ModelCapabilityStreamDisposition, ModelCapabilityStreamChunk, PolicyActionProbability, PolicyInferenceInput, PolicyInferenceOutput, RankedCandidate, RankingCandidate, RankingInput, RankingOutput, ProjectModelCapabilityClientPort, ProjectModelCapabilityProviderPort, ScoredCandidate, ScoringCandidate, ScoringInput, ScoringOutput, StructuredGenerationOutput, StructuredGenerationInput, StructuredGenerationDecoderPort, ValueInferenceInput, ValueInferenceOutput, ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateProposal, ModelUpdateSource, PreparedModelRevision, ModelAuthorities, ModelBindingDiagnostic, ModelBindingDiagnosticCode, ModelBindingDiagnosticSeverity, ModelCapabilityRequirement, ModelProjectBindingError, ModelProjectDefinition, MultimodalInferenceOutput, MultimodalInferenceInput, MultimodalContent, ModelRequirementContribution, ModelProviderProfile, ProjectModelBinding, ProjectModelClientPort, ProjectModelProviderPort, ProjectModelRequest, ProjectModelResponse
- noetrium_platform.capabilities.model.api.authorities ?w^~)?t ModelAuthorities
- noetrium_platform.capabilities.model.api.capability ?w^~)?t EmbeddingInput, EmbeddingOutput, EmbeddingVector, ModelCapabilityInput, ModelCapabilityInvocation, ModelCapabilityOutput, ModelCapabilityResponse, NamedScalar, ProjectModelStreamingCapabilityProviderPort, ProjectModelStreamingCapabilityClientPort, ModelCapabilityStreamTerminal, ModelCapabilityStreamSession, ModelCapabilityStreamDisposition, ModelCapabilityStreamChunk, PolicyActionProbability, PolicyInferenceInput, PolicyInferenceOutput, RankedCandidate, RankingCandidate, RankingInput, RankingOutput, ProjectModelCapabilityClientPort, ProjectModelCapabilityProviderPort, ScoredCandidate, ScoringCandidate, ScoringInput, ScoringOutput, StructuredGenerationOutput, StructuredGenerationDecoderPort, ValueInferenceInput, ValueInferenceOutput
- noetrium_platform.capabilities.model.api.multimodal ?w^~)?t MultimodalMethodSpec, MultimodalPart, MultimodalRequest, MultimodalRequestCodecPort, MultimodalResponse
- noetrium_platform.capabilities.model.api.project ?w^~)?t ModelBindingDiagnostic, ModelBindingDiagnosticCode, ModelBindingDiagnosticSeverity, ModelCapabilityRequirement, ModelProjectBindingError, ModelProjectDefinition, MultimodalInferenceOutput, MultimodalInferenceInput, MultimodalContent, ModelRequirementContribution, ModelProviderProfile, ProjectModelBinding, ProjectModelClientPort, ProjectModelProviderPort, ProjectModelRequest, ProjectModelResponse, StructuredGenerationInput

### model/asset

- Package: noetrium_platform.capabilities.model.asset
- Authority: model_asset
- Owns: immutable model asset identity and provenance
- Must not own: artifact byte storage
- Requires: none
- Provides: model.asset, model.asset-acquisition
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__asset

#### API modules

- noetrium_platform.capabilities.model.asset.api.contracts ?w^~)?t ManagedModelAsset, ModelAcquisitionReceipt, ModelAssetMode, ModelAssetOrigin, ModelAssetStats, ModelAssetUsage, ModelConfigSummary, ModelSourceSpec, ModelStoragePoolStatus
- noetrium_platform.capabilities.model.asset.api.ports ?w^~)?t ModelAssetLookupPort, ModelAssetManagementPort, ModelAssetStoragePort, ModelAssetUsagePort, ModelSourceBackend

### model/assignment

- Package: noetrium_platform.capabilities.model.assignment
- Authority: model_assignment
- Owns: assign models to scope/run/participant roles
- Must not own: serving process lifecycle
- Requires: none
- Provides: model.assignment
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__assignment

#### API modules

- noetrium_platform.capabilities.model.assignment.api.contracts ?w^~)?t ModelAssignment, ResolvedModelAssignment
- noetrium_platform.capabilities.model.assignment.api.ports ?w^~)?t ModelAssignmentPort

### model/catalog

- Package: noetrium_platform.capabilities.model.catalog
- Authority: model_catalog
- Owns: model families/revisions catalog and metadata
- Must not own: live deployment state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__catalog

### model/catalog/family

- Package: noetrium_platform.capabilities.model.catalog.family
- Authority: model_family
- Owns: model family identity and metadata
- Must not own: revision deployment state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__catalog__family

#### API modules

- noetrium_platform.capabilities.model.catalog.family.api.boundary ?w^~)?t SystemLeafContract, contract

### model/catalog/revision

- Package: noetrium_platform.capabilities.model.catalog.revision
- Authority: model_revision
- Owns: versioned model revision identity
- Must not own: mutable serving state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__catalog__revision

#### API modules

- noetrium_platform.capabilities.model.catalog.revision.api ?w^~)?t CONTRACT, contract, ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateProposal, PreparedModelRevision, ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateSource
- noetrium_platform.capabilities.model.catalog.revision.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.capabilities.model.catalog.revision.api.contracts ?w^~)?t ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateProposal, PreparedModelRevision
- noetrium_platform.capabilities.model.catalog.revision.api.update ?w^~)?t ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateSource

### model/deployment

- Package: noetrium_platform.capabilities.model.deployment
- Authority: model_deployment
- Owns: deployment identity, exact closure and lifecycle contract
- Must not own: server process implementation
- Requires: none
- Provides: model.deployment, model.deployment-control
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__deployment

#### API modules

- noetrium_platform.capabilities.model.deployment.api.contracts ?w^~)?t ModelControlSnapshot, ModelControllerPhase, ModelControllerState, ModelDeploymentLogs, ModelDeploymentSelector, ModelDeploymentSpec, ModelDeploymentStatus, ModelDesiredState, ModelEnvironmentUsage, ModelGpuAllocation, ModelGpuConflict, ModelGpuProcessBinding, ModelLogTail, ModelReconcileCycle, ModelRuntimeState
- noetrium_platform.capabilities.model.deployment.api.ports ?w^~)?t ModelControllerStatePort, ModelControllerStopPort, ModelDeploymentCatalogPort, ModelDeploymentLogPort, ModelDeploymentRuntimePort, ModelFleetRuntimePort, ModelReconcileControllerPort, ModelResourceViewPort, ModelServiceRuntimeFactoryPort

### model/deployment/closure

- Package: noetrium_platform.capabilities.model.deployment.closure
- Authority: deployment_closure
- Owns: exact deployment closure across model, stack, runtime and artifact identities
- Must not own: server runtime health
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__deployment__closure

#### API modules

- noetrium_platform.capabilities.model.deployment.closure.api.boundary ?w^~)?t SystemLeafContract, contract

### model/qualification

- Package: noetrium_platform.capabilities.model.qualification
- Authority: model_qualification
- Owns: model/runtime/host qualification evidence and compatibility claims
- Must not own: live capacity snapshots
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__qualification

#### API modules

- noetrium_platform.capabilities.model.qualification.api.qualification ?w^~)?t BackendCandidatePlan, CandidateDecision, DeploymentQualificationApplicationPort, DeploymentQualificationApplicationReceipt, DeploymentQualificationApplicationRequest, DeploymentQualificationApplicationStorePort, DeploymentQualificationRuntimePort, DeploymentQualificationRuntimeReceipt, DeploymentQualificationRuntimeRequest, DeploymentQualificationRuntimeStorePort, CudaFacts, DEFAULT_DEPLOYMENT_PROBE_TIMEOUT_SECONDS, DEFAULT_PACKAGE_INDEX_URL, native_cuda_runtime_package_names, DeploymentCapabilityFacts, DeploymentCapabilityProbePort, DeploymentQualificationPlan, DeploymentQualificationEvidenceRecord, DeploymentQualificationEvidenceStorePort, DeploymentQualificationPort, DeploymentQualificationRequest, GpuCapabilityFacts, GpuFabricFacts, HostExecutionFacts, InstallPackage, ModelArtifactFacts, OperatingSystemFacts, PackageArtifactFacts, PackageDependencyNodeFacts, PackageIndexFacts, PythonRuntimeFacts, StorageCapabilityFacts, QualificationCommandReceipt, QualificationMaterializationStatus, QualificationPackageInstallerPort, DeploymentRuntimeQualificationStatus, QualificationRuntimeProbePort, RuntimeCheckReceipt

### model/request

- Package: noetrium_platform.capabilities.model.request
- Authority: model_request
- Owns: model request identity, exact input contract and response envelope
- Must not own: business result semantics
- Requires: none
- Provides: model.request
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__request

#### API modules

- noetrium_platform.capabilities.model.request.api ?w^~)?t ExecutionContext, ImmutableModelIdentity, ContentAddressedStorePort, ContentRef, ModelRequestEnvelope, ModelRequestLedgerPort, ModelRequestRecorderPort, ReconstructedModelRequest
- noetrium_platform.capabilities.model.request.api.contracts ?w^~)?t ContentAddressedStorePort, ContentRef, ModelRequestEnvelope, ModelRequestLedgerPort, ModelRequestRecorderPort, ReconstructedModelRequest

### model/request/input

- Package: noetrium_platform.capabilities.model.request.input
- Authority: request_input
- Owns: exact request input identity and canonicalization
- Must not own: serving process lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__request__input

#### API modules

- noetrium_platform.capabilities.model.request.input.api.boundary ?w^~)?t SystemLeafContract, contract

### model/request/output

- Package: noetrium_platform.capabilities.model.request.output
- Authority: request_output
- Owns: response envelope and response artifact references
- Must not own: business metric semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__request__output

#### API modules

- noetrium_platform.capabilities.model.request.output.api.boundary ?w^~)?t SystemLeafContract, contract

### model/request/prompt

- Package: noetrium_platform.capabilities.model.request.prompt
- Authority: model_prompt_compilation
- Owns: model-request prompt blocks, deterministic compilation and prompt publication contracts
- Must not own: model serving, inference transport or participant cognition state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__request__prompt

#### API modules

- noetrium_platform.capabilities.model.request.prompt.api ?w^~)?t ActivePromptEvidenceReadPort, ActivePromptVerificationEvidence, PromptVerificationIntegrityError, PromptTraceDescriptor, PromptTraceObserverFailure, PromptTraceObserverFailureSink, PromptTraceObserverPort, PromptTracePoint, PromptTraceStage, PromptTraceSummary, PromptBoundRequest, PromptBodyContext, PromptDynamicBlock, PromptRequestBindingPort, PromptRequestBodyBuilder, PromptSelectionIdentity, PromptSelectionPort
- noetrium_platform.capabilities.model.request.prompt.api.request ?w^~)?t PromptBoundRequest, PromptBodyContext, PromptDynamicBlock, PromptRequestBindingPort, PromptRequestBodyBuilder
- noetrium_platform.capabilities.model.request.prompt.api.selection ?w^~)?t PromptSelectionIdentity, PromptSelectionPort
- noetrium_platform.capabilities.model.request.prompt.api.trace ?w^~)?t PromptTraceDescriptor, PromptTraceObserverFailure, PromptTraceObserverFailureSink, PromptTraceObserverPort, PromptTracePoint, PromptTraceStage, PromptTraceSummary
- noetrium_platform.capabilities.model.request.prompt.api.verification ?w^~)?t ActivePromptEvidenceReadPort, ActivePromptVerificationEvidence, PromptVerificationIntegrityError

### model/serving

- Package: noetrium_platform.capabilities.model.serving
- Authority: model_serving
- Owns: serving endpoint contract and request routing semantics
- Must not own: model catalog metadata
- Requires: none
- Provides: model.serving, model.qualification
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__serving

#### API modules

- noetrium_platform.capabilities.model.serving.api ?w^~)?t CPUInventory, CPUNode, DeploymentPlacement, GpuPlacementPolicyPort, DurableRecoveryAttempt, DurableRecoveryObserverFailureSink, DurableRecoveryObserverPort, DurableRecoveryPhase, DurableRecoveryStorePort, FrozenDeploymentIdentity, FrozenDeploymentSet, FrozenRoleAssignment, GPUFabricLink, GPUInventory, HostInventory, HostInventoryEvidenceStorePort, HostInventoryProvider, HostInventoryReceipt, HostLimits, HostResourceDelta, MemoryInventory, ModelAdmissionClosed, ModelAdmissionLeasePort, ModelAdmissionPort, ModelAdmissionRegistryPort, ModelAdmissionTimeout, ModelPhase, ModelRunState, ModelSupervisorStateStorePort, MountInventory, PerformanceSample, QualificationCertificate, QualificationDecision, QualificationEvidence, QualificationPolicy, ResourceQualificationMeasurements, QualifiedDeploymentManifest, RecoveryObserverFailure, RecoveryPlan, RecoveryResumeDecision, RecoveryStep, ResourceEnvelope, RoleCanaryResult, RoleModelAssignment, RoleModelManifest, RuntimeCanaryContract, RuntimeCanaryEvidence, RuntimeCanaryEvidenceStorePort, RuntimeCanaryProbe, RuntimeInventory, RuntimeQualificationEvidenceStorePort, RuntimeQualificationPublication, RuntimeQualificationPublisherPort, RuntimeQualificationReceipt, ServiceHeartbeat, begin_recovery_step, build_host_inventory_receipt, build_runtime_qualification_receipt, compare_host_inventory_receipts, complete_recovery_step, decide_resume, evaluate_qualification, evaluate_runtime_canary_contract, fail_recovery_step, new_recovery_attempt, recovery_plan_digest, succeed_recovery
- noetrium_platform.capabilities.model.serving.api.admission ?w^~)?t ModelAdmissionClosed, ModelAdmissionLeasePort, ModelAdmissionPort, ModelAdmissionRegistryPort, ModelAdmissionTimeout
- noetrium_platform.capabilities.model.serving.api.deployment ?w^~)?t FrozenDeploymentIdentity, FrozenDeploymentSet, FrozenRoleAssignment, RuntimeQualificationPublication, RuntimeQualificationPublisherPort
- noetrium_platform.capabilities.model.serving.api.heartbeat ?w^~)?t ServiceHeartbeat
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

### model/serving/endpoint

- Package: noetrium_platform.capabilities.model.serving.endpoint
- Authority: serving_endpoint
- Owns: serving endpoint identity and exposure contract
- Must not own: request result truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__serving__endpoint

#### API modules

- noetrium_platform.capabilities.model.serving.endpoint.api ?w^~)?t AsyncJsonHttpTransportPort, JsonHttpResponse, ModelEndpointError, ModelEndpointObserverPort, ModelEndpointFactoryPort, ModelEndpointPort, ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute, QualifiedModelClosurePublication, QualifiedModelClosurePublicationReceipt, QualifiedModelEndpointBinding, QualifiedModelEndpointBindingPort
- noetrium_platform.capabilities.model.serving.endpoint.api.contracts ?w^~)?t JsonHttpResponse, ModelEndpointError, ModelEndpointObserverPort, ModelEndpointRequest, ModelEndpointResponse, ModelEndpointRoute
- noetrium_platform.capabilities.model.serving.endpoint.api.ports ?w^~)?t AsyncJsonHttpTransportPort, ModelEndpointFactoryPort, ModelEndpointPort
- noetrium_platform.capabilities.model.serving.endpoint.api.publication ?w^~)?t QualifiedModelClosurePublication, QualifiedModelClosurePublicationReceipt
- noetrium_platform.capabilities.model.serving.endpoint.api.qualification ?w^~)?t QualifiedModelEndpointBinding, QualifiedModelEndpointBindingPort

### model/stack

- Package: noetrium_platform.capabilities.model.stack
- Authority: model_stack
- Owns: model stack composition and runtime build identity
- Must not own: server health
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__stack

#### API modules

- noetrium_platform.capabilities.model.stack.api ?w^~)?t ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
- noetrium_platform.capabilities.model.stack.api.stack ?w^~)?t ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity

### observability

- Package: noetrium_platform.evidence.observability
- Authority: observability
- Owns: logs, telemetry, traces, status and observation projections
- Must not own: durable state/failure authority
- Requires: data, governance, platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability

#### API modules

- noetrium_platform.evidence.observability.api ?w^~)?t ContextMetricSink, ContextRawObservationSink, EventDeliveryError, EventDeliveryFailure, EventEnvelope, EventSink, FanoutEventSink, OperationAuxiliaryFailureEventSink, OperationLifecycleObserver
- noetrium_platform.evidence.observability.api.auxiliary_events ?w^~)?t OperationAuxiliaryFailureEventSink
- noetrium_platform.evidence.observability.api.events ?w^~)?t EventEnvelope, EventSink
- noetrium_platform.evidence.observability.api.fanout ?w^~)?t EventDeliveryError, EventDeliveryFailure, FanoutEventSink
- noetrium_platform.evidence.observability.api.metrics ?w^~)?t ExecutionContext, ContextMetricSink
- noetrium_platform.evidence.observability.api.operation_events ?w^~)?t EMITTED_EVENT_TYPES, OperationLifecycleObserver
- noetrium_platform.evidence.observability.api.raw ?w^~)?t ContextRawObservationSink

### observability/capture

- Package: noetrium_platform.evidence.observability.capture
- Authority: capture_observation
- Owns: raw byte/event/process capture contracts
- Must not own: semantic log interpretation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__capture

#### API modules

- noetrium_platform.evidence.observability.capture.api ?w^~)?t RawCaptureHealth, RawObservationCorruptionError, RawObservationEnvelope, RawObservationReceipt, RawObservationSchema, RetentionClass, RawObservationPersistencePort, RawObservationSinkPort
- noetrium_platform.evidence.observability.capture.api.contracts ?w^~)?t SystemIdentity, ExecutionContext, JsonObject, JsonValue, freeze_json, RetentionClass, RawObservationSchema, RawObservationReceipt, RawObservationEnvelope, RawCaptureHealth, RawObservationCorruptionError
- noetrium_platform.evidence.observability.capture.api.ports ?w^~)?t RawObservationPersistencePort, RawObservationSinkPort

### observability/diagnostic

- Package: noetrium_platform.evidence.observability.diagnostic
- Authority: diagnostic_view_contract
- Owns: operator-facing diagnostic correlation contracts
- Must not own: failure/state authority
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__diagnostic

### observability/diagnostic/correlation

- Package: noetrium_platform.evidence.observability.diagnostic.correlation
- Authority: diagnostic_correlation
- Owns: cross-system correlation graph for diagnostic references
- Must not own: causal authority
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__diagnostic__correlation

#### API modules

- noetrium_platform.evidence.observability.diagnostic.correlation.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/diagnostic/query

- Package: noetrium_platform.evidence.observability.diagnostic.query
- Authority: diagnostic_query
- Owns: operator/debug query language over observation sources
- Must not own: source mutation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__diagnostic__query

#### API modules

- noetrium_platform.evidence.observability.diagnostic.query.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/diagnostic/snapshot

- Package: noetrium_platform.evidence.observability.diagnostic.snapshot
- Authority: diagnostic_snapshot
- Owns: portable diagnostic snapshots assembled from existing authorities
- Must not own: new business truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__diagnostic__snapshot

#### API modules

- noetrium_platform.evidence.observability.diagnostic.snapshot.api ?w^~)?t AdmissionPressureDiagnostic, ExecutionCapacityDiagnosticSnapshot, GroupExecutionDiagnostic, SerialMailboxDiagnostic
- noetrium_platform.evidence.observability.diagnostic.snapshot.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.evidence.observability.diagnostic.snapshot.api.contracts ?w^~)?t AdmissionPressureDiagnostic, ExecutionCapacityDiagnosticSnapshot, GroupExecutionDiagnostic, SerialMailboxDiagnostic

### observability/logging

- Package: noetrium_platform.evidence.observability.logging
- Authority: log_observation
- Owns: structured logs, context, sinks, stores, queries, retention and capture
- Must not own: failure taxonomy and recovery
- Requires: none
- Provides: logging.observation
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging

### observability/logging/capture

- Package: noetrium_platform.evidence.observability.logging.capture
- Authority: raw_capture
- Owns: raw process/stream/event capture before semantic logging
- Must not own: semantic event taxonomy
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__capture

#### API modules

- noetrium_platform.evidence.observability.logging.capture.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/logging/context

- Package: noetrium_platform.evidence.observability.logging.context
- Authority: log_context
- Owns: diagnostic context construction and propagation metadata
- Must not own: log record persistence and query
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__context

#### API modules

- noetrium_platform.evidence.observability.logging.context.api ?w^~)?t DiagnosticAddress
- noetrium_platform.evidence.observability.logging.context.api.contracts ?w^~)?t DiagnosticAddress

### observability/logging/projection

- Package: noetrium_platform.evidence.observability.logging.projection
- Authority: log_projection
- Owns: derived log indexes and projections
- Must not own: source log truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__projection

#### API modules

- noetrium_platform.evidence.observability.logging.projection.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/logging/query

- Package: noetrium_platform.evidence.observability.logging.query
- Authority: log_query
- Owns: log query contracts and filtering
- Must not own: log writes
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__query

#### API modules

- noetrium_platform.evidence.observability.logging.query.api ?w^~)?t LogQueryPort
- noetrium_platform.evidence.observability.logging.query.api.ports ?w^~)?t LogQueryPort

### observability/logging/record

- Package: noetrium_platform.evidence.observability.logging.record
- Authority: log_record_schema
- Owns: structured log schema, normalization and identity
- Must not own: sink routing and storage
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__record

#### API modules

- noetrium_platform.evidence.observability.logging.record.api ?w^~)?t ExceptionDescriptorPort, LoggingSystemBinding, LogBatch, LogLevel, LogRecord, LogWriterPort, LoggingSystemPort, ObservationBindingPort, ObservationFactoryPort
- noetrium_platform.evidence.observability.logging.record.api.binding ?w^~)?t LoggingSystemBinding
- noetrium_platform.evidence.observability.logging.record.api.contracts ?w^~)?t LogBatch, LogLevel, LogRecord
- noetrium_platform.evidence.observability.logging.record.api.ports ?w^~)?t ExceptionDescriptorPort, LogWriterPort, LoggingSystemPort

### observability/logging/retention

- Package: noetrium_platform.evidence.observability.logging.retention
- Authority: log_retention
- Owns: retention, archival and deletion policy for logs
- Must not own: failure retention and artifact retention
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__retention

#### API modules

- noetrium_platform.evidence.observability.logging.retention.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/logging/routing

- Package: noetrium_platform.evidence.observability.logging.routing
- Authority: log_routing
- Owns: log routing rules and fan-out decisions
- Must not own: log storage mutation
- Requires: none
- Provides: logging.routing
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__routing

#### API modules

- noetrium_platform.evidence.observability.logging.routing.api ?w^~)?t LogRoutingPort
- noetrium_platform.evidence.observability.logging.routing.api.ports ?w^~)?t LogRoutingPort

### observability/logging/sink

- Package: noetrium_platform.evidence.observability.logging.sink
- Authority: log_sink_delivery
- Owns: sink contracts and delivery lifecycle
- Must not own: query/index semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__sink

#### API modules

- noetrium_platform.evidence.observability.logging.sink.api ?w^~)?t LogSinkPort
- noetrium_platform.evidence.observability.logging.sink.api.ports ?w^~)?t LogSinkPort

### observability/logging/storage

- Package: noetrium_platform.evidence.observability.logging.storage
- Authority: log_storage
- Owns: durable or volatile log storage backends
- Must not own: log schema policy
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__logging__storage

#### API modules

- noetrium_platform.evidence.observability.logging.storage.api ?w^~)?t LogStorageWriteActorPort
- noetrium_platform.evidence.observability.logging.storage.api.ports ?w^~)?t LogStorageWriteActorPort

### observability/projection

- Package: noetrium_platform.evidence.observability.projection
- Authority: observation_projection
- Owns: observation projections/indexes and read models
- Must not own: source-of-truth mutation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__projection

#### API modules

- noetrium_platform.evidence.observability.projection.api ?w^~)?t ExecutionAdmissionScopeFact, ExecutionCapacityFacts, ExecutionGroupFact, SerialMailboxFact
- noetrium_platform.evidence.observability.projection.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.evidence.observability.projection.api.execution_capacity ?w^~)?t ExecutionAdmissionScopeFact, ExecutionCapacityFacts, ExecutionGroupFact, SerialMailboxFact

### observability/status

- Package: noetrium_platform.evidence.observability.status
- Authority: status_observation
- Owns: health/status observations and status projections
- Must not own: authoritative lifecycle state
- Requires: none
- Provides: status.read-model
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__status

#### API modules

- noetrium_platform.evidence.observability.status.api ?w^~)?t HealthState, PlatformStatus, SubsystemSnapshot, SubsystemStatusProbePort, StatusEvent, StatusEventReaderPort, StatusEventSinkPort
- noetrium_platform.evidence.observability.status.api.contracts ?w^~)?t HealthState, PlatformStatus, SubsystemSnapshot
- noetrium_platform.evidence.observability.status.api.events ?w^~)?t StatusEvent, StatusEventReaderPort, StatusEventSinkPort
- noetrium_platform.evidence.observability.status.api.ports ?w^~)?t SubsystemStatusProbePort

### observability/status/health

- Package: noetrium_platform.evidence.observability.status.health
- Authority: health_observation
- Owns: health observations and health snapshots
- Must not own: authoritative lifecycle transitions
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__status__health

#### API modules

- noetrium_platform.evidence.observability.status.health.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/status/lifecycle_view

- Package: noetrium_platform.evidence.observability.status.lifecycle_view
- Authority: lifecycle_projection
- Owns: read-only lifecycle status views
- Must not own: lifecycle state authority
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__status__lifecycle_view

#### API modules

- noetrium_platform.evidence.observability.status.lifecycle_view.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/telemetry

- Package: noetrium_platform.evidence.observability.telemetry
- Authority: telemetry_observation
- Owns: metrics/events/counters and telemetry routing
- Must not own: durable domain state
- Requires: none
- Provides: telemetry.metrics
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__telemetry

### observability/telemetry/event

- Package: noetrium_platform.evidence.observability.telemetry.event
- Authority: telemetry_event
- Owns: structured telemetry event definitions and emission contracts
- Must not own: durable facts
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__telemetry__event

#### API modules

- noetrium_platform.evidence.observability.telemetry.event.api ?w^~)?t EventDefinition, RuntimeStage
- noetrium_platform.evidence.observability.telemetry.event.api.contracts ?w^~)?t EventDefinition, RuntimeStage

### observability/telemetry/metric

- Package: noetrium_platform.evidence.observability.telemetry.metric
- Authority: telemetry_metric
- Owns: metric definitions, aggregation and metric identity
- Must not own: business result truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__telemetry__metric

#### API modules

- noetrium_platform.evidence.observability.telemetry.metric.api ?w^~)?t ContextualMetricRow, MetricDefinition, MetricKind, MetricObservation, PendingMetric, PendingMetricWriteSessionPort, TelemetryBatchStorePort, TelemetryMetricCorruptionError, TelemetryPersistencePort, TelemetryPersistenceWriteSessionPort, TelemetryStorageReadRow, TelemetryStorageWriteRow, TelemetryWriteActorPort
- noetrium_platform.evidence.observability.telemetry.metric.api.contracts ?w^~)?t MetricDefinition, MetricKind, MetricObservation
- noetrium_platform.evidence.observability.telemetry.metric.api.errors ?w^~)?t TelemetryMetricCorruptionError
- noetrium_platform.evidence.observability.telemetry.metric.api.json_contract ?w^~)?t decode_string_map
- noetrium_platform.evidence.observability.telemetry.metric.api.ports ?w^~)?t PendingMetricWriteSessionPort, TelemetryBatchStorePort, TelemetryPersistencePort, TelemetryPersistenceWriteSessionPort, TelemetryStorageReadRow, TelemetryStorageWriteRow, TelemetryWriteActorPort
- noetrium_platform.evidence.observability.telemetry.metric.api.rows ?w^~)?t ContextualMetricRow, PendingMetric

### observability/tracing

- Package: noetrium_platform.evidence.observability.tracing
- Authority: trace_observation
- Owns: trace/span identity and propagation
- Must not own: business operation truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__tracing

### observability/tracing/context

- Package: noetrium_platform.evidence.observability.tracing.context
- Authority: trace_context
- Owns: trace/span context creation and attachment
- Must not own: business operation state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__tracing__context

#### API modules

- noetrium_platform.evidence.observability.tracing.context.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/tracing/propagation

- Package: noetrium_platform.evidence.observability.tracing.propagation
- Authority: trace_propagation
- Owns: cross-process trace propagation contracts
- Must not own: trace storage
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__tracing__propagation

#### API modules

- noetrium_platform.evidence.observability.tracing.propagation.api.boundary ?w^~)?t SystemLeafContract, contract

### observability/tracing/storage

- Package: noetrium_platform.evidence.observability.tracing.storage
- Authority: trace_storage
- Owns: trace/span storage backends
- Must not own: trace identity semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.observability__tracing__storage

#### API modules

- noetrium_platform.evidence.observability.tracing.storage.api.boundary ?w^~)?t SystemLeafContract, contract

### operator

- Package: noetrium_platform.product.operator
- Authority: operator_surface
- Owns: human-facing query, command, maintenance and incident surfaces
- Must not own: domain authority and business state
- Requires: environment, execution, experimentation, governance, model, observability, platform, portfolio, reliability, resource, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.operator

#### API modules

- noetrium_platform.product.operator.api ?w^~)?t OperatorHandlerPort, OperatorRoutePort, PROJECT_AUTHOR_TEMPLATE_REVISION, PROJECT_PROVIDER_TEMPLATE_REVISION, ProjectCreateReceipt, ProjectCreateRequest, ProjectDoctorCheck, ProjectDoctorDisposition, ProjectDoctorReport, ProjectExperiencePort, ProjectFacade, ProjectTemplateProfile, ProjectTestReceipt, ProjectTestStage, ProjectTestStageReceipt, project_template_revision, ResearchAction, ResearchApplicationPort, ResearchFacade, ResearchOperationFailure, ResearchRequest, ResearchResult
- noetrium_platform.product.operator.api.facade ?w^~)?t ResearchAction, ResearchApplicationPort, ResearchFacade, ResearchOperationFailure, ResearchRequest, ResearchResult
- noetrium_platform.product.operator.api.json_rendering ?w^~)?t plain_json, render_json
- noetrium_platform.product.operator.api.project_experience ?w^~)?t PROJECT_AUTHOR_TEMPLATE_REVISION, PROJECT_PROVIDER_TEMPLATE_REVISION, ProjectCreateReceipt, ProjectCreateRequest, ProjectDoctorCheck, ProjectDoctorDisposition, ProjectDoctorReport, ProjectExperiencePort, ProjectFacade, ProjectTemplateProfile, ProjectTestReceipt, ProjectTestStage, ProjectTestStageReceipt, project_template_revision
- noetrium_platform.product.operator.api.routes ?w^~)?t OperatorHandlerPort, OperatorRoutePort

### operator/audit

- Package: noetrium_platform.product.operator.audit
- Authority: operator_audit
- Owns: audit/reporting views across system authorities
- Must not own: new durable truth
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__audit

### operator/command

- Package: noetrium_platform.product.operator.command
- Authority: operator_commands
- Owns: operator command intent and command result contracts
- Must not own: domain command execution
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.operator__command

### operator/command/intent

- Package: noetrium_platform.product.operator.command.intent
- Authority: operator_command_intent
- Owns: human command intents and authorization context
- Must not own: command execution side effects
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.operator__command__intent

#### API modules

- noetrium_platform.product.operator.command.intent.api.boundary ?w^~)?t SystemLeafContract, contract

### operator/incident

- Package: noetrium_platform.product.operator.incident
- Authority: operator_incident_view
- Owns: incident triage and incident work surfaces
- Must not own: incident authority
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.operator__incident

#### API modules

- noetrium_platform.product.operator.incident.api.boundary ?w^~)?t SystemLeafContract, contract

### operator/maintenance

- Package: noetrium_platform.product.operator.maintenance
- Authority: operator_maintenance
- Owns: maintenance workflows and administrative actions
- Must not own: provider internals
- Requires: runtime
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.operator__maintenance

#### API modules

- noetrium_platform.product.operator.maintenance.api ?w^~)?t ControlAction, ControlStep, ServerStartupPlan, exact_server_startup_plan
- noetrium_platform.product.operator.maintenance.api.control_plan ?w^~)?t ControlAction, ControlStep, ServerStartupPlan, exact_server_startup_plan

### operator/query

- Package: noetrium_platform.product.operator.query
- Authority: operator_queries
- Owns: operator read/query contracts
- Must not own: durable state mutation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.operator__query

### operator/query/search

- Package: noetrium_platform.product.operator.query.search
- Authority: operator_search
- Owns: human-readable search and filtering over read-side projections
- Must not own: authoritative writes
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.operator__query__search

#### API modules

- noetrium_platform.product.operator.query.search.api.boundary ?w^~)?t SystemLeafContract, contract

### participant

- Package: noetrium_platform.capabilities.participant
- Authority: participant_state
- Owns: participant definitions, bindings, sessions and participant capabilities
- Must not own: server/process supervision and scientific truth
- Requires: data, platform, reliability
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant

#### API modules

- noetrium_platform.capabilities.participant.api ?w^~)?t AgentIdentity, AgentImplementation, AgentProjectDefinition, MethodProjectDefinition, method_program_identity_for_requirement, method_program_identity_for_runtime_binding, require_method_program_runtime_binding, AgentSession, AgentSnapshot, AgentTurnRequest, AgentTurnResult, ArchitectureChangeKind, ParticipantArchitectureChange, ParticipantArchitectureComponent, ParticipantArchitectureRevision, ParticipantArchitectureTransition, ParticipantBindingDiagnostic, ParticipantBindingDiagnosticCode, ParticipantBindingDiagnosticSeverity, ParticipantMessageSchedule, ParticipantMessageScheduleEntry, ParticipantProjectBindingError, ParticipantProviderProfile, ParticipantRequirement, ParticipantRequirementContribution, ParticipantRevisionAuthorityPort, ParticipantRevisionAuthoritySnapshot, ParticipantRevisionCommit, ParticipantRevisionConflictError, ParticipantRevisionEvidence, ParticipantRevisionEvidenceKind, ParticipantRevisionIntegrityError, ParticipantRevisionProposal, ParticipantRevisionStateError, ParticipantRevisionValue, ParticipantStateCompatibility, ParticipantStateRevision, ParticipantStateTransition, ParticipantTransitionValue, PreparedParticipantRevision, ParticipantTopology, ParticipantTopologyChange, ParticipantTopologyMember, ParticipantTopologyTransition, ProjectParticipantBinding, ProjectParticipantProviderPort, TopologyChangeKind
- noetrium_platform.capabilities.participant.api.project ?w^~)?t AgentProjectDefinition, MethodProjectDefinition, method_program_identity_for_requirement, method_program_identity_for_runtime_binding, require_method_program_runtime_binding, ParticipantBindingDiagnostic, ParticipantBindingDiagnosticCode, ParticipantBindingDiagnosticSeverity, ParticipantProjectBindingError, ParticipantProviderProfile, ParticipantRequirementContribution, ParticipantRequirement, ProjectParticipantBinding, ProjectParticipantProviderPort
- noetrium_platform.capabilities.participant.api.revision ?w^~)?t ParticipantRevisionAuthorityPort, ParticipantRevisionAuthoritySnapshot, ParticipantRevisionCommit, ParticipantRevisionConflictError, ParticipantRevisionEvidence, ParticipantRevisionEvidenceKind, ParticipantRevisionIntegrityError, ParticipantRevisionProposal, ParticipantRevisionStateError, ParticipantRevisionValue, ParticipantStateCompatibility, ParticipantStateRevision, ParticipantStateTransition, ParticipantTransitionValue, PreparedParticipantRevision
- noetrium_platform.capabilities.participant.api.topology ?w^~)?t ArchitectureChangeKind, ParticipantArchitectureChange, ParticipantArchitectureComponent, ParticipantArchitectureRevision, ParticipantArchitectureTransition, ParticipantMessageSchedule, ParticipantMessageScheduleEntry, ParticipantTopology, ParticipantTopologyChange, ParticipantTopologyMember, ParticipantTopologyTransition, TopologyChangeKind

### participant/core

- Package: noetrium_platform.capabilities.participant.core
- Authority: participant_runtime_abi
- Owns: foundational participant runtime identities, capability descriptors, runtime binding, delivery, lifecycle and checkpoint contracts
- Must not own: project participant selection policy, method semantics, environment semantics or process supervision implementation
- Requires: platform
- Provides: participant.runtime.abi
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__core

#### API modules

- noetrium_platform.capabilities.participant.core.api ?w^~)?t BoundParticipant, BoundParticipants, ParticipantSessionBinding
- noetrium_platform.capabilities.participant.core.api.bound ?w^~)?t BoundParticipant, BoundParticipants, ParticipantSessionBinding
- noetrium_platform.capabilities.participant.core.api.checkpoint ?w^~)?t ParticipantCheckpoint, ParticipantCheckpointIdentityMismatch, ParticipantCheckpointRef
- noetrium_platform.capabilities.participant.core.api.contracts ?w^~)?t ParticipantConfigurationArtifact, ParticipantImplementationIdentity, ParticipantRuntimeBinding, ParticipantSessionRuntimeIdentity
- noetrium_platform.capabilities.participant.core.api.frozen_manifests ?w^~)?t ParticipantImplementationInventory, ParticipantRuntimeBindingManifest, ParticipantRuntimeInventory
- noetrium_platform.capabilities.participant.core.api.lifecycle ?w^~)?t ParticipantIdentityMismatch, ParticipantLifecycleAdapter, ParticipantLifecycleAdapterRegistry
- noetrium_platform.capabilities.participant.core.api.runtime ?w^~)?t ParticipantResolverPort, ParticipantRuntimeEndpoint, ParticipantRuntimeHandle, ParticipantSessionRuntime
- noetrium_platform.capabilities.participant.core.api.runtime_operations ?w^~)?t PARTICIPANT_OPERATION_VERBS, ParticipantOperationContractError, participant_operation_type, participant_operation_verb, validate_participant_kind
- noetrium_platform.capabilities.participant.core.api.runtime_ports ?w^~)?t ParticipantCheckpointOperationsPort, ParticipantCheckpointRuntimePort, ParticipantResolutionPort, ParticipantSessionLifecyclePort

### participant/agent

- Package: noetrium_platform.capabilities.participant.agent
- Authority: agent_identity
- Owns: agent participant contracts, provider-independent agent identity and bounded cognition-loop orchestration
- Must not own: model serving lifecycle
- Requires: model
- Provides: agent.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__agent

#### API modules

- noetrium_platform.capabilities.participant.agent.api ?w^~)?t AGENT_COORDINATION_CHECKPOINT_SCHEMA, AGENT_MEMORY_CHECKPOINT_SCHEMA, AGENT_SKILL_LIBRARY_CHECKPOINT_SCHEMA, AgentConversationCheckpoint, AgentConversationMessageCheckpoint, AgentConversationSessionCheckpoint, AgentCoordinationCheckpoint, AgentIdentity, AgentSession, AgentSnapshot, AgentTurnRequest, AgentTurnResult, AgentImplementation, AgentActionExecutorPort, AgentActionSequence, AgentActionStep, AgentActionSummary, AgentCognitionError, AgentCompletionPort, AgentDiagnosticsPort, AgentEvidencePort, AgentGoal, AgentLoopCheckpoint, AgentLoopResult, AgentLoopTerminationReason, AgentMemoryContext, AgentMemoryCheckpoint, AgentMemoryCheckpointRecord, AgentModeDecision, AgentModeDisposition, AgentMemoryPort, AgentObservation, AgentObservationPort, AgentPlannerPort, AgentPlanningRequest, AgentPeerCheckpoint, AgentProgressPort, AgentReactiveModePort, AgentReceiptCheckpoint, AgentSafetyDecision, AgentSafetyDisposition, AgentSafetySupervisorPort, AgentSkillCatalogPort, AgentSkillDescription, AgentSkillLibraryCheckpoint, AgentSkillLibraryPort, AgentSkillRecord, AgentSkillSelection, AgentStepReceipt, action_summary_payload, JsonObject, JsonValue
- noetrium_platform.capabilities.participant.agent.api.cognition ?w^~)?t AgentActionSequence, AgentActionStep, AgentActionSummary, AgentCognitionError, AgentGoal, AgentLoopCheckpoint, AgentLoopResult, AgentLoopTerminationReason, AgentMemoryContext, AgentModeDecision, AgentModeDisposition, AgentObservation, AgentPlanningRequest, AgentReceiptCheckpoint, AgentSafetyDecision, AgentSafetyDisposition, AgentSkillDescription, AgentSkillRecord, AgentSkillSelection, AgentStepReceipt, action_summary_payload, JsonObject, JsonValue
- noetrium_platform.capabilities.participant.agent.api.cognition_ports ?w^~)?t AgentActionExecutorPort, AgentCompletionPort, AgentDiagnosticsPort, AgentEvidencePort, AgentMemoryPort, AgentObservationPort, AgentPlannerPort, AgentProgressPort, AgentReactiveModePort, AgentSafetySupervisorPort, AgentSkillCatalogPort, AgentSkillLibraryPort
- noetrium_platform.capabilities.participant.agent.api.contracts ?w^~)?t CapabilityPort, ExecutionContext, JsonInput, JsonValue, freeze_json, require_sha256, AgentIdentity, AgentSnapshot, AgentTurnRequest, AgentTurnResult, AgentSession, AgentImplementation
- noetrium_platform.capabilities.participant.agent.api.coordination_checkpoint ?w^~)?t AGENT_COORDINATION_CHECKPOINT_SCHEMA, AgentConversationCheckpoint, AgentConversationMessageCheckpoint, AgentConversationSessionCheckpoint, AgentCoordinationCheckpoint, AgentPeerCheckpoint
- noetrium_platform.capabilities.participant.agent.api.memory_checkpoint ?w^~)?t AGENT_MEMORY_CHECKPOINT_SCHEMA, AgentMemoryCheckpoint, AgentMemoryCheckpointRecord
- noetrium_platform.capabilities.participant.agent.api.skill_checkpoint ?w^~)?t AGENT_SKILL_LIBRARY_CHECKPOINT_SCHEMA, AgentSkillLibraryCheckpoint

### participant/binding

- Package: noetrium_platform.capabilities.participant.binding
- Authority: participant_binding
- Owns: binding participants to scopes, methods, environments or models
- Must not own: provider internals
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__binding

#### API modules

- noetrium_platform.capabilities.participant.binding.api.contracts ?w^~)?t ParticipantBindingResolverPort, ParticipantConfigurationCatalogPort, ParticipantImplementationCatalogPort, ParticipantImplementationRegistration, ParticipantRuntimeEndpointFactory, ParticipantSessionRuntimeCatalogPort, ParticipantSessionRuntimeRegistration

### participant/capability

- Package: noetrium_platform.capabilities.participant.capability
- Authority: participant_capability
- Owns: participant capability declarations and exposure
- Must not own: execution capability implementation
- Requires: none
- Provides: capability.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__capability

#### API modules

- noetrium_platform.capabilities.participant.capability.api ?w^~)?t CapabilityApprovalDenied, CapabilityApprovalPort, CapabilityCarrierTransportPort, CapabilityDescriptor, CapabilityEffectReconciliationResult, CapabilityExportSession, CapabilityGuardPort, CapabilityInputCarrier, CapabilityOutputCarrier, CapabilityPolicyDenied, CapabilityPolicySet, CapabilityPort, CapabilityPostPolicyPort, CapabilityPostPolicyViolation, CapabilityProviderImplementation, CapabilityProviderIdentity, CapabilityProviderSession, CapabilityRequest, CapabilityResult, DurablePreparedCapabilitySession, GuardDecision, GuardVerdict, TypedCapabilityCarrierCodec, TypedCarrierReference, capability_effect_request_id, capability_request_digest, decode_typed_capability_input, decode_typed_capability_result, make_typed_capability_request, make_typed_capability_result, require_pure_typed_descriptor
- noetrium_platform.capabilities.participant.capability.api.contracts ?w^~)?t EffectReconciliationDisposition, PreparedEffectHandle, EffectClass, EffectReceipt, ExecutionContext, JsonObject, JsonValue, canonical_digest, freeze_json, CapabilityProviderIdentity, CapabilityDescriptor, CapabilityRequest, capability_effect_request_id, capability_request_digest, CapabilityResult, CapabilityEffectReconciliationResult, DurablePreparedCapabilitySession, CapabilityPort, CapabilityExportSession, CapabilityProviderSession, CapabilityProviderImplementation
- noetrium_platform.capabilities.participant.capability.api.policy ?w^~)?t CapabilityApprovalDenied, CapabilityApprovalPort, CapabilityGuardPort, CapabilityPolicyDenied, CapabilityPolicySet, CapabilityPostPolicyPort, CapabilityPostPolicyViolation, GuardDecision, GuardVerdict
- noetrium_platform.capabilities.participant.capability.api.typed ?w^~)?t CapabilityCarrierTransportPort, CapabilityInputCarrier, CapabilityOutputCarrier, TypedCapabilityCarrierCodec, TypedCarrierReference, decode_typed_capability_input, decode_typed_capability_result, make_typed_capability_request, make_typed_capability_result, require_pure_typed_descriptor

### participant/definition

- Package: noetrium_platform.capabilities.participant.definition
- Authority: participant_definition
- Owns: participant identities and types
- Must not own: execution session state
- Requires: none
- Provides: participant.definition
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__definition

#### API modules

- noetrium_platform.capabilities.participant.definition.api ?w^~)?t ParticipantConfigurationArtifact, ParticipantImplementationCatalogPort, ParticipantImplementationFactory, ParticipantImplementationIdentity, RegisteredParticipantImplementation
- noetrium_platform.capabilities.participant.definition.api.contracts ?w^~)?t ParticipantImplementationFactory, RegisteredParticipantImplementation
- noetrium_platform.capabilities.participant.definition.api.ports ?w^~)?t ParticipantImplementationCatalogPort

### participant/method

- Package: noetrium_platform.capabilities.participant.method
- Authority: method_participant_binding
- Owns: method participant binding contracts
- Must not own: method implementation itself
- Requires: governance
- Provides: method.contract, method.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__method

#### API modules

- noetrium_platform.capabilities.participant.method.api ?w^~)?t IdempotentTaskCompletionSession, MethodIdentity, MethodGraphCheckpointPort, MethodGraphEvent, MethodGraphInterrupt, MethodGraphProgram, MethodGraphRequest, MethodGraphResult, MethodCompositionPorts, MethodEndpointFactoryPort, MethodEndpointPort, MethodImplementation, MethodObservation, MethodProgramIdentity, MethodProgramIdentityMismatch, MethodObservationDeliveryError, MethodObservationOutboxFactoryPort, MethodObservationOutboxPort, MethodObservationSink, MethodRuntimeBinding, ResearchMethodProgram, StatefulResearchMethodProgram, MethodRuntimeIdentity, MethodServices, MethodSession, MethodSessionRuntime, MethodSystemBinding, MethodSnapshot, MethodTaskCompletionReceipt, MethodTaskOutcome, RecallRequest, RecallResult, TaskCompletionReconciliationSession, TaskCompletionSafetyCapabilityMissing
- noetrium_platform.capabilities.participant.method.api.binding ?w^~)?t MethodSystemBinding
- noetrium_platform.capabilities.participant.method.api.contracts ?w^~)?t ExecutionContext, JsonValue, canonical_digest, require_sha256, MethodIdentity, MethodProgramIdentity, MethodProgramIdentityMismatch, ResearchMethodProgram, StatefulResearchMethodProgram, MethodSnapshot, RecallRequest, RecallResult, MethodTaskOutcome, MethodTaskCompletionReceipt, IdempotentTaskCompletionSession, TaskCompletionReconciliationSession, MethodSession
- noetrium_platform.capabilities.participant.method.api.errors ?w^~)?t TaskCompletionSafetyCapabilityMissing
- noetrium_platform.capabilities.participant.method.api.graph ?w^~)?t MethodGraphCheckpointPort, MethodGraphEvent, MethodGraphInterrupt, MethodGraphProgram, MethodGraphRequest, MethodGraphResult
- noetrium_platform.capabilities.participant.method.api.observability ?w^~)?t ExecutionContext, JsonValue, canonical_bytes, freeze_json, MethodObservation, MethodObservationDeliveryError, MethodObservationSink, MethodObservationOutboxPort, MethodObservationOutboxFactoryPort, MethodServices
- noetrium_platform.capabilities.participant.method.api.ports ?w^~)?t MethodCompositionPorts, MethodEndpointFactoryPort, MethodEndpointPort, MethodImplementation, MethodRuntimeBinding, MethodRuntimeIdentity, MethodSessionRuntime
- noetrium_platform.capabilities.participant.method.api.runtime ?w^~)?t MethodCompositionPorts, MethodEndpointFactoryPort, MethodEndpointPort, MethodImplementation, MethodRuntimeBinding, MethodRuntimeIdentity, MethodSessionRuntime

### participant/session

- Package: noetrium_platform.capabilities.participant.session
- Authority: participant_session
- Owns: participant session identity and lifecycle contract
- Must not own: server/process implementation
- Requires: none
- Provides: participant.session
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__session

#### API modules

- noetrium_platform.capabilities.participant.session.api ?w^~)?t ParticipantCheckpointRuntimePort, ParticipantRuntimeEndpoint, ParticipantSessionLifecyclePort, ParticipantSessionRuntime, ParticipantSessionRuntimeCatalogPort, ParticipantSessionRuntimeFactory, ParticipantSessionRuntimeIdentity, RegisteredParticipantSessionRuntime
- noetrium_platform.capabilities.participant.session.api.contracts ?w^~)?t ParticipantSessionRuntimeFactory, RegisteredParticipantSessionRuntime
- noetrium_platform.capabilities.participant.session.api.ports ?w^~)?t ParticipantSessionRuntimeCatalogPort

### platform

- Package: noetrium_platform.foundation.kernel
- Authority: platform_identity
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

### platform/concurrency

- Package: noetrium_platform.foundation.kernel.concurrency
- Authority: platform_concurrency_runtime
- Owns: process-owned bounded executors, serial lanes, timers and structured concurrency lifecycle mechanisms
- Must not own: domain mutable state, admission quotas/decisions, scheduling priority/fairness or business semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.platform__concurrency

#### API modules

- noetrium_platform.foundation.kernel.concurrency.api ?w^~)?t SerialMailboxPolicy, SerialMailboxRejected, CancellationTokenPort, ConcurrencyBudget, ConcurrencyTopologySnapshot, Deadline, ExecutionLaneKind, ExecutionPermitRejected, ExecutionSpec, ExecutorPort, ExecutionPermitLeasePort, ExecutionPermitPort, HeartbeatSchedulerPort, HeartbeatSpec, HeartbeatTopologySnapshot, ScheduledTaskHandlePort, ScheduledTaskSpec, SerialActorPort, SerialLaneTopologySnapshot, StructuredConcurrencyRuntimePort, TaskCancelled, TaskContextPort, TaskDeadlineExceeded, TaskFailurePolicy, TaskFailureScope, TaskGroupPort, TaskGroupTopologySnapshot, TaskHandlePort, TaskState, TaskTopologySnapshot
- noetrium_platform.foundation.kernel.concurrency.api.contracts ?w^~)?t ExecutionLaneKind, SerialMailboxPolicy, TaskFailurePolicy, TaskFailureScope, TaskState, TaskCancelled, TaskDeadlineExceeded, ExecutionPermitRejected, SerialMailboxRejected, ConcurrencyBudget, Deadline, ExecutionSpec, HeartbeatSpec, ScheduledTaskSpec, TaskTopologySnapshot, TaskGroupTopologySnapshot, SerialLaneTopologySnapshot, HeartbeatTopologySnapshot, ConcurrencyTopologySnapshot
- noetrium_platform.foundation.kernel.concurrency.api.ports ?w^~)?t ConcurrencyTopologySnapshot, Deadline, ExecutionLaneKind, ExecutionSpec, HeartbeatSpec, HeartbeatTopologySnapshot, ScheduledTaskSpec, TaskFailurePolicy, TaskGroupTopologySnapshot, TaskState, SerialLaneTopologySnapshot, CancellationTokenPort, ExecutionPermitLeasePort, ExecutionPermitPort, TaskContextPort, TaskHandlePort, ScheduledTaskHandlePort, ExecutorPort, SerialActorPort, TaskGroupPort, HeartbeatSchedulerPort, StructuredConcurrencyRuntimePort, ExecutionAuthorityProviderPort, ExecutorProviderPort, CpuWorkerPoolProviderPort, SerialExecutionLaneProviderPort, SerialExecutionLaneFactoryProviderPort, TimerSchedulerProviderPort

### platform/configuration

- Package: noetrium_platform.foundation.kernel.configuration
- Authority: platform_configuration
- Owns: platform configuration sources and frozen configuration snapshots
- Must not own: domain configuration semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.platform__configuration

#### API modules

- noetrium_platform.foundation.kernel.configuration.api.boundary ?w^~)?t SystemLeafContract, contract

### platform/identity

- Package: noetrium_platform.foundation.kernel.identity
- Authority: platform_identity
- Owns: platform identity and immutable platform metadata
- Must not own: workspace/project/run identity
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.platform__identity

#### API modules

- noetrium_platform.foundation.kernel.identity.api.boundary ?w^~)?t SystemLeafContract, contract

### platform/lifecycle

- Package: noetrium_platform.foundation.kernel.lifecycle
- Authority: platform_lifecycle
- Owns: platform startup/shutdown/readiness semantics
- Must not own: service/process lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.platform__lifecycle

#### API modules

- noetrium_platform.foundation.kernel.lifecycle.api.boundary ?w^~)?t SystemLeafContract, contract

### portfolio

- Package: noetrium_platform.foundation.portfolio
- Authority: portfolio_metadata
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

### portfolio/membership

- Package: noetrium_platform.foundation.portfolio.membership
- Authority: portfolio_membership
- Owns: portfolio-level ownership and membership records
- Must not own: runtime participant sessions
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.portfolio__membership

#### API modules

- noetrium_platform.foundation.portfolio.membership.api.boundary ?w^~)?t SystemLeafContract, contract

### portfolio/program

- Package: noetrium_platform.foundation.portfolio.program
- Authority: program_metadata
- Owns: research program metadata and project grouping
- Must not own: study semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.portfolio__program

#### API modules

- noetrium_platform.foundation.portfolio.program.api.boundary ?w^~)?t SystemLeafContract, contract

### portfolio/project

- Package: noetrium_platform.foundation.portfolio.project
- Authority: project_metadata
- Owns: project metadata, configuration references and lifecycle
- Must not own: experiment/run execution state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.portfolio__project

#### API modules

- noetrium_platform.foundation.portfolio.project.api.contracts ?w^~)?t PROJECT_MANIFEST_SCHEMA, ProjectCapabilityRequirement, ProjectConfigurationReference, ProjectIdentity, ProjectManifest, ProjectManifestDecodeError, ProjectManifestFacet, ProjectManifestFacetChange, ProjectManifestFacetDiff, ProjectManifestIdentityFacets, ProjectProviderBinding, ProjectMethodRequirement, ProjectRequirementCardinality, ProjectSpec, ProjectToolProvenance, decode_project_manifest_bytes, decode_project_manifest_document, diff_project_manifest_facets, encode_project_manifest, project_manifest_document, project_manifest_identity_facets

### portfolio/workspace

- Package: noetrium_platform.foundation.portfolio.workspace
- Authority: workspace_metadata
- Owns: workspace metadata and lifecycle
- Must not own: generic scope tree authority
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.portfolio__workspace

#### API modules

- noetrium_platform.foundation.portfolio.workspace.api.boundary ?w^~)?t SystemLeafContract, contract

### reliability

- Package: noetrium_platform.infrastructure.reliability
- Authority: reliability_authority
- Owns: effects, failures, incidents, forensics, diagnosis, reconciliation and recovery
- Must not own: scientific truth and UI projections
- Requires: data, governance, observability, platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability

### reliability/diagnostics

- Package: noetrium_platform.infrastructure.reliability.diagnostics
- Authority: diagnostic_queries
- Owns: read-side cross-system correlation and root-cause views
- Must not own: durable authority mutation
- Requires: none
- Provides: diagnostics.causal
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability__diagnostics

#### API modules

- noetrium_platform.infrastructure.reliability.diagnostics.api ?w^~)?t DiagnosticEvidencePort, DiagnosticIndexSessionPort, DiagnosticLogQueryPort, DiagnosticObjectRecord, IncidentPattern, IncidentProjectionPort, IncidentProjectionSync, MetricQueryPort, OperationInvocationRecord, StateWriterRecord
- noetrium_platform.infrastructure.reliability.diagnostics.api.incidents ?w^~)?t IncidentPattern, IncidentProjectionPort, IncidentProjectionSync
- noetrium_platform.infrastructure.reliability.diagnostics.api.logging ?w^~)?t DiagnosticLogQueryPort
- noetrium_platform.infrastructure.reliability.diagnostics.api.ports ?w^~)?t DiagnosticEvidencePort, DiagnosticIndexSessionPort, MetricQueryPort, MetricQueryRow
- noetrium_platform.infrastructure.reliability.diagnostics.api.records ?w^~)?t DiagnosticObjectRecord, OperationInvocationRecord, StateWriterRecord, freeze_diagnostic_mapping

### reliability/effect

- Package: noetrium_platform.infrastructure.reliability.effect
- Authority: effect_authority
- Owns: external effect intent, outcome certainty and reconciliation state
- Must not own: process/server ownership
- Requires: none
- Provides: effect.safety, effect.journal
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

### reliability/forensics

- Package: noetrium_platform.infrastructure.reliability.forensics
- Authority: forensic_authority
- Owns: durable evidence bundles, causal evidence and forensic indexes
- Must not own: business result semantics
- Requires: none
- Provides: forensics.ledger
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability__forensics

#### API modules

- noetrium_platform.infrastructure.reliability.forensics.api ?w^~)?t CRASH_BUNDLE_SCHEMA_VERSION, CrashBundleManifest, CrashBundleVerification, ForensicCriticalWriteLanePort, ForensicEventWriteLanePort, ForensicIndexPort, ForensicIndexReadSessionPort, ForensicLedgerPort, ForensicRuntimeParts, ForensicStorePort, ForensicWriterLeasePort, MutationRecord, VerifiedLedgerCut, VerifiedLedgerSlice
- noetrium_platform.infrastructure.reliability.forensics.api.crash_bundle_contracts ?w^~)?t CrashBundleManifest, CrashBundleVerification
- noetrium_platform.infrastructure.reliability.forensics.api.ledger ?w^~)?t VerifiedLedgerCut, VerifiedLedgerSlice
- noetrium_platform.infrastructure.reliability.forensics.api.mutation ?w^~)?t ExecutionContext, MutationRecord
- noetrium_platform.infrastructure.reliability.forensics.api.ports ?w^~)?t ForensicCriticalWriteLanePort, ForensicEventWriteLanePort, ForensicIndexPort, ForensicIndexReadSessionPort, ForensicLedgerPort, ForensicStorePort, ForensicWriterLeasePort, ForensicWriteActorPort
- noetrium_platform.infrastructure.reliability.forensics.api.runtime_parts ?w^~)?t ForensicRuntimeParts

### reliability/recovery

- Package: noetrium_platform.infrastructure.reliability.recovery
- Authority: recovery_authority
- Owns: recovery plans, exact replay/reconcile and recovery lifecycle
- Must not own: provider storage internals
- Requires: none
- Provides: recovery.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability__recovery

#### API modules

- noetrium_platform.infrastructure.reliability.recovery.api ?w^~)?t RecoveryActionCode, RecoveryAutomation, RecoveryDecisionReport, RecoveryRecommendation, RecoveryLease, RecoveryLeaseBusy, RecoveryExecutionFactoryPort, RecoveryExecutionPort, RecoveryLeaseReadPort, RecoveryLeaseStatePort, RecoveryLeaseStatusPort
- noetrium_platform.infrastructure.reliability.recovery.api.contracts ?w^~)?t RecoveryActionCode, RecoveryAutomation, RecoveryDecisionReport, RecoveryRecommendation
- noetrium_platform.infrastructure.reliability.recovery.api.lease ?w^~)?t RecoveryLease, RecoveryLeaseBusy
- noetrium_platform.infrastructure.reliability.recovery.api.ports ?w^~)?t RecoveryExecutionFactoryPort, RecoveryExecutionPort, RecoveryLeaseReadPort, RecoveryLeaseStatePort, RecoveryLeaseStatusPort

### reliability/recovery/execution

- Package: noetrium_platform.infrastructure.reliability.recovery.execution
- Authority: recovery_execution
- Owns: recovery execution lifecycle and effect handoff
- Must not own: failure taxonomy
- Requires: none
- Provides: recovery.execution
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability__recovery__execution

#### API modules

- noetrium_platform.infrastructure.reliability.recovery.execution.api ?w^~)?t RecoveryExecutionFactoryPort, RecoveryExecutionPort

### resource

- Package: noetrium_platform.infrastructure.resources
- Authority: resource_inventory
- Owns: resource inventory, compute, directories, leases and allocation/resolution
- Must not own: environment semantics and model deployment truth
- Requires: platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource

### resource/allocation

- Package: noetrium_platform.infrastructure.resources.allocation
- Authority: resource_allocation
- Owns: resource allocation intents and allocations
- Must not own: execution workflow semantics
- Requires: resource/lease
- Provides: resource.endpoint-allocation
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource__allocation

#### API modules

- noetrium_platform.infrastructure.resources.allocation.api ?w^~)?t AtomicEndpointReservationPort, DEFAULT_ENDPOINT_LEASE_POLICY, EndpointAllocation, EndpointAllocationPort, EndpointAllocationRequest, EndpointBindingProof, EndpointAllocationState, EndpointLeaseGuardFactoryPort, EndpointLeaseGuardPort, EndpointLeasePolicy, EndpointProbePort, EndpointProbeResult, EndpointProtocol, EndpointReservationResult, EndpointReservationStatus, NetworkEndpoint
- noetrium_platform.infrastructure.resources.allocation.api.contracts ?w^~)?t EndpointAllocation, EndpointBindingProof, EndpointAllocationRequest, EndpointAllocationState, EndpointLeasePolicy, DEFAULT_ENDPOINT_LEASE_POLICY, EndpointReservationResult, EndpointReservationStatus, EndpointProbeResult, EndpointProtocol, NetworkEndpoint
- noetrium_platform.infrastructure.resources.allocation.api.ports ?w^~)?t AtomicEndpointReservationPort, EndpointAllocationPort, EndpointLeaseGuardFactoryPort, EndpointLeaseGuardPort, EndpointProbePort

### resource/compute

- Package: noetrium_platform.infrastructure.resources.compute
- Authority: compute_inventory
- Owns: compute resource identity, capacities and provider facts
- Must not own: environment packaging
- Requires: runtime/process
- Provides: compute.inventory, compute.scheduler
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource__compute

#### API modules

- noetrium_platform.infrastructure.resources.compute.api ?w^~)?t ComputeAllocation, ComputeCandidatePort, ComputeCluster, ComputeGPU, ComputeHost, ComputeRequirement, ComputeInventoryPort, ComputeSchedulerPort, GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot
- noetrium_platform.infrastructure.resources.compute.api.contracts ?w^~)?t ComputeAllocation, ComputeCluster, ComputeGPU, ComputeHost, ComputeRequirement
- noetrium_platform.infrastructure.resources.compute.api.ports ?w^~)?t ComputeCandidatePort, ComputeInventoryPort, ComputeSchedulerPort
- noetrium_platform.infrastructure.resources.compute.api.runtime_status ?w^~)?t GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot

### resource/directory

- Package: noetrium_platform.infrastructure.resources.directory
- Authority: directory_inventory
- Owns: managed filesystem/directory identity and lifecycle
- Must not own: artifact immutable content
- Requires: none
- Provides: directory.layout, workspace.storage
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource__directory

#### API modules

- noetrium_platform.infrastructure.resources.directory.api ?w^~)?t DirectoryCleanupCandidate, DirectoryCleanupPort, DirectoryContentStats, DirectoryEntryStats, DirectoryInspectionPort, DirectoryLayout, DirectoryLayoutPort, DirectoryManagementAuthorities, DirectoryOverview, DirectoryUsage, ManagedDirectoryKind, WorkspaceAllocation, WorkspaceMetadataError, WorkspaceMetadataFailureCode, WorkspaceManagementPort
- noetrium_platform.infrastructure.resources.directory.api.contracts ?w^~)?t DirectoryCleanupCandidate, DirectoryContentStats, DirectoryEntryStats, DirectoryLayout, DirectoryOverview, DirectoryUsage, ManagedDirectoryKind, WorkspaceAllocation, WorkspaceMetadataError, WorkspaceMetadataFailureCode
- noetrium_platform.infrastructure.resources.directory.api.ports ?w^~)?t DirectoryCleanupPort, DirectoryInspectionPort, DirectoryLayoutPort, DirectoryManagementAuthorities, WorkspaceManagementPort

### resource/lease

- Package: noetrium_platform.infrastructure.resources.lease
- Authority: resource_lease
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

### resource/resolution

- Package: noetrium_platform.infrastructure.resources.resolution
- Authority: resource_resolution
- Owns: resource resolution policies and resolved bindings
- Must not own: environment/model identity
- Requires: none
- Provides: resource.hierarchical-resolution
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource__resolution

#### API modules

- noetrium_platform.infrastructure.resources.resolution.api ?w^~)?t ResourceResolutionPort, ResourceResolutionRequest, ResolvedResourceBinding
- noetrium_platform.infrastructure.resources.resolution.api.contracts ?w^~)?t ResourceResolutionRequest, ResolvedResourceBinding
- noetrium_platform.infrastructure.resources.resolution.api.ports ?w^~)?t ResourceResolutionPort

### runtime

- Package: noetrium_platform.infrastructure.lifecycle
- Authority: runtime_state
- Owns: server, process, service and session orchestration
- Must not own: experiment semantics and model catalog truth
- Requires: governance, observability, platform, reliability, resource, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime

#### API modules

- noetrium_platform.infrastructure.lifecycle.api ?w^~)?t SystemIdentity, SystemSpec, SystemPort
- noetrium_platform.infrastructure.lifecycle.api.contracts ?w^~)?t SystemIdentity, SystemPort, SystemSpec
- noetrium_platform.infrastructure.lifecycle.api.ports ?w^~)?t SystemPort, SystemSpec

### runtime/host

- Package: noetrium_platform.infrastructure.lifecycle.host
- Authority: host_runtime_state
- Owns: live host identity and runtime host attachment
- Must not own: resource catalog metadata
- Requires: none
- Provides: host.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__host

#### API modules

- noetrium_platform.infrastructure.lifecycle.host.api ?w^~)?t HostOperatingSystem, OperatingSystemFamily, OperatingSystemRoute
- noetrium_platform.infrastructure.lifecycle.host.api.contracts ?w^~)?t HostOperatingSystem, OperatingSystemFamily
- noetrium_platform.infrastructure.lifecycle.host.api.ports ?w^~)?t OperatingSystemRoute

### runtime/process

- Package: noetrium_platform.infrastructure.lifecycle.process
- Authority: process_state
- Owns: process identity, launch contract and lifecycle
- Must not own: experiment semantics
- Requires: none
- Provides: process.execution, process.capture
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__process

#### API modules

- noetrium_platform.infrastructure.lifecycle.process.api ?w^~)?t ByteSegment, CaptureIntegrityError, CaptureManifest, CaptureRotationReceipt, CaptureSyncReceipt, CaptureWriterState, LocalCommandExecutionError, LocalCommandResult, LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError, ProcessByteCapturePort
- noetrium_platform.infrastructure.lifecycle.process.api.capture ?w^~)?t ProcessByteCapturePort
- noetrium_platform.infrastructure.lifecycle.process.api.contracts ?w^~)?t CaptureIntegrityError, ByteSegment, CaptureManifest, CaptureWriterState, CaptureRotationReceipt, CaptureSyncReceipt
- noetrium_platform.infrastructure.lifecycle.process.api.local_command ?w^~)?t LocalCommandExecutionError, LocalCommandResult, LocalCommandRunnerPort, LocalCommandStartError, LocalCommandTimeoutError

### runtime/process/supervision

- Package: noetrium_platform.infrastructure.lifecycle.process.supervision
- Authority: process_supervision
- Owns: process health/reconcile loops
- Must not own: durable runtime history storage
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__process__supervision

#### API modules

- noetrium_platform.infrastructure.lifecycle.process.supervision.api ?w^~)?t ProcessCommandResult, ProcessCommandRunnerPort, ProcessExitReceipt, ProcessSupervisorPort, ProcessTerminationPolicy, SupervisedProcessPort
- noetrium_platform.infrastructure.lifecycle.process.supervision.api.boundary ?w^~)?t SystemLeafContract, contract
- noetrium_platform.infrastructure.lifecycle.process.supervision.api.contracts ?w^~)?t ProcessCommandResult, ProcessExitReceipt, ProcessTerminationPolicy
- noetrium_platform.infrastructure.lifecycle.process.supervision.api.ports ?w^~)?t ProcessCommandRunnerPort, ProcessSupervisorPort, SupervisedProcessPort

### runtime/server

- Package: noetrium_platform.infrastructure.lifecycle.server
- Authority: server_state
- Owns: server identity, lifecycle and health contract
- Must not own: model serving truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__server

#### API modules

- noetrium_platform.infrastructure.lifecycle.server.api ?w^~)?t ServerOperationEffect, ServerOperationFinished, ServerOperationJournalPort, ServerOperationKind, ServerOperationRecord, ServerOperationReconciliationRequired, ServerOperationTransitionConflict, ServerMutationBusy, ServerTransportBusy, ServerOperationResolved, ServerOperationResolution, ServerOperationStarted, ServerOperationState
- noetrium_platform.infrastructure.lifecycle.server.api.operations ?w^~)?t ServerOperationFinished, ServerOperationEffect, ServerOperationJournalPort, ServerOperationKind, ServerOperationStarted, ServerOperationRecord, ServerOperationReconciliationRequired, ServerOperationTransitionConflict, ServerMutationBusy, ServerTransportBusy, ServerOperationResolved, ServerOperationResolution, ServerOperationState

### runtime/server/bootstrap

- Package: noetrium_platform.infrastructure.lifecycle.host.bootstrap
- Authority: server_bootstrap_transaction
- Owns: server bootstrap commands, phases, durable bootstrap state/facts and forward-repair transaction contracts
- Must not own: persistent session implementation, release selection authority or server steady-state lifecycle policy
- Requires: governance/release, platform, runtime/session
- Provides: server.bootstrap
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__server__bootstrap

#### API modules

- noetrium_platform.infrastructure.lifecycle.host.bootstrap.api ?w^~)?t ServerBootstrapBlocked, ServerBootstrapIdentityConflict, ServerBootstrapPhase, ServerBootstrapState, ServerBootstrapStateConflict, ServerBootstrapStatePort, ServerBootstrapTransactionPort, ServerBootstrapTransactionReport
- noetrium_platform.infrastructure.lifecycle.host.bootstrap.api.contracts ?w^~)?t ServerBootstrapBlocked, ServerBootstrapIdentityConflict, ServerBootstrapPhase, ServerBootstrapState, ServerBootstrapStateConflict, ServerBootstrapTransactionReport
- noetrium_platform.infrastructure.lifecycle.host.bootstrap.api.ports ?w^~)?t ServerBootstrapStatePort, ServerBootstrapTransactionPort

### runtime/server/health

- Package: noetrium_platform.infrastructure.lifecycle.server.health
- Authority: server_health_contract
- Owns: runtime server health contracts
- Must not own: observability health storage
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__server__health

#### API modules

- noetrium_platform.infrastructure.lifecycle.server.health.api ?w^~)?t ServerDiagnosticIssue, ServerDiagnosticProjectorPort, ServerDiagnosticReport, ServerDiagnosticSeverity, ServerDiagnosticStatus, ServerHealthProbePort, ServerHealthReport, ServerRuntimeHealthSpec, ServerSessionDiagnostic
- noetrium_platform.infrastructure.lifecycle.server.health.api.contracts ?w^~)?t ServerDiagnosticIssue, ServerDiagnosticReport, ServerDiagnosticSeverity, ServerDiagnosticStatus, ServerHealthReport, ServerRuntimeHealthSpec, ServerSessionDiagnostic
- noetrium_platform.infrastructure.lifecycle.server.health.api.ports ?w^~)?t ServerDiagnosticProjectorPort, ServerHealthProbePort

### runtime/server/identity

- Package: noetrium_platform.infrastructure.lifecycle.server.identity
- Authority: server_identity
- Owns: stable server identity and deployment attachment
- Must not own: live health
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__server__identity

#### API modules

- noetrium_platform.infrastructure.lifecycle.server.identity.api ?w^~)?t ServerAuthenticationUnavailable, ServerCommandResult, ServerConnectionFactoryPort, ServerConnectionPort, ServerConnectionProfile, ServerFileTransferFactoryPort, ServerFileTransferPort, ServerFileTransferResult, ServerIdentityConfigurationError, ServerProfileCatalog, ServerProfileCatalogEntry, ServerProfileCatalogError, ServerTransportFailureKind, server_environment_prefix
- noetrium_platform.infrastructure.lifecycle.server.identity.api.contracts ?w^~)?t ServerAuthenticationUnavailable, ServerCommandResult, ServerConnectionProfile, ServerFileTransferResult, ServerIdentityConfigurationError, ServerProfileCatalog, ServerProfileCatalogEntry, ServerProfileCatalogError, ServerTransportFailureKind, server_environment_prefix
- noetrium_platform.infrastructure.lifecycle.server.identity.api.ports ?w^~)?t ServerConnectionFactoryPort, ServerConnectionPort, ServerFileTransferFactoryPort, ServerFileTransferPort

### runtime/server/lifecycle

- Package: noetrium_platform.infrastructure.lifecycle.server.lifecycle
- Authority: server_lifecycle
- Owns: server lifecycle state and transitions
- Must not own: process internals
- Requires: runtime/server/bootstrap
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__server__lifecycle

#### API modules

- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api ?w^~)?t ServerReleaseDeploymentError, ServerReleaseLayoutError, ServerReleaseDeploymentPort, ServerReleaseDirectoryPort, ServerRepositorySyncError, ServerRepositorySyncPort, ServerRepositorySyncReceipt, ServerRepositorySyncRequest, ServerRepositoryStatus, ServerRepositoryCommandPort, ServerRepositoryCommandReceipt, ServerRepositoryCommandRequest, ServerReleaseDeploymentReceipt, ServerReleaseDeploymentRequest, ServerReleaseLayout, ServerRemoteProfile, ServerRuntimeLaunchManifestPort, ServerRuntimeLaunchManifestMismatch, ServerSessionPolicyMismatch
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.command ?w^~)?t ServerRepositoryCommandReceipt, ServerRepositoryCommandRequest
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.contracts ?w^~)?t ServerReleaseDeploymentError, ServerReleaseDeploymentReceipt, ServerReleaseDeploymentRequest, ServerReleaseLayout
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.errors ?w^~)?t ServerReleaseLayoutError, ServerRuntimeLaunchManifestMismatch, ServerSessionPolicyMismatch
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.ports ?w^~)?t ServerReleaseDeploymentPort, ServerReleaseDirectoryPort, ServerRepositorySyncPort, ServerRepositoryCommandPort, ServerRuntimeLaunchManifestPort
- noetrium_platform.infrastructure.lifecycle.server.lifecycle.api.repository ?w^~)?t ServerRepositorySyncError, ServerRepositorySyncReceipt, ServerRepositorySyncRequest, ServerRepositoryStatus

### runtime/service

- Package: noetrium_platform.infrastructure.lifecycle.service
- Authority: service_state
- Owns: managed service identity, registration and lifecycle
- Must not own: scientific truth
- Requires: none
- Provides: service.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__service

#### API modules

- noetrium_platform.infrastructure.lifecycle.service.api ?w^~)?t ExactServiceRuntimePort, ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity, ServiceReadyObservation, ServiceReconcileObservation, ServiceStartOutcome, ServiceStopOutcome
- noetrium_platform.infrastructure.lifecycle.service.api.contracts ?w^~)?t ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity
- noetrium_platform.infrastructure.lifecycle.service.api.ports ?w^~)?t ExactServiceRuntimePort, ServiceReadyObservation, ServiceReconcileObservation, ServiceStartOutcome, ServiceStopOutcome
- noetrium_platform.infrastructure.lifecycle.service.api.runtime ?w^~)?t ExactServiceRuntimePort, ServiceReadyObservation, ServiceReconcileObservation, ServiceStartOutcome, ServiceStopOutcome

### runtime/session

- Package: noetrium_platform.infrastructure.lifecycle.session
- Authority: runtime_session
- Owns: runtime session identity and host/process bindings
- Must not own: participant scientific semantics
- Requires: none
- Provides: persistent-session.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__session

#### API modules

- noetrium_platform.infrastructure.lifecycle.session.api ?w^~)?t PersistentSessionBackendConfig, PersistentSessionBinding, PersistentSessionBindingStorePort, PersistentSessionLaunchManifestPort, PersistentSessionControlPort, PersistentSessionHostPort, PersistentSessionDrift, PersistentSessionReasonCode, PersistentSessionEffectUncertain, PersistentSessionObservation, PersistentSessionObservationState, PersistentSessionReport, PersistentSessionRuntimePort, PersistentSessionSnapshot, PersistentSessionSpec, process_environment_digest, PersistentSessionStatusConfig, PersistentSessionStatusProbePort, ServerSessionPolicy, RuntimeControllerCommand
- noetrium_platform.infrastructure.lifecycle.session.api.binding ?w^~)?t PersistentSessionBinding, PersistentSessionBindingStorePort
- noetrium_platform.infrastructure.lifecycle.session.api.contracts ?w^~)?t PersistentSessionDrift, PersistentSessionReasonCode, PersistentSessionEffectUncertain, PersistentSessionObservation, PersistentSessionObservationState, PersistentSessionReport, PersistentSessionSnapshot, PersistentSessionSpec, process_environment_digest, ServerSessionPolicy
- noetrium_platform.infrastructure.lifecycle.session.api.controller ?w^~)?t PersistentSessionLaunchManifestPort, RuntimeControllerCommand
- noetrium_platform.infrastructure.lifecycle.session.api.ports ?w^~)?t PersistentSessionControlPort, PersistentSessionRuntimePort, PersistentSessionStatusProbePort, PersistentSessionHostPort
- noetrium_platform.infrastructure.lifecycle.session.api.status_config ?w^~)?t PersistentSessionBackendConfig, PersistentSessionStatusConfig

### runtime/toolchain

- Package: noetrium_platform.infrastructure.lifecycle.toolchain
- Authority: runtime_toolchain
- Owns: verified host toolchain acquisition, materialization, identity and receipts
- Must not own: environment scenarios, experiment protocols, or project policy
- Requires: artifact
- Provides: runtime.toolchain
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__toolchain

#### API modules

- noetrium_platform.infrastructure.lifecycle.toolchain.api ?w^~)?t JavaRuntimePlatform, JavaRuntimeProvisioningPort, JavaRuntimeProvisioningRequest, JavaRuntimeProvisioningResult, JavaRuntimeReceipt, RuntimeToolchainError, current_java_runtime_platform, parse_java_major
- noetrium_platform.infrastructure.lifecycle.toolchain.api.contracts ?w^~)?t JavaRuntimePlatform, JavaRuntimeProvisioningRequest, JavaRuntimeProvisioningResult, JavaRuntimeReceipt, RuntimeToolchainError, current_java_runtime_platform, parse_java_major
- noetrium_platform.infrastructure.lifecycle.toolchain.api.ports ?w^~)?t JavaRuntimeProvisioningPort

### runtime/python

- Package: noetrium_platform.infrastructure.lifecycle.python
- Authority: python_environment
- Owns: Python interpreter environments, package lifecycle and execution bindings
- Must not own: generic process supervisor
- Requires: runtime, resource
- Provides: python-environment.registry, python-environment.lifecycle, python-environment.execution, python-environment.packages
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__python

#### API modules

- noetrium_platform.infrastructure.lifecycle.python.api ?w^~)?t EnvironmentCommandResult, InstalledPythonPackage, EnvironmentCommandRunnerPort, ManagedPythonEnvironment, PythonEnvironmentAuthorities, PythonEnvironmentBackend, PythonEnvironmentCloneResult, PythonEnvironmentExecutionPort, PythonEnvironmentLifecyclePort, PythonEnvironmentLookupPort, PythonEnvironmentOwnership, PythonEnvironmentSpec, PythonEnvironmentState, PythonPackageManagementPort
- noetrium_platform.infrastructure.lifecycle.python.api.contracts ?w^~)?t EnvironmentCommandResult, InstalledPythonPackage, ManagedPythonEnvironment, PythonEnvironmentCloneResult, PythonEnvironmentOwnership, PythonEnvironmentSpec, PythonEnvironmentState
- noetrium_platform.infrastructure.lifecycle.python.api.ports ?w^~)?t EnvironmentCommandRunnerPort, PythonEnvironmentAuthorities, PythonEnvironmentBackend, PythonEnvironmentExecutionPort, PythonEnvironmentLifecyclePort, PythonEnvironmentLookupPort, PythonPackageManagementPort

### components

- Package: components
- Authority: reference_component_library
- Owns: reusable single-agent methods, memory, tools and external-framework bridges
- Must not own: platform authority mutation, project semantics, provider credentials or scientific result acceptance
- Requires: platform
- Provides: reference.agent.components, reference.agent.runtime.bridge
- Downstream surface: public
- Facade: noetrium.contracts.systems.components

#### API modules

- components.api ?w^~)?t MemoryEdgeRecord, MemoryGraphConflict, MemoryGraphIntegrityError, MemoryGraphLedgerEntry, MemoryGraphOperation, MemoryGraphPort, MemoryGraphSnapshot, MemoryGraphTransaction, MemoryNodeRecord, VersionedMemoryGraph, JsonlReferenceAgentProgress, NullReferenceAgentProgress, PlatformCapabilityToolPort, ReferenceAgentAction, ReferenceAgentActionKind, ReferenceAgentActionToolPort, ReferenceAgentDecision, ReferenceAgentDecisionPort, ReferenceAgentEvent, ReferenceAgentMessage, ReferenceAgentObservation, ReferenceAgentPlannerPort, ReferenceAgentProgressPort, ReferenceAgentReflectionPort, ReferenceAgentRunResult, ReferenceAgentSolverPort, ReferenceAgentState, ReferenceAgentStatus, ReferenceAgentToolPort, ReferencePlanAndSolveMethod, ReferenceReActMethod, ReferenceReflexionMethod, ReferenceToolRegistryPort, EpisodicMemoryStore, MemoryEmbedderPort, MemoryItem, MemoryPersistencePort, SQLiteMemoryPersistence, VectorMemoryStore, WorkingMemory, ToolArguments, ToolAuditPort, ToolAuthorization, ToolAuthorizationPort, ToolDefinition, ToolHandler, ToolRegistry, ToolResult, ToolRiskClass

### orchestration

- Package: orchestration
- Authority: multi_agent_orchestration
- Owns: multi-agent topology, communication, group/debate/hierarchical coordination and transport seams
- Must not own: single-agent cognition, memory, model providers, scientific truth or platform authority
- Requires: components, platform
- Provides: multi_agent.orchestration
- Downstream surface: public
- Facade: noetrium.contracts.systems.orchestration

#### API modules

- orchestration.api ?w^~)?t CommunicationEdge, CommunicationTopology, MultiAgentCancellationPort, MultiAgentCheckpoint, MultiAgentDeliveryReceipt, MultiAgentDeliveryStatus, MultiAgentJournalPort, MultiAgentMessage, MultiAgentNodePort, MultiAgentRunResult, MultiAgentRunStatus, DebateCoordinator, GroupChatCoordinator, HierarchicalCoordinator, MultiAgentCoordinator, MultiAgentMembershipPort, MultiAgentTransportPort, TransportBackedMultiAgentCoordinator, SQLiteMultiAgentJournal

### scope

- Package: noetrium_platform.foundation.scope
- Authority: scope_tree
- Owns: generic hierarchical scope identity, ancestry and ownership paths
- Must not own: business metadata and runtime state
- Requires: platform
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope

#### API modules

- noetrium_platform.foundation.scope.api ?w^~)?t PLATFORM_SCOPE, ScopeIdentity, ScopeKind, ScopeLink, ScopeRegistryPort, scope_from_data, scope_to_data
- noetrium_platform.foundation.scope.api.codec ?w^~)?t scope_from_data, scope_to_data
- noetrium_platform.foundation.scope.api.contracts ?w^~)?t PLATFORM_SCOPE, ScopeIdentity, ScopeKind, ScopeLink
- noetrium_platform.foundation.scope.api.ports ?w^~)?t ScopeRegistryPort

### scope/hierarchy

- Package: noetrium_platform.foundation.scope.hierarchy
- Authority: scope_hierarchy
- Owns: parent/child relationships, ancestry, descendants
- Must not own: project business fields
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope__hierarchy

#### API modules

- noetrium_platform.foundation.scope.hierarchy.api.boundary ?w^~)?t SystemLeafContract, contract

### scope/identity

- Package: noetrium_platform.foundation.scope.identity
- Authority: scope_identity
- Owns: stable scope identities and typed scope kinds
- Must not own: portfolio metadata
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope__identity

#### API modules

- noetrium_platform.foundation.scope.identity.api.boundary ?w^~)?t SystemLeafContract, contract

### scope/membership

- Package: noetrium_platform.foundation.scope.membership
- Authority: scope_membership
- Owns: membership of entities in scopes
- Must not own: participant sessions
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope__membership

#### API modules

- noetrium_platform.foundation.scope.membership.api.boundary ?w^~)?t SystemLeafContract, contract

### scope/ownership

- Package: noetrium_platform.foundation.scope.ownership
- Authority: scope_ownership
- Owns: generic owner links and owner-path rules
- Must not own: portfolio business metadata
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope__ownership

#### API modules

- noetrium_platform.foundation.scope.ownership.api.boundary ?w^~)?t SystemLeafContract, contract

### scope/path

- Package: noetrium_platform.foundation.scope.path
- Authority: scope_path
- Owns: canonical scope paths and resolution
- Must not own: domain-specific routing
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope__path

#### API modules

- noetrium_platform.foundation.scope.path.api ?w^~)?t PathFlavor, ScopePathPort, is_absolute_target_path, require_absolute_target_path
- noetrium_platform.foundation.scope.path.api.contracts ?w^~)?t PathFlavor, is_absolute_target_path, require_absolute_target_path
- noetrium_platform.foundation.scope.path.api.ports ?w^~)?t ScopePathPort

### scope/resolution

- Package: noetrium_platform.foundation.scope.resolution
- Authority: scope_resolution
- Owns: resolve a scope reference to canonical scope path
- Must not own: domain-specific lookup semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope__resolution

#### API modules

- noetrium_platform.foundation.scope.resolution.api.boundary ?w^~)?t SystemLeafContract, contract

