from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from noetrium_platform.capabilities.model.serving.api import (
    ModelAdmissionRegistryPort,
    QualifiedDeploymentManifest,
    RoleModelManifest,
    RuntimeCanaryProbe,
    ServiceHeartbeat,
    build_runtime_qualification_receipt,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AsyncJsonHttpTransportPort,
    ModelEndpointRoute,
    QualifiedModelClosurePublication,
    QualifiedModelClosurePublicationReceipt,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_runtime_canary_endpoint,
)
from noetrium_platform.capabilities.model.serving.runtime import run_runtime_canary
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import SchedulingAuthorityPort

from .qualified_closure import publish_qualified_model_deployment_closure


_T = TypeVar("_T")


def _by_deployment(items: tuple[_T, ...], *, label: str) -> dict[str, _T]:
    result: dict[str, _T] = {}
    for item in items:
        deployment_id = getattr(item, "deployment_id", None)
        if type(deployment_id) is not str or not deployment_id.strip():
            raise ValueError(f"{label} item has no deployment identity")
        if deployment_id in result:
            raise ValueError(f"duplicate {label} deployment: {deployment_id}")
        result[deployment_id] = item
    if not result:
        raise ValueError(f"{label} must not be empty")
    return result


def _heartbeat_ref(heartbeat: ServiceHeartbeat) -> str:
    return (
        f"heartbeat:{heartbeat.deployment_id}:{heartbeat.pid}:"
        f"{heartbeat.process_start_marker}:{heartbeat.timestamp}"
    )


