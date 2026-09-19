from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import PurePosixPath
from typing import Any

from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    QualificationCertificate,
    QualifiedDeploymentManifest,
    ResourceEnvelope,
    RoleModelAssignment,
    RoleModelManifest,
)
from noetrium_platform.capabilities.model.stack.api import (
    ModelArtifactClosure,
    ModelStackSpec,
    RuntimeBuildIdentity,
)
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, canonical_digest

from ..api import ModelEndpointRoute


SCHEMA = "qualified-model-deployment-closure.v3"


class QualifiedClosureCodecError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DecodedQualifiedClosure:
    role_manifest: RoleModelManifest
    deployments: tuple[QualifiedDeploymentManifest, ...]
    routes: tuple[ModelEndpointRoute, ...]
    runtime_manifest_digest: str
    runtime_qualification_root: str
    runtime_qualification_receipt_digests: tuple[tuple[str, str], ...]
    runtime_canary_root: str
    runtime_canary_evidence_digests: tuple[str, ...]
    closure_digest: str


def _mapping(value: object, *, field: str, fields: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise QualifiedClosureCodecError(f"closure field must be an object: {field}")
    actual = frozenset(value)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise QualifiedClosureCodecError(
            f"closure field set mismatch: {field}; missing={missing}; extra={extra}"
        )
    return value


def _string(value: object, *, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise QualifiedClosureCodecError(f"closure field must be non-empty text: {field}")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    return None if value is None else _string(value, field=field)


def _integer(value: object, *, field: str, positive: bool = False) -> int:
    if type(value) is not int:
        raise QualifiedClosureCodecError(f"closure field must be an integer: {field}")
    if positive and value <= 0:
        raise QualifiedClosureCodecError(f"closure field must be positive: {field}")
    return value


def _number(value: object, *, field: str, positive: bool = False) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise QualifiedClosureCodecError(f"closure field must be a finite JSON float: {field}")
    if positive and value <= 0:
        raise QualifiedClosureCodecError(f"closure field must be positive: {field}")
    return value


def _strings(value: object, *, field: str, non_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not list:
        raise QualifiedClosureCodecError(f"closure field must be a list: {field}")
    result = tuple(_string(item, field=f"{field}[]") for item in value)
    if non_empty and not result:
        raise QualifiedClosureCodecError(f"closure field must not be empty: {field}")
    return result


def _digest(value: object, *, field: str) -> str:
    text = _string(value, field=field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise QualifiedClosureCodecError(f"closure field must be lowercase SHA-256: {field}")
    return text


def _relative_root(value: object, *, field: str) -> str:
    text = _string(value, field=field).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or text in {".", ""}:
        raise QualifiedClosureCodecError(f"{field} must be a safe relative path")
    return text


def _relative_runtime_root(value: object) -> str:
    return _relative_root(value, field="runtime_qualification_root")


def _relative_canary_root(value: object) -> str:
    return _relative_root(value, field="runtime_canary_root")


def _identity(raw: object, *, field: str) -> ImmutableModelIdentity:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({
            "logical_name", "model_id", "revision", "engine", "engine_version",
            "dtype", "quantization", "context_length", "tokenizer_revision",
        }),
    )
    return ImmutableModelIdentity(
        logical_name=_string(value["logical_name"], field=f"{field}.logical_name"),
        model_id=_string(value["model_id"], field=f"{field}.model_id"),
        revision=_string(value["revision"], field=f"{field}.revision"),
        engine=_string(value["engine"], field=f"{field}.engine"),
        engine_version=_string(value["engine_version"], field=f"{field}.engine_version"),
        dtype=_string(value["dtype"], field=f"{field}.dtype"),
        quantization=_optional_string(value["quantization"], field=f"{field}.quantization"),
        context_length=_integer(value["context_length"], field=f"{field}.context_length", positive=True),
        tokenizer_revision=_optional_string(value["tokenizer_revision"], field=f"{field}.tokenizer_revision"),
    )


def _artifacts(raw: object, *, field: str) -> ModelArtifactClosure:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({
            "weights_manifest_sha256", "tokenizer_sha256", "model_config_sha256",
            "model_code_sha256", "chat_template_sha256",
        }),
    )
    return ModelArtifactClosure(
        weights_manifest_sha256=_digest(value["weights_manifest_sha256"], field=f"{field}.weights_manifest_sha256"),
        tokenizer_sha256=_digest(value["tokenizer_sha256"], field=f"{field}.tokenizer_sha256"),
        model_config_sha256=_digest(value["model_config_sha256"], field=f"{field}.model_config_sha256"),
        model_code_sha256=(
            None if value["model_code_sha256"] is None
            else _digest(value["model_code_sha256"], field=f"{field}.model_code_sha256")
        ),
        chat_template_sha256=(
            None if value["chat_template_sha256"] is None
            else _digest(value["chat_template_sha256"], field=f"{field}.chat_template_sha256")
        ),
    )


def _runtime(raw: object, *, field: str) -> RuntimeBuildIdentity:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({
            "container_digest", "engine_build_digest", "python_lock_digest", "cuda_runtime",
            "nccl_version", "torch_version", "kernel_extensions_digest",
        }),
    )
    return RuntimeBuildIdentity(
        container_digest=_digest(value["container_digest"], field=f"{field}.container_digest"),
        engine_build_digest=_digest(value["engine_build_digest"], field=f"{field}.engine_build_digest"),
        python_lock_digest=_digest(value["python_lock_digest"], field=f"{field}.python_lock_digest"),
        cuda_runtime=_string(value["cuda_runtime"], field=f"{field}.cuda_runtime"),
        nccl_version=_string(value["nccl_version"], field=f"{field}.nccl_version"),
        torch_version=_string(value["torch_version"], field=f"{field}.torch_version"),
        kernel_extensions_digest=_digest(
            value["kernel_extensions_digest"], field=f"{field}.kernel_extensions_digest"
        ),
    )


def _stack(raw: object, *, field: str) -> ModelStackSpec:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({
            "identity", "artifacts", "runtime", "tensor_parallel", "data_parallel",
            "expert_parallel", "pipeline_parallel", "reasoning_parser", "tool_call_parser",
            "kv_cache_dtype", "attention_backend", "scheduler_policy", "engine_args",
        }),
    )
    return ModelStackSpec(
        identity=_identity(value["identity"], field=f"{field}.identity"),
        artifacts=_artifacts(value["artifacts"], field=f"{field}.artifacts"),
        runtime=_runtime(value["runtime"], field=f"{field}.runtime"),
        tensor_parallel=_integer(value["tensor_parallel"], field=f"{field}.tensor_parallel", positive=True),
        data_parallel=_integer(value["data_parallel"], field=f"{field}.data_parallel", positive=True),
        expert_parallel=_integer(value["expert_parallel"], field=f"{field}.expert_parallel", positive=True),
        pipeline_parallel=_integer(value["pipeline_parallel"], field=f"{field}.pipeline_parallel", positive=True),
        reasoning_parser=_optional_string(value["reasoning_parser"], field=f"{field}.reasoning_parser"),
        tool_call_parser=_optional_string(value["tool_call_parser"], field=f"{field}.tool_call_parser"),
        kv_cache_dtype=_optional_string(value["kv_cache_dtype"], field=f"{field}.kv_cache_dtype"),
        attention_backend=_optional_string(value["attention_backend"], field=f"{field}.attention_backend"),
        scheduler_policy=_string(value["scheduler_policy"], field=f"{field}.scheduler_policy"),
        engine_args=_strings(value["engine_args"], field=f"{field}.engine_args"),
    )


