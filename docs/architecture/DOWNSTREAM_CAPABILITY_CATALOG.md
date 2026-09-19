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
- Public API modules: 349
- Public symbols: 2999
- Registry digest: 2e19b6efb53f251f88af2bb61b62fcd528dd89174acfac18a2a1020aab8fc25c

## Capability domains

| Domain | Systems | API modules | Symbols |
| --- | ---: | ---: | ---: |
| artifact | 7 | 26 | 137 |
| data | 8 | 19 | 106 |
| environment | 18 | 27 | 226 |
| execution | 8 | 32 | 411 |
| experimentation | 16 | 64 | 647 |
| governance | 13 | 18 | 130 |
| model | 16 | 30 | 323 |
| observability | 27 | 0 | 0 |
| operator | 8 | 0 | 0 |
| participant | 8 | 36 | 373 |
| platform | 5 | 9 | 89 |
| portfolio | 5 | 7 | 75 |
| reliability | 7 | 15 | 87 |
| resource | 6 | 17 | 130 |
| runtime | 13 | 37 | 233 |
| scope | 7 | 12 | 32 |

## System surfaces

### artifact

- Package: noetrium_platform.evidence.artifact
- Authority: artifact_identity
- Canonical authority: artifact
- Node kind: authority
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
- Authority: none
- Canonical authority: artifact
- Node kind: facet
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
- Authority: none
- Canonical authority: artifact
- Node kind: facet
- Owns: immutable content storage and content digest identity
- Must not own: business metadata
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__content

#### API modules

- noetrium_platform.evidence.artifact.content.api ?w^~)?t ArtifactBlobRef, ArtifactBlobStoreError, ArtifactBlobStorePort, TensorContentRef, TensorContentStorePort, ArtifactAcquisitionError, ArtifactHttpOpener, ArtifactHttpResponse, ArtifactAcquisitionPort, ArtifactAcquisitionRequest, ArtifactAcquisitionResult, ArtifactContentIdentityResolverPort, ArtifactContentIdentityVerificationError, ArtifactStorageBinding, ArtifactStorageBindingConflict, ArtifactStorageBindingCorruptionError, ArtifactStorageBindingNotFound, ArtifactStorageBindingPort, ArtifactStoragePlacementVerifierPort, ArtifactStorageVerificationError, VerifiedArtifactStoragePlacement, ArchiveMaterializationError, ArchiveMaterializationPort, ArchiveMaterializationRequest, ArchiveMaterializationResult, MaterializedTreeInspection, MaterializedTreeInspectionPort
- noetrium_platform.evidence.artifact.content.api.acquisition ?w^~)?t ArtifactAcquisitionError, ArtifactHttpOpener, ArtifactHttpResponse, ArtifactAcquisitionPort, ArtifactAcquisitionRequest, ArtifactAcquisitionResult
- noetrium_platform.evidence.artifact.content.api.blob ?w^~)?t ArtifactBlobRef, ArtifactBlobStoreError, ArtifactBlobStorePort
- noetrium_platform.evidence.artifact.content.api.identity ?w^~)?t ArtifactContentIdentityResolverPort, ArtifactContentIdentityVerificationError
- noetrium_platform.evidence.artifact.content.api.materialization ?w^~)?t ArchiveMaterializationError, ArchiveMaterializationPort, ArchiveMaterializationRequest, ArchiveMaterializationResult, MaterializedTreeInspection, MaterializedTreeInspectionPort
- noetrium_platform.evidence.artifact.content.api.storage ?w^~)?t ArtifactStorageBinding, ArtifactStorageBindingConflict, ArtifactStorageBindingCorruptionError, ArtifactStorageBindingNotFound, ArtifactStorageBindingPort, ArtifactStoragePlacementVerifierPort, ArtifactStorageVerificationError, VerifiedArtifactStoragePlacement
- noetrium_platform.evidence.artifact.content.api.tensor ?w^~)?t TensorContentRef, TensorContentStorePort

### artifact/lineage

- Package: noetrium_platform.evidence.artifact.lineage
- Authority: none
- Canonical authority: artifact
- Node kind: facet
- Owns: artifact lineage and provenance relations
- Must not own: scientific result truth
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.artifact__lineage

### artifact/lineage/relation

- Package: noetrium_platform.evidence.artifact.lineage.relation
- Authority: none
- Canonical authority: artifact
- Node kind: facet
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
- Authority: none
- Canonical authority: artifact
- Node kind: facet
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
- Authority: none
- Canonical authority: artifact
- Node kind: facet
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
- Canonical authority: data
- Node kind: authority
- Owns: durable facts, records, datasets, canonical state and projections
- Must not own: immutable artifact content identity
- Requires: artifact, platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.data

### data/dataset

- Package: noetrium_platform.evidence.data.dataset
- Authority: none
- Canonical authority: data
- Node kind: facet
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

### data/projection

- Package: noetrium_platform.evidence.data.projection
- Authority: none
- Canonical authority: data
- Node kind: projection
- Owns: derived read models and projection lifecycle
- Must not own: source-of-truth mutation
- Requires: none
- Provides: projection.runtime
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.data__projection

### data/query

- Package: noetrium_platform.evidence.data.query
- Authority: none
- Canonical authority: data
- Node kind: projection
- Owns: read query contracts spanning non-authoritative projections
- Must not own: durable writes
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.data__query

#### API modules

- noetrium_platform.evidence.data.query.api ?w^~)?t ResearchDimension, ResearchDimensionKind, ResearchQueryGap, ResearchQueryGapKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultPage, ResearchResultQuery, ResearchResultQueryPort, ResearchResultRecord, ResearchResultReference, ResearchResultSourcePort, ResearchSourceCut, ResearchSourceDisposition, ResearchSourceSnapshot, ResearchSourceStatus, SemanticSimilarityMatch, SemanticSimilarityMetric, SemanticSimilarityQuery, SemanticSimilarityQueryPort, SemanticSimilarityResult
- noetrium_platform.evidence.data.query.api.contracts ?w^~)?t ResearchDimension, ResearchDimensionKind, ResearchQueryGap, ResearchQueryGapKind, ResearchQuerySourceError, ResearchResultKind, ResearchResultPage, ResearchResultQuery, ResearchResultRecord, ResearchResultReference, ResearchSourceCut, ResearchSourceDisposition, ResearchSourceSnapshot, ResearchSourceStatus
- noetrium_platform.evidence.data.query.api.identity ?w^~)?t input_cut_digest, query_document, record_document, research_query_digest, source_cut
- noetrium_platform.evidence.data.query.api.ports ?w^~)?t ResearchResultQueryPort, ResearchResultSourcePort
- noetrium_platform.evidence.data.query.api.semantic ?w^~)?t SemanticSimilarityMatch, SemanticSimilarityMetric, SemanticSimilarityQuery, SemanticSimilarityQueryPort, SemanticSimilarityResult

### data/query/cross

- Package: noetrium_platform.evidence.data.query.cross
- Authority: none
- Canonical authority: data
- Node kind: projection
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
- Authority: none
- Canonical authority: data
- Node kind: facet
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
- Requires: platform, reliability, resource, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment

#### API modules

- noetrium_platform.capabilities.environment.api ?w^~)?t observation_payload, observation_from_payload, effect_receipt_payload, effect_receipt_from_payload, action_result_payload, action_result_from_payload, SystemIdentity, SystemSpec, SystemPort, ExecutionContext, EffectClass, EffectCertainty, EffectReceipt, ActionIdentityViolation, ActionNotApplied, ActionRecoveryRequired, ActionReconciliationDisposition, ActionReconciliationResult, ActionRequest, ActionResult, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, ActionSemanticIdentity, EnvironmentBranchState, EnvironmentBranchStateMismatch, EnvironmentBranchStatePort, EnvironmentRecoverySession, EnvironmentResetPort, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationPort, EnvironmentAssignmentIsolationReceipt, EnvironmentCapabilityUnsupported, EnvironmentCapability, EnvironmentConformanceProbe, EnvironmentProviderConformanceReceipt, verify_environment_provider_conformance, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentProviderPort, EnvironmentSessionDiagnostics, EnvironmentSessionServices, EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort, DurablePreparedActionSession, EnvironmentIdentity, EnvironmentImplementation, EnvironmentSession, Observation, action_request_digest, require_action_recovery_handle_identity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_recovery_handle_reconciliation_identity, JsonScalar, JsonInput, JsonMutableValue, JsonValue, StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json, thaw_json_mapping
- noetrium_platform.capabilities.environment.api.action_identity ?w^~)?t ActionIdentityViolation, ActionSemanticIdentity, require_action_result_identity, require_effect_receipt_digest, require_reconciliation_identity, require_action_recovery_handle_identity, require_recovery_handle_reconciliation_identity
- noetrium_platform.capabilities.environment.api.branch_state ?w^~)?t EnvironmentBranchState, EnvironmentBranchStateMismatch, EnvironmentBranchStatePort
- noetrium_platform.capabilities.environment.api.codec ?w^~)?t action_result_from_payload, action_result_payload, effect_receipt_from_payload, effect_receipt_payload, observation_from_payload, observation_payload
- noetrium_platform.capabilities.environment.api.conformance ?w^~)?t EnvironmentConformanceProbe, EnvironmentProviderConformanceReceipt, verify_environment_provider_conformance
- noetrium_platform.capabilities.environment.api.contracts ?w^~)?t ExecutionContext, JsonInput, JsonValue, SystemIdentity, SystemPort, SystemSpec, canonical_digest, EffectReceipt, PreparedEffectHandle, EnvironmentIdentity, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationReceipt, EnvironmentAssignmentIsolationPort, Observation, ActionRequest, action_request_digest, ActionResult, ActionReconciliationDisposition, ActionReconciliationResult, DurablePreparedActionSession, EnvironmentSession, EnvironmentImplementation
- noetrium_platform.capabilities.environment.api.errors ?w^~)?t ActionNotApplied, ActionRecoveryRequired, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, EnvironmentCapabilityUnsupported
- noetrium_platform.capabilities.environment.api.interaction ?w^~)?t EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort
- noetrium_platform.capabilities.environment.api.ports ?w^~)?t SystemPort, SystemSpec
- noetrium_platform.capabilities.environment.api.provider ?w^~)?t EnvironmentCapability, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentProviderPort, EnvironmentSessionDiagnostics, EnvironmentSessionServices
- noetrium_platform.capabilities.environment.api.recovery ?w^~)?t EnvironmentRecoverySession
- noetrium_platform.capabilities.environment.api.reset ?w^~)?t EnvironmentResetPort
- noetrium_platform.capabilities.environment.api.state_machine ?w^~)?t JsonScalar, JsonInput, JsonMutableValue, JsonValue, StateMachineDynamicsIdentity, StateMachineDynamicsPort, StateMachineEnvironmentSpec, StateTransition, freeze_json_mapping, thaw_json, thaw_json_mapping