def qualify_and_publish_model_deployment_closure(
    path: str | Path,
    *,
    role_manifest: RoleModelManifest,
    deployments: tuple[QualifiedDeploymentManifest, ...],
    routes: tuple[ModelEndpointRoute, ...],
    heartbeats: tuple[ServiceHeartbeat, ...],
    canary_probes: tuple[RuntimeCanaryProbe, ...],
    runtime_manifest_digest: str,
    max_heartbeat_age_seconds: float,
    task_group: TaskGroupPort,
    admission_registry: ModelAdmissionRegistryPort,
    scheduling_authority: SchedulingAuthorityPort,
    api_keys_by_deployment: Mapping[str, str] | None = None,
    transports_by_deployment: Mapping[str, AsyncJsonHttpTransportPort] | None = None,
    extra_evidence_refs_by_deployment: Mapping[str, tuple[str, ...]] | None = None,
    replace_malformed_existing: bool = False,
) -> QualifiedModelClosurePublicationReceipt:
    """Run exact live canaries and atomically publish one claim-eligible closure."""

    deployment_map = _by_deployment(tuple(deployments), label="qualified deployment")
    route_map = _by_deployment(tuple(routes), label="endpoint route")
    heartbeat_map = _by_deployment(tuple(heartbeats), label="service heartbeat")
    deployment_ids = set(deployment_map)
    if set(route_map) != deployment_ids or set(heartbeat_map) != deployment_ids:
        raise ValueError("deployments, routes, and heartbeats must align exactly")

    assigned_deployments = {item.deployment_id for item in role_manifest.assignments}
    unknown_assignments = assigned_deployments - deployment_ids
    if unknown_assignments:
        raise ValueError(
            f"role manifest references unknown deployments: {sorted(unknown_assignments)}"
        )

    required_keys = {item.protocol_key for item in role_manifest.assignments}
    if not required_keys:
        raise ValueError("qualified closure requires at least one frozen model capability")
    keys_by_stack: dict[str, set[tuple[str, str, str, str]]] = {}
    for assignment in role_manifest.assignments:
        deployment = deployment_map[assignment.deployment_id]
        keys_by_stack.setdefault(deployment.stack.digest(), set()).add(assignment.protocol_key)
    required_keys_by_deployment = {
        deployment_id: tuple(sorted(keys_by_stack.get(deployment.stack.digest(), set())))
        for deployment_id, deployment in deployment_map.items()
    }
    orphaned = sorted(
        deployment_id
        for deployment_id, keys in required_keys_by_deployment.items()
        if not keys
    )
    if orphaned:
        raise ValueError(
            "qualified deployments have no canonical capability for their exact stack: "
            f"{orphaned}"
        )
    probe_keys = {
        (probe.role,probe.capability_id,probe.input_schema_id,probe.output_schema_id)
        for probe in canary_probes
    }
    if probe_keys != required_keys:
        missing = sorted(required_keys - probe_keys)
        extra = sorted(probe_keys - required_keys)
        raise ValueError(
            f"runtime canary probe coverage mismatch: missing={missing}; extra={extra}"
        )
    canary_ids = tuple(probe.canary_id for probe in canary_probes)
    if len(set(canary_ids)) != len(canary_ids):
        raise ValueError("runtime canary probe ids must be globally unique")

    api_keys = {} if api_keys_by_deployment is None else dict(api_keys_by_deployment)
    transports = (
        {} if transports_by_deployment is None else dict(transports_by_deployment)
    )
    extras = (
        {}
        if extra_evidence_refs_by_deployment is None
        else dict(extra_evidence_refs_by_deployment)
    )
    unknown_config = (set(api_keys) | set(transports) | set(extras)) - deployment_ids
    if unknown_config:
        raise ValueError(
            f"runtime qualification configuration references unknown deployments: {sorted(unknown_config)}"
        )

    # One physical deployment is an independent qualification unit. Keep the
    # probes for each deployment in their original order, but overlap distinct
    # deployments through the already-owned concurrency runtime. Neither an
    # extra thread pool nor a bypass of model admission is introduced.
    probe_buckets: dict[
        tuple[str, str, str, str], list[RuntimeCanaryProbe]
    ] = {}
    for probe in canary_probes:
        key = (
            probe.role,
            probe.capability_id,
            probe.input_schema_id,
            probe.output_schema_id,
        )
        probe_buckets.setdefault(key, []).append(probe)
    probes_by_key = {
        key: tuple(sorted(probe_buckets.get(key, ()), key=lambda probe: probe.canary_id))
        for key in sorted(required_keys)
    }

    def qualify_one(deployment_id: str):
        deployment = deployment_map[deployment_id]
        endpoint = build_runtime_canary_endpoint(
            deployment,
            route_map[deployment_id],
            task_group=task_group,
            admission_registry=admission_registry,
            scheduling_authority=scheduling_authority,
            api_key=api_keys.get(deployment_id, ""),
            transport=transports.get(deployment_id),
        )
        try:
            return tuple(
                run_runtime_canary(
                    endpoint,
                    deployment,
                    route_map[deployment_id],
                    heartbeat_map[deployment_id],
                    probe,
                    max_heartbeat_age_seconds=max_heartbeat_age_seconds,
                )
                for key in required_keys_by_deployment[deployment_id]
                for probe in probes_by_key[key]
            )
        finally:
            endpoint.close()

    # Submission must finish before awaiting any one replica; otherwise the
    # first slow canary serializes the whole fleet. The existing platform
    # SERIAL executor multiplexes independent deployment lanes onto its
    # bounded worker set. BLOCKING_IO stays free for nested HTTP lease release,
    # including on a one-worker host. No unmanaged threads are spawned.
    # Results remain in deployment order to preserve deterministic evidence.
    ordered_ids = tuple(sorted(deployment_ids))
    handles = []
    submission_error: BaseException | None = None
    for deployment_id in ordered_ids:
        try:
            actor = task_group.open_serial_actor(
                "qualified-model-canary:" + deployment_id,
            )
            handles.append(actor.submit(
                "verify",
                qualify_one,
                deployment_id,
            ))
        except BaseException as exc:
            submission_error = exc
            break

    canary_evidence = []
    failures: list[BaseException] = []
    for handle in handles:
        try:
            canary_evidence.extend(handle.result())
        except BaseException as exc:
            failures.append(exc)
    if submission_error is not None:
        failures.insert(0, submission_error)
    if failures:
        if len(failures) == 1:
            raise failures[0]
        raise BaseExceptionGroup(
            "concurrent runtime qualification canaries failed",
            failures,
        )

    evidence_refs_by_deployment: dict[str, list[str]] = {
        deployment_id: [] for deployment_id in deployment_ids
    }
    for item in canary_evidence:
        evidence_refs_by_deployment[item.deployment_id].append(
            f"canary:sha256:{item.evidence_digest}"
        )

    receipts = []
    for deployment_id in sorted(deployment_ids):
        deployment = deployment_map[deployment_id]
        heartbeat = heartbeat_map[deployment_id]
        roles = tuple(sorted({
            key[0] for key in required_keys_by_deployment[deployment_id]
        }))
        canary_refs = tuple(sorted(evidence_refs_by_deployment[deployment_id]))
        evidence_refs = (
            _heartbeat_ref(heartbeat),
            *tuple(extras.get(deployment_id, ())),
            *canary_refs,
        )
        receipts.append(
            build_runtime_qualification_receipt(
                deployment,
                heartbeat,
                required_roles=roles,
                evidence_refs=evidence_refs,
                max_heartbeat_age_seconds=max_heartbeat_age_seconds,
            )
        )

    publication = QualifiedModelClosurePublication(
        role_manifest=role_manifest,
        deployments=tuple(deployments),
        routes=tuple(routes),
        runtime_manifest_digest=runtime_manifest_digest,
        runtime_qualification_receipts=tuple(receipts),
        runtime_canary_evidence=tuple(canary_evidence),
    )
    return publish_qualified_model_deployment_closure(
        path,
        publication,
        replace_malformed_existing=replace_malformed_existing,
    )


__all__ = ["qualify_and_publish_model_deployment_closure"]
