# Performance Governance Report

- Source digest: `7dccc9108cffb2c1ba769e86323c4d9081b269a2b61e082b417bff643fca117a`
- Hotspots: **76**
- Findings: **88**
- P0/P1 blockers: **0**

## Coverage

| Language | Files | Hotspots | Parse errors |
|---|---:|---:|---:|
| javascript | 8 | 0 | 0 |
| python | 2444 | 74 | 0 |
| shell | 2 | 2 | 0 |

## Debt by system

| System | Hotspots |
|---|---:|
| governance | 22 |
| runtime | 10 |
| environment | 9 |
| reliability | 8 |
| model | 6 |
| observability | 6 |
| experimentation | 5 |
| artifact | 3 |
| deploy | 2 |
| resource | 2 |
| execution | 2 |
| scripts | 1 |

## Top 76 hotspots

| Score | Hotspot | Findings |
|---:|---|---|
| 40 | `deploy/container-entrypoint.sh` | sync-io-density |
| 30 | `deploy/install_workspace_docker_engine.sh` | io-in-loop, sync-io-density |
| 30 | `noetrium_platform/capabilities/model/serving/runtime/durable_recovery.py::DurableExactRecoveryRunner.run` | io-in-loop |
| 28 | `noetrium_platform/evidence/artifact/content/providers/tar_archive.py::digest_materialized_tree` | serialization-in-loop |
| 28 | `noetrium_platform/capabilities/model/request/prompt/runtime/rendering.py::PromptRenderer.render` | serialization-in-loop |
| 28 | `noetrium_platform/evidence/observability/capture/providers/file_persistence.py::FileRawObservationPersistence.verify` | serialization-in-loop |
| 27 | `noetrium_platform/foundation/governance/quality/degradation_config_scan.py::scan_config_degradation` | io-in-loop, serialization-in-loop |
| 20 | `noetrium_platform/evidence/artifact/content/providers/download.py::HttpArtifactAcquirer.acquire` | io-in-loop |
| 20 | `noetrium_platform/foundation/governance/algorithm/providers/filesystem.py::RepositorySourceInventory.documents` | io-in-loop, serialization-in-loop |
| 20 | `noetrium_platform/foundation/governance/concurrency/providers/filesystem.py::RepositoryConcurrencySourceInventory.documents` | io-in-loop, serialization-in-loop |
| 20 | `noetrium_platform/foundation/governance/performance/providers/filesystem.py::RepositoryPerformanceSourceInventory.documents` | io-in-loop, serialization-in-loop |
| 20 | `noetrium_platform/foundation/governance/release/runtime/active_pin_store.py::ActiveReleasePinStore.all` | io-in-loop, serialization-in-loop |
| 20 | `noetrium_platform/foundation/governance/release/runtime/packager.py::ReleasePackager._stream_member` | io-in-loop |
| 20 | `noetrium_platform/infrastructure/resources/directory/runtime/workspaces.py::LocalWorkspaceManager.list_workspaces` | io-in-loop, serialization-in-loop |
| 20 | `noetrium_platform/infrastructure/lifecycle/process/capture/storage.py::CaptureStorage.scan_segments` | io-in-loop |
| 17 | `noetrium_platform/research/execution/runtime/manager/runtime_history_integrity.py::verify_runtime_history_lines` | serialization-in-loop |
| 17 | `noetrium_platform/evidence/observability/capture/providers/segment_recovery.py::recover_raw_segment` | serialization-in-loop |
| 17 | `noetrium_platform/evidence/observability/logging/storage/runtime/jsonl.py::JsonlLogStore.query` | serialization-in-loop |
| 17 | `noetrium_platform/infrastructure/reliability/forensics/providers/segment_verifier.py::scan_segment_chain` | io-in-loop, serialization-in-loop |
| 17 | `noetrium_platform/infrastructure/reliability/forensics/providers/segment_verifier.py::scan_segment_chain_payloads` | io-in-loop, serialization-in-loop |
| 17 | `noetrium_platform/infrastructure/lifecycle/service/runtime/linux_procfs.py::LinuxProcfsReader.environment` | serialization-in-loop |
| 16 | `noetrium_platform/research/experimentation/checkpoint/providers/directory_store.py::DirectoryRunCheckpointStore.load` | io-in-loop, whole-file-read |
| 16 | `noetrium_platform/research/experimentation/checkpoint/providers/workload_store.py::DirectoryWorkloadCheckpointStore.load` | io-in-loop, whole-file-read |
| 14 | `noetrium_platform/foundation/governance/algorithm/runtime/scanner.py::AlgorithmScanner.scan` | serialization-in-loop |
| 14 | `noetrium_platform/foundation/governance/concurrency/runtime/scanner.py::ConcurrencyScanner.scan` | serialization-in-loop |
| 14 | `noetrium_platform/foundation/governance/performance/runtime/scanner.py::PerformanceScanner.scan` | serialization-in-loop |
| 14 | `noetrium_platform/capabilities/model/request/prompt/runtime/generation_codec.py::decode_generation` | serialization-in-loop |
| 14 | `noetrium_platform/infrastructure/lifecycle/server/runtime/operation_journal.py::JsonlServerOperationJournal._read_records` | serialization-in-loop |
| 13 | `noetrium_platform/foundation/governance/architecture/concurrency_boundary_invariants.py::_audit_concurrency_policy_ownership` | io-in-loop |
| 13 | `noetrium_platform/foundation/governance/architecture/concurrency_boundary_invariants.py::_audit_legacy_execution_seams` | io-in-loop |
| 13 | `noetrium_platform/foundation/governance/architecture/source_profile.py::scan_architecture_source_profile` | io-in-loop |
| 13 | `noetrium_platform/foundation/governance/quality/degradation_python_scan.py::scan_python_degradation` | io-in-loop |
| 13 | `noetrium_platform/foundation/governance/quality/silent_failure.py::scan_silent_failures` | io-in-loop |
| 13 | `noetrium_platform/foundation/governance/repository_boundary/runtime/audit.py::_audit_core_imports` | io-in-loop |
| 13 | `noetrium_platform/evidence/observability/telemetry/metric/providers/query.py::SQLiteTelemetryReader.query` | serialization-in-loop, allocation-in-loop |
| 13 | `noetrium_platform/infrastructure/reliability/forensics/runtime/catalog_audit.py::FailureCatalogSourceAudit.run` | io-in-loop |
| 13 | `noetrium_platform/infrastructure/lifecycle/service/runtime/linux_procfs.py::LinuxProcfsReader._process_directory` | io-in-loop |
| 12 | `noetrium_platform/capabilities/environment/minecraft/composition/branch_runtime.py::MinecraftBranchRuntimeBinding._release_allocations` | lock-in-loop |
| 12 | `noetrium_platform/capabilities/environment/minecraft/composition/branch_runtime.py::MinecraftBranchRuntimeFactory.open` | lock-in-loop |
| 12 | `noetrium_platform/infrastructure/resources/allocation/runtime/endpoint_allocator.py::InMemoryEndpointAllocator.allocate` | lock-in-loop |
| 10 | `noetrium_platform/evidence/artifact/content/providers/tar_archive.py::SafeTarArchiveMaterializer.materialize` | io-in-loop |
| 10 | `noetrium_platform/capabilities/environment/minecraft/providers/jsonl_bridge.py::JsonlMinecraftBridge._drain_stderr` | io-in-loop |
| 10 | `noetrium_platform/capabilities/environment/minecraft/providers/rcon.py::_read_exact` | io-in-loop |
| 10 | `noetrium_platform/research/execution/runtime/manager/model_ports.py::HeartbeatRuntimeQualificationVerifier.verify` | io-in-loop |
| 10 | `noetrium_platform/foundation/governance/release/runtime/package_verification.py::_stream_member_digest` | io-in-loop |
| 10 | `noetrium_platform/capabilities/model/deployment/runtime/controller.py::ModelDesiredStateController.run` | io-in-loop |
| 10 | `noetrium_platform/evidence/observability/capture/providers/segment_writer.py::RawSegmentWriter._write_all` | io-in-loop |
| 10 | `noetrium_platform/evidence/observability/logging/storage/runtime/jsonl.py::JsonlLogStore._iter_frozen_lines` | io-in-loop |
| 10 | `noetrium_platform/infrastructure/reliability/forensics/providers/directory_change_signal.py::DirectoryChangeSignal._drain_events` | io-in-loop |
| 10 | `noetrium_platform/infrastructure/lifecycle/process/capture/fd.py::CaptureFD.write_all` | io-in-loop |
| 10 | `noetrium_platform/infrastructure/lifecycle/process/capture/storage.py::CaptureStorage.read_range_unverified` | io-in-loop |
| 10 | `noetrium_platform/infrastructure/lifecycle/process/supervision/runtime/command_runner.py::_BoundedPipeCollector.drain` | io-in-loop |
| 9 | `noetrium_platform/research/experimentation/workload/runtime/runner.py::GenericWorkloadTaskRunner.run` | allocation-in-loop |
| 9 | `noetrium_platform/foundation/governance/system_registry/api/topology.py::_load_catalog_semantics` | allocation-in-loop |
| 9 | `scripts/release_regression.py::_run_parallel_plans` | allocation-in-loop |
| 7 | `noetrium_platform/capabilities/environment/minecraft/composition/server_service.py::MinecraftServerReadinessProbe.wait_ready` | serialization-in-loop |
| 7 | `noetrium_platform/capabilities/environment/minecraft/composition/server_service.py::MinecraftTcpReadinessProbe._wait_ready_async` | serialization-in-loop |
| 7 | `noetrium_platform/capabilities/model/serving/endpoint/providers/openai_compatible.py::AsyncioJsonTransport._read_headers` | serialization-in-loop |
| 7 | `noetrium_platform/infrastructure/reliability/forensics/composition/rebuild.py::_hash_payloads` | serialization-in-loop |
| 7 | `noetrium_platform/infrastructure/reliability/forensics/providers/hashlog_lookup.py::find_payload_in_hashlog` | serialization-in-loop |
| 7 | `noetrium_platform/infrastructure/reliability/forensics/providers/hashlog_scanner.py::scan_hash_chain` | serialization-in-loop |
| 7 | `noetrium_platform/infrastructure/reliability/forensics/providers/hashlog_scanner.py::scan_hash_chain_payloads` | serialization-in-loop |
| 7 | `noetrium_platform/infrastructure/lifecycle/service/runtime/readiness.py::HttpEndpointReadinessProbe._wait_ready_async` | serialization-in-loop |
| 7 | `noetrium_platform/infrastructure/lifecycle/service/runtime/readiness.py::ProcessAliveReadinessProbe._wait_ready_async` | serialization-in-loop |
| 6 | `noetrium_platform/capabilities/environment/minecraft/providers/jsonl_bridge.py::JsonlMinecraftBridge._start_owned` | allocation-in-loop |
| 6 | `noetrium_platform/capabilities/environment/minecraft/runtime/tasks.py::MinecraftTaskSpec.from_mapping` | allocation-in-loop |
| 6 | `noetrium_platform/research/experimentation/checkpoint/providers/codec.py::RunCheckpointManifestCodec.decode` | allocation-in-loop |
| 6 | `noetrium_platform/research/experimentation/run/manifest/runtime/evidence.py::decode_evidence_bundle_manifest` | allocation-in-loop |
| 6 | `noetrium_platform/foundation/governance/algorithm/runtime/diff.py::diff_snapshots` | allocation-in-loop |
| 6 | `noetrium_platform/foundation/governance/architecture/import_graph.py::package_cycles` | allocation-in-loop |
| 6 | `noetrium_platform/foundation/governance/architecture/optimization.py::analyze_optimization_risks` | allocation-in-loop |
| 6 | `noetrium_platform/foundation/governance/architecture/system_dependency_invariants.py::audit_system_dependency_invariants` | allocation-in-loop |
| 6 | `noetrium_platform/foundation/governance/repository_boundary/runtime/audit.py::_audit_metadata` | whole-file-read |
| 6 | `noetrium_platform/infrastructure/lifecycle/service/runtime/linux_procfs.py::LinuxProcfsReader.start_identity` | whole-file-read |
| 5 | `noetrium_platform/capabilities/environment/minecraft/providers/world_cut.py::FilesystemMinecraftWorldCopier.copy` | deep-copy |
| 5 | `noetrium_platform/capabilities/model/asset/runtime/storage.py::LocalModelAssetStorage.materialize` | deep-copy |