### environment/category

- Package: noetrium_platform.capabilities.environment.category
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Authority: none
- Canonical authority: environment
- Node kind: facet
- Owns: environment instance identity, readiness and lifecycle
- Must not own: host supervision implementation
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__instance

### environment/instance/identity

- Package: noetrium_platform.capabilities.environment.instance.identity
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: Minecraft environment contracts, server-control/world-cut semantics, state projection, bridge providers and readiness adapters
- Must not own: generic environment catalog, process/server supervision, model serving, project method semantics or telemetry storage
- Requires: artifact, environment, reliability, resource, runtime
- Provides: environment.minecraft.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__minecraft

### environment/embodied

- Package: noetrium_platform.capabilities.environment.embodied
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Requires: environment, runtime, resource
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

### environment/resolution

- Package: noetrium_platform.capabilities.environment.resolution
- Authority: none
- Canonical authority: environment
- Node kind: adapter
- Owns: resolve logical environment requirements to concrete instance plan
- Must not own: process lifecycle
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__resolution

### environment/runtime

- Package: noetrium_platform.capabilities.environment.runtime
- Authority: none
- Canonical authority: environment
- Node kind: adapter
- Owns: environment runtime adapter contracts
- Must not own: environment catalog authority
- Requires: none
- Provides: environment.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__runtime

### environment/specification

- Package: noetrium_platform.capabilities.environment.specification
- Authority: none
- Canonical authority: environment
- Node kind: facet
- Owns: environment definition and immutable spec identity
- Must not own: live host process state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.environment__specification

### environment/specification/digest

- Package: noetrium_platform.capabilities.environment.specification.digest
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Authority: none
- Canonical authority: environment
- Node kind: facet
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
- Canonical authority: execution
- Node kind: authority
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
- Authority: none
- Canonical authority: execution
- Node kind: policy
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
- Authority: none
- Canonical authority: execution
- Node kind: facet
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
- Authority: none
- Canonical authority: execution
- Node kind: facet
- Owns: immutable typed command intent and routing contracts evaluated by Execution
- Must not own: durable execution truth, operation lifecycle, Machine state or provider effects
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
- Canonical authority: execution/operation
- Node kind: authority
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

### execution/research_program

- Package: noetrium_platform.research.execution.machines
- Authority: none
- Canonical authority: execution
- Node kind: facet
- Owns: paper-programmable ResearchProgram, RuntimeModule, rule and host authoring contracts for non-Method research Machines
- Must not own: Machine Journal transition truth, MethodProgram semantics, provider effects or physical resource scheduling
- Requires: artifact/content, environment, model, participant/capability, platform
- Provides: research.program, runtime.program, research.machine.authoring
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__research_program

#### API modules

- noetrium_platform.research.execution.machines.api ?w^~)?t CapabilityMediationDenied, CapabilityMediationRequest, CapabilityMediationResult, CapabilityMediationStage, CapabilityMediationVerdict, CapabilityMediator, CapabilityMediatorRegistry, CapabilityMediatorRegistryPort, CapabilityProgram, CapabilityRuleProgram, CapabilityRuntimeBinding, ChildFailurePolicy, ChildResearchBindingFactory, ChildResearchHostRegistry, ChildResearchHostRegistryPort, ChildResearchMachineExecution, ChildResearchMachineExecutor, ChildResearchMachineRequest, CommunicationRuntimeSpec, ContextBlockProgram, ContextBudgetExceeded, ContextProgram, ContextProjection, ContextRenderRequest, ContextRenderResult, ContextRenderer, ContextRendererRegistry, ContextRendererRegistryPort, ContextRuntimeBinding, DomainProgramBuilder, EnvironmentConcern, EnvironmentMachineSpec, EnvironmentProgramBuilder, EvaluationConcern, EvaluationProgramBuilder, ExperimentConcern, ExperimentProgramBuilder, FunctionalModelInvocationRequestFactory, InterventionDecision, InterventionDecider, InterventionDeciderRegistry, InterventionDeciderRegistryPort, InterventionKind, InterventionPolicyRequest, InterventionProgram, InterventionResponse, InterventionRuntimeBinding, InterventionTrigger, LogicalSchedulingCandidate, LogicalSchedulingProgram, LogicalSchedulingRequest, LogicalSchedulingRuntimeBinding, LogicalSchedulingSelection, LogicalSchedulingSelector, LogicalSchedulingSelectorRegistry, LogicalSchedulingSelectorRegistryPort, MachineEvent, MemoryConcern, MemoryPresetSpec, MemoryProgramBuilder, MemoryRecord, ModelInvocationCandidate, ModelInvocationMode, ModelInvocationOutcome, ModelInvocationProgram, ModelInvocationRequestFactoryPort, ModelInvocationRuntime, ModelInvocationRuntimeBinding, ModelResponseSelector, ModelResponseSelectorRegistry, ModelResponseSelectorRegistryPort, ModelSelectionRequest, ObjectiveDirection, OptimizationConcern, OptimizationObjective, OptimizationPresetSpec, OptimizationProgramBuilder, PARTICIPANT_TURN_FACT_KINDS, PARTICIPANT_TURN_FACT_WIRE_SCHEMA, ParticipantConcern, ParticipantMessageKind, ParticipantProgramBuilder, ProgramHandlerRegistry, ProgramHandlerRegistryPort, ProgramNode, ProgramNodeRequest, ProgramNodeResult, ProgramOperationHandler, ProgramRule, ProgramRuleSet, RecoveryAction, RecoveryDecision, RecoveryDecider, RecoveryDeciderRegistry, RecoveryDeciderRegistryPort, RecoveryProgram, RecoveryRequest, RecoveryRuntimeBinding, RecoverySignal, RegisteredChildResearchHost, RegisteredChildResearchMachineExecutor, ResearchHostBindingRestorer, ResearchHostExecution, ResearchHostHandler, ResearchHostOperation, ResearchProgram, ResearchProgramBuilder, ResearchProgramHost, ResearchRunProgramBuilder, RuleDispatchMode, RunConcern, RuntimeConcern, RuntimeModule, RuntimeModuleBuilder, RuntimeModuleLink, RuntimeModuleNode, RuntimeProgramBuilder, RuntimeProgramComposer, SynchronizationAction, SynchronizationDecision, SynchronizationDecider, SynchronizationDeciderRegistry, SynchronizationDeciderRegistryPort, SynchronizationMode, SynchronizationPoint, SynchronizationPresetSpec, SynchronizationProgram, SynchronizationRequest, SynchronizationRuntimeBinding, UnhandledEventPolicy, VisibilityDecision, VisibilityDecider, VisibilityDeciderRegistry, VisibilityDeciderRegistryPort, VisibilityDisposition, VisibilityProgram, VisibilityRequest, VisibilityResource, VisibilityRuntimeBinding, VisibilitySubject, build_rule_handlers, capability_mediator_binding_digest, capability_program_from_policy, capability_runtime_module, communication_initial_data, communication_rule_set, compile_communication_runtime_program, compile_context, compile_environment_program, compile_memory_program, compile_optimization_program, compile_rule_program, context_projection_payload, context_renderer_binding_digest, context_runtime_module, context_runtime_operation, environment_initial_data, environment_rule_set, execution_context_from_payload, execution_context_payload, intervention_initial_data, intervention_runtime_module, logical_scheduling_initial_data, logical_scheduling_runtime_module, memory_initial_data, memory_rule_set, model_invocation_runtime_module, optimization_initial_data, optimization_rule_set, participant_turn_initial_data, participant_turn_program, program_handler_binding_digest, recovery_initial_data, recovery_runtime_module, standard_synchronization_decider, synchronization_initial_data, synchronization_program_from_preset, synchronization_runtime_module, visibility_initial_data, visibility_runtime_module

### execution/scheduling

- Package: noetrium_platform.research.execution.scheduling
- Authority: none
- Canonical authority: execution
- Node kind: policy
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
- Authority: none
- Canonical authority: execution
- Node kind: facet
- Owns: workflow definitions, universal method-machine orchestration, and resumable control semantics
- Must not own: process supervision
- Requires: participant/capability, participant/method, platform
- Provides: workflow.runtime, method.machine, method.abi, method.checkpoint
- Downstream surface: public
- Facade: noetrium.contracts.systems.execution__workflow

#### API modules