def _envelope(raw: object, *, field: str) -> ResourceEnvelope:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({
            "peak_gpu_memory_bytes_per_device", "peak_host_memory_bytes",
            "max_qualified_concurrency", "ttft_p99_seconds", "tpot_p99_seconds",
            "minimum_output_tokens_per_second",
        }),
    )
    return ResourceEnvelope(
        peak_gpu_memory_bytes_per_device=_integer(
            value["peak_gpu_memory_bytes_per_device"], field=f"{field}.peak_gpu_memory_bytes_per_device", positive=True
        ),
        peak_host_memory_bytes=_integer(
            value["peak_host_memory_bytes"], field=f"{field}.peak_host_memory_bytes", positive=True
        ),
        max_qualified_concurrency=_integer(
            value["max_qualified_concurrency"], field=f"{field}.max_qualified_concurrency", positive=True
        ),
        ttft_p99_seconds=_number(value["ttft_p99_seconds"], field=f"{field}.ttft_p99_seconds", positive=True),
        tpot_p99_seconds=_number(value["tpot_p99_seconds"], field=f"{field}.tpot_p99_seconds", positive=True),
        minimum_output_tokens_per_second=_number(
            value["minimum_output_tokens_per_second"],
            field=f"{field}.minimum_output_tokens_per_second",
            positive=True,
        ),
    )


