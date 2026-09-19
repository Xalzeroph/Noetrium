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
    build_openai_compatible_runtime_canary_endpoint,
)
from noetrium_platform.capabilities.model.serving.runtime import run_runtime_canary
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort

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
    api_keys_by_deployment: Mapping[str, str] | None = None,
    transports_by_deployment: Mapping[str, AsyncJsonHttpTransportPort] | None = None,
    extra_evidence_refs_by_deployment: Mapping[str, tuple[str, ...]] | None = None,
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

    required_roles = {item.role for item in role_manifest.assignments}
    if not required_roles:
        raise ValueError("qualified closure requires at least one frozen role")
    probe_roles = {probe.role for probe in canary_probes}
    if probe_roles != required_roles:
        missing = sorted(required_roles - probe_roles)
        extra = sorted(probe_roles - required_roles)
        raise ValueError(
            f"runtime canary probe coverage mismatch: missing={missing}; extra={extra}"
        )

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

    endpoints = {}
    canary_evidence = []
    for probe in canary_probes:
        deployment_id = role_manifest.deployment_for(probe.role)
        deployment = deployment_map[deployment_id]
        route = route_map[deployment_id]
        heartbeat = heartbeat_map[deployment_id]
        endpoint = endpoints.get(deployment_id)
        if endpoint is None:
            endpoint = build_openai_compatible_runtime_canary_endpoint(
                deployment,
                route,
                task_group=task_group,
                admission_registry=admission_registry,
                api_key=api_keys.get(deployment_id, ""),
                transport=transports.get(deployment_id),
            )
            endpoints[deployment_id] = endpoint
        canary_evidence.append(
            run_runtime_canary(
                endpoint,
                deployment,
                route,
                heartbeat,
                probe,
                max_heartbeat_age_seconds=max_heartbeat_age_seconds,
            )
        )

    receipts = []
    for deployment_id in sorted(deployment_ids):
        deployment = deployment_map[deployment_id]
        heartbeat = heartbeat_map[deployment_id]
        roles = tuple(sorted(
            item.role
            for item in role_manifest.assignments
            if item.deployment_id == deployment_id
        ))
        if not roles:
            raise ValueError(
                f"qualified deployment has no frozen role assignment: {deployment_id}"
            )
        canary_refs = tuple(sorted(
            f"canary:sha256:{item.evidence_digest}"
            for item in canary_evidence
            if item.deployment_id == deployment_id
        ))
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
    return publish_qualified_model_deployment_closure(path, publication)


__all__ = ["qualify_and_publish_model_deployment_closure"]