- noetrium_platform.research.execution.workflow.api ?w^~)?t EffectIntentOperationPort, OperationDispatchPort, OperationExecutionPort, TrialCycleExecution, WorkflowGraph, WorkflowGraphError, WorkflowParticipantRequirementError, WorkflowStep, WorkflowSurfaceBindingContext, WorkflowSurfaceFactory, WorkflowSurfaceReuseScope, workflow_surface_id, workflow_surface_reuse_scope, AsyncMethodAgentLoopPort, AsyncOperationDispatchPort, MethodAgentLoopPort, MethodAgentRequest, MethodAgentResult, MethodAgentTargetHandler, MethodCapabilityTargetHandler, MethodAgentViewHandler, MethodCheckpoint, MethodCheckpointStorePort, MethodEvidenceStatus, MethodExecutionClass, MethodEvidencePort, MethodEvent, MethodGraph, MethodInterrupt, MethodMachinePort, MethodChildMachinePort, MethodNodeHandler, MethodNodeKind, MethodNodeRequest, MethodNodeResult, MethodNodeSpec, MethodObservationPort, MethodProgram, MethodProgramBuilder, MethodRunResult, MethodRunStatus, MethodRuntimeContext
- noetrium_platform.research.execution.workflow.api.dispatch ?w^~)?t OperationDispatchPort, OperationExecutionPort
- noetrium_platform.research.execution.workflow.api.effect_intents ?w^~)?t EffectIntentOperationPort
- noetrium_platform.research.execution.workflow.api.errors ?w^~)?t WorkflowParticipantRequirementError
- noetrium_platform.research.execution.workflow.api.graph ?w^~)?t WorkflowGraph, WorkflowGraphError, WorkflowStep
- noetrium_platform.research.execution.workflow.api.method_machine ?w^~)?t AsyncMethodAgentLoopPort, AsyncOperationDispatchPort, MethodAgentLoopPort, MethodAgentRequest, MethodAgentResult, MethodCheckpoint, MethodCheckpointStorePort, MethodEvidencePort, MethodEvent, MethodEvidenceStatus, MethodExecutionClass, MethodGraph, MethodInterrupt, MethodNodeHandler, MethodNodeKind, MethodNodeRequest, MethodNodeResult, MethodNodeSpec, MethodObservationPort, MethodProgram, MethodProgramBuilder, MethodChildMachinePort, MethodRunResult, MethodMachinePort, MethodRunStatus, MethodRuntimeContext, MethodSchemaPort, MethodAuthoritativeState, MethodControlRecord, MethodTransitionAuthorityPort, MethodTransitionRecord
- noetrium_platform.research.execution.workflow.api.surfaces ?w^~)?t WorkflowSurfaceBindingContext, WorkflowSurfaceFactory, WorkflowSurfaceReuseScope, workflow_surface_reuse_scope, workflow_surface_id
- noetrium_platform.research.execution.workflow.api.trial ?w^~)?t TrialCycleExecution

### experimentation

- Package: noetrium_platform.research.experimentation
- Authority: experimentation_state
- Canonical authority: experimentation
- Node kind: authority
- Owns: study, experiment, run, branch and checkpoint semantics
- Must not own: server/process control and model serving
- Requires: environment, execution, participant, platform, portfolio, scope, governance, model
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation

#### API modules

- noetrium_platform.research.experimentation.api ?w^~)?t MachineCut, ResearchBindingContribution, ResearchCapabilityBinding, ResearchModelRoleBinding, ResearchModelRoleRequirement, ResearchParticipantBinding, ResearchBindingRequirements, ResearchParticipantRequirement, ResearchRequirementResolution, resolve_research_requirements, TaskVerifierArtifact, TaskVerifierPort, TaskVerifierReceipt, TaskVerifierRequest, TrialProviderPort, TrialMatrixExecutionReport, TrialExecutionRequest, TrialExecutionReceipt, TrialExecutionStageReceipt, ModelRoleUsage, ReplayLevel, AnalysisDefinition, AnalysisResult, PostHocEvaluationDefinition, PostHocEvaluationResult, Study, StudyModel, StudyParticipant, BenchmarkAssignmentMode, BenchmarkTaskSet, BenchmarkSourceKind, BenchmarkSourcePort, BenchmarkSourceResolution, BenchmarkSourceSpec, InMemoryBenchmarkSource, MeasurementContentReference, MeasurementCut, TaskArtifactSpec, TaskDefinition, TaskPackageSpec, TaskVerifierIsolation, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, diff_research_plans, compile_research_plan, ResearchPlanDiff, CompiledResearchPlan, ResearchMethodHost, ResearchMethodHostPort, CompiledTrialExperimentProgram, TrialExperimentProgramBinding, compile_trial_experiment_program, trial_report_from_data, CompiledExperimentProgram, ExperimentBatch, ExperimentBatchKind, ExperimentProgramBinding, compile_experiment_program, experiment_report_from_data, CompiledResearchCampaign, CompiledResearchCampaignLane, ResearchCampaignCompilationUnit, compile_research_campaign, ResearchCampaignExecutionPort, ResearchCampaignExecutionReport, ResearchCampaignLaneResult, ResearchCampaignLaneState, ResearchCampaignPlan, ResearchCampaignStudy, ResearchCampaignStudyBinding, StudyIntervention, StudyFactorSpec, ResearchStudyDefinition, StudyExecutionPolicy, ResearchRevision, ParticipantSchedule, MeasurementValueKind, MeasurementValue, MeasurementRecord, MeasurementProtocol, MeasurementDefinition, FactorSelection, FactorLevelSpec, ProjectIdentityProjection, ProjectManifestProjection, ProjectRunDefinition, RunControlAction, RunControlPort, RunControlPreparedOperation, RunControlReceipt, RunControlRequest, RunControlTarget, RunEvidenceValidity, RunExecutionOutcome, RunOutcomeProjection, RunScientificValidity, RunTaskOutcome
- noetrium_platform.research.experimentation.api.campaign ?w^~)?t CompiledResearchCampaign, CompiledResearchCampaignLane, ResearchCampaignCompilationUnit, ResearchCampaignExecutionPort, ResearchCampaignExecutionReport, ResearchCampaignLaneResult, ResearchCampaignLaneState, ResearchCampaignPlan, ResearchCampaignStudy, ResearchCampaignStudyBinding, compile_research_campaign
- noetrium_platform.research.experimentation.api.construction ?w^~)?t ProjectIdentityProjection, ProjectManifestProjection, ProjectRunDefinition
- noetrium_platform.research.experimentation.api.method_host ?w^~)?t ResearchMethodHost, ResearchMethodHostPort
- noetrium_platform.research.experimentation.api.program ?w^~)?t CompiledExperimentProgram, ExperimentBatch, ExperimentBatchKind, ExperimentProgramBinding, compile_experiment_program, experiment_report_from_data
- noetrium_platform.research.experimentation.api.research_compiler ?w^~)?t CompiledResearchPlan, ResearchPlanDiff, compile_research_plan, resolve_research_requirements, diff_research_plans

### experimentation/branch

- Package: noetrium_platform.research.experimentation.branch
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
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
- Authority: none
- Canonical authority: experimentation
- Node kind: projection
- Owns: typed experiment catalog views, implementation candidates, slot health and catalog publication/query contracts
- Must not own: experiment execution, study measurement truth, run lifecycle or benchmark implementation runtime
- Requires: experimentation/experiment, experimentation/run/identity, experimentation/study, scope
- Provides: experiment.catalog
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.experimentation__catalog

### experimentation/checkpoint

- Package: noetrium_platform.research.experimentation.checkpoint
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: checkpoint identity, binding and lifecycle
- Must not own: artifact content storage
- Requires: none
- Provides: run.checkpoint
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__checkpoint

#### API modules

- noetrium_platform.research.experimentation.checkpoint.api ?w^~)?t CheckpointCapturePolicy, CheckpointTrigger, CheckpointTriggerKind, RunCheckpointBundle, RunCheckpointConflict, RunCheckpointCoordinatorPort, RunCheckpointIntegrityError, RunCheckpointManifest, RunCheckpointResult, RunCheckpointStore, RunParticipantPayload, RunParticipantSnapshotRef, RunRestoreResult, WorkloadCheckpointBindingPort, WorkloadCheckpointBundle, WorkloadCheckpointRestoreError, WorkloadCheckpointComponentPort, WorkloadCheckpointComponentRef, WorkloadCheckpointManifest, WorkloadCheckpointPayload, WorkloadCheckpointStore, WorkloadExecutionCut, WorkloadRestoreStateCertainty, build_workload_checkpoint_manifest, WorkloadCheckpointCoordinatorPort, WorkloadCheckpointPublicationPort
- noetrium_platform.research.experimentation.checkpoint.api.contracts ?w^~)?t RunCheckpointBundle, RunCheckpointConflict, RunCheckpointIntegrityError, RunCheckpointManifest, RunCheckpointStore, RunParticipantPayload, RunParticipantSnapshotRef
- noetrium_platform.research.experimentation.checkpoint.api.policy ?w^~)?t CheckpointCapturePolicy, CheckpointTrigger, CheckpointTriggerKind
- noetrium_platform.research.experimentation.checkpoint.api.ports ?w^~)?t RunCheckpointCoordinatorPort
- noetrium_platform.research.experimentation.checkpoint.api.results ?w^~)?t RunCheckpointResult, RunRestoreResult
- noetrium_platform.research.experimentation.checkpoint.api.workload ?w^~)?t WorkloadCheckpointBindingPort, WorkloadCheckpointRestoreError, WorkloadCheckpointBundle, WorkloadCheckpointComponentPort, WorkloadCheckpointComponentRef, WorkloadCheckpointManifest, WorkloadCheckpointPayload, WorkloadCheckpointStore, WorkloadExecutionCut, WorkloadRestoreStateCertainty, build_workload_checkpoint_manifest
- noetrium_platform.research.experimentation.checkpoint.api.workload_ports ?w^~)?t WorkloadCheckpointCoordinatorPort, WorkloadCheckpointPublicationPort

### experimentation/evaluation

- Package: noetrium_platform.research.experimentation.evaluation
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
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
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: experiment definitions, variants and experiment lifecycle
- Must not own: runtime process state
- Requires: none
- Provides: experiment.definition, experiment.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__experiment

#### API modules