def _certificate(raw: object, *, field: str) -> QualificationCertificate:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({
            "model_stack_digest", "evidence_digest", "qualified_roles",
            "resource_envelope", "target_host_identity_digest",
        }),
    )
    return QualificationCertificate(
        model_stack_digest=_digest(value["model_stack_digest"], field=f"{field}.model_stack_digest"),
        evidence_digest=_digest(value["evidence_digest"], field=f"{field}.evidence_digest"),
        qualified_roles=_strings(value["qualified_roles"], field=f"{field}.qualified_roles", non_empty=True),
        resource_envelope=_envelope(value["resource_envelope"], field=f"{field}.resource_envelope"),
        target_host_identity_digest=_digest(
            value["target_host_identity_digest"], field=f"{field}.target_host_identity_digest"
        ),
    )


def _deployment(raw: object, *, field: str) -> QualifiedDeploymentManifest:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({"deployment_id", "stack", "certificate", "placement", "host_identity_digest"}),
    )
    placement = _mapping(
        value["placement"], field=f"{field}.placement", fields=frozenset({"gpu_uuids"})
    )
    return QualifiedDeploymentManifest(
        deployment_id=_string(value["deployment_id"], field=f"{field}.deployment_id"),
        stack=_stack(value["stack"], field=f"{field}.stack"),
        certificate=_certificate(value["certificate"], field=f"{field}.certificate"),
        placement=DeploymentPlacement(
            _strings(placement["gpu_uuids"], field=f"{field}.placement.gpu_uuids", non_empty=True)
        ),
        host_identity_digest=_digest(value["host_identity_digest"], field=f"{field}.host_identity_digest"),
    )


def _route(raw: object, *, field: str) -> ModelEndpointRoute:
    value = _mapping(
        raw,
        field=field,
        fields=frozenset({
            "deployment_id", "deployment_generation", "base_url", "completion_path", "timeout_s",
        }),
    )
    return ModelEndpointRoute(
        deployment_id=_string(value["deployment_id"], field=f"{field}.deployment_id"),
        deployment_generation=_digest(
            value["deployment_generation"], field=f"{field}.deployment_generation"
        ),
        base_url=_string(value["base_url"], field=f"{field}.base_url"),
        completion_path=_string(value["completion_path"], field=f"{field}.completion_path"),
        timeout_s=_number(value["timeout_s"], field=f"{field}.timeout_s", positive=True),
    )


def _roles(raw: object) -> RoleModelManifest:
    value = _mapping(raw, field="role_manifest", fields=frozenset({"assignments"}))
    assignments = value["assignments"]
    if type(assignments) is not list or not assignments:
        raise QualifiedClosureCodecError("closure role_manifest.assignments must be a non-empty list")
    rows: list[RoleModelAssignment] = []
    for index, raw_assignment in enumerate(assignments):
        field = f"role_manifest.assignments[{index}]"
        assignment = _mapping(
            raw_assignment, field=field, fields=frozenset({"role", "deployment_id"})
        )
        rows.append(
            RoleModelAssignment(
                role=_string(assignment["role"], field=f"{field}.role"),
                deployment_id=_string(
                    assignment["deployment_id"], field=f"{field}.deployment_id"
                ),
            )
        )
    return RoleModelManifest(tuple(rows))


