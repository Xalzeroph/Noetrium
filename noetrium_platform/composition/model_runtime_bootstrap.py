from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import statistics
import time

from noetrium_platform.capabilities.model.asset.runtime import ModelAssetManager
from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentRuntimePort,
    ModelResourceViewPort,
)
from noetrium_platform.capabilities.model.deployment.composition import (
    LocalModelReplicaPoolRuntime,
    ModelReplicaPoolRequest,
)
from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    PerformanceSample,
    QualificationEvidence,
    QualificationPolicy,
    QualifiedDeploymentManifest,
    ResourceQualificationMeasurements,
    RoleCanaryResult,
    RoleModelAssignment,
    RoleModelManifest,
)
from noetrium_platform.capabilities.model.serving.composition import (
    canonical_runtime_canary_probe,
    issue_measured_qualification_certificate,
    qualify_and_publish_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
)
from noetrium_platform.infrastructure.resources.compute.api import ComputeSchedulerPort
from noetrium_platform.infrastructure.resources.container.api import (
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ServiceHeartbeat

from .model_stack_materialization import DockerModelStackMaterializer
from .research_execution_pool import ResearchExecutionPool


_GIB = 1024 ** 3
_PROTOCOL = (
    "generation",
    "model.generation.request.v1",
    "model.generation.response.v1",
)
GPU_MEMORY_ACCOUNTING_EVIDENCE_REF = "gpu-memory-accounting:container-process-v1"


@dataclass(frozen=True, slots=True)
class RequiredModelRuntime:
    model_id: str
    role: str
    required_capabilities: tuple[str, ...] = ("generation",)

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.role.strip():
            raise ValueError("required model runtime identity is incomplete")
        capabilities = tuple(sorted(set(self.required_capabilities)))
        if "generation" not in capabilities:
            raise ValueError("required model runtime must include generation")
        unsupported = set(capabilities) - {"generation", "structured_output"}
        if unsupported:
            raise ValueError(
                "unsupported automatic model qualification capabilities: "
                + ",".join(sorted(unsupported))
            )
        object.__setattr__(self, "required_capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class _Exchange:
    text: str
    finish_reason: str | None
    output_tokens: int
    elapsed_seconds: float


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not text:
        raise ValueError("model runtime authority path identity is empty")
    return text


def _qualification_body(
    model_id: str,
    capabilities: tuple[str, ...],
) -> dict[str, object]:
    if "structured_output" in capabilities:
        return {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": "Return exactly one JSON object with ok set to true.",
                }
            ],
            "temperature": 0,
            "max_tokens": 16,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "noetrium_model_qualification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"ok": {"const": True}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                },
            },
        }
    return {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": "Reply with exactly the token OK.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def _extract_exchange(response, elapsed_seconds: float) -> _Exchange:
    if response.status_code != 200:
        raise RuntimeError(
            f"model qualification HTTP status is not successful: {response.status_code}"
        )
    body = response.body
    if not isinstance(body, Mapping):
        raise RuntimeError("model qualification response body is not an object")
    choices = body.get("choices")
    if not isinstance(choices, tuple) or not choices:
        raise RuntimeError("model qualification response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise RuntimeError("model qualification first choice is invalid")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise RuntimeError("model qualification response has no message")
    text = message.get("content")
    if type(text) is not str or not text.strip():
        raise RuntimeError("model qualification response has empty content")
    finish = first.get("finish_reason")
    if finish is not None and type(finish) is not str:
        raise RuntimeError("model qualification finish reason is invalid")
    usage = body.get("usage")
    output_tokens = 0
    if isinstance(usage, Mapping):
        raw = usage.get("completion_tokens")
        if type(raw) is int and raw > 0:
            output_tokens = raw
    if output_tokens <= 0:
        output_tokens = max(1, len(text.split()))
    return _Exchange(
        text=text,
        finish_reason=finish,
        output_tokens=output_tokens,
        elapsed_seconds=max(float(elapsed_seconds), 1e-9),
    )


def _contract_passed(
    exchange: _Exchange,
    capabilities: tuple[str, ...],
) -> bool:
    if exchange.finish_reason not in {None, "stop", "length"}:
        return False
    if "structured_output" in capabilities:
        try:
            value = json.loads(exchange.text)
        except json.JSONDecodeError:
            return False
        return type(value) is dict and value == {"ok": True}
    return exchange.text.strip() == "OK"


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("qualification percentile requires measurements")
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _parse_memory_bytes(text: str) -> int:
    value = text.strip().split("/", 1)[0].strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?i?b)", value, re.I)
    if match is None:
        raise RuntimeError("Docker memory measurement format is unsupported: " + value)
    amount = float(match.group(1))
    unit = match.group(2).lower()
    multipliers = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
        "tb": 1000**4,
        "tib": 1024**4,
    }
    return max(1, int(amount * multipliers[unit]))