- noetrium_platform.research.experimentation.experiment.api ?w^~)?t ExperimentComponentBindingPort, AnalysisPlan, DoctorFinding, ExperimentDefinition, ExperimentLifecycleState, ExperimentModePort, ExecutionMode, ExperimentModelRoleSpec, ExperimentParticipantSpec, ExperimentPlan, ExperimentRunReport, ExperimentTransition, ExperimentUnit, ExperimentUnitExecutorPort, ExperimentUnitKind, ExperimentUnitPlannerPort, RawRecordStorePort, RawRecord, MetricAggregation, MetricMissingPolicy, MetricPredicate, MetricDefinition, MetricValue, MetricReport, ExperimentParticipantTopology, ExperimentTrialCycleExecutorPort, ExperimentTaskSpec, ExperimentWorkloadFailure, ExperimentSpec, ExperimentTrialProtocolIdentity, ExperimentTrialProtocolIdentityMismatch, FailureScope, FailureScopeRank, failure_scope_rank, validate_task_graph
- noetrium_platform.research.experimentation.experiment.api.contracts ?w^~)?t ExperimentParticipantSpec, ExperimentModelRoleSpec, ExperimentSpec, AnalysisPlan, DoctorFinding, ExecutionMode, ExperimentDefinition, ExperimentLifecycleState, ExperimentModePort, ExperimentPlan, ExperimentRunReport, ExperimentTransition, ExperimentUnit, ExperimentUnitExecutorPort, ExperimentUnitKind, ExperimentUnitPlannerPort, FindingSeverity, ObservationEnvelope, ObservationKind, ObservationSinkPort, ExperimentDoctorPort, UnitOutcome, UnitOutcomeState, RawRecordStorePort, RawRecord, MetricAggregation, MetricMissingPolicy, MetricPredicate, MetricDefinition, MetricValue, MetricReport
- noetrium_platform.research.experimentation.experiment.api.failure ?w^~)?t ExperimentWorkloadFailure, FailureScope, FailureScopeRank, failure_scope_rank
- noetrium_platform.research.experimentation.experiment.api.ports ?w^~)?t ExperimentComponentBindingPort, ExperimentTrialCycleExecutorPort
- noetrium_platform.research.experimentation.experiment.api.tasks ?w^~)?t ExperimentTaskSpec, validate_task_graph
- noetrium_platform.research.experimentation.experiment.api.topology ?w^~)?t ExperimentParticipantTopology
- noetrium_platform.research.experimentation.experiment.api.trial_protocol ?w^~)?t ExperimentTrialProtocolIdentity, ExperimentTrialProtocolIdentityMismatch

### experimentation/resource

- Package: noetrium_platform.research.experimentation.resource
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: typed experiment resource policy identity, placement requirements and allocation receipts
- Must not own: physical compute truth, model-serving capacity or execution scheduling policy
- Requires: experimentation/experiment, resource/compute, scope
- Provides: experiment.resource-policy
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__resource

#### API modules

- noetrium_platform.research.experimentation.resource.api ?w^~)?t ComputeDemand, ModelCapacityMode, ResourceAllocationReceipt, ResourcePolicy, ExperimentResourceBinderPort, ResourceAllocationLeasePort
- noetrium_platform.research.experimentation.resource.api.contracts ?w^~)?t ComputeDemand, ModelCapacityMode, ResourceAllocationReceipt, ResourcePolicy
- noetrium_platform.research.experimentation.resource.api.ports ?w^~)?t ExperimentResourceBinderPort, ResourceAllocationLeasePort

### experimentation/run

- Package: noetrium_platform.research.experimentation.run
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: run identity, frozen run contract and run lifecycle
- Must not own: server supervision internals
- Requires: none
- Provides: run.lifecycle, run.decision
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run

#### API modules

- noetrium_platform.research.experimentation.run.api ?w^~)?t DecisionCycleRuntimePort, RunArtifactFinalizationError, RunArtifactFinalizationPort, RunArtifactKind, RunArtifactSnapshotReceipt, RunArtifactSealedError, RunArtifactStorePort, RunArtifactVerificationError, RunArtifactVerificationPort, RunArtifactWriteActorPort, RunRuntimePort, RunDiagnosticsPort, RunSessionPort, ExperimentRunSpec, ExperimentRunExecutionPort, ExperimentRunResult
- noetrium_platform.research.experimentation.run.api.artifacts ?w^~)?t RunArtifactFinalizationError, RunArtifactFinalizationPort, RunArtifactKind, RunArtifactSnapshotReceipt, RunArtifactSealedError, RunArtifactStorePort, RunArtifactVerificationError, RunArtifactVerificationPort, RunArtifactWriteActorPort
- noetrium_platform.research.experimentation.run.api.diagnostics ?w^~)?t RunDiagnosticsPort
- noetrium_platform.research.experimentation.run.api.execution ?w^~)?t ExperimentRunExecutionPort, ExperimentRunResult
- noetrium_platform.research.experimentation.run.api.ports ?w^~)?t DecisionCycleRuntimePort, RunRuntimePort, RunSessionPort
- noetrium_platform.research.experimentation.run.api.spec ?w^~)?t ExperimentRunSpec

### experimentation/run/control

- Package: noetrium_platform.research.experimentation.run.control
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: external run lifecycle effect coordination and read-only RunMachine projections
- Must not own: run phase, control revision, checkpoint head, Machine Journal truth, operator product intents or server supervision internals
- Requires: execution, execution/operation, experimentation/checkpoint, experimentation/run, experimentation/run/identity, experimentation/run/lifecycle, experimentation/run/manifest, platform
- Provides: run.control
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run__control

#### API modules

- noetrium_platform.research.experimentation.run.control.api ?w^~)?t MachineCut, RunControlAction, RunControlActionFailure, RunControlCheckpointBundlePort, RunControlCheckpointStorePort, RunControlConflict, RunControlError, RunControlEvidencePort, RunControlIntegrityError, RunControlLifecyclePort, RunControlNotFound, RunControlPhase, RunControlPort, RunControlPreparedOperation, RunControlReceipt, RunControlReconciliationPort, RunControlRequest, RunControlStaleRevision, RunControlTarget, RunControlTransitionOutcome, RunEvidenceValidity, RunExecutionOutcome, RunOutcomeProjection, RunScientificValidity, RunTaskOutcome
- noetrium_platform.research.experimentation.run.control.api.contracts ?w^~)?t RunIdentity, RunLaunchManifest, RunControlAction, RunControlPhase, RunControlTarget, RunControlRequest, RunControlPreparedOperation, RunExecutionOutcome, RunTaskOutcome, RunEvidenceValidity, RunScientificValidity, RunOutcomeProjection, RunControlReceipt, RunControlTransitionOutcome, RunControlError, RunControlNotFound, RunControlConflict, RunControlStaleRevision, RunControlIntegrityError, RunControlActionFailure, RunControlPort, RunControlCheckpointBundlePort, RunControlCheckpointStorePort, RunControlLifecyclePort, RunControlReconciliationPort, RunControlEvidencePort

### experimentation/run/identity

- Package: noetrium_platform.research.experimentation.run.identity
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
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
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: run lifecycle state and transitions
- Must not own: runtime server lifecycle
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__run__lifecycle

#### API modules

- noetrium_platform.research.experimentation.run.lifecycle.api ?w^~)?t attach_cleanup_note, RunCleanupFailure, RunCleanupReport, RunClosed, RunRecoveryRequired, RunCycleExecutionPort, RunCycleExecutorPort, RunLifetimePort, RunSessionPort
- noetrium_platform.research.experimentation.run.lifecycle.api.cleanup ?w^~)?t attach_cleanup_note
- noetrium_platform.research.experimentation.run.lifecycle.api.contracts ?w^~)?t RunCleanupFailure, RunCleanupReport, RunClosed, RunRecoveryRequired
- noetrium_platform.research.experimentation.run.lifecycle.api.ports ?w^~)?t RunCycleExecutionPort, RunCycleExecutorPort, RunLifetimePort, RunSessionPort

### experimentation/run/manifest

- Package: noetrium_platform.research.experimentation.run.manifest
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
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
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: study definitions, hypotheses and study lifecycle
- Must not own: method implementation internals
- Requires: artifact
- Provides: study.definition
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__study

#### API modules