def _unsigned_payload(
    role_manifest: RoleModelManifest,
    deployments: tuple[QualifiedDeploymentManifest, ...],
    routes: tuple[ModelEndpointRoute, ...],
    runtime_manifest_digest: str,
    runtime_qualification_root: str,
    runtime_qualification_receipt_digests: tuple[tuple[str, str], ...],
    runtime_canary_root: str,
    runtime_canary_evidence_digests: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA,
        "runtime_manifest_digest": _digest(
            runtime_manifest_digest, field="runtime_manifest_digest"
        ),
        "runtime_qualification_root": _relative_runtime_root(runtime_qualification_root),
        "runtime_qualification_receipt_digests": [
            {
                "deployment_id": _string(deployment_id, field="runtime_qualification_receipt_digests[].deployment_id"),
                "receipt_digest": _digest(receipt_digest, field="runtime_qualification_receipt_digests[].receipt_digest"),
            }
            for deployment_id, receipt_digest in sorted(runtime_qualification_receipt_digests)
        ],
        "runtime_canary_root": _relative_canary_root(runtime_canary_root),
        "runtime_canary_evidence_digests": [
            _digest(item, field="runtime_canary_evidence_digests[]")
            for item in sorted(runtime_canary_evidence_digests)
        ],
        "role_manifest": json.loads(json.dumps(asdict(role_manifest))),
        "deployments": json.loads(json.dumps([asdict(item) for item in deployments])),
        "routes": json.loads(json.dumps([asdict(item) for item in routes])),
    }


def encode_qualified_closure(
    *,
    role_manifest: RoleModelManifest,
    deployments: tuple[QualifiedDeploymentManifest, ...],
    routes: tuple[ModelEndpointRoute, ...],
    runtime_manifest_digest: str,
    runtime_qualification_root: str,
    runtime_qualification_receipt_digests: tuple[tuple[str, str], ...],
    runtime_canary_root: str,
    runtime_canary_evidence_digests: tuple[str, ...],
) -> dict[str, object]:
    payload = _unsigned_payload(
        role_manifest,
        deployments,
        routes,
        runtime_manifest_digest,
        runtime_qualification_root,
        runtime_qualification_receipt_digests,
        runtime_canary_root,
        runtime_canary_evidence_digests,
    )
    return {**payload, "closure_digest": canonical_digest(payload)}