def _managed_container_id(command_runner, pid: int) -> str:
    listed = command_runner.run(
        (
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label={MANAGED_CONTAINER_LABEL}={MANAGED_CONTAINER_LABEL_VALUE}",
        ),
        timeout_seconds=20.0,
    )
    if listed.returncode != 0:
        raise RuntimeError("Docker managed-container inventory failed")
    container_ids = tuple(
        row.strip() for row in listed.stdout.splitlines() if row.strip()
    )
    if not container_ids:
        raise RuntimeError("model qualification found no managed Docker container")
    inspected = command_runner.run(
        (
            "docker",
            "inspect",
            "--format",
            "{{.Id}} {{.State.Pid}}",
            *container_ids,
        ),
        timeout_seconds=20.0,
    )
    if inspected.returncode != 0:
        raise RuntimeError("Docker managed-container process inspection failed")
    for line in inspected.stdout.splitlines():
        fields = line.strip().split()
        if len(fields) != 2:
            continue
        try:
            observed_pid = int(fields[1])
        except ValueError:
            continue
        if observed_pid == pid:
            return fields[0]
    raise RuntimeError("model qualification cannot resolve exact Docker container")


def _container_process_pids(command_runner, container_id: str) -> frozenset[int]:
    measured = command_runner.run(
        ("docker", "top", container_id, "-eo", "pid"),
        timeout_seconds=20.0,
    )
    if measured.returncode != 0:
        raise RuntimeError("Docker model process inventory failed")
    pids: set[int] = set()
    for line in measured.stdout.splitlines():
        fields = line.strip().split()
        if not fields:
            continue
        try:
            pid = int(fields[0])
        except ValueError:
            continue
        if pid > 0:
            pids.add(pid)
    if not pids:
        raise RuntimeError("Docker model process inventory is empty")
    return frozenset(pids)


def _container_memory_bytes(command_runner, container_id: str) -> int:
    measured = command_runner.run(
        (
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.MemUsage}}",
            container_id,
        ),
        timeout_seconds=20.0,
    )
    if measured.returncode != 0 or not measured.stdout.strip():
        raise RuntimeError("Docker model memory measurement failed")
    return _parse_memory_bytes(measured.stdout.splitlines()[0])


def _gpu_memory_bytes(
    resources: ModelResourceViewPort,
    gpu_ids: tuple[str, ...],
    command_runner,
    container_id: str,
) -> int:
    snapshot = resources.gpu_runtime()
    if not snapshot.available:
        raise RuntimeError("GPU runtime measurement is unavailable")
    if not snapshot.processes_complete:
        raise RuntimeError("GPU process memory measurement is incomplete")
    selected_gpus = frozenset(gpu_ids)
    if not selected_gpus or len(selected_gpus) != len(gpu_ids):
        raise RuntimeError("GPU process memory measurement requires unique placement")
    container_pids = _container_process_pids(command_runner, container_id)
    usage = {gpu_id: 0 for gpu_id in selected_gpus}
    for process in snapshot.processes:
        if process.pid not in container_pids or process.gpu_uuid not in selected_gpus:
            continue
        usage[process.gpu_uuid] += process.used_memory_mb * 1024 * 1024
    missing = tuple(sorted(gpu_id for gpu_id, used in usage.items() if used <= 0))
    if missing:
        raise RuntimeError(
            "GPU process memory measurement does not cover placement: "
            + ",".join(missing)
        )
    return max(usage.values())