- noetrium_platform.research.experimentation.study.api ?w^~)?t Study, BenchmarkAssignmentMode, StudyModel, StudyParticipant, PostHocEvaluationDefinition, PostHocEvaluationResult, TaskVerifierArtifact, TaskVerifierPort, TaskVerifierReceipt, TaskVerifierRequest, TrialProviderPort, StudyResearchReadPort, StudyResearchReadSnapshot, TrialMatrixExecutionReport, TrialExecutionRequest, TrialExecutionReceipt, TrialExecutionStageReceipt, ReplayLevel, AnalysisDefinition, AnalysisResult, MeasurementCut, BenchmarkTaskSet, BenchmarkSourceKind, BenchmarkSourcePort, BenchmarkSourceResolution, BenchmarkSourceSpec, InMemoryBenchmarkSource, TaskArtifactSpec, TaskDefinition, TaskPackageSpec, TaskVerifierIsolation, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, StudyIntervention, StudyFactorSpec, ResearchStudyDefinition, StudyExecutionPolicy, ResearchRevision, ParticipantSchedule, FactorSelection, FactorLevelSpec, StudyConcurrencyPolicy, MeasurementContentReference, MeasurementDefinition, MeasurementProtocol, MeasurementRecord, MeasurementValue, MeasurementValueKind, StudyAssignment, StudyExecutionUnit, StudyArtifactPublicationPort, StudyAssignmentPort, StudyMetricAggregate, StudyMatrixExecutionReport, StudyMetricAggregationPort, StudyMetricObservation, StudyProtocol, StudyVariantSpec, VariantKind, ExperimentPlan, VariantBinding, VariantExecutionProvider, VariantExecutionRequest, BoundStudyExecutionPort
- noetrium_platform.research.experimentation.study.api.analysis ?w^~)?t AnalysisDefinition, AnalysisResult, DatasetVersionProjection, EvidenceManifestProjection, MeasurementCut
- noetrium_platform.research.experimentation.study.api.authoring ?w^~)?t Study, StudyModel, StudyParticipant
- noetrium_platform.research.experimentation.study.api.benchmark ?w^~)?t BenchmarkTaskSet, TaskDefinition, TaskPackageSpec, TaskArtifactSpec, TaskVerifierIsolation, TaskGraph, TaskGraphEdge, TaskGraphRelation, TaskSetSplit, TrialBudget, BenchmarkSourceKind, BenchmarkSourceSpec, BenchmarkSourceResolution, BenchmarkSourcePort, InMemoryBenchmarkSource
- noetrium_platform.research.experimentation.study.api.contracts ?w^~)?t StudyConcurrencyPolicy, StudyAssignment, StudyExecutionUnit, StudyMatrixExecutionReport, StudyMetricAggregate, StudyMetricObservation, StudyProtocol, StudyVariantSpec, VariantKind
- noetrium_platform.research.experimentation.study.api.design ?w^~)?t BenchmarkAssignmentMode, FactorLevelSpec, FactorSelection, ParticipantSchedule, ResearchRevision, ResearchStudyDefinition, StudyExecutionPolicy, StudyFactorSpec, StudyIntervention
- noetrium_platform.research.experimentation.study.api.evaluation ?w^~)?t PostHocEvaluationDefinition, PostHocEvaluationResult
- noetrium_platform.research.experimentation.study.api.materialization ?w^~)?t MaterializedTaskVerifierArchive, TaskVerifierArchiveMaterializationPort
- noetrium_platform.research.experimentation.study.api.measurement ?w^~)?t MeasurementContentReference, MeasurementDefinition, MeasurementProtocol, MeasurementRecord, MeasurementValue, MeasurementValueKind
- noetrium_platform.research.experimentation.study.api.plan ?w^~)?t ExperimentPlan, VariantBinding, VariantExecutionProvider, VariantExecutionRequest
- noetrium_platform.research.experimentation.study.api.ports ?w^~)?t BoundStudyExecutionPort, StudyArtifactPublicationPort, StudyAssignmentPort, StudyMetricAggregationPort
- noetrium_platform.research.experimentation.study.api.research_read ?w^~)?t StudyResearchReadPort, StudyResearchReadSnapshot
- noetrium_platform.research.experimentation.study.api.trial ?w^~)?t TaskVerifierArtifact, TaskVerifierPort, TaskVerifierReceipt, TaskVerifierRequest, TrialExecutionReceipt, TrialExecutionRequest, TrialExecutionStageReceipt, TrialMatrixExecutionReport, TrialProviderPort

### experimentation/variant

- Package: noetrium_platform.research.experimentation.variant
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
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
- Authority: none
- Canonical authority: experimentation
- Node kind: facet
- Owns: typed research analysis tables, deterministic statistics/evaluation workflow and report/figure publication semantics
- Must not own: experiment execution lifecycle, measurement truth, method semantics or vendor-specific scientific backends
- Requires: experimentation/study
- Provides: research.workbench
- Downstream surface: public
- Facade: noetrium.contracts.systems.experimentation__workbench

#### API modules

- noetrium_platform.research.experimentation.workbench.api ?w^~)?t AggregationFunction, AggregationSpec, BaselineRegistryPort, BaselineSpec, CandidateProgramExecutionPort, CandidateProgramExecutionReceipt, CandidateProgramExecutionRequest, CandidateProgramExecutionStatus, CandidateProgramIdentity, CandidateProgramMeasurementProjection, CandidateProgramMeasurementProjectionPort, CandidateProgramSourcePublicationPort, DataColumn, DataTable, EvaluationContext, EvaluationStage, FigureCategory, FigureCell, FigureKind, FigureOutputFormat, FigurePoint, FigureRendererPort, FigureSeries, FigureSpec, FigureStyle, GroupComparison, InferenceResult, MetricSummary, MissingValuePolicy, MultipleComparisonMethod, MultipleComparisonResult, PairedComparison, RenderedResearchPackage, ResearchEvaluation, ResearchFigureFactoryPort, ResearchLifecyclePort, ResearchReport, ResearchStatisticsPort, ResearchTablePipelinePort, ReportTableRendererPort, SplitStrategy, TableAnalysisPort, TableReaderPort, TableTransformPort, MeasurementRecordTableAdapter, StudyObservationTableAdapter
- noetrium_platform.research.experimentation.workbench.api.adapters ?w^~)?t MeasurementRecordTableAdapter, StudyObservationTableAdapter
- noetrium_platform.research.experimentation.workbench.api.candidate_program ?w^~)?t CandidateProgramExecutionPort, CandidateProgramExecutionReceipt, CandidateProgramExecutionRequest, CandidateProgramExecutionStatus, CandidateProgramIdentity, CandidateProgramMeasurementProjection, CandidateProgramMeasurementProjectionPort, CandidateProgramSourcePublicationPort
- noetrium_platform.research.experimentation.workbench.api.contracts ?w^~)?t AggregationFunction, AggregationSpec, BaselineRegistryPort, BaselineSpec, DataColumn, DataTable, EvaluationContext, EvaluationStage, FigureCategory, FigureCell, FigureKind, FigureOutputFormat, FigurePoint, FigureRendererPort, FigureSeries, FigureSpec, FigureStyle, GroupComparison, InferenceResult, MetricSummary, MissingValuePolicy, MultipleComparisonMethod, MultipleComparisonResult, PairedComparison, RenderedResearchPackage, ResearchEvaluation, ResearchFigureFactoryPort, ResearchLifecyclePort, ResearchReport, ResearchStatisticsPort, ResearchTablePipelinePort, ReportTableRendererPort, SplitStrategy, TableAnalysisPort, TableReaderPort, TableTransformPort
- noetrium_platform.research.experimentation.workbench.api.table_program ?w^~)?t TableAggregateStep, TableDeriveStep, TableExecutionReceipt, TableExecutionResult, TableExpression, TableExpressionKind, TableFilterStep, TableJoinStep, TableProgram, TableProgramExecutionPort, TableProgramStep, TableProjectStep, TableStepKind

### experimentation/workload

- Package: noetrium_platform.research.experimentation.workload
- Authority: none
- Canonical authority: experimentation
- Node kind: adapter
- Owns: generic experiment task-runner contracts, workload context, task handles/results and checkpointable workload execution semantics
- Must not own: experiment definition truth, environment provider internals, participant method semantics or run durability authority
- Requires: environment/runtime, experimentation/experiment, experimentation/run, participant/method, platform
- Provides: experiment.workload
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.experimentation__workload

### governance

- Package: noetrium_platform.foundation.governance
- Authority: none
- Canonical authority: none
- Node kind: facet
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
- Authority: none
- Canonical authority: none
- Node kind: tool
- Owns: repository-wide algorithm inventory, complexity baselines and regression gates
- Must not own: runtime execution or scientific result semantics
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__algorithm

### governance/architecture

- Package: noetrium_platform.foundation.governance.architecture
- Authority: none
- Canonical authority: none
- Node kind: tool
- Owns: architecture rules, dependencies and invariants
- Must not own: business state
- Requires: scope
- Provides: architecture.audit
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__architecture

### governance/concurrency

- Package: noetrium_platform.foundation.governance.concurrency
- Authority: none
- Canonical authority: none
- Node kind: tool
- Owns: repository-wide concurrency topology findings, reviewed debt baselines and concurrency regression gates
- Must not own: runtime task scheduling or mutable execution state
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__concurrency

### governance/gate

- Package: noetrium_platform.foundation.governance.gate
- Authority: none
- Canonical authority: none
- Node kind: policy
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
- Authority: none
- Canonical authority: none
- Node kind: tool
- Owns: repository-wide performance hotspots, reviewed debt baselines and performance regression gates
- Must not own: runtime resource scheduling or business execution
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__performance

### governance/quality

- Package: noetrium_platform.foundation.governance.quality
- Authority: none
- Canonical authority: none
- Node kind: tool
- Owns: quality gates, audits and invariants as descriptive policy
- Must not own: runtime business control
- Requires: none
- Provides: quality.audit
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__quality

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

### governance/repository_boundary

- Package: noetrium_platform.foundation.governance.repository_boundary
- Authority: none
- Canonical authority: none
- Node kind: tool
- Owns: enforce reusable upstream repository/package/release boundary
- Must not own: downstream project scientific or deployment policy
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__repository_boundary

### governance/schema

- Package: noetrium_platform.foundation.governance.schema
- Authority: none
- Canonical authority: none
- Node kind: policy
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
- Authority: none
- Canonical authority: none
- Node kind: policy
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
- Canonical authority: governance/system_registry
- Node kind: authority
- Owns: recursive system topology and ownership declarations
- Must not own: runtime orchestration
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.governance__system_registry

#### API modules

- noetrium_platform.foundation.governance.system_registry.api ?w^~)?t AuthorityDescriptor, DownstreamSurfaceMode, SYSTEM_CATALOG, SystemDescriptor, SystemIdentity, SystemLayer, SystemNodeKind, SystemRegistryChange, SystemRegistryObserver, SystemRegistryPort, TopologySourceAudit, audit_system_topology_source, system_catalog
- noetrium_platform.foundation.governance.system_registry.api.contracts ?w^~)?t AuthorityDescriptor, DownstreamSurfaceMode, STANDARD_SYSTEM_SHAPE, SystemDescriptor, SystemIdentity, SystemNodeKind, SystemRegistryChange, SystemLayer
- noetrium_platform.foundation.governance.system_registry.api.ports ?w^~)?t SystemRegistryObserver, SystemRegistryPort
- noetrium_platform.foundation.governance.system_registry.api.topology ?w^~)?t SYSTEM_CATALOG, TopologySourceAudit, audit_system_topology_source, system_catalog

### governance/evolution

- Package: noetrium_platform.foundation.governance.evolution
- Authority: none
- Canonical authority: none
- Node kind: policy
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
- Canonical authority: model
- Node kind: authority
- Owns: model assets, stacks, assignments, deployments and serving identity
- Must not own: process lifecycle implementation and experiment semantics
- Requires: artifact, environment, platform, resource, runtime, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model

#### API modules