def decode_qualified_closure(document: object) -> DecodedQualifiedClosure:
    root = _mapping(
        document,
        field="root",
        fields=frozenset({
            "schema_version", "closure_digest", "runtime_manifest_digest",
            "runtime_qualification_root", "runtime_qualification_receipt_digests",
            "runtime_canary_root", "runtime_canary_evidence_digests",
            "role_manifest", "deployments", "routes",
        }),
    )
    if root["schema_version"] != SCHEMA:
        raise QualifiedClosureCodecError(
            f"unsupported qualified model closure schema: {root['schema_version']!r}"
        )
    supplied_digest = _digest(root["closure_digest"], field="closure_digest")
    unsigned = {key: value for key, value in root.items() if key != "closure_digest"}
    if canonical_digest(unsigned) != supplied_digest:
        raise QualifiedClosureCodecError("qualified model closure digest mismatch")

    deployments_raw = root["deployments"]
    routes_raw = root["routes"]
    if type(deployments_raw) is not list or not deployments_raw:
        raise QualifiedClosureCodecError("closure deployments must be a non-empty list")
    if type(routes_raw) is not list or not routes_raw:
        raise QualifiedClosureCodecError("closure routes must be a non-empty list")

    roles = _roles(root["role_manifest"])
    deployments = tuple(
        _deployment(item, field=f"deployments[{index}]")
        for index, item in enumerate(deployments_raw)
    )
    routes = tuple(
        _route(item, field=f"routes[{index}]")
        for index, item in enumerate(routes_raw)
    )
    runtime_manifest_digest = _digest(
        root["runtime_manifest_digest"], field="runtime_manifest_digest"
    )
    runtime_root = _relative_runtime_root(root["runtime_qualification_root"])
    receipt_rows_raw = root["runtime_qualification_receipt_digests"]
    if type(receipt_rows_raw) is not list or not receipt_rows_raw:
        raise QualifiedClosureCodecError(
            "closure runtime qualification receipt digests must be a non-empty list"
        )
    receipt_rows: list[tuple[str, str]] = []
    for index, raw_row in enumerate(receipt_rows_raw):
        field = f"runtime_qualification_receipt_digests[{index}]"
        row = _mapping(
            raw_row,
            field=field,
            fields=frozenset({"deployment_id", "receipt_digest"}),
        )
        receipt_rows.append((
            _string(row["deployment_id"], field=f"{field}.deployment_id"),
            _digest(row["receipt_digest"], field=f"{field}.receipt_digest"),
        ))
    receipt_digests = tuple(receipt_rows)
    receipt_ids = tuple(item[0] for item in receipt_digests)
    if len(receipt_ids) != len(set(receipt_ids)):
        raise QualifiedClosureCodecError(
            "closure runtime qualification receipt deployment ids must be unique"
        )
    if receipt_digests != tuple(sorted(receipt_digests)):
        raise QualifiedClosureCodecError(
            "closure runtime qualification receipt digests must be canonically ordered"
        )
    canary_root = _relative_canary_root(root["runtime_canary_root"])
    canary_raw = root["runtime_canary_evidence_digests"]
    if type(canary_raw) is not list or not canary_raw:
        raise QualifiedClosureCodecError("closure runtime canary evidence digests must be a non-empty list")
    canary_digests = tuple(
        _digest(item, field="runtime_canary_evidence_digests[]") for item in canary_raw
    )
    if len(canary_digests) != len(set(canary_digests)):
        raise QualifiedClosureCodecError("closure runtime canary evidence digests must be unique")
    if canary_digests != tuple(sorted(canary_digests)):
        raise QualifiedClosureCodecError("closure runtime canary evidence digests must be canonically ordered")

    deployment_map = {item.deployment_id: item for item in deployments}
    route_map = {item.deployment_id: item for item in routes}
    if len(deployment_map) != len(deployments) or len(route_map) != len(routes):
        raise QualifiedClosureCodecError("closure contains duplicate deployment or route identity")
    if set(deployment_map) != set(route_map):
        raise QualifiedClosureCodecError("closure deployments/routes must have identical identities")
    receipt_digest_map = dict(receipt_digests)
    if set(receipt_digest_map) != set(deployment_map):
        raise QualifiedClosureCodecError(
            "closure runtime qualification receipt digests must align with deployments"
        )
    for deployment_id, deployment in deployment_map.items():
        if route_map[deployment_id].deployment_generation != deployment.digest():
            raise QualifiedClosureCodecError(
                f"closure route generation drift: {deployment_id}"
            )
    for assignment in roles.assignments:
        if assignment.deployment_id not in deployment_map:
            raise QualifiedClosureCodecError(
                f"closure role assignment references missing deployment: {assignment.role}"
            )

    return DecodedQualifiedClosure(
        role_manifest=roles,
        deployments=deployments,
        routes=routes,
        runtime_manifest_digest=runtime_manifest_digest,
        runtime_qualification_root=runtime_root,
        runtime_qualification_receipt_digests=receipt_digests,
        runtime_canary_root=canary_root,
        runtime_canary_evidence_digests=canary_digests,
        closure_digest=supplied_digest,
    )


__all__ = [
    "DecodedQualifiedClosure",
    "QualifiedClosureCodecError",
    "SCHEMA",
    "decode_qualified_closure",
    "encode_qualified_closure",
]
