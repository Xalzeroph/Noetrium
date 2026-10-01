from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
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
    AsyncJsonHttpTransportPort,
    AsyncJsonSseTransportPort,
    ModelEndpointRoute,
    ModelStreamEventKind,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.capabilities.model.serving.provider import (
    OpenAIChatStreamDecoder,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.capabilities.model.stack.api import (
    ModelStackSpec,
    parse_vllm_engine_resource_args,
)
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
)
from noetrium_platform.infrastructure.resources.compute.api import ComputeSchedulerPort
from noetrium_platform.infrastructure.resources.container.api import (
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ServiceHeartbeat

from .model_stack_materialization import (
    DockerModelStackMaterializer,
    ModelStackPlacementUnavailable,
    model_kv_cache_budget_bytes,
    model_kv_cache_bytes_per_token,
)
from .research_execution_pool import ResearchExecutionPool


_GIB = 1024 ** 3
_PROTOCOL = (
    "generation",
    "model.generation.request.v1",
    "model.generation.response.v1",
)
_GPU_MEMORY_ACCOUNTING_EVIDENCE = {
    "schema": "noetrium.gpu-memory-accounting.v1",
    "scope": "managed-container-processes",
    "aggregation": "max-per-placement-device",
    "foreign_processes": "excluded",
}
GPU_MEMORY_ACCOUNTING_EVIDENCE_REF = (
    "gpu-memory-accounting:sha256:"
    + canonical_digest(_GPU_MEMORY_ACCOUNTING_EVIDENCE)
)


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
    prompt_tokens: int
    output_tokens: int
    elapsed_seconds: float
    ttft_seconds: float | None = None
    tpot_seconds: float | None = None


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
    prompt_tokens = 0
    output_tokens = 0
    if isinstance(usage, Mapping):
        raw_prompt = usage.get("prompt_tokens")
        if type(raw_prompt) is int and raw_prompt > 0:
            prompt_tokens = raw_prompt
        raw = usage.get("completion_tokens")
        if type(raw) is int and raw > 0:
            output_tokens = raw
    if output_tokens <= 0:
        output_tokens = max(1, len(text.split()))
    return _Exchange(
        text=text,
        finish_reason=finish,
        prompt_tokens=max(1, prompt_tokens),
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

def _static_qualification_concurrency_ceiling(
    *,
    stack,
    execution_pool: ResearchExecutionPool,
) -> int:
    ceiling = execution_pool.model_http_max_connections
    if type(ceiling) is not int or ceiling <= 0:
        raise RuntimeError(
            "model qualification requires a positive HTTP concurrency ceiling"
        )
    if stack.identity.engine.lower() == "vllm":
        intent = parse_vllm_engine_resource_args(stack.engine_args)
        active_limit = (
            intent.max_num_seqs
            if intent.max_num_active_seqs is None
            else intent.max_num_active_seqs
        )
        if active_limit is not None:
            ceiling = min(ceiling, active_limit)
        if intent.max_num_queued_requests is not None:
            ceiling = min(ceiling, intent.max_num_queued_requests)
    return max(1, ceiling)


def _throughput_qualification_body(
    model_id: str,
    *,
    prefill_padding_tokens: int = 0,
) -> dict[str, object]:
    if type(prefill_padding_tokens) is not int or prefill_padding_tokens < 0:
        raise ValueError("qualification prefill_padding_tokens must be non-negative")
    instruction = (
        "Generate a compact deterministic numbered sequence from "
        "1 upward and continue until the output budget ends."
    )
    content = (
        instruction
        if prefill_padding_tokens == 0
        else ("x " * prefill_padding_tokens) + "\n" + instruction
    )
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 64,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def _throughput_qualification_payloads(
    model_id: str,
    *,
    context_length: int,
    observed_prompt_tokens: int,
) -> tuple[bytes, ...]:
    if type(context_length) is not int or context_length <= 0:
        raise ValueError("qualification context_length must be positive")
    if type(observed_prompt_tokens) is not int or observed_prompt_tokens <= 0:
        raise ValueError("qualification observed_prompt_tokens must be positive")
    derived_prefill = math.ceil(
        math.sqrt(context_length * observed_prompt_tokens)
    )
    safe_prefill = min(
        max(observed_prompt_tokens * 2, derived_prefill),
        max(observed_prompt_tokens, context_length // 8),
    )
    bodies = (
        _throughput_qualification_body(model_id),
        _throughput_qualification_body(
            model_id,
            prefill_padding_tokens=safe_prefill,
        ),
    )
    return tuple(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        for body in bodies
    )


async def _stream_qualification_exchange(
    *,
    completion_url: str,
    payload: bytes,
    http_transport: AsyncJsonSseTransportPort,
    timeout_s: float,
    clock=time.perf_counter,
) -> _Exchange:
    if not isinstance(http_transport, AsyncJsonSseTransportPort):
        raise TypeError(
            "model static performance qualification requires SSE transport"
        )
    decoder = OpenAIChatStreamDecoder(
        provider_id="noetrium.vllm.static-qualification",
    )
    started = float(clock())
    first_text_at: float | None = None
    last_text_at: float | None = None
    text_parts: list[str] = []
    finish_reason: str | None = None
    prompt_tokens = 0
    output_tokens = 0

    def on_event(raw) -> None:
        nonlocal first_text_at, last_text_at
        nonlocal finish_reason, prompt_tokens, output_tokens
        observed_at = float(clock())
        for event in decoder.decode(raw):
            if event.kind is ModelStreamEventKind.TEXT_DELTA and event.text_delta:
                if first_text_at is None:
                    first_text_at = observed_at
                last_text_at = observed_at
                text_parts.append(event.text_delta)
            elif event.kind is ModelStreamEventKind.USAGE and event.usage is not None:
                raw_prompt = event.usage.get("prompt_tokens")
                raw_output = event.usage.get("completion_tokens")
                if type(raw_prompt) is int and raw_prompt > 0:
                    prompt_tokens = raw_prompt
                if type(raw_output) is int and raw_output > 0:
                    output_tokens = raw_output
            elif (
                event.kind is ModelStreamEventKind.COMPLETED
                and isinstance(event.content, Mapping)
            ):
                value = event.content.get("finish_reason")
                if isinstance(value, str) and value:
                    finish_reason = value

    response = await http_transport.post_sse(
        completion_url,
        payload,
        timeout_s=timeout_s,
        idle_timeout_s=min(timeout_s, 30.0),
        on_event=on_event,
    )
    finished = float(clock())
    if response.status_code != 200:
        raise RuntimeError(
            "model qualification SSE status is not successful: "
            f"{response.status_code}"
        )
    if first_text_at is None or last_text_at is None:
        raise RuntimeError(
            "model qualification SSE produced no text token"
        )
    text = "".join(text_parts)
    if output_tokens <= 0:
        output_tokens = max(1, len(text.split()))
    prompt_tokens = max(1, prompt_tokens)
    ttft = max(0.0, first_text_at - started)
    if output_tokens > 1:
        tpot = max(
            0.0,
            (last_text_at - first_text_at) / (output_tokens - 1),
        )
    else:
        tpot = max(0.0, finished - first_text_at)
    return _Exchange(
        text=text,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        elapsed_seconds=max(finished - started, 1e-9),
        ttft_seconds=ttft,
        tpot_seconds=tpot,
    )


def _run_concurrency_probe(
    *,
    concurrency: int,
    payloads: tuple[bytes, ...],
    completion_url: str,
    http_transport: AsyncJsonSseTransportPort,
    task_group: TaskGroupPort,
) -> tuple[PerformanceSample | None, tuple[_Exchange, ...]]:
    if type(concurrency) is not int or concurrency <= 0:
        raise ValueError("model qualification concurrency must be positive")
    if not payloads:
        raise ValueError("model qualification requires at least one payload")

    handles = []
    wave_started = time.perf_counter()
    for ordinal in range(concurrency):
        payload = payloads[ordinal % len(payloads)]

        async def invoke(context, *, _payload=payload):
            context.checkpoint()
            started = time.perf_counter()
            remaining = context.remaining_seconds
            timeout_s = 120.0 if remaining is None else min(120.0, remaining)
            if timeout_s <= 0:
                context.checkpoint()
                raise TimeoutError(
                    "model qualification deadline expired before transport"
                )
            try:
                exchange = await _stream_qualification_exchange(
                    completion_url=completion_url,
                    payload=_payload,
                    http_transport=http_transport,
                    timeout_s=timeout_s,
                )
                context.checkpoint()
                return exchange
            except Exception:
                return None

        handles.append(
            task_group.submit(
                ExecutionSpec(
                    task_id=(
                        "model-static-qualification:"
                        f"{concurrency}:{ordinal}"
                    ),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                invoke,
                deadline=Deadline.after(120.0),
            )
        )

    exchanges: list[_Exchange] = []
    failed = 0
    for handle in handles:
        try:
            value = handle.result()
        except BaseException:
            failed += 1
            continue
        if not isinstance(value, _Exchange):
            failed += 1
            continue
        exchanges.append(value)

    wall_seconds = max(time.perf_counter() - wave_started, 1e-9)
    if failed or len(exchanges) != concurrency:
        return None, tuple(exchanges)

    ttft_values = [
        exchange.ttft_seconds
        for exchange in exchanges
        if exchange.ttft_seconds is not None
    ]
    tpot_values = [
        exchange.tpot_seconds
        for exchange in exchanges
        if exchange.tpot_seconds is not None
    ]
    if len(ttft_values) != len(exchanges) or len(tpot_values) != len(exchanges):
        raise RuntimeError(
            "streaming qualification lost TTFT/TPOT measurements"
        )
    total_output_tokens = sum(
        exchange.output_tokens for exchange in exchanges
    )
    return (
        PerformanceSample(
            concurrency=concurrency,
            ttft_p50=_percentile(ttft_values, 0.50),
            ttft_p99=_percentile(ttft_values, 0.99),
            tpot_p50=_percentile(tpot_values, 0.50),
            tpot_p99=_percentile(tpot_values, 0.99),
            output_tokens_per_second=(
                total_output_tokens / wall_seconds
            ),
            error_rate=0.0,
        ),
        tuple(exchanges),
    )


def _without_engine_option(
    args: tuple[str, ...],
    *,
    name: str,
) -> tuple[str, ...]:
    rows: list[str] = []
    index = 0
    prefix = name + "="
    while index < len(args):
        item = args[index]
        if item == name:
            if index + 1 >= len(args):
                raise ValueError(f"engine option requires a value: {name}")
            index += 2
            continue
        if item.startswith(prefix):
            index += 1
            continue
        rows.append(item)
        index += 1
    return tuple(rows)


def qualification_source_stack_digest(stack: ModelStackSpec) -> str:
    """Digest the immutable qualification source, excluding measured tuning.

    Static qualification may produce a re-qualified vLLM stack whose only
    derived scheduler mutation is ``--max-num-seqs``. Runtime refresh must
    compare the current materialized source against that source identity, not
    mistake the measured tuning result for a user/model/runtime change.
    """
    if not isinstance(stack, ModelStackSpec):
        raise TypeError("qualification source digest requires ModelStackSpec")
    if stack.identity.engine.strip().lower() != "vllm":
        return stack.digest()
    source_args = _without_engine_option(
        stack.engine_args,
        name="--max-num-seqs",
    )
    if source_args == stack.engine_args:
        return stack.digest()
    return replace(stack, engine_args=source_args).digest()


def _with_engine_integer_option(
    args: tuple[str, ...],
    *,
    name: str,
    value: int,
) -> tuple[str, ...]:
    if type(value) is not int or value <= 0:
        raise ValueError("engine integer option must be positive")
    rows = list(_without_engine_option(args, name=name))
    rows.extend((name, str(value)))
    return tuple(rows)


def _tuned_vllm_stack_candidate(
    stack: ModelStackSpec,
    certificate,
) -> ModelStackSpec:
    if stack.identity.engine.strip().lower() != "vllm":
        return stack
    envelope = certificate.resource_envelope
    safe = envelope.max_qualified_concurrency
    preferred = envelope.preferred_operating_concurrency
    if preferred is None or safe <= preferred:
        return stack
    # Explore exactly one measured step beyond the current throughput knee.
    # The final tuned stack is re-qualified, so this is a candidate proposal,
    # never an unverified production mutation.
    target = min(safe, preferred * 2)
    if target <= preferred:
        return stack
    args = _with_engine_integer_option(
        stack.engine_args,
        name="--max-num-seqs",
        value=target,
    )
    return replace(stack, engine_args=args)


def _historical_preferred_concurrency(
    path: Path,
    *,
    stack_digest: str,
    host_identity_digest: str,
) -> int | None:
    if not path.is_file():
        return None
    try:
        closure = load_qualified_model_deployment_closure(
            path,
            runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
            runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
        )
    except Exception:
        return None
    values = tuple(
        deployment.certificate.resource_envelope.preferred_operating_concurrency
        for deployment in closure.deployments
        if (
            deployment.stack.digest() == stack_digest
            and deployment.host_identity_digest == host_identity_digest
        )
    )
    valid = tuple(
        value for value in values
        if type(value) is int and value > 0
    )
    return min(valid) if valid else None


def _computed_initial_qualification_concurrency(
    *,
    asset_path: Path,
    stack,
    max_concurrency: int,
    observed_prompt_tokens: int,
    output_token_budget: int,
) -> int:
    if type(max_concurrency) is not int or max_concurrency <= 0:
        raise ValueError("qualification max_concurrency must be positive")
    if type(observed_prompt_tokens) is not int or observed_prompt_tokens <= 0:
        raise ValueError("qualification observed prompt tokens must be positive")
    if type(output_token_budget) is not int or output_token_budget <= 0:
        raise ValueError("qualification output token budget must be positive")

    per_token = model_kv_cache_bytes_per_token(
        asset_path,
        dtype=stack.identity.dtype,
        tensor_parallel=stack.tensor_parallel,
    )
    kv_budget = model_kv_cache_budget_bytes(
        asset_path,
        context_length=stack.identity.context_length,
        dtype=stack.identity.dtype,
        tensor_parallel=stack.tensor_parallel,
    )
    request_tokens = min(
        stack.identity.context_length,
        observed_prompt_tokens + output_token_budget,
    )
    if request_tokens <= 0:
        return 1
    estimated_capacity = max(
        1,
        min(
            max_concurrency,
            int(kv_budget // max(1, per_token * request_tokens)),
        ),
    )
    # No prior performance curve exists on a true cold start.  Treat the KV /
    # transport estimate as a hard search ceiling, not as an operating point.
    # The geometric center minimizes the worst-case multiplicative distance to
    # an unknown throughput knee and lets the bidirectional qualifier converge
    # quickly without starting at either 1 or the capacity cliff.
    return max(1, min(
        estimated_capacity,
        int(math.ceil(math.sqrt(estimated_capacity))),
    ))


def _measure_static_concurrency_capacity(
    *,
    payloads: tuple[bytes, ...],
    completion_url: str,
    http_transport: AsyncJsonSseTransportPort,
    task_group: TaskGroupPort,
    max_concurrency: int,
    initial_concurrency: int,
    resources: ModelResourceViewPort,
    gpu_ids: tuple[str, ...],
    command_runner,
    container_id: str,
) -> tuple[tuple[PerformanceSample, ...], int, int, int]:
    if type(max_concurrency) is not int or max_concurrency <= 0:
        raise ValueError(
            "model qualification max_concurrency must be positive"
        )
    if type(initial_concurrency) is not int or initial_concurrency <= 0:
        raise ValueError(
            "model qualification initial_concurrency must be positive"
        )
    initial_concurrency = min(initial_concurrency, max_concurrency)

    samples: dict[int, PerformanceSample] = {}
    peak_gpu = 0
    peak_host = 0

    def probe(concurrency: int) -> bool:
        nonlocal peak_gpu, peak_host
        if concurrency in samples:
            return True
        sample, _exchanges = _run_concurrency_probe(
            concurrency=concurrency,
            payloads=payloads,
            completion_url=completion_url,
            http_transport=http_transport,
            task_group=task_group,
        )
        if sample is None:
            return False
        samples[concurrency] = sample
        peak_gpu = max(
            peak_gpu,
            _gpu_memory_bytes(
                resources,
                gpu_ids,
                command_runner,
                container_id,
            ),
        )
        peak_host = max(
            peak_host,
            _container_memory_bytes(command_runner, container_id),
        )
        return True

    failed_upper: int | None = None
    if probe(initial_concurrency):
        highest = initial_concurrency
        # Calibrate one point below the computed launch point so the
        # preferred-operating-concurrency knee can be measured without making
        # concurrency=1 the cold-start path.
        lower = max(1, initial_concurrency // 2)
        calibration_points = 0
        while lower != initial_concurrency and calibration_points < 2:
            probe(lower)
            calibration_points += 1
            if lower == 1:
                break
            lower = max(1, lower // 2)

        plateau_streak = 0
        candidate = min(max_concurrency, initial_concurrency * 2)
        while candidate > highest:
            if not probe(candidate):
                failed_upper = candidate
                break
            previous = samples[highest]
            current = samples[candidate]
            throughput_gain = (
                current.output_tokens_per_second
                / max(previous.output_tokens_per_second, 1e-9)
            )
            ttft_ratio = current.ttft_p99 / max(previous.ttft_p99, 1e-9)
            tpot_ratio = current.tpot_p99 / max(previous.tpot_p99, 1e-9)
            highest = candidate
            strong_plateau = (
                throughput_gain <= 1.05
                and max(ttft_ratio, tpot_ratio) >= 1.30
            )
            soft_plateau = (
                throughput_gain <= 1.03
                and max(ttft_ratio, tpot_ratio) >= 1.15
            )
            if soft_plateau:
                plateau_streak += 1
            else:
                plateau_streak = 0
            if (
                strong_plateau
                or plateau_streak >= 2
                or candidate == max_concurrency
            ):
                break
            candidate = min(max_concurrency, candidate * 2)
    else:
        failed_upper = initial_concurrency
        candidate = max(1, initial_concurrency // 2)
        while True:
            if probe(candidate):
                highest = candidate
                break
            failed_upper = candidate
            if candidate == 1:
                raise RuntimeError(
                    "model qualification failed down to concurrency=1"
                )
            candidate = max(1, candidate // 2)

    if failed_upper is not None and failed_upper - highest > 1:
        low = highest
        high = failed_upper - 1
        while low < high:
            middle = (low + high + 1) // 2
            if probe(middle):
                low = middle
            else:
                high = middle - 1
        highest = low

    if highest not in samples:
        if not probe(highest):
            raise RuntimeError(
                "model qualification lost the measured safe concurrency"
            )

    ordered_samples = tuple(
        samples[key] for key in sorted(samples)
    )
    return (
        ordered_samples,
        highest,
        max(1, peak_gpu),
        max(1, peak_host),
    )


def _run_static_qualification(
    *,
    model_id: str,
    requirements: tuple[RequiredModelRuntime, ...],
    asset_path: Path,
    stack,
    initial_concurrency_hint: int | None,
    completion_url: str,
    http_client,
    http_transport: AsyncJsonHttpTransportPort,
    task_group: TaskGroupPort,
    max_concurrency: int,
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
    if not isinstance(http_transport, AsyncJsonSseTransportPort):
        raise TypeError(
            "local static model qualification requires JSON+SSE transport"
        )
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

    observed_prompt_tokens = max(
        exchange.prompt_tokens for exchange in all_exchanges
    )
    payloads = _throughput_qualification_payloads(
        model_id,
        context_length=stack.identity.context_length,
        observed_prompt_tokens=observed_prompt_tokens,
    )
    computed_initial = _computed_initial_qualification_concurrency(
        asset_path=asset_path,
        stack=stack,
        max_concurrency=max_concurrency,
        observed_prompt_tokens=observed_prompt_tokens,
        output_token_budget=int(
            _throughput_qualification_body(model_id)["max_tokens"]
        ),
    )
    initial_concurrency = (
        computed_initial
        if initial_concurrency_hint is None
        else max(1, min(max_concurrency, initial_concurrency_hint))
    )
    performance, qualified_concurrency, probe_peak_gpu, probe_peak_host = (
        _measure_static_concurrency_capacity(
            payloads=payloads,
            completion_url=completion_url,
            http_transport=http_transport,
            task_group=task_group,
            max_concurrency=max_concurrency,
            initial_concurrency=initial_concurrency,
            resources=resources,
            gpu_ids=gpu_ids,
            command_runner=command_runner,
            container_id=container_id,
        )
    )
    peak_gpu = max(peak_gpu, probe_peak_gpu)
    peak_host = max(peak_host, probe_peak_host)
    evidence = QualificationEvidence(
        model_stack_digest=stack_digest,
        canaries=tuple(role_results),
        performance=performance,
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
        max_qualified_concurrency=qualified_concurrency,
    )
    certificate = issue_measured_qualification_certificate(
        evidence,
        policy,
        measured,
        qualified_roles=tuple(sorted({row.role for row in requirements})),
        target_host_identity_digest=host_identity_digest,
    )
    return certificate, evidence, measured


@dataclass(slots=True)
class _QualifiedRuntimeRealization:
    stack: ModelStackSpec
    request: ModelReplicaPoolRequest
    lease: object
    row: object
    applied: object
    certificate: object
    evidence: QualificationEvidence
    measured: ResourceQualificationMeasurements


def _realize_and_qualify_model_stack(
    *,
    model_id: str,
    roles: tuple[str, ...],
    stack: ModelStackSpec,
    compute,
    runtime_workdir: Path,
    model_replica_pool: LocalModelReplicaPoolRuntime,
    deployment_runtime: ModelDeploymentRuntimePort,
    execution_pool: ResearchExecutionPool,
    authority_root: Path,
    requirements: tuple[RequiredModelRuntime, ...],
    assets: ModelAssetManager,
    model_resources: ModelResourceViewPort,
    command_runner,
    initial_concurrency_hint: int | None,
) -> _QualifiedRuntimeRealization:
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
        cwd=runtime_workdir,
        compute=compute,
        model_stack=stack,
        replica_count=1,
        endpoint_host="127.0.0.1",
        tags=("qualified-model", "automatic"),
    )
    lease = model_replica_pool.ensure(request)
    try:
        lease.assert_healthy()
        row = lease.report.placements[0]
        applied = deployment_runtime.applied_identity(row.deployment_id)
        completion_url = (
            f"http://{row.endpoint.endpoint.host}:"
            f"{row.endpoint.endpoint.port}/v1/chat/completions"
        )
        historical_preferred = initial_concurrency_hint
        if historical_preferred is None:
            historical_closure_path = (
                authority_root
                / "models"
                / _slug(model_id)
                / "qualified-model-closure.json"
            )
            historical_preferred = _historical_preferred_concurrency(
                historical_closure_path,
                stack_digest=stack.digest(),
                host_identity_digest=row.compute.host_id,
            )
        qualification_group = execution_pool.open_model_io_group(
            "model-static-qualification:"
            + _slug(model_id)
            + ":"
            + stack.digest()[:12],
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )
        try:
            certificate, evidence, measured = _run_static_qualification(
                model_id=model_id,
                requirements=requirements,
                asset_path=assets.model(model_id).path,
                stack=stack,
                initial_concurrency_hint=historical_preferred,
                completion_url=completion_url,
                http_client=execution_pool.model_json_http_client,
                http_transport=execution_pool.model_http_transport,
                task_group=qualification_group,
                max_concurrency=_static_qualification_concurrency_ceiling(
                    stack=stack,
                    execution_pool=execution_pool,
                ),
                resources=model_resources,
                gpu_ids=row.compute.gpu_ids,
                command_runner=command_runner,
                process_pid=applied.pid,
                stack_digest=stack.digest(),
                host_identity_digest=row.compute.host_id,
            )
        finally:
            execution_pool.close_model_io_group(
                qualification_group,
                cancel_pending=True,
            )
        return _QualifiedRuntimeRealization(
            stack=stack,
            request=request,
            lease=lease,
            row=row,
            applied=applied,
            certificate=certificate,
            evidence=evidence,
            measured=measured,
        )
    except BaseException:
        lease.close()
        raise


def bootstrap_required_qualified_model_runtime(
    *,
    authority_root: Path,
    project_root: Path,
    state_root: Path,
    runtime_workdir: Path,
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
        materializer = DockerModelStackMaterializer(
            assets=assets,
            compute_scheduler=compute_scheduler,
            command_runner=command_runner,
            state_root=state_root,
        )
        while True:
            try:
                materialized = materializer.materialize(model_id)
                break
            except ModelStackPlacementUnavailable:
                reclaimed = model_replica_pool.reclaim_one_stale_warm_realization()
                if reclaimed is None:
                    raise
        stack = materialized.stack
        runtime_workdir.mkdir(parents=True, exist_ok=True)
        realization = _realize_and_qualify_model_stack(
            model_id=model_id,
            roles=roles,
            stack=stack,
            compute=materialized.compute,
            runtime_workdir=runtime_workdir,
            model_replica_pool=model_replica_pool,
            deployment_runtime=deployment_runtime,
            execution_pool=execution_pool,
            authority_root=authority_root,
            requirements=requirements,
            assets=assets,
            model_resources=model_resources,
            command_runner=command_runner,
            initial_concurrency_hint=None,
        )
        lease = realization.lease
        request = realization.request
        row = realization.row
        applied = realization.applied
        certificate = realization.certificate
        evidence = realization.evidence
        measured = realization.measured

        tuned_stack = _tuned_vllm_stack_candidate(
            stack,
            certificate,
        )
        if tuned_stack.digest() != stack.digest():
            preferred = (
                certificate.resource_envelope.preferred_operating_concurrency
            )
            lease.close()
            lease = None
            try:
                retired = model_replica_pool.retire(request)
            except RuntimeError as exc:
                if "active consumers" not in str(exc):
                    raise
                retired = False

            if retired:
                tuned = _realize_and_qualify_model_stack(
                    model_id=model_id,
                    roles=roles,
                    stack=tuned_stack,
                    compute=materialized.compute,
                    runtime_workdir=runtime_workdir,
                    model_replica_pool=model_replica_pool,
                    deployment_runtime=deployment_runtime,
                    execution_pool=execution_pool,
                    authority_root=authority_root,
                    requirements=requirements,
                    assets=assets,
                    model_resources=model_resources,
                    command_runner=command_runner,
                    initial_concurrency_hint=preferred,
                )
                realization = tuned
                stack = tuned.stack
                request = tuned.request
                lease = tuned.lease
                row = tuned.row
                applied = tuned.applied
                certificate = tuned.certificate
                evidence = tuned.evidence
                measured = tuned.measured
            else:
                # Another live consumer owns the same warm realization.
                # Reattach without rerunning static qualification; the
                # already-measured certificate still describes this exact
                # stack/host and tuning must never disrupt active research.
                lease = model_replica_pool.ensure(request)
                lease.assert_healthy()
                row = lease.report.placements[0]
                applied = deployment_runtime.applied_identity(
                    row.deployment_id
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
                replace_malformed_existing=True,
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
    "qualification_source_stack_digest",
]