- noetrium_platform.capabilities.model.api ?w^~)?t ModelRequestContextExceeded, ModelRequestTokenBudget, ModelRequestTokenizationIdentity, ModelRequestTokenizationPort, ModelRequestTokenizationProviderPort, EmbeddingInput, MultimodalMethodSpec, MultimodalPart, MultimodalRequest, MultimodalRequestCodecPort, MultimodalResponse, EmbeddingOutput, EmbeddingVector, ModelCapabilityInput, ModelCapabilityInvocation, ModelCapabilityOutput, ModelCapabilityResponse, NamedScalar, ProjectModelStreamingCapabilityProviderPort, ProjectModelStreamingCapabilityClientPort, ModelCapabilityStreamTerminal, ModelCapabilityStreamSession, ModelCapabilityStreamDisposition, ModelCapabilityStreamChunk, PolicyActionProbability, PolicyInferenceInput, PolicyInferenceOutput, RankedCandidate, RankingCandidate, RankingInput, RankingOutput, ProjectModelCapabilityClientPort, ProjectModelCapabilityProviderPort, ScoredCandidate, ScoringCandidate, ScoringInput, ScoringOutput, StructuredGenerationOutput, StructuredGenerationInput, StructuredGenerationDecoderPort, ValueInferenceInput, ValueInferenceOutput, ModelPromotionDecision, ModelPromotionDisposition, ModelPromotionReceipt, ModelRevisionAuthorityPort, ModelRevisionAuthoritySnapshot, ModelRevisionCommit, ModelRevisionConflictError, ModelRevisionEvidence, ModelRevisionEvidenceKind, ModelRevisionIdentity, ModelRevisionIntegrityError, ModelRevisionStateError, ModelRollbackReceipt, ModelUpdateBuildEvidence, ModelUpdateBuildReceipt, ModelUpdatePlan, ModelUpdateProducerPort, ModelUpdateProposal, ModelUpdateSource, PreparedModelRevision, ModelAuthorities, ModelBindingSelectionReceipt, ModelBindingDiagnostic, ModelBindingDiagnosticCode, ModelBindingDiagnosticSeverity, ModelCapabilityRequirement, ModelProjectBindingError, ModelProjectDefinition, MultimodalInferenceOutput, MultimodalInferenceInput, MultimodalContent, ModelRequirementContribution, ModelProviderProfile, ProjectModelBinding, ProjectModelBindingSet, ProjectModelClientPort, ProjectModelProviderPort, ProjectModelRequest, ProjectModelResponse
- noetrium_platform.capabilities.model.api.authorities ?w^~)?t ModelAuthorities
- noetrium_platform.capabilities.model.api.capability ?w^~)?t EmbeddingInput, EmbeddingOutput, EmbeddingVector, ModelCapabilityInput, ModelCapabilityInvocation, ModelCapabilityOutput, ModelCapabilityResponse, NamedScalar, ProjectModelStreamingCapabilityProviderPort, ProjectModelStreamingCapabilityClientPort, ModelCapabilityStreamTerminal, ModelCapabilityStreamSession, ModelCapabilityStreamDisposition, ModelCapabilityStreamChunk, PolicyActionProbability, PolicyInferenceInput, PolicyInferenceOutput, RankedCandidate, RankingCandidate, RankingInput, RankingOutput, ProjectModelCapabilityClientPort, ProjectModelCapabilityProviderPort, ScoredCandidate, ScoringCandidate, ScoringInput, ScoringOutput, StructuredGenerationOutput, StructuredGenerationDecoderPort, ValueInferenceInput, ValueInferenceOutput
- noetrium_platform.capabilities.model.api.multimodal ?w^~)?t MultimodalMethodSpec, MultimodalPart, MultimodalRequest, MultimodalRequestCodecPort, MultimodalResponse
- noetrium_platform.capabilities.model.api.project ?w^~)?t ModelBindingSelectionReceipt, ModelBindingDiagnostic, ModelBindingDiagnosticCode, ModelBindingDiagnosticSeverity, ModelCapabilityRequirement, ModelProjectBindingError, ModelProjectDefinition, MultimodalInferenceOutput, MultimodalInferenceInput, MultimodalContent, ModelRequirementContribution, ModelProviderProfile, ProjectModelBinding, ProjectModelBindingSet, ProjectModelClientPort, ProjectModelProviderPort, ProjectModelRequest, ProjectModelResponse, StructuredGenerationInput
- noetrium_platform.capabilities.model.api.tokenization ?w^~)?t ModelRequestContextExceeded, ModelRequestTokenBudget, ModelRequestTokenizationIdentity, ModelRequestTokenizationPort, ModelRequestTokenizationProviderPort

### model/asset

- Package: noetrium_platform.capabilities.model.asset
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: facet
- Owns: model families/revisions catalog and metadata
- Must not own: live deployment state
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__catalog

### model/catalog/family

- Package: noetrium_platform.capabilities.model.catalog.family
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: policy
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
- Authority: none
- Canonical authority: model
- Node kind: facet
- Owns: model request identity, exact input contract and response envelope
- Must not own: business result semantics
- Requires: none
- Provides: model.request
- Downstream surface: public
- Facade: noetrium.contracts.systems.model__request

#### API modules

- noetrium_platform.capabilities.model.request.api ?w^~)?t ExecutionContext, ImmutableModelIdentity, ModelRequestEnvelope, ModelRequestLedgerPort, ModelRequestRecorderPort, ReconstructedModelRequest
- noetrium_platform.capabilities.model.request.api.contracts ?w^~)?t ModelRequestEnvelope, ModelRequestLedgerPort, ModelRequestRecorderPort, ReconstructedModelRequest

### model/request/input

- Package: noetrium_platform.capabilities.model.request.input
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: model
- Node kind: adapter
- Owns: serving endpoint contract and request routing semantics
- Must not own: model catalog metadata
- Requires: none
- Provides: model.serving, model.qualification
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.model__serving

### model/serving/endpoint

- Package: noetrium_platform.capabilities.model.serving.endpoint
- Authority: none
- Canonical authority: model
- Node kind: adapter
- Owns: serving endpoint identity and exposure contract
- Must not own: request result truth
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.model__serving__endpoint

### model/stack

- Package: noetrium_platform.capabilities.model.stack
- Authority: none
- Canonical authority: model
- Node kind: facet
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
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: logs, telemetry, traces, status and observation projections
- Must not own: durable state/failure authority
- Requires: data, governance, platform, scope
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability

### observability/capture

- Package: noetrium_platform.evidence.observability.capture
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: raw byte/event/process capture contracts
- Must not own: semantic log interpretation
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__capture

### observability/diagnostic

- Package: noetrium_platform.evidence.observability.diagnostic
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: operator-facing diagnostic correlation contracts
- Must not own: failure/state authority
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__diagnostic

### observability/diagnostic/correlation

- Package: noetrium_platform.evidence.observability.diagnostic.correlation
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: cross-system correlation graph for diagnostic references
- Must not own: causal authority
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__diagnostic__correlation

### observability/diagnostic/query

- Package: noetrium_platform.evidence.observability.diagnostic.query
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: operator/debug query language over observation sources
- Must not own: source mutation
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__diagnostic__query

### observability/diagnostic/snapshot

- Package: noetrium_platform.evidence.observability.diagnostic.snapshot
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: portable diagnostic snapshots assembled from existing authorities
- Must not own: new business truth
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__diagnostic__snapshot

### observability/logging

- Package: noetrium_platform.evidence.observability.logging
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: structured logs, context, sinks, stores, queries, retention and capture
- Must not own: failure taxonomy and recovery
- Requires: none
- Provides: logging.observation
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging

### observability/logging/capture

- Package: noetrium_platform.evidence.observability.logging.capture
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: raw process/stream/event capture before semantic logging
- Must not own: semantic event taxonomy
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__capture

### observability/logging/context

- Package: noetrium_platform.evidence.observability.logging.context
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: diagnostic context construction and propagation metadata
- Must not own: log record persistence and query
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__context

### observability/logging/projection

- Package: noetrium_platform.evidence.observability.logging.projection
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: derived log indexes and projections
- Must not own: source log truth
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__projection

### observability/logging/query

- Package: noetrium_platform.evidence.observability.logging.query
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: log query contracts and filtering
- Must not own: log writes
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__query

### observability/logging/record

- Package: noetrium_platform.evidence.observability.logging.record
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: structured log schema, normalization and identity
- Must not own: sink routing and storage
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__record

### observability/logging/retention

- Package: noetrium_platform.evidence.observability.logging.retention
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: retention, archival and deletion policy for logs
- Must not own: failure retention and artifact retention
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__retention

### observability/logging/routing

- Package: noetrium_platform.evidence.observability.logging.routing
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: log routing rules and fan-out decisions
- Must not own: log storage mutation
- Requires: none
- Provides: logging.routing
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__routing

### observability/logging/sink

- Package: noetrium_platform.evidence.observability.logging.sink
- Authority: none
- Canonical authority: none
- Node kind: provider
- Owns: sink contracts and delivery lifecycle
- Must not own: query/index semantics
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__sink

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

### observability/projection

- Package: noetrium_platform.evidence.observability.projection
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: observation projections/indexes and read models
- Must not own: source-of-truth mutation
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__projection

### observability/status

- Package: noetrium_platform.evidence.observability.status
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: health/status observations and status projections
- Must not own: authoritative lifecycle state
- Requires: none
- Provides: status.read-model
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__status

### observability/status/health

- Package: noetrium_platform.evidence.observability.status.health
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: health observations and health snapshots
- Must not own: authoritative lifecycle transitions
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__status__health

### observability/status/lifecycle_view

- Package: noetrium_platform.evidence.observability.status.lifecycle_view
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: read-only lifecycle status views
- Must not own: lifecycle state authority
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__status__lifecycle_view

### observability/telemetry

- Package: noetrium_platform.evidence.observability.telemetry
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: metrics/events/counters and telemetry routing
- Must not own: durable domain state
- Requires: none
- Provides: telemetry.metrics
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__telemetry

### observability/telemetry/event

- Package: noetrium_platform.evidence.observability.telemetry.event
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: structured telemetry event definitions and emission contracts
- Must not own: durable facts
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__telemetry__event

