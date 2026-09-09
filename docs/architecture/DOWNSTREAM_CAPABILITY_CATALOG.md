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
- Public symbols: 3663
- Registry digest: c07bdb0976a71d3a2c6102013101a02aa39f61abaa0c4a8104fb0cfc7daa24e7

## Capability domains

| Domain | Systems | API modules | Symbols |
| --- | ---: | ---: | ---: |
| artifact | 7 | 24 | 127 |
| components | 1 | 1 | 49 |
| data | 8 | 20 | 106 |
| environment | 18 | 53 | 444 |
| execution | 7 | 31 | 183 |
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

- noetrium_platform.capabilities.environment.api ?w^~)?t SystemIdentity, SystemSpec, SystemPort, ExecutionContext, EffectClass, EffectCertainty, EffectReceipt, ActionIdentityViolation, ActionNotApplied, ActionRecoveryRequired, ActionReconciliationDisposition, ActionReconciliationResult, ActionRequest, ActionResult, ActionSafetyCapabilityMissing, ActionScientificCommitContradiction, ActionSemanticIdentity, EnvironmentAssignmentIdentity, EnvironmentAssignmentIsolationPort, EnvironmentAssignmentIsolationReceipt, EnvironmentCapabilityUnsupported, EnvironmentCapability, EnvironmentConformanceProbe, EnvironmentProviderConformanceReceipt, verify_environment_provider_conformance, EnvironmentDiagnosticsPort, EnvironmentProviderCapabilities, EnvironmentProviderPort, EnvironmentSessionDiagnostics, EnvironmentSessionServices, EnvironmentActionLifecycle, EnvironmentActionPhase, EnvironmentCapabilityDescriptor, EnvironmentCoordinationPort, EnvironmentCoordinationReceipt, EnvironmentCoordinationRequest, EnvironmentQuery, EnvironmentQueryKind, EnvironmentQueryPort, EnvironmentQueryResult, EnvironmentRawEventReceipt, EnvironmentRawEventRecord, EnvironmentRawRecordSinkPort, DurablePreparedActionSession, EnvironmentIdentity, EnvironmentImplementation, EnvironmentSession, Observation, action_request_digest, require_action_recovery_handle_identity, require_action_result_identity, require_effect_receipt_digest, require_reconciliat