def _run_static_qualification(
    *,
    model_id: str,
    requirements: tuple[RequiredModelRuntime, ...],
    completion_url: str,
    http_client,
    resources: ModelResourceViewPort,
    gpu_ids: tuple[str, ...],
    command_runner,
    process_pid: int,
    stack_digest: str,
    host_identity_digest: str,
):
    role_results: list[RoleCanaryResult] = []
    all_exchanges: list[_Exchange] = []
    exact_reproducible = True
    peak_gpu = 0
    peak_host = 0
    container_id = _managed_container_id(command_runner, process_pid)

    for requirement in requirements:
        body = _qualification_body(model_id, requirement.required_capabilities)
        payload = json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        exchanges: list[_Exchange] = []
        for _ in range(2):
            started = time.perf_counter()
            response = http_client.post_json(
                completion_url,
                payload,
                timeout_s=120.0,
            )
            exchange = _extract_exchange(
                response,
                time.perf_counter() - started,
            )
            exchanges.append(exchange)
            all_exchanges.append(exchange)
            peak_gpu = max(
                peak_gpu,
                _gpu_memory_bytes(resources, gpu_ids, command_runner, container_id),
            )
            peak_host = max(
                peak_host,
                _container_memory_bytes(command_runner, container_id),
            )

        passed = sum(
            1
            for exchange in exchanges
            if _contract_passed(exchange, requirement.required_capabilities)
        )
        role_results.append(
            RoleCanaryResult(
                role=requirement.role,
                total=len(exchanges),
                passed=passed,
                critical_total=len(exchanges),
                critical_passed=passed,
                contract_errors=len(exchanges) - passed,
            )
        )
        exact_reproducible = (
            exact_reproducible
            and len({exchange.text for exchange in exchanges}) == 1
        )

    if not all_exchanges:
        raise RuntimeError("model qualification produced no measurements")

    completion_latencies = [
        exchange.elapsed_seconds for exchange in all_exchanges
    ]
    token_periods = [
        exchange.elapsed_seconds / max(1, exchange.output_tokens)
        for exchange in all_exchanges
    ]
    throughputs = [
        exchange.output_tokens / exchange.elapsed_seconds
        for exchange in all_exchanges
    ]
    performance = PerformanceSample(
        concurrency=1,
        # Non-streaming completion latency is a conservative upper bound for
        # first-token latency and therefore cannot overstate qualified capacity.
        ttft_p50=_percentile(completion_latencies, 0.50),
        ttft_p99=_percentile(completion_latencies, 0.99),
        tpot_p50=_percentile(token_periods, 0.50),
        tpot_p99=_percentile(token_periods, 0.99),
        output_tokens_per_second=min(throughputs),
        error_rate=0.0,
    )
    evidence = QualificationEvidence(
        model_stack_digest=stack_digest,
        canaries=tuple(role_results),
        performance=(performance,),
        exact_output_reproducibility_checked=exact_reproducible,
        long_context_checked=False,
        tool_call_checked=False,
    )
    policy = QualificationPolicy(
        minimum_role_pass_rate=1.0,
        require_zero_critical_failures=True,
        max_error_rate=0.0,
        require_exact_output_reproducibility=True,
        require_long_context_checked=False,
        require_tool_call_checked=False,
    )
    measured = ResourceQualificationMeasurements(
        peak_gpu_memory_bytes_per_device=max(1, peak_gpu),
        peak_host_memory_bytes=max(1, peak_host),
        max_qualified_concurrency=1,
    )
    certificate = issue_measured_qualification_certificate(
        evidence,
        policy,
        measured,
        qualified_roles=tuple(sorted({row.role for row in requirements})),
        target_host_identity_digest=host_identity_digest,
    )
    return certificate, evidence, measured


