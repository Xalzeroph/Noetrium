from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentRuntimePort,
)
from noetrium_platform.capabilities.model.deployment.composition import (
    LocalModelReplicaPoolRuntime,
    ModelReplicaPoolRequest,
)
from noetrium_platform.capabilities.model.stack.api import (
    MAX_VLLM_GPU_MEMORY_UTILIZATION,
)
from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    QualifiedDeploymentManifest,
    RoleModelManifest,
)
from noetrium_platform.capabilities.model.serving.composition import (
    canonical_runtime_canary_probe,
    qualify_and_publish_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointRoute
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    QualifiedModelClosureReadError,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeInventoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuSharingMode,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ServiceHeartbeat

from .model_runtime_bootstrap import (
    GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
    RequiredModelRuntime,
    bootstrap_required_qualified_model_runtime,
)
from .research_execution_pool import ResearchExecutionPool


def _load_strict(path: Path):
    return load_qualified_model_deployment_closure(
        path,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )


def _uses_current_gpu_memory_accounting(closure) -> bool:
    for deployment in closure.deployments:
        receipt = closure.runtime_qualifications.load(
            closure.runtime_manifest_digest,
            deployment.deployment_id,
        )
        if GPU_MEMORY_ACCOUNTING_EVIDENCE_REF not in receipt.evidence_refs:
            return False
    return True


def _refresh_compute_requirement(source) -> ComputeRequirement:
    envelope = source.certificate.resource_envelope
    engine = source.stack.identity.engine.lower()
    gpu_count = (
        source.stack.tensor_parallel * source.stack.pipeline_parallel
        if engine == "vllm"
        else source.stack.tensor_parallel
    )
    return ComputeRequirement(
        cpu_cores=1,
        memory_bytes=max(
            2 * 1024**3,
            int(envelope.peak_host_memory_bytes * 2),
        ),
        gpu_count=gpu_count,
        required_gpu_free_memory_bytes=envelope.peak_gpu_memory_bytes_per_device,
        gpu_admission_headroom_fraction=(
            1.0 - MAX_VLLM_GPU_MEMORY_UTILIZATION
            if engine == "vllm" and gpu_count > 0
            else 0.0
        ),
        max_gpu_utilization_percent=100,
        gpu_sharing_mode=(
            GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
            if gpu_count > 0
            else GpuSharingMode.IDLE_ONLY
        ),
    )


def refresh_required_qualified_model_runtimes(
    *,
    authority_root: Path,
    project_root: Path,
    required_models: tuple[RequiredModelRuntime, ...],
    assets,
    compute_scheduler,
    model_resources,
    state_root: Path,
    model_replica_pool: LocalModelReplicaPoolRuntime,
    deployment_runtime: ModelDeploymentRuntimePort,
    compute_inventory: ComputeInventoryPort,
    execution_pool: ResearchExecutionPool,
) -> tuple[str, ...]:
    """Refresh exact runtime closures for already-qualified model stacks.

    The current qualified closure is the static qualification source for its
    frozen stack/certificate. Physical replica, endpoint, process heartbeat and
    canary evidence are always regenerated for this ManagedResearchRuntime
    generation. Legacy closure schemas are deliberately not decoded here.
    """

    if type(required_models) is not tuple or any(
        type(row) is not RequiredModelRuntime for row in required_models
    ):
        raise TypeError(
            "qualified model runtime refresh requires RequiredModelRuntime rows"
        )
    required = tuple(sorted({row.model_id for row in required_models}))
    if not required:
        return ()
    if authority_root.exists():
        if authority_root.is_symlink() or not authority_root.is_dir():
            raise RuntimeError(
                "qualified model authority root must be a real directory"
            )
    else:
        authority_root.mkdir(parents=True, exist_ok=True)
        if authority_root.is_symlink() or not authority_root.is_dir():
            raise RuntimeError(
                "qualified model authority root creation did not converge"
            )
    if not project_root.is_dir():
        raise RuntimeError("research project root is missing")
    if model_replica_pool is None:
        raise RuntimeError("qualified model runtime refresh requires replica pool")

    loaded: list[tuple[Path, object]] = []
    for path in sorted(
        authority_root.glob("models/*/qualified-model-closure.json")
    ):
        try:
            closure = _load_strict(path)
        except QualifiedModelClosureReadError:
            continue
        if not _uses_current_gpu_memory_accounting(closure):
            continue
        model_ids = {
            deployment.stack.identity.model_id
            for deployment in closure.deployments
        }
        if model_ids.intersection(required):
            loaded.append((path, closure))

    found = {
        deployment.stack.identity.model_id
        for _path, closure in loaded
        for deployment in closure.deployments
    }
    missing = sorted(set(required) - found)
    receipts: list[str] = []
    bootstrapped: set[str] = set()
    for model_id in missing:
        rows = tuple(
            row for row in required_models if row.model_id == model_id
        )
        receipts.append(
            bootstrap_required_qualified_model_runtime(
                authority_root=authority_root,
                project_root=project_root,
                state_root=state_root,
                requirements=rows,
                assets=assets,
                compute_scheduler=compute_scheduler,
                model_replica_pool=model_replica_pool,
                deployment_runtime=deployment_runtime,
                model_resources=model_resources,
                execution_pool=execution_pool,
            )
        )
        bootstrapped.add(model_id)

    for path, closure in loaded:
        replacement_deployments = []
        replacement_routes = []
        heartbeats = []
        deployment_id_map: dict[str, str] = {}
        opened_leases = []

        try:
            for source in closure.deployments:
                model_id = source.stack.identity.model_id
                if model_id not in required:
                    continue
                # Static qualification is host-specific. Never reuse measured
                # capacity on a different physical host.
                compute_inventory.host(source.certificate.target_host_identity_digest)
                request = ModelReplicaPoolRequest(
                    pool_id=(
                        "qualified-runtime-refresh:"
                        + canonical_digest(
                            {
                                "closure_path": str(path),
                                "source_deployment": source.deployment_id,
                                "stack_digest": source.stack.digest(),
                            }
                        )[:24]
                    ),
                    scope=PLATFORM_SCOPE,
                    model_id=model_id,
                    engine=source.stack.identity.engine,
                    cwd=project_root,
                    compute=_refresh_compute_requirement(source),
                    model_stack=source.stack,
                    replica_count=1,
                    endpoint_host="127.0.0.1",
                    tags=(
                        "qualified-runtime-refresh",
                        "closure:"
                        + canonical_digest(str(path))[:24],
                    ),
                )
                lease = model_replica_pool.ensure(request)
                opened_leases.append(lease)
                lease.assert_healthy()
                row = lease.report.placements[0]
                applied = deployment_runtime.applied_identity(row.deployment_id)

                deployment = QualifiedDeploymentManifest(
                    deployment_id=row.deployment_id,
                    stack=source.stack,
                    certificate=source.certificate,
                    placement=DeploymentPlacement(row.compute.gpu_ids),
                    host_identity_digest=(
                        source.certificate.target_host_identity_digest
                    ),
                )
                route = ModelEndpointRoute(
                    deployment_id=row.deployment_id,
                    deployment_generation=deployment.digest(),
                    base_url=(
                        f"http://{row.endpoint.endpoint.host}:"
                        f"{row.endpoint.endpoint.port}"
                    ),
                )
                heartbeat = ServiceHeartbeat(
                    deployment_id=row.deployment_id,
                    stack_digest=source.stack.digest(),
                    pid=applied.pid,
                    process_start_marker=applied.process_start_marker,
                    argv_digest=applied.argv_digest,
                    ready=True,
                    qualification_digest=source.certificate.digest(),
                    timestamp=time.time(),
                )
                deployment_id_map[source.deployment_id] = row.deployment_id
                replacement_deployments.append(deployment)
                replacement_routes.append(route)
                heartbeats.append(heartbeat)

            if not replacement_deployments:
                continue

            assignments = tuple(
                replace(
                    assignment,
                    deployment_id=deployment_id_map[assignment.deployment_id],
                )
                for assignment in closure.role_manifest.assignments
                if assignment.deployment_id in deployment_id_map
            )
            role_manifest = RoleModelManifest(assignments)
            deployment_by_id = {
                item.deployment_id: item for item in replacement_deployments
            }
            source_capabilities: dict[
                tuple[str, str, str, str],
                set[str],
            ] = {}
            for evidence in closure.runtime_canary_evidence:
                if not evidence.passed:
                    continue
                key = (
                    evidence.role,
                    evidence.capability_id,
                    evidence.input_schema_id,
                    evidence.output_schema_id,
                )
                source_capabilities.setdefault(key, set()).update(
                    evidence.verified_capabilities
                )
            probes = tuple(
                canonical_runtime_canary_probe(
                    assignment,
                    deployment_by_id[assignment.deployment_id],
                    required_capabilities=tuple(
                        sorted(
                            source_capabilities.get(
                                (
                                    assignment.role,
                                    assignment.capability_id,
                                    assignment.input_schema_id,
                                    assignment.output_schema_id,
                                ),
                                {"generation"},
                            )
                        )
                    ),
                )
                for assignment in role_manifest.assignments
            )
            runtime_manifest_digest = canonical_digest(
                {
                    "schema": "noetrium.qualified-runtime-refresh",
                    "prior_runtime_manifest_digest": (
                        closure.runtime_manifest_digest
                    ),
                    "deployments": tuple(
                        (
                            item.deployment_id,
                            item.digest(),
                        )
                        for item in replacement_deployments
                    ),
                    "routes": tuple(
                        canonical_digest(item)
                        for item in replacement_routes
                    ),
                    "heartbeats": tuple(
                        canonical_digest(item) for item in heartbeats
                    ),
                }
            )
            group = execution_pool.open_model_io_group(
                "qualified-runtime-refresh:"
                + canonical_digest(str(path))[:24]
            )
            try:
                receipt = qualify_and_publish_model_deployment_closure(
                    path,
                    role_manifest=role_manifest,
                    deployments=tuple(replacement_deployments),
                    routes=tuple(replacement_routes),
                    heartbeats=tuple(heartbeats),
                    canary_probes=probes,
                    runtime_manifest_digest=runtime_manifest_digest,
                    max_heartbeat_age_seconds=120.0,
                    task_group=group,
                    admission_registry=execution_pool.model_admission,
                    extra_evidence_refs_by_deployment={
                        item.deployment_id: (
                            "prior-runtime-manifest:sha256:"
                            + closure.runtime_manifest_digest,
                            GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
                        )
                        for item in replacement_deployments
                    },
                )
            finally:
                execution_pool.close_model_io_group(
                    group,
                    cancel_pending=True,
                )
            verified = _load_strict(path)
            if verified.runtime_manifest_digest != runtime_manifest_digest:
                raise RuntimeError(
                    "qualified model runtime refresh readback drift"
                )
            receipts.append(receipt.closure_digest)
        except ComputePlacementUnavailable:
            for lease in reversed(opened_leases):
                try:
                    lease.close()
                except BaseException:
                    pass
            model_ids = tuple(
                sorted(
                    {
                        source.stack.identity.model_id
                        for source in closure.deployments
                        if source.stack.identity.model_id in required
                    }
                )
            )
            for model_id in model_ids:
                if model_id in bootstrapped:
                    continue
                rows = tuple(
                    row for row in required_models if row.model_id == model_id
                )
                receipts.append(
                    bootstrap_required_qualified_model_runtime(
                        authority_root=authority_root,
                        project_root=project_root,
                        state_root=state_root,
                        requirements=rows,
                        assets=assets,
                        compute_scheduler=compute_scheduler,
                        model_replica_pool=model_replica_pool,
                        deployment_runtime=deployment_runtime,
                        model_resources=model_resources,
                        execution_pool=execution_pool,
                    )
                )
                bootstrapped.add(model_id)
            continue
        except BaseException:
            # Failed refreshes must not pin resource leases. Successful leases
            # intentionally remain registered in LocalModelReplicaPoolRuntime
            # and are retired by ManagedResearchRuntime.close().
            for lease in reversed(opened_leases):
                try:
                    lease.close()
                except BaseException:
                    pass
            raise

    return tuple(receipts)


__all__ = ["refresh_required_qualified_model_runtimes"]
