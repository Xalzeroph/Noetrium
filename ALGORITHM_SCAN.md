# Algorithm Governance Report

- Source digest: `7dccc9108cffb2c1ba769e86323c4d9081b269a2b61e082b417bff643fca117a`
- Analyzer revision: `javascript:javascript-structural-v2|python:python-ast-v4|shell:shell-structural-v2`
- Symbols: **5732**
- Optimization candidates: **348**

## Coverage

| Language | Files | Symbols | Parse errors |
|---|---:|---:|---:|
| javascript | 8 | 103 | 0 |
| python | 2444 | 5623 | 0 |
| shell | 2 | 6 | 0 |

## Candidate debt by system

| System | Candidates |
|---|---:|
| governance | 134 |
| environment | 50 |
| model | 32 |
| runtime | 21 |
| platform | 20 |
| reliability | 19 |
| experimentation | 16 |
| participant | 11 |
| observability | 11 |
| scripts | 11 |
| execution | 9 |
| resource | 7 |
| artifact | 4 |
| operator | 2 |
| tests_support.py | 1 |

## Top 100 hotspots

| Score | Complexity | Symbol | Findings |
|---:|---|---|---|
| 98 | O(N^3+) | `noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/resources.js::craftItem` | deep-nested-loop |
| 84 | O(N^3+) | `noetrium_platform/capabilities/model/qualification/providers/qualification_evidence.py::FileDeploymentQualificationEvidenceStore._record` | deep-nested-loop, large-control-surface |
| 81 | recursive+iterative | `noetrium_platform/foundation/kernel/kernel/canonical.py::_normalize` | recursion-plus-loop |
| 79 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/optimization.py::analyze_optimization_risks` | deep-nested-loop |
| 79 | O(N) | `noetrium_platform/foundation/governance/architecture/source_profile.py::scan_architecture_source_profile` | complexity-contract, io-in-loop, large-control-surface |
| 76 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/effect_dependency_invariants.py::audit_effect_dependency_invariants` | deep-nested-loop |
| 74 | O(N^2) | `noetrium_platform/capabilities/model/qualification/providers/qualification_probe.py::LocalDeploymentCapabilityProbe._simple_index_snapshot` | nested-loop, large-control-surface |
| 72 | O(N^2) | `noetrium_platform/capabilities/model/serving/runtime/capacity.py::ExactCapacityPlanner.plan` | nested-loop |
| 71 | O(N^2) | `noetrium_platform/capabilities/participant/agent/runtime/cognition_loop.py::AgentCognitionLoop.run` | nested-loop, database-in-loop, large-control-surface |
| 70 | O(N) | `noetrium_platform/capabilities/model/serving/runtime/durable_recovery.py::DurableExactRecoveryRunner.run` | database-in-loop, io-in-loop |
| 70 | O(N^2) | `noetrium_platform/evidence/observability/logging/storage/runtime/jsonl.py::JsonlLogStore.query` | nested-loop, serialization-in-loop |
| 69 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/failure_dependency_invariants.py::audit_failure_dependency_invariants` | deep-nested-loop |
| 69 | O(N^3+) | `noetrium_platform/product/operator/maintenance/runtime/management/deployments.py::dispatch` | deep-nested-loop, large-control-surface |
| 68 | O(N^3+) | `noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/combat.js::attackTarget` | deep-nested-loop |
| 67 | O(N^2) | `noetrium_platform/evidence/artifact/content/providers/tar_archive.py::digest_materialized_tree` | nested-loop, serialization-in-loop |
| 67 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/observability_dependency_invariants.py::audit_observability_logging_leaf_invariants` | deep-nested-loop |
| 66 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/participant_dependency_invariants.py::audit_participant_dependency_invariants` | deep-nested-loop |
| 65 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/participant_lifecycle_invariants.py::audit_participant_lifecycle_invariants` | deep-nested-loop |
| 64 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/service_runtime_invariants.py::audit_service_runtime_invariants` | deep-nested-loop |
| 63 | O(N^2) | `noetrium_platform/infrastructure/lifecycle/server/identity/providers/catalog.py::build_server_profile_catalog` | nested-loop |
| 62 | O(N log N) | `noetrium_platform/evidence/artifact/content/providers/tar_archive.py::SafeTarArchiveMaterializer.materialize` | io-in-loop, large-control-surface |
| 62 | O(N^2) | `noetrium_platform/research/experimentation/study/runtime/protocol.py::BasicStudyMetricAggregator.aggregate` | nested-loop |
| 61 | O(N^2) | `noetrium_platform/research/experimentation/workload/runtime/batch.py::GenericWorkloadBatchExecutor.execute` | nested-loop |
| 61 | O(N log N) | `noetrium_platform/foundation/governance/release/runtime/package_verification.py::verify_release_package` | complexity-review |
| 61 | O(N^2) | `noetrium_platform/infrastructure/reliability/forensics/runtime/catalog_audit.py::FailureCatalogSourceAudit.run` | nested-loop, io-in-loop |
| 60 | O(N^2) | `noetrium_platform/research/experimentation/experiment/api/tasks.py::validate_task_graph` | nested-loop |
| 60 | O(N^2) | `noetrium_platform/composition/execution_observability.py::build_execution_capacity_facts` | nested-loop |
| 59 | O(N^2) | `noetrium_platform/foundation/governance/algorithm/runtime/diff.py::diff_snapshots` | nested-loop |
| 59 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/capability_composition_invariants.py::audit_capability_composition_boundaries` | deep-nested-loop |
| 59 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/import_graph.py::scan_imports` | deep-nested-loop |
| 58 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/audit.py::ArchitectureAudit.run` | deep-nested-loop |
| 58 | O(N^3+) | `noetrium_platform/foundation/governance/repository_boundary/runtime/audit.py::_audit_core_imports` | deep-nested-loop, io-in-loop |
| 58 | O(N^2) | `noetrium_platform/capabilities/model/qualification/runtime/qualification.py::DeploymentQualificationResolver._append_native_cuda_runtime` | nested-loop |
| 56 | O(N^2) | `noetrium_platform/research/experimentation/run/manifest/api/contracts.py::RunLaunchManifest.__post_init__` | nested-loop |
| 56 | O(N^2) | `noetrium_platform/foundation/governance/architecture/participant_binding_invariants.py::audit_participant_binding_invariants` | nested-loop |
| 55 | O(N^2) | `noetrium_platform/research/experimentation/run/manifest/runtime/evidence.py::decode_evidence_bundle_manifest` | nested-loop |
| 55 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/service_api_invariants.py::audit_service_api_invariants` | deep-nested-loop |
| 55 | O(N^2) | `noetrium_platform/foundation/kernel/concurrency/providers/serial_lane.py::SharedSerialExecutionLaneFactory._run` | nested-loop, lock-in-loop |
| 54 | O(N) | `noetrium_platform/research/execution/capability/runtime/scoped_registry.py::ScopedRegistrationRuntime.dispose` | lock-in-loop |
| 54 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/composition_workflow_invariants.py::audit_workflow_family_firewall` | deep-nested-loop |
| 53 | O(N^3+) | `noetrium_platform/research/experimentation/experiment/runtime/participant_topology.py::ExperimentParticipantTopology.ordered` | deep-nested-loop |
| 53 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/composition_root_invariants.py::audit_composition_root_imports` | deep-nested-loop |
| 53 | O(N^2) | `noetrium_platform/infrastructure/reliability/forensics/providers/segment_verifier.py::scan_segment_chain_payloads` | nested-loop, io-in-loop, serialization-in-loop |
| 53 | O(N) | `noetrium_platform/infrastructure/lifecycle/server/health/runtime/diagnostics.py::ServerDiagnosticProjector.project` | complexity-review |
| 53 | O(N) | `noetrium_platform/infrastructure/lifecycle/server/runtime/operation_journal.py::JsonlServerOperationJournal._read_records` | serialization-in-loop |
| 52 | O(N log N) | `noetrium_platform/capabilities/environment/minecraft/runtime/state.py::MinecraftStateProjection.from_compact` | large-control-surface |
| 52 | O(N^2) | `noetrium_platform/research/execution/lifecycle/manager.py::LifecycleManager._topological_order` | nested-loop |
| 52 | O(N^2) | `noetrium_platform/foundation/governance/algorithm/providers/filesystem.py::RepositorySourceInventory.documents` | nested-loop, io-in-loop, serialization-in-loop |
| 52 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/status_invariants.py::audit_status_invariants` | deep-nested-loop |
| 51 | O(N^2) | `noetrium_platform/foundation/governance/algorithm/runtime/diff.py::gate_against_baseline` | nested-loop |
| 51 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/composition_family_invariants.py::audit_composition_family_firewall` | deep-nested-loop |
| 51 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/composition_participant_invariants.py::audit_generic_participant_signatures` | deep-nested-loop |
| 51 | O(N^2) | `noetrium_platform/foundation/governance/architecture/model_dependency_invariants.py::audit_model_dependency_invariants` | nested-loop |
| 51 | O(N^2) | `noetrium_platform/foundation/governance/concurrency/providers/filesystem.py::RepositoryConcurrencySourceInventory.documents` | nested-loop, io-in-loop, serialization-in-loop |
| 51 | O(N^2) | `noetrium_platform/foundation/governance/performance/providers/filesystem.py::RepositoryPerformanceSourceInventory.documents` | nested-loop, io-in-loop, serialization-in-loop |
| 51 | O(N) | `noetrium_platform/evidence/observability/capture/providers/file_persistence.py::FileRawObservationPersistence.verify` | serialization-in-loop |
| 50 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/document_integrity_invariants.py::audit_document_integrity_invariants` | deep-nested-loop |
| 50 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/import_graph.py::package_cycles` | deep-nested-loop |
| 50 | O(N) | `noetrium_platform/capabilities/model/qualification/providers/qualification_probe.py::LocalDeploymentCapabilityProbe._index` | large-control-surface |
| 50 | O(N^2) | `noetrium_platform/evidence/observability/logging/storage/runtime/jsonl.py::_decode_record` | nested-loop |
| 50 | O(N^2) | `noetrium_platform/infrastructure/lifecycle/session/runtime/environment.py::load_controller_environment` | nested-loop |
| 49 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/operator_route_invariants.py::audit_operator_route_invariants` | deep-nested-loop |
| 48 | O(N^3+) | `noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge/resources.js::smeltItem` | deep-nested-loop |
| 48 | O(N^2) | `noetrium_platform/capabilities/environment/minecraft/runtime/tasks.py::MinecraftTaskSpec.from_mapping` | nested-loop |
| 48 | O(N log N) | `noetrium_platform/foundation/governance/algorithm/runtime/scanner.py::AlgorithmScanner.scan` | serialization-in-loop |
| 48 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/hotspots.py::analyze_hotspots` | deep-nested-loop |
| 48 | O(N^2) | `noetrium_platform/foundation/governance/architecture/process_invariants.py::audit_process_invariants` | nested-loop |
| 48 | O(N^2) | `noetrium_platform/foundation/governance/architecture/seam_graphs.py::_scan_file` | nested-loop, large-control-surface |
| 48 | O(N^2) | `noetrium_platform/foundation/governance/architecture/source_profile.py::_scan_seams` | nested-loop, large-control-surface |
| 48 | recursive+iterative | `noetrium_platform/foundation/governance/concurrency/runtime/python_analyzer.py::PythonConcurrencyAnalyzer.analyze.walk` | nested-loop, recursion-plus-loop |
| 48 | recursive+iterative | `noetrium_platform/product/operator/maintenance/runtime/management_cli.py::_plain` | recursion-plus-loop |
| 48 | O(N^2) | `noetrium_platform/infrastructure/lifecycle/server/identity/providers/profile_file.py::load_server_profile_environment` | nested-loop |
| 47 | O(N) | `noetrium_platform/capabilities/environment/runtime/runtime/state_machine.py::StateMachineEnvironmentSession._decode_result` | large-control-surface |
| 47 | O(N^2) | `noetrium_platform/capabilities/environment/runtime/runtime/state_machine.py::StateMachineEnvironmentSession.restore` | nested-loop, large-control-surface |
| 47 | O(N) | `noetrium_platform/research/execution/capability/runtime/scoped_registry.py::ScopedRegistrationRuntime._unregister` | lock-in-loop |
| 47 | O(N log N) | `noetrium_platform/research/experimentation/run/manifest/api/evidence.py::EvidenceBundleManifest.__post_init__` | complexity-review |
| 47 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/recovery_invariants.py::_audit_contract_firewall` | deep-nested-loop |
| 47 | O(N^2) | `noetrium_platform/foundation/governance/architecture/runtime_state_invariants.py::audit_runtime_state_invariants` | nested-loop |
| 47 | O(N^2) | `noetrium_platform/foundation/governance/quality/silent_failure.py::scan_silent_failures` | nested-loop, io-in-loop |
| 47 | O(N^2) | `noetrium_platform/infrastructure/reliability/forensics/providers/segment_verifier.py::scan_segment_chain` | nested-loop, io-in-loop, serialization-in-loop |
| 47 | O(N) | `noetrium_platform/infrastructure/resources/providers/sqlite_endpoint.py::SQLiteEndpointAllocationStore.renew_many` | complexity-review |
| 46 | O(N^2) | `noetrium_platform/foundation/governance/architecture/prompt_api_invariants.py::audit_prompt_api_invariants` | nested-loop |
| 46 | O(N^3+) | `noetrium_platform/foundation/governance/concurrency/runtime/python_analyzer.py::_LocalBlockingCatalog._summarize` | deep-nested-loop |
| 46 | O(N) | `noetrium_platform/capabilities/model/request/prompt/runtime/rendering.py::PromptRenderer.render` | serialization-in-loop |
| 46 | O(N^2) | `noetrium_platform/capabilities/participant/agent/runtime/memory.py::InMemoryAgentMemory.recall` | nested-loop |
| 46 | recursive+iterative | `noetrium_platform/foundation/kernel/kernel/errors/redaction.py::redact_value` | recursion-plus-loop |
| 46 | O(N) | `scripts/release_regression.py::_run_parallel_plans` | complexity-contract |
| 45 | O(N log N) | `noetrium_platform/capabilities/environment/catalog/runtime/catalog.py::ExecutionEnvironmentCatalog.resolve` | complexity-review |
| 45 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/error_invariants.py::_audit_error_semantic_authority` | deep-nested-loop |
| 45 | O(N^2) | `noetrium_platform/foundation/governance/architecture/model_recovery_invariants.py::audit_model_recovery_observability_boundary` | nested-loop |
| 45 | O(N) | `noetrium_platform/foundation/governance/architecture/report.py::build_architecture_report` | complexity-review |
| 45 | O(N^2) | `noetrium_platform/foundation/governance/architecture/service_supervisor_invariants.py::audit_service_supervisor_invariants` | nested-loop |
| 44 | O(N) | `noetrium_platform/research/execution/admission/runtime/authority.py::HierarchicalAdmissionAuthority.acquire` | lock-in-loop |
| 44 | O(N^2) | `noetrium_platform/foundation/governance/architecture/model_storage_invariants.py::audit_model_storage_boundaries` | nested-loop |
| 44 | O(N^2) | `noetrium_platform/foundation/governance/architecture/prompt_trace_invariants.py::audit_prompt_trace_invariants` | nested-loop |
| 44 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/source_authority_engine.py::audit_authority_rules` | deep-nested-loop |
| 44 | O(N^3+) | `noetrium_platform/foundation/governance/architecture/workflow_invariants.py::_audit_dispatch_authority` | deep-nested-loop |
| 44 | O(N^2) | `noetrium_platform/foundation/governance/quality/degradation_python_scan.py::scan_python_degradation` | nested-loop, io-in-loop |
| 44 | O(N^2) | `noetrium_platform/capabilities/model/serving/api/deployment.py::FrozenDeploymentSet.__post_init__` | nested-loop |
| 44 | O(N) | `noetrium_platform/foundation/kernel/concurrency/runtime/runtime.py::StructuredConcurrencyRuntime.close` | large-control-surface |
