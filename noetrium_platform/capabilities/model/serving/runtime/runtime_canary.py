from __future__ import annotations

import json
import math
import time

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.capabilities.model.serving.api import (
    QualifiedDeploymentManifest,
    RuntimeCanaryEvidence,
    RuntimeCanaryProbe,
    ServiceHeartbeat,
    evaluate_runtime_canary_contract,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointPort,
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointRoute,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_bytes, canonical_digest


def _request(
    deployment: QualifiedDeploymentManifest,
    probe: RuntimeCanaryProbe,
) -> ModelRequestEnvelope:
    raw = canonical_bytes(probe.request_body)
    request_ref = ArtifactBlobRef(
        content_sha256=canonical_digest(probe.request_body),
        size_bytes=len(raw),
        media_type="application/json",
    )
    request_id = f"runtime-canary:{deployment.deployment_id}:{probe.canary_id}"
    context = ExecutionContext(
        run_id=f"runtime-canary:{deployment.deployment_id}",
        trace_id=canonical_digest({"deployment": deployment.digest(), "suite": probe.suite_digest}),
        span_id=probe.canary_id,
        operation_id="runtime-canary",
        component_id="model.serving.runtime_canary",
    )
    return ModelRequestEnvelope(
        schema_version="runtime-canary-request.v1",
        request_id=request_id,
        context=context,
        role=probe.role,
        model=deployment.stack.identity,
        prompt_generation_id=probe.suite_digest,
        prompt_id=probe.canary_id,
        prompt_digest=probe.digest(),
        request_body=request_ref,
    )


def run_runtime_canary(
    endpoint: ModelEndpointPort,
    deployment: QualifiedDeploymentManifest,
    route: ModelEndpointRoute,
    heartbeat: ServiceHeartbeat,
    probe: RuntimeCanaryProbe,
    *,
    max_heartbeat_age_seconds: float,
    now: float | None = None,
) -> RuntimeCanaryEvidence:
    generation = deployment.digest()
    if route.deployment_id != deployment.deployment_id or route.deployment_generation != generation:
        raise ValueError("runtime canary route does not match frozen deployment")
    endpoint_route = getattr(endpoint, "route", None)
    if not isinstance(endpoint_route, ModelEndpointRoute):
        raise ValueError("runtime canary endpoint does not expose authoritative route")
    if canonical_digest(endpoint_route) != canonical_digest(route):
        raise ValueError("runtime canary endpoint route authority drift")
    if heartbeat.deployment_id != deployment.deployment_id:
        raise ValueError("runtime canary heartbeat deployment drift")
    if heartbeat.stack_digest != deployment.stack.digest():
        raise ValueError("runtime canary heartbeat stack drift")
    if not heartbeat.ready:
        raise ValueError("runtime canary requires ready heartbeat")
    if heartbeat.qualification_digest != deployment.certificate.digest():
        raise ValueError("runtime canary heartbeat qualification drift")
    if probe.role not in deployment.certificate.qualified_roles:
        raise ValueError("runtime canary role is not frozen-qualified")
    if type(heartbeat.argv_digest) is not str or len(heartbeat.argv_digest) != 64:
        raise ValueError("runtime canary heartbeat argv digest is invalid")

    if isinstance(max_heartbeat_age_seconds, bool) or not isinstance(max_heartbeat_age_seconds, (int, float)):
        raise TypeError("runtime canary max heartbeat age must be numeric")
    max_age = float(max_heartbeat_age_seconds)
    if not math.isfinite(max_age) or max_age <= 0:
        raise ValueError("runtime canary max heartbeat age must be positive and finite")
    started_at = time.time() if now is None else float(now)
    if not math.isfinite(started_at) or heartbeat.timestamp > started_at:
        raise ValueError("runtime canary heartbeat is from the future")
    if started_at - heartbeat.timestamp > max_age:
        raise ValueError("runtime canary heartbeat is stale")
    envelope = _request(deployment, probe)
    materialized_body = json.loads(canonical_bytes(probe.request_body))
    if type(materialized_body) is not dict:
        raise RuntimeError("runtime canary request body materialization drift")
    request = ModelEndpointRequest(
        request=envelope,
        deployment_id=deployment.deployment_id,
        deployment_generation=generation,
        body=materialized_body,
    )
    response: ModelEndpointResponse = endpoint.complete(request)
    observed_at = time.time() if now is None else started_at
    if observed_at - heartbeat.timestamp > max_age:
        raise ValueError("runtime canary heartbeat expired during canary execution")
    if response.request_id != envelope.request_id:
        raise ValueError("runtime canary response request identity drift")
    if response.deployment_id != deployment.deployment_id:
        raise ValueError("runtime canary response deployment identity drift")
    passed = evaluate_runtime_canary_contract(
        probe.contract,
        text=response.text,
        finish_reason=response.finish_reason,
    )
    return RuntimeCanaryEvidence(
        deployment_id=deployment.deployment_id,
        deployment_generation=generation,
        route_digest=canonical_digest(route),
        role=probe.role,
        canary_id=probe.canary_id,
        suite_digest=probe.suite_digest,
        process_pid=heartbeat.pid,
        process_start_marker=heartbeat.process_start_marker,
        argv_digest=heartbeat.argv_digest,
        request_digest=request.digest(),
        probe_digest=probe.digest(),
        response_digest=response.response_digest,
        contract_digest=probe.contract.digest(),
        passed=passed,
        observed_at=float(observed_at),
    )


__all__ = ["run_runtime_canary"]
