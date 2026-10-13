from __future__ import annotations

from contextlib import ExitStack
import json
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
    parse_vllm_engine_resource_args,
)
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
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
from noetrium_platform.capabilities.model.serving.endpoint.providers.qualified_closure_codec import (
    decode_qualified_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.concurrency.api import ContentAddressedSingleFlight
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime.phase_trace import (
    CausalPhaseTrace,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeInventoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuRuntimeObserverPort,
    GpuSharingMode,
    HostRuntimeObserverPort,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ServiceHeartbeat

from .model_runtime_bootstrap import (
    GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
    RequiredModelRuntime,
    STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF,
    bootstrap_required_qualified_model_runtime,
    qualified_model_closure_path,
    qualification_source_stack_digest,
)
from .model_stack_materialization import (
    DockerModelStackMaterializer,
    ModelStackPlacementUnavailable,
)
from .research_execution_pool import ResearchExecutionPool


def _load_strict(path: Path):
    return load_qualified_model_deployment_closure(
        path,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )


def _refresh_replica_source_groups(
    closure,
    *,
    required_model_ids: frozenset[str],
) -> tuple[tuple[QualifiedDeploymentManifest, ...], ...]:
    """Group source replicas by exact runtime stack before physical refresh.

    A qualified closure can contain multiple physical replicas of the same
    exact stack. Refreshing each source with replica_count=1 collapses those
    calls onto the same content-addressed Runtime Fabric owner. Preserve the
    qualified replica cardinality by materializing each exact stack as one
    replica-pool request.
    """

    buckets: dict[
        tuple[str, str],
        list[QualifiedDeploymentManifest],
    ] = {}
    for source in closure.deployments:
        model_id = source.stack.identity.model_id
        if model_id not in required_model_ids:
            continue
        key = (model_id, source.stack.digest())
        buckets.setdefault(key, []).append(source)

    groups: list[tuple[QualifiedDeploymentManifest, ...]] = []
    for key in sorted(buckets):
        sources = tuple(
            sorted(
                buckets[key],
                key=lambda source: source.deployment_id,
            )
        )
        certificate_digests = {
            source.certificate.digest() for source in sources
        }
        if len(certificate_digests) != 1:
            raise ValueError(
                "qualified source replicas for one exact stack have "
                f"conflicting certificates: model_id={key[0]!r}; "
                f"stack_digest={key[1]}"
            )
        host_digests = {
            source.certificate.target_host_identity_digest
            for source in sources
        }
        if len(host_digests) != 1:
            raise ValueError(
                "qualified source replicas for one exact stack span "
                f"multiple host identities: model_id={key[0]!r}; "
                f"stack_digest={key[1]}"
            )
        groups.append(sources)
    return tuple(groups)


def _uses_current_model_qualification_protocol(closure) -> bool:
    required_refs = frozenset((
        GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
        STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF,
    ))
    for deployment in closure.deployments:
        receipt = closure.runtime_qualifications.load(
            closure.runtime_manifest_digest,
            deployment.deployment_id,
        )
        if not required_refs.issubset(receipt.evidence_refs):
            return False
    return True



def _closure_covers_required_model_rows(
    closure,
    *,
    model_id: str,
    rows: tuple[RequiredModelRuntime, ...],
) -> bool:
    """Return whether one qualified closure proves every required model role.

    Assignment and canary evidence are indexed once per model closure so role
    coverage is linear in closure evidence plus required capability counts.
    """
    if type(rows) is not tuple or not rows:
        raise ValueError("required model role coverage requires non-empty rows")

    deployment_ids = {
        deployment.deployment_id
        for deployment in closure.deployments
        if deployment.stack.identity.model_id == model_id
    }
    if not deployment_ids:
        return False

    assignment_by_role = {}
    duplicate_roles: set[str] = set()
    for assignment in closure.role_manifest.assignments:
        if assignment.deployment_id not in deployment_ids:
            continue
        role = assignment.role
        if role in assignment_by_role:
            duplicate_roles.add(role)
        else:
            assignment_by_role[role] = assignment

    verified_by_binding: dict[tuple[str, str, str, str, str], set[str]] = {}
    for evidence in closure.runtime_canary_evidence:
        if not evidence.passed or evidence.deployment_id not in deployment_ids:
            continue
        key = (
            evidence.role,
            evidence.deployment_id,
            evidence.capability_id,
            evidence.input_schema_id,
            evidence.output_schema_id,
        )
        verified_by_binding.setdefault(key, set()).update(
            evidence.verified_capabilities
        )

    for requirement in rows:
        if requirement.role in duplicate_roles:
            return False
        assignment = assignment_by_role.get(requirement.role)
        if assignment is None:
            return False
        key = (
            requirement.role,
            assignment.deployment_id,
            assignment.capability_id,
            assignment.input_schema_id,
            assignment.output_schema_id,
        )
        verified = verified_by_binding.get(key)
        if verified is None or not set(
            requirement.required_capabilities
        ).issubset(verified):
            return False
    return True


def _can_reuse_generation_bound_qualification(
    closure,
    *,
    deployments: tuple[QualifiedDeploymentManifest, ...],
    routes: tuple[ModelEndpointRoute, ...],
    applied_identities: dict[str, object],
) -> bool:
    """Reuse only a closure proving the *exact same* still-owned physical cut.

    This is a read-only proof check, not a new readiness or qualification
    authority. A replica-pool lease must already have fenced retirement and
    verified Resource Authority bindings and live physical status. A changed
    deployment, route, process generation or canary proof requires full online
    requalification. Published qualification evidence is generation-bound,
    not invalidated by elapsed time alone.
    """
    existing = {row.deployment_id: row for row in closure.deployments}
    original_routes = {row.deployment_id: row for row in closure.routes}
    assignments_by_protocol = {
        assignment.protocol_key: assignment
        for assignment in closure.role_manifest.assignments
    }
    if len(assignments_by_protocol) != len(closure.role_manifest.assignments):
        return False
    if (
        len(existing) != len(closure.deployments)
        or len(original_routes) != len(closure.routes)
        or len(deployments) != len(existing)
        or len(routes) != len(original_routes)
        or set(applied_identities) != set(existing)
    ):
        return False
    for deployment, route in zip(deployments, routes, strict=True):
        ident = deployment.deployment_id
        source = existing.get(ident)
        source_route = original_routes.get(ident)
        if (
            source is None or source_route is None
            or deployment.digest() != source.digest()
            or route != source_route
            or route.deployment_generation != deployment.digest()
        ):
            return False
        applied = applied_identities[ident]
        receipt = closure.runtime_qualifications.load(
            closure.runtime_manifest_digest, ident
        )
        if (
            receipt.deployment_id != ident
            or receipt.stack_digest != deployment.stack.digest()
            or receipt.qualification_certificate_digest != deployment.certificate.digest()
            or (
                receipt.process_pid,
                receipt.process_start_marker,
                receipt.argv_digest,
            ) != (applied.pid, applied.process_start_marker, applied.argv_digest)
        ):
            return False
        assigned_roles = {
            assignment.role
            for assignment in closure.role_manifest.assignments
            if assignment.deployment_id == ident
        }
        if not assigned_roles.issubset(set(receipt.qualified_roles)):
            return False
        matched = False
        for evidence in closure.runtime_canary_evidence:
            if evidence.deployment_id != ident:
                continue
            assignment = assignments_by_protocol.get((
                evidence.role, evidence.capability_id,
                evidence.input_schema_id, evidence.output_schema_id,
            ))
            if assignment is None:
                return False
            try:
                expected_probe = canonical_runtime_canary_probe(
                    assignment, deployment,
                    required_capabilities=evidence.verified_capabilities,
                )
            except (TypeError, ValueError, KeyError):
                return False
            # A canonical canary contract may evolve without changing the
            # model process or stack. Its cryptographic probe identity must
            # remain identical; otherwise re-run the new online proof.
            if evidence.probe_digest != expected_probe.digest():
                return False
            if (
                not evidence.passed
                or evidence.deployment_generation != deployment.digest()
                or evidence.route_digest != canonical_digest(route)
                or (
                    evidence.process_pid,
                    evidence.process_start_marker,
                    evidence.argv_digest,
                ) != (applied.pid, applied.process_start_marker, applied.argv_digest)
                or f"canary:sha256:{evidence.evidence_digest}" not in receipt.evidence_refs
                or not receipt.heartbeat_timestamp <= evidence.observed_at <= receipt.valid_until
            ):
                return False
            matched = True
        if not matched:
            return False
    return True


def _desired_stack_materializations(
    model_topologies: tuple[tuple[str, int, int, int], ...],
    *,
    assets,
    resource_authority: UniversalResourceAuthority,
    compute_inventory: ComputeInventoryPort,
    gpu_runtime_observer: GpuRuntimeObserverPort | None,
    host_runtime_observer: HostRuntimeObserverPort | None,
    state_root: Path,
    execution_pool: ResearchExecutionPool,
    model_replica_pool: LocalModelReplicaPoolRuntime,
):
    if not model_topologies:
        return {}
    plan_identity = canonical_digest(
        {
            "schema": "noetrium.qualified-model-refresh-stack-plan.v1",
            "model_topologies": model_topologies,
        }
    )
    group_id = "qualified-model-refresh-stack-plan:" + plan_identity[:24]
    group = execution_pool.open_control_group(
        group_id,
        resource_id=group_id,
    )
    try:
        runner = build_local_command_runner(
            group,
            task_namespace="qualified-model-refresh-stack-plan",
        )
        materializer = DockerModelStackMaterializer(
            assets=assets,
            resource_authority=resource_authority,
            compute_inventory=compute_inventory,
            gpu_runtime_observer=gpu_runtime_observer,
            host_runtime_observer=host_runtime_observer,
            command_runner=runner,
            state_root=state_root,
        )
        desired = {}
        for (
            model_id,
            tensor_parallel,
            context_length,
            cpu_offload_bytes_per_gpu,
        ) in model_topologies:
            desired[(
                model_id,
                tensor_parallel,
                context_length,
                cpu_offload_bytes_per_gpu,
            )] = materializer.materialize_for_tensor_parallel(
                model_id,
                tensor_parallel,
                context_length=context_length,
                cpu_offload_bytes_per_gpu=cpu_offload_bytes_per_gpu,
            )
        return desired
    finally:
        execution_pool.close_control_group(
            group,
            cancel_pending=True,
        )


def _pair_qualified_replica_sources(sources, placements):
    """Match the same physical cut by identity; use positional mapping only
    when a new physical generation makes full requalification mandatory.
    """
    by_id = {item.deployment_id: item for item in sources}
    if len(by_id) == len(sources) and set(by_id) == {
        item.deployment_id for item in placements
    }:
        return tuple(
            (by_id[row.deployment_id], row) for row in placements
        )
    return tuple(zip(sources, placements, strict=True))


def _ensure_with_pressure_reclaim(
    model_replica_pool: LocalModelReplicaPoolRuntime,
    request: ModelReplicaPoolRequest,
):
    while True:
        try:
            return model_replica_pool.ensure(request)
        except ComputePlacementUnavailable:
            reclaimed = model_replica_pool.reclaim_one_stale_warm_realization()
            if reclaimed is None:
                raise


def _refresh_required_qualified_model_runtimes_unfenced(
    *,
    authority_root: Path,
    required_models: tuple[RequiredModelRuntime, ...],
    assets,
    resource_authority: UniversalResourceAuthority,
    model_resources,
    state_root: Path,
    runtime_workdir: Path,
    model_replica_pool: LocalModelReplicaPoolRuntime,
    deployment_runtime: ModelDeploymentRuntimePort,
    compute_inventory: ComputeInventoryPort,
    gpu_runtime_observer: GpuRuntimeObserverPort | None,
    host_runtime_observer: HostRuntimeObserverPort | None,
    execution_pool: ResearchExecutionPool,
    phase_trace: CausalPhaseTrace | None = None,
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
    required_rows_by_model: dict[str, list[RequiredModelRuntime]] = {}
    for row in required_models:
        required_rows_by_model.setdefault(row.model_id, []).append(row)
    minimum_context_by_model = {
        model_id: max(row.minimum_context_tokens for row in rows)
        for model_id, rows in required_rows_by_model.items()
    }
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
    if model_replica_pool is None:
        raise RuntimeError("qualified model runtime refresh requires replica pool")

    candidate_closures: list[tuple[Path, object]] = []
    seen_paths: set[Path] = set()
    for model_id in required:
        path = qualified_model_closure_path(authority_root, model_id)
        if path in seen_paths or not path.is_file():
            continue
        seen_paths.add(path)
        try:
            closure = _load_strict(path)
        except QualifiedModelClosureReadError:
            continue
        if not _uses_current_model_qualification_protocol(closure):
            continue
        if any(
            deployment.stack.identity.model_id == model_id
            for deployment in closure.deployments
        ):
            candidate_closures.append((path, closure))

    candidate_model_topologies = tuple(
        sorted(
            {
                (
                    deployment.stack.identity.model_id,
                    deployment.stack.tensor_parallel,
                    deployment.stack.identity.context_length,
                    parse_vllm_engine_resource_args(
                        deployment.stack.engine_args
                    ).cpu_offload_bytes_per_gpu,
                )
                for _path, closure in candidate_closures
                for deployment in closure.deployments
                if deployment.stack.identity.model_id in required
            }
        )
    )
    stack_phase = (
        None
        if phase_trace is None
        else phase_trace.start(
            "model.runtime.stack-materialize",
            attributes={
                "topology_count": len(candidate_model_topologies),
                "model_ids": required,
            },
        )
    )
    try:
        desired_stack_materializations = _desired_stack_materializations(
            candidate_model_topologies,
            assets=assets,
            resource_authority=resource_authority,
            compute_inventory=compute_inventory,
            gpu_runtime_observer=gpu_runtime_observer,
            host_runtime_observer=host_runtime_observer,
            state_root=state_root,
            execution_pool=execution_pool,
            model_replica_pool=model_replica_pool,
        )
    except BaseException as exc:
        if phase_trace is not None and stack_phase is not None:
            phase_trace.fail(stack_phase, exc)
        raise
    else:
        if phase_trace is not None and stack_phase is not None:
            phase_trace.complete(stack_phase)

    loaded: list[tuple[Path, object]] = []
    for path, closure in candidate_closures:
        relevant = tuple(
            deployment
            for deployment in closure.deployments
            if deployment.stack.identity.model_id in required
        )
        represented_models = tuple(
            sorted({deployment.stack.identity.model_id for deployment in relevant})
        )
        if (
            relevant
            and all(
                (
                    deployment.stack.identity.context_length
                    >= minimum_context_by_model[
                        deployment.stack.identity.model_id
                    ]
                    and qualification_source_stack_digest(deployment.stack)
                    == qualification_source_stack_digest(
                        desired_stack_materializations[(
                            deployment.stack.identity.model_id,
                            deployment.stack.tensor_parallel,
                            deployment.stack.identity.context_length,
                            parse_vllm_engine_resource_args(
                                deployment.stack.engine_args
                            ).cpu_offload_bytes_per_gpu,
                        )].stack
                    )
                )
                for deployment in relevant
            )
            and all(
                _closure_covers_required_model_rows(
                    closure,
                    model_id=model_id,
                    rows=tuple(required_rows_by_model[model_id]),
                )
                for model_id in represented_models
            )
        ):
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
        rows = tuple(required_rows_by_model[model_id])
        bootstrap_phase = (
            None
            if phase_trace is None
            else phase_trace.start(
                "model.runtime.bootstrap",
                attributes={
                    "model_id": model_id,
                    "requirement_count": len(rows),
                },
            )
        )
        try:
            receipt = bootstrap_required_qualified_model_runtime(
                authority_root=authority_root,
                state_root=state_root,
                runtime_workdir=runtime_workdir,
                requirements=rows,
                assets=assets,
                resource_authority=resource_authority,
                compute_inventory=compute_inventory,
                gpu_runtime_observer=gpu_runtime_observer,
                host_runtime_observer=host_runtime_observer,
                model_replica_pool=model_replica_pool,
                deployment_runtime=deployment_runtime,
                model_resources=model_resources,
                execution_pool=execution_pool,
                phase_trace=phase_trace,
            )
        except BaseException as exc:
            if phase_trace is not None and bootstrap_phase is not None:
                phase_trace.fail(bootstrap_phase, exc)
            raise
        else:
            if phase_trace is not None and bootstrap_phase is not None:
                phase_trace.complete(bootstrap_phase)
        receipts.append(receipt)
        bootstrapped.add(model_id)

    for path, closure in loaded:
        replacement_deployments = []
        replacement_routes = []
        heartbeats = []
        applied_identities: dict[str, object] = {}
        deployment_id_map: dict[str, str] = {}
        opened_leases = []

        try:
            runtime_workdir.mkdir(parents=True, exist_ok=True)
            source_groups = _refresh_replica_source_groups(
                closure,
                required_model_ids=frozenset(required),
            )
            for sources in source_groups:
                source = sources[0]
                model_id = source.stack.identity.model_id

                # Static qualification is host-specific. Every replica in one
                # exact-stack group has already been proven to share this
                # certificate/host identity.
                compute_inventory.host(
                    source.certificate.target_host_identity_digest
                )
                source_deployment_ids = tuple(
                    item.deployment_id for item in sources
                )
                request = ModelReplicaPoolRequest(
                    pool_id=(
                        "qualified-runtime-refresh:"
                        + canonical_digest(
                            {
                                "closure_path": str(path),
                                "source_deployments": source_deployment_ids,
                                "stack_digest": source.stack.digest(),
                            }
                        )[:24]
                    ),
                    scope=PLATFORM_SCOPE,
                    model_id=model_id,
                    engine=source.stack.identity.engine,
                    cwd=runtime_workdir,
                    compute=desired_stack_materializations[(
                        model_id,
                        source.stack.tensor_parallel,
                        source.stack.identity.context_length,
                        parse_vllm_engine_resource_args(
                            source.stack.engine_args
                        ).cpu_offload_bytes_per_gpu,
                    )].compute,
                    model_stack=source.stack,
                    # Canonical adaptive identity is shared with bootstrap.
                    # The published closure's cardinality is still verified
                    # against actual physical placements below.  A fixed
                    # count here created a second independent Resource-Fabric
                    # owner of the same Qwen stack, provoking avoidable GPU
                    # placement failure after bootstrap already succeeded.
                    replica_count=None,
                    endpoint_host="127.0.0.1",
                    tags=(
                        "qualified-runtime-refresh",
                        "closure:"
                        + canonical_digest(str(path))[:24],
                    ),
                )
                replica_phase = (
                    None
                    if phase_trace is None
                    else phase_trace.start(
                        "model.runtime.replica.ensure",
                        attributes={
                            "model_id": model_id,
                            "source_deployment_ids": source_deployment_ids,
                            "replica_count": len(sources),
                        },
                    )
                )
                try:
                    # The bootstrap's adaptive fleet (replica_count=None) may
                    # already be alive in this ResearchExecutionPool. Borrow it
                    # by the *same* runtime identity, only if its actual
                    # Authority-backed cardinality equals this qualified
                    # closure. Never reserve another full GPU fleet simply
                    # because source qualification now knows its count.
                    lease = model_replica_pool.borrow_existing(
                        request,
                        expected_replica_count=len(sources),
                    )
                    if lease is None:
                        lease = _ensure_with_pressure_reclaim(
                            model_replica_pool,
                            request,
                        )
                except BaseException as exc:
                    if phase_trace is not None and replica_phase is not None:
                        phase_trace.fail(replica_phase, exc)
                    raise
                else:
                    if phase_trace is not None and replica_phase is not None:
                        phase_trace.complete(replica_phase)

                opened_leases.append(lease)
                # ReplicaPool.ensure already validated the exact physical
                # owner under its identity lock and started a fenced consumer
                # heartbeat before returning this lease. Immediately calling
                # lease.assert_healthy() performs a second full Authority
                # snapshot and per-replica runtime.status probe without any
                # intervening effect; the single ensure receipt is sufficient
                # for this materialization boundary. Runtime execution and
                # heartbeat maintain their own liveness fences afterward.
                placements = tuple(
                    sorted(
                        lease.report.placements,
                        key=lambda row: row.replica_index,
                    )
                )
                if len(placements) != len(sources):
                    # The adaptive topology may have grown or shrunk since
                    # the static certificate was captured. Do not publish a
                    # closure with invented/duplicated replica ownership.
                    # Signal ordinary capacity fallback to requalify using
                    # the current Authority-backed dynamic fleet size.
                    raise ComputePlacementUnavailable(request.effective_compute)
                replica_indexes = tuple(
                    row.replica_index for row in placements
                )
                if replica_indexes != tuple(range(len(sources))):
                    raise RuntimeError(
                        "model replica refresh returned non-canonical "
                        f"replica indexes: {replica_indexes}"
                    )
                deployment_ids = tuple(
                    row.deployment_id for row in placements
                )
                if len(set(deployment_ids)) != len(deployment_ids):
                    raise RuntimeError(
                        "model replica refresh collapsed distinct replicas "
                        "onto one physical deployment"
                    )

                # Preserve the scientific role's canonical physical replica
                # even when hashed deployment IDs sort in a different order
                # than physical replica indices.
                for source_replica, row in _pair_qualified_replica_sources(
                    sources, placements,
                ):
                    applied = deployment_runtime.applied_identity(
                        row.deployment_id
                    )
                    applied_identities[row.deployment_id] = applied
                    deployment = QualifiedDeploymentManifest(
                        deployment_id=row.deployment_id,
                        stack=source_replica.stack,
                        certificate=source_replica.certificate,
                        placement=DeploymentPlacement(row.gpu_ids),
                        host_identity_digest=(
                            source_replica.certificate
                            .target_host_identity_digest
                        ),
                    )
                    route = ModelEndpointRoute(
                        deployment_id=row.deployment_id,
                        deployment_generation=deployment.digest(),
                        base_url=(
                            f"http://{row.endpoint_host}:"
                            f"{row.endpoint_port}"
                        ),
                    )
                    heartbeat = ServiceHeartbeat(
                        deployment_id=row.deployment_id,
                        stack_digest=source_replica.stack.digest(),
                        pid=applied.pid,
                        process_start_marker=applied.process_start_marker,
                        argv_digest=applied.argv_digest,
                        ready=True,
                        qualification_digest=(
                            source_replica.certificate.digest()
                        ),
                        timestamp=time.time(),
                    )
                    deployment_id_map[
                        source_replica.deployment_id
                    ] = row.deployment_id
                    replacement_deployments.append(deployment)
                    replacement_routes.append(route)
                    heartbeats.append(heartbeat)

            if not replacement_deployments:
                continue

            # A borrowed exact physical owner is already fenced against
            # retirement and its Authority/physical status was checked by
            # borrow_existing(). Repeating the online canary for the same
            # process and serving contract would only reproduce existing
            # generation-bound evidence. Never reuse across any identity drift.
            if _can_reuse_generation_bound_qualification(
                closure,
                deployments=tuple(replacement_deployments),
                routes=tuple(replacement_routes),
                applied_identities=applied_identities,
            ):
                verified = _load_strict(path)
                if verified.runtime_manifest_digest != closure.runtime_manifest_digest:
                    raise RuntimeError("qualified model closure changed during reuse")
                document = decode_qualified_closure(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if (
                    document.runtime_manifest_digest != closure.runtime_manifest_digest
                    or {
                        row.deployment_id: row.digest()
                        for row in document.deployments
                    } != {
                        row.deployment_id: row.digest()
                        for row in replacement_deployments
                    }
                ):
                    raise RuntimeError(
                        "qualified model closure drifted during reuse receipt read"
                    )
                receipts.append(document.closure_digest)
                if phase_trace is not None:
                    reused_phase = phase_trace.start(
                        "model.runtime.qualification.reused",
                        attributes={
                            "runtime_manifest_digest": closure.runtime_manifest_digest,
                            "deployment_ids": tuple(sorted(deployment_id_map.values())),
                        },
                    )
                    phase_trace.complete(reused_phase)
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
            publication_phase = (
                None if phase_trace is None else phase_trace.start(
                    "model.runtime.refresh.publish-qualified-closure",
                    attributes={
                        "model_ids": tuple(sorted({
                            item.stack.identity.model_id
                            for item in replacement_deployments
                        })),
                        "replica_count": len(replacement_deployments),
                    },
                )
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
                scheduling_authority=execution_pool.scheduling_authority,
                    extra_evidence_refs_by_deployment={
                        item.deployment_id: (
                            "prior-runtime-manifest:sha256:"
                            + closure.runtime_manifest_digest,
                            GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
                            STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF,
                        )
                        for item in replacement_deployments
                    },
                )
            except BaseException as exc:
                if phase_trace is not None and publication_phase is not None:
                    phase_trace.fail(publication_phase, exc)
                raise
            else:
                if phase_trace is not None and publication_phase is not None:
                    phase_trace.complete(publication_phase)
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
                rows = tuple(required_rows_by_model[model_id])
                receipts.append(
                    bootstrap_required_qualified_model_runtime(
                        authority_root=authority_root,
                                state_root=state_root,
                        runtime_workdir=runtime_workdir,
                        requirements=rows,
                        assets=assets,
                        resource_authority=resource_authority,
                        compute_inventory=compute_inventory,
                        gpu_runtime_observer=gpu_runtime_observer,
                        host_runtime_observer=host_runtime_observer,
                        model_replica_pool=model_replica_pool,
                        deployment_runtime=deployment_runtime,
                        model_resources=model_resources,
                        execution_pool=execution_pool,
                        phase_trace=phase_trace,
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

    # Once every currently required model lease is live, retire only warm
    # identities that are strictly redundant under the same serving contract.
    # The pool itself proves exclusive Runtime-Fabric ownership and protects
    # active consumers before any Authority retirement.
    model_replica_pool.reclaim_dominated_warm_realizations()
    return tuple(receipts)


def refresh_required_qualified_model_runtimes(
    *,
    authority_root: Path,
    required_models: tuple[RequiredModelRuntime, ...],
    assets,
    resource_authority: UniversalResourceAuthority,
    model_resources,
    state_root: Path,
    runtime_workdir: Path,
    model_replica_pool: LocalModelReplicaPoolRuntime,
    deployment_runtime: ModelDeploymentRuntimePort,
    compute_inventory: ComputeInventoryPort,
    gpu_runtime_observer: GpuRuntimeObserverPort | None,
    host_runtime_observer: HostRuntimeObserverPort | None,
    execution_pool: ResearchExecutionPool,
    phase_trace: CausalPhaseTrace | None = None,
) -> tuple[str, ...]:
    """Refresh qualified runtimes with one durable producer per model identity.

    Distinct upper-layer requirement sets can converge on the same physical
    model realization.  The fence is keyed by model identity rather than by the
    caller's requirement-set digest so those callers serialize only where their
    physical realization overlaps.  After waiting, the unfenced implementation
    re-reads qualified-closure and Resource-Authority truth before deciding
    whether another bootstrap is necessary.
    """

    if type(required_models) is not tuple or any(
        type(row) is not RequiredModelRuntime for row in required_models
    ):
        raise TypeError(
            "qualified model runtime refresh requires RequiredModelRuntime rows"
        )
    model_ids = tuple(sorted({row.model_id for row in required_models}))
    if not model_ids:
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

    singleflight = ContentAddressedSingleFlight(
        authority_root / ".runtime-refresh-single-flight"
    )
    # Sorted acquisition gives a canonical lock order for rare multi-model
    # refreshes, preventing AB/BA deadlock while preserving full concurrency for
    # disjoint model sets.
    with ExitStack() as stack:
        for model_id in model_ids:
            stack.enter_context(
                singleflight.producer(
                    "qualified-model-runtime-refresh",
                    model_id,
                )
            )
        return _refresh_required_qualified_model_runtimes_unfenced(
            authority_root=authority_root,
            required_models=required_models,
            assets=assets,
            resource_authority=resource_authority,
            model_resources=model_resources,
            state_root=state_root,
            runtime_workdir=runtime_workdir,
            model_replica_pool=model_replica_pool,
            deployment_runtime=deployment_runtime,
            compute_inventory=compute_inventory,
            gpu_runtime_observer=gpu_runtime_observer,
            host_runtime_observer=host_runtime_observer,
            execution_pool=execution_pool,
            phase_trace=phase_trace,
        )


__all__ = ["refresh_required_qualified_model_runtimes"]