def bootstrap_required_qualified_model_runtime(
    *,
    authority_root: Path,
    project_root: Path,
    state_root: Path,
    requirements: tuple[RequiredModelRuntime, ...],
    assets: ModelAssetManager,
    compute_scheduler: ComputeSchedulerPort,
    model_replica_pool: LocalModelReplicaPoolRuntime,
    deployment_runtime: ModelDeploymentRuntimePort,
    model_resources: ModelResourceViewPort,
    execution_pool: ResearchExecutionPool,
) -> str:
    if not requirements:
        raise ValueError("model runtime bootstrap requires model requirements")
    model_ids = {row.model_id for row in requirements}
    if len(model_ids) != 1:
        raise ValueError("one bootstrap closure must target exactly one model")
    model_id = next(iter(model_ids))
    roles = tuple(row.role for row in requirements)
    if len(set(roles)) != len(roles):
        raise ValueError("model runtime bootstrap roles must be unique")

    control_group = execution_pool.open_control_group(
        "model-runtime-bootstrap:" + _slug(model_id),
        resource_id="model-runtime-bootstrap:" + model_id,
    )
    lease = None
    try:
        command_runner = build_local_command_runner(
            control_group,
            task_namespace="model-runtime-bootstrap",
        )
        materialized = DockerModelStackMaterializer(
            assets=assets,
            compute_scheduler=compute_scheduler,
            command_runner=command_runner,
            state_root=state_root,
        ).materialize(model_id)
        stack = materialized.stack
        request = ModelReplicaPoolRequest(
            pool_id=(
                "qualified-model:"
                + canonical_digest(
                    {
                        "model_id": model_id,
                        "roles": tuple(sorted(roles)),
                        "stack_digest": stack.digest(),
                    }
                )[:24]
            ),
            scope=PLATFORM_SCOPE,
            model_id=model_id,
            engine=stack.identity.engine,
            cwd=project_root,
            compute=materialized.compute,
            model_stack=stack,
            replica_count=1,
            endpoint_host="127.0.0.1",
            tags=("qualified-model", "automatic"),
        )
        lease = model_replica_pool.ensure(request)
        lease.assert_healthy()
        row = lease.report.placements[0]
        applied = deployment_runtime.applied_identity(row.deployment_id)
        completion_url = (
            f"http://{row.endpoint.endpoint.host}:"
            f"{row.endpoint.endpoint.port}/v1/chat/completions"
        )
        certificate, evidence, measured = _run_static_qualification(
            model_id=model_id,
            requirements=requirements,
            completion_url=completion_url,
            http_client=execution_pool.model_json_http_client,
            resources=model_resources,
            gpu_ids=row.compute.gpu_ids,
            command_runner=command_runner,
            process_pid=applied.pid,
            stack_digest=stack.digest(),
            host_identity_digest=row.compute.host_id,
        )

        deployment = QualifiedDeploymentManifest(
            deployment_id=row.deployment_id,
            stack=stack,
            certificate=certificate,
            placement=DeploymentPlacement(row.compute.gpu_ids),
            host_identity_digest=row.compute.host_id,
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
            stack_digest=stack.digest(),
            pid=applied.pid,
            process_start_marker=applied.process_start_marker,
            argv_digest=applied.argv_digest,
            ready=True,
            qualification_digest=certificate.digest(),
            timestamp=time.time(),
        )
        assignments = tuple(
            RoleModelAssignment(
                role=requirement.role,
                capability_id=_PROTOCOL[0],
                input_schema_id=_PROTOCOL[1],
                output_schema_id=_PROTOCOL[2],
                deployment_id=row.deployment_id,
            )
            for requirement in sorted(requirements, key=lambda item: item.role)
        )
        role_manifest = RoleModelManifest(assignments)
        capability_by_role = {
            row.role: row.required_capabilities for row in requirements
        }
        probes = tuple(
            canonical_runtime_canary_probe(
                assignment,
                deployment,
                required_capabilities=capability_by_role[assignment.role],
            )
            for assignment in role_manifest.assignments
        )
        runtime_manifest_digest = canonical_digest(
            {
                "schema": "noetrium.qualified-model-runtime",
                "model_id": model_id,
                "stack_digest": stack.digest(),
                "certificate_digest": certificate.digest(),
                "deployment_id": row.deployment_id,
                "deployment_generation": deployment.digest(),
                "compute_allocation": row.compute,
                "endpoint_allocation": row.endpoint,
                "applied_runtime_identity": applied,
                "static_qualification_evidence": evidence,
                "resource_measurements": measured,
            }
        )
        closure_path = (
            authority_root
            / "models"
            / _slug(model_id)
            / "qualified-model-closure.json"
        )
        group = execution_pool.open_model_io_group(
            "qualified-model-bootstrap:" + _slug(model_id)
        )
        try:
            receipt = qualify_and_publish_model_deployment_closure(
                closure_path,
                role_manifest=role_manifest,
                deployments=(deployment,),
                routes=(route,),
                heartbeats=(heartbeat,),
                canary_probes=probes,
                runtime_manifest_digest=runtime_manifest_digest,
                max_heartbeat_age_seconds=120.0,
                task_group=group,
                admission_registry=execution_pool.model_admission,
                transports_by_deployment={
                    row.deployment_id: execution_pool.model_http_transport,
                },
                extra_evidence_refs_by_deployment={
                    row.deployment_id: (
                        "static-qualification:sha256:"
                        + certificate.evidence_digest,
                        "model-stack-fingerprint:sha256:"
                        + canonical_digest(materialized.fingerprint_ref),
                        GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
                    ),
                },
            )
        finally:
            execution_pool.close_model_io_group(
                group,
                cancel_pending=True,
            )
        return receipt.closure_digest
    except BaseException:
        if lease is not None:
            try:
                lease.close()
            except BaseException:
                pass
        raise
    finally:
        execution_pool.close_control_group(
            control_group,
            cancel_pending=True,
        )


__all__ = [
    "RequiredModelRuntime",
    "bootstrap_required_qualified_model_runtime",
]