### observability/telemetry/metric

- Package: noetrium_platform.evidence.observability.telemetry.metric
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: metric definitions, aggregation and metric identity
- Must not own: business result truth
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__telemetry__metric

### observability/tracing

- Package: noetrium_platform.evidence.observability.tracing
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: trace/span identity and propagation
- Must not own: business operation truth
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__tracing

### observability/tracing/context

- Package: noetrium_platform.evidence.observability.tracing.context
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: trace/span context creation and attachment
- Must not own: business operation state
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__tracing__context

### observability/tracing/propagation

- Package: noetrium_platform.evidence.observability.tracing.propagation
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: cross-process trace propagation contracts
- Must not own: trace storage
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__tracing__propagation

### observability/tracing/storage

- Package: noetrium_platform.evidence.observability.tracing.storage
- Authority: none
- Canonical authority: none
- Node kind: provider
- Owns: trace/span storage backends
- Must not own: trace identity semantics
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__tracing__storage

### operator

- Package: noetrium_platform.product.operator
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: human-facing query, command, maintenance and incident surfaces
- Must not own: domain authority and business state
- Requires: environment, execution, experimentation, governance, model, observability, platform, portfolio, reliability, resource, scope
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator

### operator/audit

- Package: noetrium_platform.product.operator.audit
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: audit/reporting views across system authorities
- Must not own: new durable truth
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__audit

### operator/command

- Package: noetrium_platform.product.operator.command
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: operator command intent and command result contracts
- Must not own: domain command execution
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__command

### operator/command/intent

- Package: noetrium_platform.product.operator.command.intent
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: human command intents and authorization context
- Must not own: command execution side effects
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__command__intent

### operator/incident

- Package: noetrium_platform.product.operator.incident
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: incident triage and incident work surfaces
- Must not own: incident authority
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__incident

### operator/maintenance

- Package: noetrium_platform.product.operator.maintenance
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: maintenance workflows and administrative actions
- Must not own: provider internals
- Requires: runtime
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__maintenance

### operator/query

- Package: noetrium_platform.product.operator.query
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: operator read/query contracts
- Must not own: durable state mutation
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__query

### operator/query/search

- Package: noetrium_platform.product.operator.query.search
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: human-readable search and filtering over read-side projections
- Must not own: authoritative writes
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator__query__search

### participant

- Package: noetrium_platform.capabilities.participant
- Authority: participant_state
- Canonical authority: participant
- Node kind: authority
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
- Authority: none
- Canonical authority: participant
- Node kind: facet
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
- Authority: none
- Canonical authority: participant
- Node kind: facet
- Owns: agent participant contracts, provider-independent agent identity and bounded cognition-loop orchestration
- Must not own: model serving lifecycle
- Requires: model
- Provides: agent.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__agent

#### API modules

- noetrium_platform.capabilities.participant.agent.api ?w^~)?t AgentIdentity, AgentSession, AgentSnapshot, AgentTurnRequest, AgentTurnResult, AgentImplementation, AgentActionExecutorPort, AgentActionSequence, AgentActionStep, AgentActionSummary, AgentCognitionError, AgentCompletionDecision, AgentCompletionDisposition, AgentCompletionPort, AgentDiagnosticsPort, AgentEvidencePort, AgentGoal, AgentLoopCheckpoint, AgentLoopResult, AgentLoopTerminationReason, AgentMemoryContext, AgentModeDecision, AgentModeDisposition, AgentMemoryPort, AgentObservation, AgentObservationPort, AgentPlannerPort, AgentPlanningRequest, AgentProgressPort, AgentReactiveModePort, AgentReceiptCheckpoint, AgentSafetyDecision, AgentSafetyDisposition, AgentSafetySupervisorPort, AgentSkillCatalogPort, AgentSkillDescription, AgentSkillRecord, AgentSkillSelection, AgentStepReceipt, action_summary_payload, JsonObject, JsonValue
- noetrium_platform.capabilities.participant.agent.api.cognition ?w^~)?t AgentActionSequence, AgentActionStep, AgentActionSummary, AgentCognitionError, AgentGoal, AgentLoopCheckpoint, AgentLoopResult, AgentLoopTerminationReason, AgentMemoryContext, AgentModeDecision, AgentModeDisposition, AgentObservation, AgentPlanningRequest, AgentReceiptCheckpoint, AgentSafetyDecision, AgentSafetyDisposition, AgentSkillDescription, AgentSkillRecord, AgentSkillSelection, AgentStepReceipt, action_summary_payload, JsonObject, JsonValue
- noetrium_platform.capabilities.participant.agent.api.cognition_ports ?w^~)?t AgentActionExecutorPort, AgentCompletionPort, AgentDiagnosticsPort, AgentEvidencePort, AgentMemoryPort, AgentObservationPort, AgentPlannerPort, AgentProgressPort, AgentReactiveModePort, AgentSafetySupervisorPort, AgentSkillCatalogPort
- noetrium_platform.capabilities.participant.agent.api.completion ?w^~)?t AgentCompletionDecision, AgentCompletionDisposition
- noetrium_platform.capabilities.participant.agent.api.contracts ?w^~)?t CapabilityPort, ExecutionContext, JsonInput, JsonValue, freeze_json, require_sha256, AgentIdentity, AgentSnapshot, AgentTurnRequest, AgentTurnResult, AgentSession, AgentImplementation

### participant/binding

- Package: noetrium_platform.capabilities.participant.binding
- Authority: none
- Canonical authority: participant
- Node kind: facet
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
- Authority: none
- Canonical authority: participant
- Node kind: facet
- Owns: participant capability declarations and exposure
- Must not own: execution capability implementation
- Requires: none
- Provides: capability.contract
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__capability

#### API modules

- noetrium_platform.capabilities.participant.capability.api ?w^~)?t CapabilityApprovalDenied, CapabilityApprovalPort, CapabilityCarrierTransportPort, CapabilityDescriptor, CapabilityEffectReconciliationResult, CapabilityExportSession, CapabilityGuardPort, CapabilityInputCarrier, CapabilityOutputCarrier, CapabilityPolicyDenied, CapabilityPolicySet, CapabilityPort, CapabilityPostPolicyPort, CapabilityPostPolicyViolation, CapabilityProviderImplementation, CapabilityProviderIdentity, CapabilityProviderSession, CapabilityRequest, CapabilityResult, CapabilitySelectionReference, CapabilitySelectionView, DurablePreparedCapabilitySession, GuardDecision, GuardVerdict, TypedCapabilityCarrierCodec, TypedCarrierReference, capability_effect_request_id, capability_request_digest, decode_typed_capability_input, decode_typed_capability_result, make_typed_capability_request, make_typed_capability_result, materialize_capability_selection_view, require_pure_typed_descriptor
- noetrium_platform.capabilities.participant.capability.api.contracts ?w^~)?t EffectReconciliationDisposition, PreparedEffectHandle, EffectClass, EffectReceipt, ExecutionContext, JsonObject, JsonValue, canonical_digest, freeze_json, CapabilityProviderIdentity, CapabilityDescriptor, CapabilityRequest, capability_effect_request_id, capability_request_digest, CapabilityResult, CapabilityEffectReconciliationResult, DurablePreparedCapabilitySession, CapabilityPort, CapabilityExportSession, CapabilityProviderSession, CapabilityProviderImplementation
- noetrium_platform.capabilities.participant.capability.api.policy ?w^~)?t CapabilityApprovalDenied, CapabilityApprovalPort, CapabilityGuardPort, CapabilityPolicyDenied, CapabilityPolicySet, CapabilityPostPolicyPort, CapabilityPostPolicyViolation, GuardDecision, GuardVerdict
- noetrium_platform.capabilities.participant.capability.api.selection ?w^~)?t CapabilitySelectionReference, CapabilitySelectionView, materialize_capability_selection_view
- noetrium_platform.capabilities.participant.capability.api.typed ?w^~)?t CapabilityCarrierTransportPort, CapabilityInputCarrier, CapabilityOutputCarrier, TypedCapabilityCarrierCodec, TypedCarrierReference, decode_typed_capability_input, decode_typed_capability_result, make_typed_capability_request, make_typed_capability_result, require_pure_typed_descriptor

### participant/definition

- Package: noetrium_platform.capabilities.participant.definition
- Authority: none
- Canonical authority: participant
- Node kind: facet
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
- Authority: none
- Canonical authority: participant
- Node kind: facet
- Owns: method participant binding contracts
- Must not own: method implementation itself
- Requires: governance
- Provides: method.contract, method.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.participant__method

#### API modules

- noetrium_platform.capabilities.participant.method.api ?w^~)?t IdempotentTaskCompletionSession, MethodIdentity, MethodCompositionPorts, MethodEndpointFactoryPort, MethodEndpointPort, MethodImplementation, MethodObservation, MethodProgramIdentity, MethodProgramIdentityMismatch, MethodObservationDeliveryError, MethodObservationOutboxFactoryPort, MethodObservationOutboxPort, MethodObservationSink, MethodRuntimeBinding, MethodRuntimeIdentity, MethodServices, MethodSession, MethodSessionRuntime, MethodSystemBinding, MethodSnapshot, MethodTaskCompletionReceipt, MethodTaskOutcome, RecallRequest, RecallResult, TaskCompletionReconciliationSession, TaskCompletionSafetyCapabilityMissing
- noetrium_platform.capabilities.participant.method.api.binding ?w^~)?t MethodSystemBinding
- noetrium_platform.capabilities.participant.method.api.contracts ?w^~)?t ExecutionContext, JsonValue, canonical_digest, require_sha256, MethodIdentity, MethodProgramIdentity, MethodProgramIdentityMismatch, MethodSnapshot, RecallRequest, RecallResult, MethodTaskOutcome, MethodTaskCompletionReceipt, IdempotentTaskCompletionSession, TaskCompletionReconciliationSession, MethodSession
- noetrium_platform.capabilities.participant.method.api.errors ?w^~)?t TaskCompletionSafetyCapabilityMissing
- noetrium_platform.capabilities.participant.method.api.observability ?w^~)?t ExecutionContext, JsonValue, canonical_bytes, freeze_json, MethodObservation, MethodObservationDeliveryError, MethodObservationSink, MethodObservationOutboxPort, MethodObservationOutboxFactoryPort, MethodServices
- noetrium_platform.capabilities.participant.method.api.ports ?w^~)?t MethodCompositionPorts, MethodEndpointFactoryPort, MethodEndpointPort, MethodImplementation, MethodRuntimeBinding, MethodRuntimeIdentity, MethodSessionRuntime

