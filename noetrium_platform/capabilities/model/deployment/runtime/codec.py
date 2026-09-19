from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model._persisted import (
    exact_fields,
    number,
    optional_text,
    text,
    text_pairs,
    text_tuple,
)
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec, ModelDesiredState
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from noetrium_platform.foundation.scope.api import scope_from_data, scope_to_data

from .applied import AppliedModelDeployment


_DEPLOYMENT_FIELDS = frozenset({
    "deployment_id", "scope", "service_id", "model_id", "engine", "executable", "argv", "cwd",
    "python_environment_id", "gpu_devices", "environment", "readiness_url", "readiness_timeout_s",
    "stop_timeout_s", "heartbeat_interval_s", "desired_state", "tags",
})
_APPLIED_FIELDS = frozenset({"spec", "contract", "environment"})
_CONTRACT_FIELDS = frozenset({
    "service_id", "generation", "executable", "argv", "cwd", "environment_digest",
    "artifact_digest", "runtime_identity_digest", "readiness_timeout_s", "stop_timeout_s",
    "heartbeat_interval_s",
})


def deployment_to_data(value: ModelDeploymentSpec) -> dict[str, object]:
    return {
        "deployment_id": value.deployment_id,
        "scope": scope_to_data(value.scope),
        "service_id": value.service_id,
        "model_id": value.model_id,
        "engine": value.engine,
        "executable": value.executable,
        "argv": list(value.argv),
        "cwd": str(value.cwd),
        "python_environment_id": value.python_environment_id,
        "gpu_devices": list(value.gpu_devices),
        "environment": [list(row) for row in value.environment],
        "readiness_url": value.readiness_url,
        "readiness_timeout_s": value.readiness_timeout_s,
        "stop_timeout_s": value.stop_timeout_s,
        "heartbeat_interval_s": value.heartbeat_interval_s,
        "desired_state": value.desired_state.value,
        "tags": list(value.tags),
    }


def encode_deployment(value: ModelDeploymentSpec) -> bytes:
    return json.dumps(
        deployment_to_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_deployment(data: dict[str, object]) -> ModelDeploymentSpec:
    document = exact_fields(data, field="model deployment", fields=_DEPLOYMENT_FIELDS)
    return ModelDeploymentSpec(
        deployment_id=text(document["deployment_id"], field="deployment_id", allow_empty=False),
        scope=scope_from_data(document["scope"]),
        service_id=text(document["service_id"], field="service_id", allow_empty=False),
        model_id=text(document["model_id"], field="model_id", allow_empty=False),
        engine=text(document["engine"], field="engine", allow_empty=False),
        executable=text(document["executable"], field="executable", allow_empty=False),
        argv=text_tuple(document["argv"], field="argv"),
        cwd=Path(text(document["cwd"], field="cwd", allow_empty=False)),
        python_environment_id=optional_text(document["python_environment_id"], field="python_environment_id"),
        gpu_devices=text_tuple(document["gpu_devices"], field="gpu_devices"),
        environment=text_pairs(document["environment"], field="environment"),
        readiness_url=optional_text(document["readiness_url"], field="readiness_url"),
        readiness_timeout_s=number(document["readiness_timeout_s"], field="readiness_timeout_s", minimum=0.0),
        stop_timeout_s=number(document["stop_timeout_s"], field="stop_timeout_s", minimum=0.0),
        heartbeat_interval_s=number(document["heartbeat_interval_s"], field="heartbeat_interval_s", minimum=0.0),
        desired_state=ModelDesiredState(text(document["desired_state"], field="desired_state", allow_empty=False)),
        tags=text_tuple(document["tags"], field="tags"),
    )


def encode_applied(value: AppliedModelDeployment) -> bytes:
    contract = value.contract
    payload = {
        "spec": deployment_to_data(value.spec),
        "contract": {
            "service_id": contract.service_id,
            "generation": contract.generation,
            "executable": contract.executable,
            "argv": list(contract.argv),
            "cwd": contract.cwd,
            "environment_digest": contract.environment_digest,
            "artifact_digest": contract.artifact_digest,
            "runtime_identity_digest": contract.runtime_identity_digest,
            "readiness_timeout_s": contract.readiness_timeout_s,
            "stop_timeout_s": contract.stop_timeout_s,
            "heartbeat_interval_s": contract.heartbeat_interval_s,
        },
        "environment": [list(row) for row in value.environment],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_applied(data: dict[str, object]) -> AppliedModelDeployment:
    document = exact_fields(data, field="applied model deployment", fields=_APPLIED_FIELDS)
    spec = decode_deployment(exact_fields(
        document["spec"], field="applied model deployment spec", fields=_DEPLOYMENT_FIELDS
    ))
    contract_data = exact_fields(
        document["contract"], field="service launch contract", fields=_CONTRACT_FIELDS
    )
    contract = ServiceLaunchContract(
        service_id=text(contract_data["service_id"], field="contract.service_id", allow_empty=False),
        generation=text(contract_data["generation"], field="contract.generation", allow_empty=False),
        executable=text(contract_data["executable"], field="contract.executable", allow_empty=False),
        argv=text_tuple(contract_data["argv"], field="contract.argv"),
        cwd=text(contract_data["cwd"], field="contract.cwd", allow_empty=False),
        environment_digest=text(contract_data["environment_digest"], field="contract.environment_digest", allow_empty=False),
        artifact_digest=text(contract_data["artifact_digest"], field="contract.artifact_digest", allow_empty=False),
        runtime_identity_digest=text(
            contract_data["runtime_identity_digest"], field="contract.runtime_identity_digest", allow_empty=False
        ),
        readiness_timeout_s=number(
            contract_data["readiness_timeout_s"], field="contract.readiness_timeout_s", minimum=0.0
        ),
        stop_timeout_s=number(
            contract_data["stop_timeout_s"], field="contract.stop_timeout_s", minimum=0.0
        ),
        heartbeat_interval_s=number(
            contract_data["heartbeat_interval_s"], field="contract.heartbeat_interval_s", minimum=0.0
        ),
    )
    environment = text_pairs(document["environment"], field="applied.environment")
    return AppliedModelDeployment(spec, contract, environment)


__all__ = ["decode_applied", "decode_deployment", "deployment_to_data", "encode_applied", "encode_deployment"]