### participant/session

- Package: noetrium_platform.capabilities.participant.session
- Authority: none
- Canonical authority: participant
- Node kind: facet
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

### platform/concurrency

- Package: noetrium_platform.foundation.kernel.concurrency
- Authority: none
- Canonical authority: platform
- Node kind: facet
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
- Authority: none
- Canonical authority: platform
- Node kind: facet
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
- Authority: none
- Canonical authority: platform
- Node kind: facet
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
- Authority: none
- Canonical authority: platform
- Node kind: facet
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

### portfolio/membership

- Package: noetrium_platform.foundation.portfolio.membership
- Authority: none
- Canonical authority: portfolio
- Node kind: facet
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
- Authority: none
- Canonical authority: portfolio
- Node kind: facet
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
- Authority: none
- Canonical authority: portfolio
- Node kind: facet
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
- Authority: none
- Canonical authority: portfolio
- Node kind: facet
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
- Authority: none
- Canonical authority: none
- Node kind: facet
- Owns: effects, failures, incidents, forensics, diagnosis, reconciliation and recovery
- Must not own: scientific truth and UI projections
- Requires: data, governance, observability, platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.reliability

### reliability/diagnostics

- Package: noetrium_platform.infrastructure.reliability.diagnostics
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: read-side cross-system correlation and root-cause views
- Must not own: durable authority mutation
- Requires: none
- Provides: diagnostics.causal
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.reliability__diagnostics

### reliability/effect

- Package: noetrium_platform.infrastructure.reliability.effect
- Authority: effect_authority
- Canonical authority: reliability/effect
- Node kind: authority
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

### reliability/forensics

- Package: noetrium_platform.infrastructure.reliability.forensics
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: durable evidence bundles, causal evidence and forensic indexes
- Must not own: business result semantics
- Requires: none
- Provides: forensics.ledger
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.reliability__forensics

### reliability/recovery

- Package: noetrium_platform.infrastructure.reliability.recovery
- Authority: none
- Canonical authority: none
- Node kind: adapter
- Owns: recovery plans, exact replay/reconcile and recovery lifecycle
- Must not own: provider storage internals
- Requires: resource
- Provides: recovery.runtime
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.reliability__recovery

### reliability/recovery/execution

- Package: noetrium_platform.infrastructure.reliability.recovery.execution
- Authority: none
- Canonical authority: none
- Node kind: adapter
- Owns: recovery execution lifecycle and effect handoff
- Must not own: failure taxonomy
- Requires: none
- Provides: recovery.execution
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.reliability__recovery__execution

### resource

- Package: noetrium_platform.infrastructure.resources
- Authority: resource_inventory
- Canonical authority: resource
- Node kind: authority
- Owns: resource inventory, compute, directories, leases and allocation/resolution
- Must not own: environment semantics and model deployment truth
- Requires: platform, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource

### resource/allocation

- Package: noetrium_platform.infrastructure.resources.allocation
- Authority: none
- Canonical authority: resource
- Node kind: facet
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
- Authority: none
- Canonical authority: resource
- Node kind: facet
- Owns: compute resource identity, capacities and provider facts
- Must not own: environment packaging
- Requires: runtime/process, resource/lease
- Provides: compute.inventory, compute.scheduler
- Downstream surface: public
- Facade: noetrium.contracts.systems.resource__compute

#### API modules

- noetrium_platform.infrastructure.resources.compute.api ?w^~)?t ComputeAllocation, ComputeCandidatePort, ComputeCluster, ComputeGPU, ComputeHost, ComputeRequirement, ComputeLeasePolicy, DEFAULT_COMPUTE_LEASE_POLICY, ComputeInventoryPort, ComputeLeaseGuardFactoryPort, ComputeLeaseGuardPort, ComputeSchedulerPort, GpuSharingMode, GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, HostRuntimeObserverPort, HostRuntimeSnapshot, HostRuntimeStatus
- noetrium_platform.infrastructure.resources.compute.api.contracts ?w^~)?t ComputeAllocation, ComputeCluster, ComputeGPU, ComputeHost, ComputeRequirement, ComputeLeasePolicy, DEFAULT_COMPUTE_LEASE_POLICY, GpuSharingMode
- noetrium_platform.infrastructure.resources.compute.api.ports ?w^~)?t ComputeCandidatePort, ComputeInventoryPort, ComputeLeaseGuardFactoryPort, ComputeLeaseGuardPort, ComputeSchedulerPort
- noetrium_platform.infrastructure.resources.compute.api.runtime_status ?w^~)?t GpuDeviceStatus, GpuProcessStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, HostRuntimeObserverPort, HostRuntimeSnapshot, HostRuntimeStatus

### resource/directory

- Package: noetrium_platform.infrastructure.resources.directory
- Authority: none
- Canonical authority: resource
- Node kind: facet
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

### resource/resolution

- Package: noetrium_platform.infrastructure.resources.resolution
- Authority: none
- Canonical authority: resource
- Node kind: policy
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
- Canonical authority: runtime
- Node kind: authority
- Owns: server, process, service and session orchestration
- Must not own: experiment semantics and model catalog truth
- Requires: governance, observability, platform, reliability, resource, scope
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime

#### API modules

- noetrium_platform.infrastructure.lifecycle.api ?w^~)?t LifecycleComponent, LifecycleEvidence, LifecyclePhase, LifecycleSpec, SystemIdentity, SystemPort, SystemSpec
- noetrium_platform.infrastructure.lifecycle.api.component ?w^~)?t LifecycleComponent, LifecycleEvidence, LifecyclePhase, LifecycleSpec
- noetrium_platform.infrastructure.lifecycle.api.contracts ?w^~)?t SystemIdentity, SystemPort, SystemSpec
- noetrium_platform.infrastructure.lifecycle.api.ports ?w^~)?t SystemPort, SystemSpec

### runtime/host

- Package: noetrium_platform.infrastructure.lifecycle.host
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: adapter
- Owns: process health/reconcile loops
- Must not own: durable runtime history storage
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.runtime__process__supervision

### runtime/server

- Package: noetrium_platform.infrastructure.lifecycle.server
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: facet
- Owns: managed service identity, registration and lifecycle
- Must not own: scientific truth
- Requires: none
- Provides: service.runtime
- Downstream surface: public
- Facade: noetrium.contracts.systems.runtime__service

#### API modules

- noetrium_platform.infrastructure.lifecycle.service.api ?w^~)?t ExactServiceRuntimePort, ServiceEnvironmentPort, ServiceLaunchPreflightPort, ServiceLaunchPreflightReport, ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity, ServiceReadyObservation, ServiceReconcileObservation, ServiceStartOutcome, ServiceStopOutcome
- noetrium_platform.infrastructure.lifecycle.service.api.contracts ?w^~)?t ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity
- noetrium_platform.infrastructure.lifecycle.service.api.ports ?w^~)?t ExactServiceRuntimePort, ServiceEnvironmentPort, ServiceLaunchPreflightReport, ServiceLaunchPreflightPort, ServiceReadyObservation, ServiceReconcileObservation, ServiceStartOutcome, ServiceStopOutcome

### runtime/session

- Package: noetrium_platform.infrastructure.lifecycle.session
- Authority: none
- Canonical authority: runtime
- Node kind: facet
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
- Authority: none
- Canonical authority: runtime
- Node kind: provider
- Owns: verified host toolchain acquisition, materialization, identity and receipts
- Must not own: environment scenarios, experiment protocols, or project policy
- Requires: artifact
- Provides: runtime.toolchain
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.runtime__toolchain

### runtime/python

- Package: noetrium_platform.infrastructure.lifecycle.python
- Authority: none
- Canonical authority: runtime
- Node kind: provider
- Owns: Python interpreter environments, package lifecycle and execution bindings
- Must not own: generic process supervisor
- Requires: runtime, resource
- Provides: python-environment.registry, python-environment.lifecycle, python-environment.execution, python-environment.packages
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.runtime__python

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

- noetrium_platform.foundation.scope.api ?w^~)?t PLATFORM_SCOPE, ScopeIdentity, ScopeKind, ScopeLink, ScopeRegistryPort, scope_from_data, scope_to_data
- noetrium_platform.foundation.scope.api.codec ?w^~)?t scope_from_data, scope_to_data
- noetrium_platform.foundation.scope.api.contracts ?w^~)?t PLATFORM_SCOPE, ScopeIdentity, ScopeKind, ScopeLink
- noetrium_platform.foundation.scope.api.ports ?w^~)?t ScopeRegistryPort

### scope/hierarchy

- Package: noetrium_platform.foundation.scope.hierarchy
- Authority: none
- Canonical authority: scope
- Node kind: facet
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
- Authority: none
- Canonical authority: scope
- Node kind: facet
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
- Authority: none
- Canonical authority: scope
- Node kind: facet
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
- Authority: none
- Canonical authority: scope
- Node kind: facet
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
- Authority: none
- Canonical authority: scope
- Node kind: facet
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
- Authority: none
- Canonical authority: scope
- Node kind: facet
- Owns: resolve a scope reference to canonical scope path
- Must not own: domain-specific lookup semantics
- Requires: none
- Provides: none
- Downstream surface: public
- Facade: noetrium.contracts.systems.scope__resolution

#### API modules

- noetrium_platform.foundation.scope.resolution.api.boundary ?w^~)?t SystemLeafContract, contract

