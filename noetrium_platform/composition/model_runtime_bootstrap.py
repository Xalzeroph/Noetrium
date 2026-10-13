from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from threading import Event
import re
import time

from noetrium_platform.capabilities.model.asset.runtime import ModelAssetManager
from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentRuntimePort,
    ModelDesiredDeployment,
    ModelDesiredState,
    ModelResourceViewPort,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.composition import (
    LocalModelReplicaPoolRuntime,
    ModelReplicaPoolRequest,
)
from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    PerformanceSample,
    PREEMPTIVE_BORROWER_PRIORITY,
    PREEMPTIVE_PROTECTED_PRIORITY,
    PreemptiveReturnSample,
    QualificationEvidence,
    QualificationPolicy,
    QualifiedDeploymentManifest,
    QualificationCertificate,
    ResourceQualificationMeasurements,
    RoleCanaryResult,
    RoleModelAssignment,
    measured_latency_isolation_concurrency,
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
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.capabilities.model.stack.api import (
    FrozenModelStack,
    parse_vllm_engine_resource_args,
)
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_local_command_runner,
)
from noetrium_platform.infrastructure.resources.authority import (
    AuthoritySnapshot,
    UniversalResourceAuthority,
    claim_field,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime.phase_trace import (
    CausalPhaseTrace,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeInventoryPort,
    ComputePlacementUnavailable,
    GpuDeviceStatus,
    GpuRuntimeObserverPort,
    GpuRuntimeSnapshot,
    HostRuntimeObserverPort,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ServiceHeartbeat

from .model_stack_materialization import (
    DockerModelStackMaterializer,
    MaterializedModelStack,
    ModelPlacementObservation,
    ModelStackPlacementUnavailable,
    model_kv_cache_budget_bytes,
    model_kv_cache_bytes_per_token,
)
from .research_execution_pool import ResearchExecutionPool
from .runtime_coordination import runtime_fabric_root


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
_STATIC_QUALIFICATION_SCOUT_CONCURRENCIES = (1, 2, 4, 8, 16, 32)
_STATIC_QUALIFICATION_REQUEST_BUDGET = sum(
    _STATIC_QUALIFICATION_SCOUT_CONCURRENCIES
)
_STATIC_QUALIFICATION_PROTOCOL = {
    "schema": "noetrium.model-static-qualification.v7",
    "capability_canary": "protocol-valid-generation-nonempty-or-strict-structured",
    "thinking_mode": "request-owned-not-overridden-by-qualification",
    "request_capacity": "authority-bounded-fixed-budget-discrete-scout",
    "prefill_capacity": "planner-kv-token-window",
    "operating_point": "bounded-discrete-latency-knee-max-goodput",
    "preemptive_isolation": (
        "full-qualified-borrower-wave-plus-latency-isolation-return-wave"
    ),
}
STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF = (
    "static-qualification-protocol:sha256:"
    + canonical_digest(_STATIC_QUALIFICATION_PROTOCOL)
)


@dataclass(frozen=True, slots=True)
class RequiredModelRuntime:
    model_id: str
    role: str
    required_capabilities: tuple[str, ...] = ("generation",)
    minimum_context_tokens: int = 1

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
        if (
            type(self.minimum_context_tokens) is not int
            or self.minimum_context_tokens <= 0
        ):
            raise ValueError("required model runtime minimum context must be positive")
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


def qualified_model_closure_path(authority_root: Path, model_id: str) -> Path:
    """Canonical authority path for one model's qualified closure."""
    if not isinstance(authority_root, Path):
        raise TypeError("qualified model authority root must be Path")
    if type(model_id) is not str or not model_id.strip():
        raise ValueError("qualified model closure model_id is required")
    return (
        authority_root
        / "models"
        / _slug(model_id)
        / "qualified-model-closure.json"
    )


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
                "content": "Produce one short plain-text response.",
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
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
    return bool(exchange.text.strip())


def _select_kth_float(values: list[float], index: int) -> float:
    """Deterministic worst-case-linear order-statistic selection.

    Median-of-medians keeps qualification control deterministic while avoiding
    an O(n log n) full sort when only one percentile position is needed.
    """

    if type(index) is not int or index < 0 or index >= len(values):
        raise IndexError("order-statistic index is out of range")
    rows = list(values)
    while True:
        size = len(rows)
        if size <= 5:
            rows.sort()
            return rows[index]

        medians: list[float] = []
        for offset in range(0, size, 5):
            group = rows[offset : offset + 5]
            group.sort()
            medians.append(group[len(group) // 2])
        pivot = _select_kth_float(medians, len(medians) // 2)

        lower: list[float] = []
        equal: list[float] = []
        upper: list[float] = []
        for value in rows:
            if value < pivot:
                lower.append(value)
            elif value > pivot:
                upper.append(value)
            else:
                equal.append(value)

        if index < len(lower):
            rows = lower
            continue
        equal_end = len(lower) + len(equal)
        if index < equal_end:
            return pivot
        index -= equal_end
        rows = upper


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("qualification percentile requires measurements")
    normalized = [float(value) for value in values]
    if any(not math.isfinite(value) for value in normalized):
        raise ValueError("qualification percentile measurements must be finite")
    index = max(
        0,
        min(
            len(normalized) - 1,
            math.ceil(fraction * len(normalized)) - 1,
        ),
    )
    return _select_kth_float(normalized, index)


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


def _container_id_from_runtime_evidence(
    evidence_refs: tuple[str, ...],
) -> str:
    if type(evidence_refs) is not tuple:
        raise TypeError(
            "model qualification runtime evidence must be a tuple"
        )
    prefix = "docker-container:"
    matches = tuple(
        ref[len(prefix):]
        for ref in evidence_refs
        if ref.startswith(prefix) and ref[len(prefix):].strip()
    )
    if len(matches) != 1:
        raise RuntimeError(
            "model qualification requires exactly one provider-confirmed "
            f"Docker container reference; matches={len(matches)}"
        )
    return matches[0]


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
        "max_tokens": 32,
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
    # Capacity qualification must exercise a genuinely long prompt rather
    # than extrapolating from a tiny canary. Keep the stress request in a
    # context-scaled band: at least 1/8 of context, at most 1/4 unless the
    # observed canary is already longer. This remains model-generic while
    # exposing KV/prefill pressure representative of long-context workloads.
    lower_stress = max(observed_prompt_tokens, context_length // 8)
    upper_stress = max(observed_prompt_tokens, context_length // 4)
    safe_prefill = min(
        max(observed_prompt_tokens * 2, lower_stress),
        upper_stress,
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
    on_first_text=None,
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
                    if on_first_text is not None:
                        if not callable(on_first_text):
                            raise TypeError(
                                "qualification first-token callback must be callable"
                            )
                        on_first_text()
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


def _qualification_payload_for_ordinal(
    payload: bytes,
    *,
    ordinal: int,
) -> bytes:
    """Make one capacity-probe request prefix-distinct.

    Capacity qualification proves a worst-case admissible envelope. Reusing
    byte-identical prompts lets prefix-cache sharing turn that proof into a
    best-case benchmark and can arbitrarily overstate safe concurrency.
    """
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("qualification probe payload must be non-empty bytes")
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("qualification probe ordinal must be non-negative")
    try:
        body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("qualification probe payload must be JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("qualification probe payload must be a JSON object")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("qualification probe payload requires messages")
    rows = [dict(row) for row in messages]
    first_user = next(
        (
            index
            for index, row in enumerate(rows)
            if row.get("role") == "user"
            and isinstance(row.get("content"), str)
        ),
        None,
    )
    if first_user is None:
        raise ValueError(
            "qualification probe payload requires one textual user message"
        )
    row = dict(rows[first_user])
    row["content"] = (
        f"qualification-capacity-probe-{ordinal:08d}\n"
        + str(row["content"])
    )
    rows[first_user] = row
    body = dict(body)
    body["messages"] = rows
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _priority_qualification_payload(
    payload: bytes,
    *,
    priority: int,
    output_budget_multiplier: int = 1,
) -> bytes:
    if not isinstance(payload, bytes) or not payload:
        raise ValueError("priority qualification payload must be non-empty bytes")
    if type(priority) is not int:
        raise TypeError("priority qualification priority must be int")
    if type(output_budget_multiplier) is not int or output_budget_multiplier <= 0:
        raise ValueError(
            "priority qualification output multiplier must be positive"
        )
    body = json.loads(payload)
    if not isinstance(body, dict):
        raise ValueError("priority qualification payload must be a JSON object")
    max_tokens = body.get("max_tokens")
    if type(max_tokens) is not int or max_tokens <= 0:
        raise ValueError("priority qualification payload requires max_tokens")
    body = dict(body)
    body["priority"] = priority
    body["max_tokens"] = max_tokens * output_budget_multiplier
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _run_preemptive_return_probe(
    *,
    borrower_concurrency: int,
    return_concurrency: int,
    probe_payload: bytes,
    completion_url: str,
    http_transport: AsyncJsonSseTransportPort,
    task_group: TaskGroupPort,
) -> PreemptiveReturnSample | None:
    """Measure protected return under a fully occupied low-priority engine.

    Every borrower must have emitted its first token and remain active through
    the complete protected return wave. This proves overlap rather than merely
    concurrent request arrival. Failure to establish that cut disables borrowing.
    """

    if type(borrower_concurrency) is not int or borrower_concurrency <= 0:
        raise ValueError("borrower concurrency must be positive")
    if type(return_concurrency) is not int or return_concurrency <= 0:
        raise ValueError("return concurrency must be positive")

    borrower_payload = _priority_qualification_payload(
        probe_payload,
        priority=PREEMPTIVE_BORROWER_PRIORITY,
        output_budget_multiplier=return_concurrency + 1,
    )
    protected_payload = _priority_qualification_payload(
        probe_payload,
        priority=PREEMPTIVE_PROTECTED_PRIORITY,
    )
    first_tokens = tuple(Event() for _ in range(borrower_concurrency))
    borrower_handles = []

    for ordinal, first_token in enumerate(first_tokens):
        payload = _qualification_payload_for_ordinal(
            borrower_payload,
            ordinal=ordinal,
        )

        async def borrow(context, *, _payload=payload, _signal=first_token):
            context.checkpoint()
            remaining = context.remaining_seconds
            timeout_s = 120.0 if remaining is None else min(120.0, remaining)
            if timeout_s <= 0:
                context.checkpoint()
                raise TimeoutError(
                    "preemptive qualification borrower deadline expired"
                )
            return await _stream_qualification_exchange(
                completion_url=completion_url,
                payload=_payload,
                http_transport=http_transport,
                timeout_s=timeout_s,
                on_first_text=_signal.set,
            )

        borrower_handles.append(
            task_group.submit(
                ExecutionSpec(
                    task_id=(
                        "model-static-qualification:borrower:"
                        f"{borrower_concurrency}:{ordinal}"
                    ),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                borrow,
                deadline=Deadline.after(120.0),
            )
        )

    overlap_deadline = time.monotonic() + 120.0
    for signal in first_tokens:
        remaining = overlap_deadline - time.monotonic()
        if remaining <= 0.0 or not signal.wait(remaining):
            for handle in borrower_handles:
                handle.cancel()
            return None
    if any(handle.done() for handle in borrower_handles):
        for handle in borrower_handles:
            if not handle.done():
                handle.cancel()
        return None

    return_sample, _return_exchanges = _run_concurrency_probe(
        probe_namespace="protected-return",
        concurrency=return_concurrency,
        payloads=(protected_payload,),
        completion_url=completion_url,
        http_transport=http_transport,
        task_group=task_group,
    )
    borrowers_remained_active = all(
        not handle.done() for handle in borrower_handles
    )

    borrower_failed = False
    for handle in borrower_handles:
        try:
            value = handle.result()
        except BaseException:
            borrower_failed = True
            continue
        if not isinstance(value, _Exchange):
            borrower_failed = True

    if return_sample is None or borrower_failed:
        return None
    return PreemptiveReturnSample(
        borrower_concurrency=borrower_concurrency,
        return_concurrency=return_concurrency,
        borrower_priority=PREEMPTIVE_BORROWER_PRIORITY,
        protected_priority=PREEMPTIVE_PROTECTED_PRIORITY,
        return_ttft_p99=float(return_sample.ttft_p99),
        return_tpot_p99=float(return_sample.tpot_p99),
        borrower_active_during_return=borrowers_remained_active,
    )


def _run_concurrency_probe(
    *,
    probe_namespace: str,
    concurrency: int,
    payloads: tuple[bytes, ...],
    completion_url: str,
    http_transport: AsyncJsonSseTransportPort,
    task_group: TaskGroupPort,
) -> tuple[PerformanceSample | None, tuple[_Exchange, ...]]:
    if type(probe_namespace) is not str or not probe_namespace.strip():
        raise ValueError("model qualification probe namespace is required")
    probe_namespace = probe_namespace.strip()
    if type(concurrency) is not int or concurrency <= 0:
        raise ValueError("model qualification concurrency must be positive")
    if not payloads:
        raise ValueError("model qualification requires at least one payload")

    handles = []
    wave_started = time.perf_counter()
    for ordinal in range(concurrency):
        payload = _qualification_payload_for_ordinal(
            payloads[ordinal % len(payloads)],
            ordinal=ordinal,
        )

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
                        f"{probe_namespace}:{concurrency}:{ordinal}"
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


def _rewrite_vllm_cudagraph_capture_sizes(
    args: tuple[str, ...],
    capture_sizes: tuple[int, ...] | None,
) -> tuple[str, ...]:
    """Set or remove only the measured CUDA-graph field in compilation config."""

    if capture_sizes is not None and (
        not capture_sizes
        or any(type(value) is not int or value <= 0 for value in capture_sizes)
    ):
        raise ValueError("vLLM cudagraph capture sizes must be positive integers")
    rows: list[str] = []
    index = 0
    found = False
    name = "--compilation-config"
    prefix = name + "="
    while index < len(args):
        item = args[index]
        raw = None
        consumed = 1
        if item == name:
            if index + 1 >= len(args):
                raise ValueError("vLLM compilation-config requires a value")
            raw = args[index + 1]
            consumed = 2
        elif item.startswith(prefix):
            raw = item[len(prefix):]
        if raw is None:
            rows.append(item)
            index += 1
            continue
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("vLLM compilation-config must be valid JSON") from exc
        if not isinstance(document, dict):
            raise ValueError("vLLM compilation-config must be a JSON object")
        document = dict(document)
        if capture_sizes is None:
            document.pop("cudagraph_capture_sizes", None)
        else:
            document["cudagraph_capture_sizes"] = list(capture_sizes)
        if document:
            rows.extend((
                name,
                json.dumps(document, sort_keys=True, separators=(",", ":")),
            ))
        found = True
        index += consumed
    if capture_sizes is not None and not found:
        rows.extend((
            name,
            json.dumps(
                {"cudagraph_capture_sizes": list(capture_sizes)},
                sort_keys=True,
                separators=(",", ":"),
            ),
        ))
    return tuple(rows)


QUALIFICATION_ALGORITHM_ID = (
    "model-static-qualification.v8.goodput-prior-adaptive-continuity"
)


def qualification_source_stack_digest(stack: FrozenModelStack) -> str:
    """Digest the immutable qualification source and exact qualification calculus.

    Static qualification derives a runtime admission certificate without
    mutating the physical stack. Runtime refresh compares the current
    materialized source against that source identity while Noetrium enforces
    measured admission above the engine hard ceiling.
    """
    if not isinstance(stack, FrozenModelStack):
        raise TypeError("qualification source digest requires FrozenModelStack")
    if stack.identity.engine.strip().lower() == "vllm":
        source_args = _without_engine_option(
            stack.engine_args,
            name="--max-num-seqs",
        )
        source_args = _rewrite_vllm_cudagraph_capture_sizes(
            source_args,
            None,
        )
        stack_digest = replace(stack, engine_args=source_args).digest()
    else:
        stack_digest = stack.digest()
    return canonical_digest({
        "qualification_algorithm": QUALIFICATION_ALGORITHM_ID,
        "source_stack_digest": stack_digest,
    })



_STATIC_QUALIFICATION_CACHE_SCHEMA = "noetrium.model-static-qualification-cache.v2"


def _static_qualification_policy() -> QualificationPolicy:
    return QualificationPolicy(
        minimum_role_pass_rate=1.0,
        require_zero_critical_failures=True,
        max_error_rate=0.0,
        require_exact_output_reproducibility=False,
        require_long_context_checked=False,
        require_tool_call_checked=False,
    )


def _static_qualification_contracts(
    requirements: tuple[RequiredModelRuntime, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        sorted(
            (
                row.role,
                tuple(row.required_capabilities),
            )
            for row in requirements
        )
    )


def _static_qualification_cache_key(
    *,
    model_id: str,
    stack: FrozenModelStack,
    host_identity_digest: str,
    requirements: tuple[RequiredModelRuntime, ...],
) -> str:
    return canonical_digest(
        {
            "schema": _STATIC_QUALIFICATION_CACHE_SCHEMA,
            "qualification_algorithm": QUALIFICATION_ALGORITHM_ID,
            "model_id": model_id,
            "stack_digest": stack.digest(),
            "host_identity_digest": host_identity_digest,
            "requirements": _static_qualification_contracts(requirements),
        }
    )


def _static_qualification_cache_path(
    *,
    model_id: str,
    stack: FrozenModelStack,
    host_identity_digest: str,
    requirements: tuple[RequiredModelRuntime, ...],
) -> tuple[str, Path]:
    key = _static_qualification_cache_key(
        model_id=model_id,
        stack=stack,
        host_identity_digest=host_identity_digest,
        requirements=requirements,
    )
    return (
        key,
        runtime_fabric_root()
        / "static-model-qualification"
        / "v1"
        / _slug(model_id)
        / f"{key}.json",
    )


def _static_qualification_payload_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    import hashlib
    return hashlib.sha256(encoded).hexdigest()


def _static_qualification_payload(
    *,
    cache_key: str,
    model_id: str,
    stack: FrozenModelStack,
    host_identity_digest: str,
    requirements: tuple[RequiredModelRuntime, ...],
    evidence: QualificationEvidence,
    measured: ResourceQualificationMeasurements,
) -> dict[str, object]:
    return {
        "schema": _STATIC_QUALIFICATION_CACHE_SCHEMA,
        "cache_key": cache_key,
        "qualification_algorithm": QUALIFICATION_ALGORITHM_ID,
        "model_id": model_id,
        "stack_digest": stack.digest(),
        "host_identity_digest": host_identity_digest,
        "requirements": [
            {
                "role": role,
                "required_capabilities": list(capabilities),
            }
            for role, capabilities in _static_qualification_contracts(requirements)
        ],
        "evidence": {
            "model_stack_digest": evidence.model_stack_digest,
            "canaries": [asdict(row) for row in evidence.canaries],
            "performance": [asdict(row) for row in evidence.performance],
            "prefill_input_tokens_per_second": evidence.prefill_input_tokens_per_second,
            "preemptive_return": (
                None
                if evidence.preemptive_return is None
                else asdict(evidence.preemptive_return)
            ),
            "exact_output_reproducibility_checked": evidence.exact_output_reproducibility_checked,
            "long_context_checked": evidence.long_context_checked,
            "tool_call_checked": evidence.tool_call_checked,
        },
        "measurements": asdict(measured),
    }


def _load_static_qualification_cache(
    path: Path,
    *,
    cache_key: str,
    model_id: str,
    stack: FrozenModelStack,
    host_identity_digest: str,
    requirements: tuple[RequiredModelRuntime, ...],
) -> tuple[QualificationCertificate, QualificationEvidence, ResourceQualificationMeasurements] | None:
    if not path.is_file():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if set(envelope) != {"payload_sha256", "payload"}:
            return None
        payload = envelope["payload"]
        if not isinstance(payload, dict):
            return None
        if _static_qualification_payload_digest(payload) != envelope["payload_sha256"]:
            return None
        expected_header = {
            "schema": _STATIC_QUALIFICATION_CACHE_SCHEMA,
            "cache_key": cache_key,
            "qualification_algorithm": QUALIFICATION_ALGORITHM_ID,
            "model_id": model_id,
            "stack_digest": stack.digest(),
            "host_identity_digest": host_identity_digest,
            "requirements": [
                {
                    "role": role,
                    "required_capabilities": list(capabilities),
                }
                for role, capabilities in _static_qualification_contracts(requirements)
            ],
        }
        for key, value in expected_header.items():
            if payload.get(key) != value:
                return None
        raw_evidence = payload["evidence"]
        raw_measurements = payload["measurements"]
        if not isinstance(raw_evidence, dict) or not isinstance(raw_measurements, dict):
            return None
        evidence = QualificationEvidence(
            model_stack_digest=str(raw_evidence["model_stack_digest"]),
            canaries=tuple(
                RoleCanaryResult(**dict(row))
                for row in raw_evidence["canaries"]
            ),
            performance=tuple(
                PerformanceSample(**dict(row))
                for row in raw_evidence["performance"]
            ),
            prefill_input_tokens_per_second=float(
                raw_evidence["prefill_input_tokens_per_second"]
            ),
            preemptive_return=(
                None
                if raw_evidence["preemptive_return"] is None
                else PreemptiveReturnSample(
                    **dict(raw_evidence["preemptive_return"])
                )
            ),
            exact_output_reproducibility_checked=bool(
                raw_evidence["exact_output_reproducibility_checked"]
            ),
            long_context_checked=bool(raw_evidence["long_context_checked"]),
            tool_call_checked=bool(raw_evidence["tool_call_checked"]),
        )
        measured = ResourceQualificationMeasurements(**dict(raw_measurements))
        if evidence.model_stack_digest != stack.digest():
            return None
        certificate = issue_measured_qualification_certificate(
            evidence,
            _static_qualification_policy(),
            measured,
            qualified_roles=tuple(sorted(row.role for row in requirements)),
            target_host_identity_digest=host_identity_digest,
        )
        return certificate, evidence, measured
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None


def _store_static_qualification_cache(
    path: Path,
    *,
    cache_key: str,
    model_id: str,
    stack: FrozenModelStack,
    host_identity_digest: str,
    requirements: tuple[RequiredModelRuntime, ...],
    evidence: QualificationEvidence,
    measured: ResourceQualificationMeasurements,
) -> None:
    payload = _static_qualification_payload(
        cache_key=cache_key,
        model_id=model_id,
        stack=stack,
        host_identity_digest=host_identity_digest,
        requirements=requirements,
        evidence=evidence,
        measured=measured,
    )
    envelope = {
        "payload_sha256": _static_qualification_payload_digest(payload),
        "payload": payload,
    }
    from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes
    atomic_replace_bytes(
        path,
        json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8"),
    )

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


def _positive_engine_integer_option(
    args: tuple[str, ...],
    *,
    name: str,
) -> int | None:
    if type(args) is not tuple or any(type(item) is not str for item in args):
        raise TypeError("engine option parsing requires tuple[str, ...]")
    found: int | None = None
    index = 0
    while index < len(args):
        token = args[index]
        raw: str | None = None
        if token == name:
            if index + 1 >= len(args):
                raise ValueError(f"engine argument requires a value: {name}")
            raw = args[index + 1]
            index += 1
        elif token.startswith(name + "="):
            raw = token[len(name) + 1 :]
        if raw is not None:
            if found is not None:
                raise ValueError(f"engine argument is duplicated: {name}")
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(
                    f"engine argument must be a positive integer: {name}"
                ) from exc
            if value <= 0:
                raise ValueError(
                    f"engine argument must be a positive integer: {name}"
                )
            found = value
        index += 1
    return found


def _warm_stack_concurrency_hint(stack: FrozenModelStack) -> int | None:
    if not isinstance(stack, FrozenModelStack):
        raise TypeError("warm stack concurrency hint requires FrozenModelStack")
    if stack.identity.engine.strip().lower() != "vllm":
        return None
    value = parse_vllm_engine_resource_args(stack.engine_args).max_num_seqs
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise ValueError("warm vLLM max-num-seqs must be positive")
    return value


def _tag_value(tags: tuple[str, ...], prefix: str) -> str | None:
    rows = tuple(tag[len(prefix):] for tag in tags if tag.startswith(prefix))
    if not rows:
        return None
    if len(rows) != 1 or not rows[0]:
        raise RuntimeError("model deployment tag identity is ambiguous: " + prefix)
    return rows[0]


def _placement_observation_without_warm_deployment(
    observation: ModelPlacementObservation,
    *,
    spec: ModelDesiredDeployment,
    service_resource_key: str,
) -> ModelPlacementObservation | None:
    """Project one placement cut as if exactly one warm deployment were absent.

    This is planning evidence only: Authority rows and the physical process remain
    untouched until ordinary reconciliation decides whether the warm realization
    can actually retire.  Return None unless self-attribution is exact.
    """

    if type(observation) is not ModelPlacementObservation:
        raise TypeError("warm placement projection requires typed observation")
    if type(spec) is not ModelDesiredDeployment or not service_resource_key.strip():
        raise TypeError("warm placement projection requires exact deployment identity")
    own_claim_ids: set[str] = set()
    retained_claims = []
    for claim in observation.authority.claims:
        attrs = dict(claim_field(claim, "attributes"))
        if (
            attrs.get("kind") == "compute"
            and attrs.get("consumer_resource_key") == service_resource_key
        ):
            own_claim_ids.add(str(claim_field(claim, "claim_id")))
            continue
        retained_claims.append(claim)
    if not own_claim_ids:
        return None

    gpu_runtime = observation.gpu_runtime
    reservations = spec.gpu_memory_reservation_bytes
    if (
        gpu_runtime is None
        or not gpu_runtime.available
        or not spec.gpu_devices
        or len(reservations) != len(spec.gpu_devices)
    ):
        return None
    reservation_by_id = {
        str(gpu_id): int(reservation)
        for gpu_id, reservation in zip(spec.gpu_devices, reservations)
    }
    matched: set[str] = set()
    projected_devices: list[GpuDeviceStatus] = []
    for device in gpu_runtime.devices:
        reservation = None
        matched_key = None
        for key in (device.uuid, device.index):
            if key in reservation_by_id:
                reservation = reservation_by_id[key]
                matched_key = key
                break
        if reservation is None:
            projected_devices.append(device)
            continue
        matched.add(str(matched_key))
        released_mb = math.ceil(reservation / (1024 * 1024))
        free_mb = min(device.memory_total_mb, device.memory_free_mb + released_mb)
        projected_devices.append(
            replace(
                device,
                memory_free_mb=free_mb,
                memory_used_mb=max(0, device.memory_total_mb - free_mb),
            )
        )
    if len(matched) != len(reservation_by_id):
        return None

    authority = observation.authority
    projected_authority = AuthoritySnapshot(
        authority.generations,
        tuple(retained_claims),
        authority.leases,
        authority.tickets,
        authority.bindings,
    )
    projected_gpu = replace(gpu_runtime, devices=tuple(projected_devices))
    return ModelPlacementObservation(
        projected_authority,
        projected_gpu,
        observation.host_runtime,
    )


def _warm_pressure_index(
    observation: ModelPlacementObservation | None,
) -> tuple[frozenset[str], dict[str, GpuDeviceStatus]] | None:
    """Index one placement observation for linear-time warm pressure scoring."""
    if (
        observation is None
        or observation.gpu_runtime is None
        or not observation.gpu_runtime.available
    ):
        return None
    compute_consumers = frozenset(
        consumer
        for claim in observation.authority.claims
        if (
            dict(claim_field(claim, "attributes")).get("kind") == "compute"
            and isinstance(
                consumer := dict(claim_field(claim, "attributes")).get(
                    "consumer_resource_key"
                ),
                str,
            )
            and consumer
        )
    )
    by_identity: dict[str, GpuDeviceStatus] = {}
    for device in observation.gpu_runtime.devices:
        for raw in (device.uuid, device.index):
            key = str(raw).strip()
            if key:
                by_identity[key] = device
    return compute_consumers, by_identity


def _warm_external_gpu_pressure(
    pressure_index: tuple[frozenset[str], dict[str, GpuDeviceStatus]] | None,
    *,
    spec: ModelDesiredDeployment,
    service_resource_key: str,
) -> tuple[float, float] | None:
    """Return external pressure using one shared observation index.

    The model's own Authority reservation is subtracted analytically from the
    live GPU free-memory observation. No candidate-specific Authority/GPU scan
    is required.
    """
    if pressure_index is None:
        return None
    compute_consumers, by_identity = pressure_index
    if service_resource_key not in compute_consumers:
        return None
    reservations = spec.gpu_memory_reservation_bytes
    if (
        not spec.gpu_devices
        or len(reservations) != len(spec.gpu_devices)
    ):
        return None

    rows: list[float] = []
    seen: set[str] = set()
    for gpu_id, reservation in zip(spec.gpu_devices, reservations):
        device = by_identity.get(str(gpu_id).strip())
        if (
            device is None
            or device.uuid in seen
            or device.memory_total_mb <= 0
        ):
            return None
        seen.add(device.uuid)
        released_mb = math.ceil(int(reservation) / (1024 * 1024))
        projected_free = min(
            device.memory_total_mb,
            device.memory_free_mb + released_mb,
        )
        external_used = max(0, device.memory_total_mb - projected_free)
        rows.append(
            float(external_used) / float(device.memory_total_mb)
        )
    if len(rows) != len(spec.gpu_devices) or not rows:
        return None
    return max(rows), sum(rows)


def _warm_materialized_stack_candidate(
    *,
    model_id: str,
    materializer: DockerModelStackMaterializer,
    model_resources: ModelResourceViewPort,
    deployment_runtime: ModelDeploymentRuntimePort,
    runtime_workdir: Path,
    minimum_context_tokens: int,
    observation: ModelPlacementObservation | None = None,
) -> tuple[
    MaterializedModelStack | None,
    str | None,
    ModelPlacementObservation | None,
]:
    """Return the best live warm stack or one exact stale identity.

    Semantic compatibility is proved first.  When multiple already-running
    warm stacks dominate the request, choose the one with the least external
    GPU-memory pressure after projecting away its own Authority reservation.
    This avoids needless model reloads while refusing to mistake the model's
    own weights/KV reservation for external contention.
    """

    if type(minimum_context_tokens) is not int or minimum_context_tokens <= 0:
        raise ValueError("warm model minimum context must be positive")
    deployment_specs, deployment_statuses = model_resources.deployment_cut()
    status_by_id = {
        row.deployment_id: row
        for row in deployment_statuses
    }
    rejected_runtime_identities: set[str] = set()
    candidates: list[
        tuple[
            MaterializedModelStack,
            ModelDesiredDeployment,
            str,
            int,
            int,
        ]
    ] = []
    shared_observation = observation

    def current_observation() -> ModelPlacementObservation:
        nonlocal shared_observation
        if shared_observation is None:
            shared_observation = materializer.placement_observation()
        return shared_observation

    materialized_by_topology: dict[
        tuple[int, int, int], MaterializedModelStack | None
    ] = {}
    specs = (
        row
        for row in deployment_specs
        if (
            row.model_id == model_id
            and row.desired_state is ModelDesiredState.RUNNING
        )
    )
    for spec in specs:
        stack_digest = _tag_value(spec.tags, "model-stack:")
        runtime_identity = _tag_value(spec.tags, "runtime-identity:")
        if stack_digest is None or runtime_identity is None:
            continue

        status = status_by_id.get(spec.deployment_id)
        if (
            status is None
            or status.runtime_state is not ModelRuntimeState.RUNNING
        ):
            # Crash-window recovery is resume-before-replace. A process may
            # have survived after the caller died before the applied proof was
            # committed. Recover only the exact durable contract; this path
            # never starts a replacement process.
            try:
                generation = deployment_runtime.generation(spec.deployment_id)
                if generation.applied_runtime_digest is None:
                    deployment_runtime.recover_applied(generation)
                status = deployment_runtime.status(spec.deployment_id)
            except (FileNotFoundError, KeyError, RuntimeError, ValueError):
                rejected_runtime_identities.add(runtime_identity)
                continue
            if status.runtime_state is not ModelRuntimeState.RUNNING:
                rejected_runtime_identities.add(runtime_identity)
                continue
        tensor_parallel = len(spec.gpu_devices)
        if tensor_parallel <= 0:
            continue
        try:
            warm_context = _positive_engine_integer_option(
                spec.argv,
                name="--max-model-len",
            )
            parsed = parse_vllm_engine_resource_args(spec.argv)
        except ValueError:
            continue
        if (
            warm_context is None
            or warm_context < minimum_context_tokens
        ):
            continue
        cpu_offload_bytes_per_gpu = parsed.cpu_offload_bytes_per_gpu
        topology_key = (
            tensor_parallel,
            warm_context,
            cpu_offload_bytes_per_gpu,
        )
        if topology_key in materialized_by_topology:
            base = materialized_by_topology[topology_key]
            if base is None:
                continue
        else:
            try:
                base = materializer.materialize_for_tensor_parallel(
                    model_id,
                    tensor_parallel,
                    context_length=warm_context,
                    cpu_offload_bytes_per_gpu=cpu_offload_bytes_per_gpu,
                )
            except (ValueError, RuntimeError):
                materialized_by_topology[topology_key] = None
                continue
            materialized_by_topology[topology_key] = base
        if base.stack.runtime.container_digest != spec.container_digest:
            continue

        stack = base.stack
        if parsed.max_num_seqs is not None:
            stack = replace(
                stack,
                engine_args=_with_engine_integer_option(
                    stack.engine_args,
                    name="--max-num-seqs",
                    value=parsed.max_num_seqs,
                ),
            )
        if stack.digest() != stack_digest:
            continue

        probe = ModelReplicaPoolRequest(
            pool_id="warm-identity-probe",
            scope=PLATFORM_SCOPE,
            model_id=model_id,
            engine=stack.identity.engine,
            cwd=runtime_workdir,
            compute=base.compute,
            model_stack=stack,
            replica_count=None,
            endpoint_host="127.0.0.1",
        )
        if probe.runtime_identity_digest != runtime_identity:
            continue

        service_resource_key = _tag_value(spec.tags, "resource-key:")
        if service_resource_key is None:
            continue
        if tensor_parallel > 1:
            projected = _placement_observation_without_warm_deployment(
                current_observation(),
                spec=spec,
                service_resource_key=service_resource_key,
            )
            if projected is not None:
                try:
                    optimal = materializer.materialize(
                        model_id,
                        minimum_context_tokens=minimum_context_tokens,
                        observation=projected,
                    )
                except ModelStackPlacementUnavailable:
                    pass
                else:
                    if optimal.stack.tensor_parallel < tensor_parallel:
                        rejected_runtime_identities.add(runtime_identity)
                        continue
        candidates.append(
            (
                replace(base, stack=stack),
                spec,
                service_resource_key,
                warm_context,
                tensor_parallel,
            )
        )

    if not candidates:
        return (
            None,
            min(rejected_runtime_identities)
            if rejected_runtime_identities
            else None,
            shared_observation,
        )
    if len(candidates) == 1:
        return candidates[0][0], None, shared_observation

    pressure_index = _warm_pressure_index(current_observation())

    def candidate_key(row):
        materialized, spec, service_resource_key, warm_context, tensor_parallel = row
        pressure = _warm_external_gpu_pressure(
            pressure_index,
            spec=spec,
            service_resource_key=service_resource_key,
        )
        if pressure is None:
            pressure_key = (1, math.inf, math.inf)
        else:
            pressure_key = (0, pressure[0], pressure[1])
        return (
            *pressure_key,
            tensor_parallel,
            warm_context - minimum_context_tokens,
            spec.deployment_id,
            materialized.stack.digest(),
        )

    selected = min(candidates, key=candidate_key)
    return selected[0], None, shared_observation


def _historical_preferred_concurrency(
    path: Path,
    *,
    qualification_source_digest: str,
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
            qualification_source_stack_digest(deployment.stack)
            == qualification_source_digest
            and deployment.host_identity_digest == host_identity_digest
        )
    )
    valid = tuple(
        value for value in values
        if type(value) is int and value > 0
    )
    return min(valid) if valid else None


def _estimated_qualification_concurrency_ceiling(
    *,
    asset_path: Path,
    stack,
    transport_ceiling: int,
    observed_prompt_tokens: int,
    output_token_budget: int,
) -> int:
    """Bound one replica by KV residency, then by transport capacity."""
    if type(transport_ceiling) is not int or transport_ceiling <= 0:
        raise ValueError("qualification transport ceiling must be positive")
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
    return max(
        1,
        min(
            transport_ceiling,
            int(kv_budget // max(1, per_token * request_tokens)),
        ),
    )


def _static_qualification_scout_concurrencies(
    *,
    max_concurrency: int,
    preferred_concurrency_hint: int | None,
) -> tuple[int, ...]:
    """Bound request-capacity measurement by a constant request budget.

    The Authority/KV calculation supplies the hard admissible ceiling. This
    scout only measures a sparse performance curve inside that ceiling; it does
    not rediscover the ceiling by flooding a queue.
    """

    if type(max_concurrency) is not int or max_concurrency <= 0:
        raise ValueError("qualification max_concurrency must be positive")
    scout_cap = min(
        max_concurrency,
        max(_STATIC_QUALIFICATION_SCOUT_CONCURRENCIES),
    )
    if preferred_concurrency_hint is not None and (
        type(preferred_concurrency_hint) is not int
        or preferred_concurrency_hint <= 0
    ):
        raise ValueError(
            "qualification preferred concurrency hint must be positive integer"
        )

    if preferred_concurrency_hint is None:
        candidates = tuple(
            value
            for value in _STATIC_QUALIFICATION_SCOUT_CONCURRENCIES
            if value < scout_cap
        ) + (scout_cap,)
    else:
        preferred = min(scout_cap, preferred_concurrency_hint)
        candidates = tuple(sorted({
            1,
            max(1, preferred // 2),
            preferred,
            min(scout_cap, preferred * 2),
            scout_cap,
        }))

    selected: list[int] = []
    request_budget = 0
    for concurrency in candidates:
        if concurrency <= 0 or concurrency > scout_cap:
            continue
        next_budget = request_budget + concurrency
        if next_budget > _STATIC_QUALIFICATION_REQUEST_BUDGET:
            continue
        selected.append(concurrency)
        request_budget = next_budget

    if not selected:
        raise RuntimeError("model qualification scout plan is empty")
    if selected[0] != 1:
        # A historical hint may have consumed the sparse candidate set, but
        # concurrency=1 is the fail-close liveness proof and is never optional.
        selected.insert(0, 1)
        request_budget += 1
    if request_budget > _STATIC_QUALIFICATION_REQUEST_BUDGET:
        raise RuntimeError("model qualification scout request budget exceeded")
    return tuple(selected)


def _qualified_kv_token_window(
    *,
    asset_path: Path,
    stack,
) -> int:
    """Canonical safe aggregate prompt+output token residency per replica."""

    per_token = model_kv_cache_bytes_per_token(
        asset_path,
        dtype=stack.identity.dtype,
        tensor_parallel=stack.tensor_parallel,
    )
    budget = model_kv_cache_budget_bytes(
        asset_path,
        context_length=stack.identity.context_length,
        dtype=stack.identity.dtype,
        tensor_parallel=stack.tensor_parallel,
    )
    return max(1, int(budget // max(1, per_token)))


def _measure_static_concurrency_capacity(
    *,
    probe_namespace: str,
    probe_payload: bytes,
    completion_url: str,
    http_transport: AsyncJsonSseTransportPort,
    task_group: TaskGroupPort,
    max_concurrency: int,
    preferred_concurrency_hint: int | None,
    resources: ModelResourceViewPort,
    gpu_ids: tuple[str, ...],
    command_runner,
    container_id: str,
) -> tuple[tuple[PerformanceSample, ...], int, int, int]:
    if not isinstance(probe_payload, bytes) or not probe_payload:
        raise ValueError("model qualification probe_payload must be non-empty bytes")
    scout = _static_qualification_scout_concurrencies(
        max_concurrency=max_concurrency,
        preferred_concurrency_hint=preferred_concurrency_hint,
    )

    samples: list[PerformanceSample] = []
    peak_gpu = 0
    peak_host = 0
    for concurrency in scout:
        sample, _exchanges = _run_concurrency_probe(
            probe_namespace=probe_namespace,
            concurrency=concurrency,
            payloads=(probe_payload,),
            completion_url=completion_url,
            http_transport=http_transport,
            task_group=task_group,
        )
        if sample is None:
            if concurrency == 1:
                raise RuntimeError(
                    "model qualification failed at concurrency=1"
                )
            break
        samples.append(sample)
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

    if not samples:
        raise RuntimeError("model qualification produced no request-capacity sample")
    qualified_concurrency = samples[-1].concurrency
    return (
        tuple(samples),
        qualified_concurrency,
        max(1, peak_gpu),
        max(1, peak_host),
    )


def _run_static_qualification(
    *,
    model_id: str,
    requirements: tuple[RequiredModelRuntime, ...],
    asset_path: Path,
    stack,
    preferred_concurrency_hint: int | None,
    completion_url: str,
    http_client,
    http_transport: AsyncJsonHttpTransportPort,
    task_group: TaskGroupPort,
    max_concurrency: int,
    resources: ModelResourceViewPort,
    gpu_ids: tuple[str, ...],
    command_runner,
    runtime_evidence_refs: tuple[str, ...],
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
    container_id = _container_id_from_runtime_evidence(runtime_evidence_refs)

    # A role canary proves a capability contract, not a scheduler capacity.
    # Identical capability contracts therefore share one exact exchange across
    # roles instead of repeating the same model request.  Reproducibility is not
    # claimed from a single sample; it is deliberately left false unless a
    # future policy explicitly asks for a repeated-output proof.
    canary_by_capabilities: dict[tuple[str, ...], _Exchange] = {}
    for requirement in requirements:
        capabilities = tuple(requirement.required_capabilities)
        exchange = canary_by_capabilities.get(capabilities)
        if exchange is None:
            body = _qualification_body(model_id, capabilities)
            payload = json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
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
            canary_by_capabilities[capabilities] = exchange
            all_exchanges.append(exchange)
            peak_gpu = max(
                peak_gpu,
                _gpu_memory_bytes(resources, gpu_ids, command_runner, container_id),
            )
            peak_host = max(
                peak_host,
                _container_memory_bytes(command_runner, container_id),
            )
        passed = int(_contract_passed(exchange, capabilities))
        role_results.append(
            RoleCanaryResult(
                role=requirement.role,
                total=1,
                passed=passed,
                critical_total=1,
                critical_passed=passed,
                contract_errors=1 - passed,
            )
        )
    exact_reproducible = False

    if not all_exchanges:
        raise RuntimeError("model qualification produced no measurements")

    observed_prompt_tokens = max(
        exchange.prompt_tokens for exchange in all_exchanges
    )
    mixed_payloads = _throughput_qualification_payloads(
        model_id,
        context_length=stack.identity.context_length,
        observed_prompt_tokens=observed_prompt_tokens,
    )
    if len(mixed_payloads) != 2:
        raise RuntimeError("model qualification payload plan must contain short and prefill probes")
    short_payload = mixed_payloads[0]
    long_prefill_payload = mixed_payloads[1]

    # Prove the larger prefill envelope once.  Repeating this expensive payload
    # in every concurrency wave measured scheduler capacity and prefill cost at
    # the same time, multiplying work without adding independent evidence.
    prefill_sample, prefill_exchanges = _run_concurrency_probe(
        probe_namespace="prefill-rate",
        concurrency=1,
        payloads=(long_prefill_payload,),
        completion_url=completion_url,
        http_transport=http_transport,
        task_group=task_group,
    )
    if prefill_sample is None:
        raise RuntimeError("model qualification long-prefill probe failed")
    if len(prefill_exchanges) != 1:
        raise RuntimeError(
            "model qualification long-prefill probe must produce one exchange"
        )
    prefill_exchange = prefill_exchanges[0]
    if (
        prefill_exchange.ttft_seconds is None
        or prefill_exchange.ttft_seconds <= 0.0
    ):
        raise RuntimeError(
            "model qualification long-prefill probe lacks positive TTFT"
        )
    prefill_input_tokens_per_second = (
        prefill_exchange.prompt_tokens / prefill_exchange.ttft_seconds
    )
    peak_gpu = max(
        peak_gpu,
        _gpu_memory_bytes(resources, gpu_ids, command_runner, container_id),
    )
    peak_host = max(
        peak_host,
        _container_memory_bytes(command_runner, container_id),
    )
    output_token_budget = int(
        _throughput_qualification_body(model_id)["max_tokens"]
    )
    request_ceiling = _estimated_qualification_concurrency_ceiling(
        asset_path=asset_path,
        stack=stack,
        transport_ceiling=max_concurrency,
        observed_prompt_tokens=observed_prompt_tokens,
        output_token_budget=output_token_budget,
    )
    bounded_preferred_concurrency_hint = (
        None
        if preferred_concurrency_hint is None
        else max(1, min(request_ceiling, preferred_concurrency_hint))
    )
    performance, qualified_concurrency, probe_peak_gpu, probe_peak_host = (
        _measure_static_concurrency_capacity(
            probe_namespace="request-capacity",
            probe_payload=short_payload,
            completion_url=completion_url,
            http_transport=http_transport,
            task_group=task_group,
            max_concurrency=request_ceiling,
            preferred_concurrency_hint=bounded_preferred_concurrency_hint,
            resources=resources,
            gpu_ids=gpu_ids,
            command_runner=command_runner,
            container_id=container_id,
        )
    )
    peak_gpu = max(peak_gpu, probe_peak_gpu)
    peak_host = max(peak_host, probe_peak_host)

    # Request-count admission and token residency are orthogonal.
    # The short-prompt wave measures the concrete frontend/engine request
    # ceiling. Aggregate prompt+output residency is instead proven exactly from
    # the canonical planner KV budget and immutable model geometry. Re-running
    # a concurrent long-prefill search would only rediscover the same memory
    # bound at O(C * prompt_tokens) cost.
    max_prefill_queued_tokens = _qualified_kv_token_window(
        asset_path=asset_path,
        stack=stack,
    )
    latency_isolation_concurrency = measured_latency_isolation_concurrency(
        performance,
        max_qualified_concurrency=qualified_concurrency,
    )
    preemptive_return = None
    if (
        stack.identity.engine.strip().lower() == "vllm"
        and stack.scheduler_policy.strip().lower() == "priority"
        and qualified_concurrency > latency_isolation_concurrency
    ):
        preemptive_return = _run_preemptive_return_probe(
            borrower_concurrency=qualified_concurrency,
            return_concurrency=latency_isolation_concurrency,
            probe_payload=short_payload,
            completion_url=completion_url,
            http_transport=http_transport,
            task_group=task_group,
        )
    if prefill_exchange.prompt_tokens > max_prefill_queued_tokens:
        raise RuntimeError(
            "model qualification long-prefill probe exceeds planner KV window"
        )

    evidence = QualificationEvidence(
        model_stack_digest=stack_digest,
        canaries=tuple(role_results),
        performance=performance,
        prefill_input_tokens_per_second=(
            prefill_input_tokens_per_second
        ),
        preemptive_return=preemptive_return,
        exact_output_reproducibility_checked=exact_reproducible,
        long_context_checked=False,
        tool_call_checked=False,
    )
    policy = _static_qualification_policy()
    measured = ResourceQualificationMeasurements(
        peak_gpu_memory_bytes_per_device=max(1, peak_gpu),
        peak_host_memory_bytes=max(1, peak_host),
        max_qualified_concurrency=qualified_concurrency,
        max_prefill_queued_tokens=max_prefill_queued_tokens,
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
    stack: FrozenModelStack
    request: ModelReplicaPoolRequest
    lease: object
    rows: tuple[object, ...]
    applied_rows: tuple[object, ...]
    certificate: object
    evidence: QualificationEvidence
    measured: ResourceQualificationMeasurements

    @property
    def row(self) -> object:
        if not self.rows:
            raise RuntimeError("qualified model realization has no replica placements")
        return self.rows[0]

    @property
    def applied(self) -> object:
        if not self.applied_rows:
            raise RuntimeError("qualified model realization has no applied replicas")
        return self.applied_rows[0]


def _model_replica_request(
    *,
    model_id: str,
    roles: tuple[str, ...],
    stack: FrozenModelStack,
    compute,
    runtime_workdir: Path,
) -> ModelReplicaPoolRequest:
    return ModelReplicaPoolRequest(
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
        # None is the canonical Authority-adaptive fleet: materialize replicas
        # until the next exact compute placement is unavailable. Physical GPU
        # occupancy and Noetrium claims remain the admission authority; no
        # fixed replica count is invented at bootstrap.
        replica_count=None,
        endpoint_host="127.0.0.1",
        tags=("qualified-model", "automatic"),
    )


def _realize_model_stack(
    *,
    model_id: str,
    roles: tuple[str, ...],
    stack: FrozenModelStack,
    compute,
    runtime_workdir: Path,
    model_replica_pool: LocalModelReplicaPoolRuntime,
    deployment_runtime: ModelDeploymentRuntimePort,
    phase_trace: CausalPhaseTrace | None = None,
):
    request = _model_replica_request(
        model_id=model_id,
        roles=roles,
        stack=stack,
        compute=compute,
        runtime_workdir=runtime_workdir,
    )
    ensure_phase = (
        None
        if phase_trace is None
        else phase_trace.start(
            "model.bootstrap.replica.ensure",
            attributes={
                "model_id": model_id,
                "runtime_identity": request.runtime_identity_digest,
                "stack_digest": stack.digest(),
                "tensor_parallel": stack.tensor_parallel,
                "context_length": stack.identity.context_length,
                "gpu_count": request.effective_compute.gpu_count,
            },
        )
    )
    try:
        lease = model_replica_pool.ensure(request)
    except BaseException as exc:
        if phase_trace is not None and ensure_phase is not None:
            phase_trace.fail(ensure_phase, exc)
        raise
    else:
        if phase_trace is not None and ensure_phase is not None:
            phase_trace.complete(ensure_phase)
    bind_phase = (
        None
        if phase_trace is None
        else phase_trace.start(
            "model.bootstrap.replica.bind",
            attributes={
                "model_id": model_id,
                "runtime_identity": request.runtime_identity_digest,
                "stack_digest": stack.digest(),
            },
        )
    )
    try:
        # ReplicaPool.ensure() has already verified the exact Authority
        # resource cut and physical status under its identity lock, then
        # attached a continuously fenced consumer before returning. An
        # immediate second assert_healthy() repeats the global Authority
        # snapshot and every replica's provider status with no intervening
        # physical effect. Applied process identities are still checked below.
        rows = tuple(lease.report.placements)
        if not rows:
            raise RuntimeError("model replica pool returned no placements")
        applied_rows = tuple(
            deployment_runtime.applied_identity(row.deployment_id)
            for row in rows
        )
        if len(applied_rows) != len(rows):
            raise RuntimeError("model replica applied identity cardinality drift")
        host_ids = {row.host_id for row in rows}
        if len(host_ids) != 1:
            raise RuntimeError(
                "local model replica pool crossed host identity boundary"
            )
    except BaseException as exc:
        if phase_trace is not None and bind_phase is not None:
            phase_trace.fail(bind_phase, exc)
        lease.close()
        raise
    else:
        if phase_trace is not None and bind_phase is not None:
            phase_trace.complete(
                bind_phase,
                attributes={
                    "replica_count": len(rows),
                    "deployment_ids": tuple(row.deployment_id for row in rows),
                    "host_id": rows[0].host_id,
                    "gpu_ids": tuple(
                        tuple(row.gpu_ids)
                        for row in rows
                    ),
                    "endpoints": tuple(
                        (row.endpoint_host, row.endpoint_port)
                        for row in rows
                    ),
                },
            )
        return request, lease, rows, applied_rows


def _realize_and_qualify_model_stack(
    *,
    model_id: str,
    roles: tuple[str, ...],
    stack: FrozenModelStack,
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
    preferred_concurrency_hint: int | None,
    phase_trace: CausalPhaseTrace | None = None,
) -> _QualifiedRuntimeRealization:
    request, lease, rows, applied_rows = _realize_model_stack(
        model_id=model_id,
        roles=roles,
        stack=stack,
        compute=compute,
        runtime_workdir=runtime_workdir,
        model_replica_pool=model_replica_pool,
        deployment_runtime=deployment_runtime,
        phase_trace=phase_trace,
    )
    row = rows[0]
    applied = applied_rows[0]
    try:
        completion_url = (
            f"http://{row.endpoint_host}:"
            f"{row.endpoint_port}/v1/chat/completions"
        )
        historical_preferred = preferred_concurrency_hint
        if historical_preferred is None:
            historical_closure_path = qualified_model_closure_path(
                authority_root, model_id
            )
            historical_preferred = _historical_preferred_concurrency(
                historical_closure_path,
                qualification_source_digest=(
                    qualification_source_stack_digest(stack)
                ),
                host_identity_digest=row.host_id,
            )
        qualification_concurrency = _static_qualification_concurrency_ceiling(
            stack=stack,
            execution_pool=execution_pool,
        )
        cache_key, cache_path = _static_qualification_cache_path(
            model_id=model_id,
            stack=stack,
            host_identity_digest=row.host_id,
            requirements=requirements,
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        qualification_phase = (
            None
            if phase_trace is None
            else phase_trace.start(
                "model.bootstrap.static-qualification",
                attributes={
                    "model_id": model_id,
                    "stack_digest": stack.digest(),
                    "completion_url": completion_url,
                    "preferred_concurrency_hint": historical_preferred,
                    "max_concurrency": qualification_concurrency,
                    "gpu_ids": tuple(row.gpu_ids),
                    "cache_key": cache_key,
                },
            )
        )
        cache_hit = False
        try:
            with InterprocessFileLock(cache_path.with_suffix(".lock")):
                cached = _load_static_qualification_cache(
                    cache_path,
                    cache_key=cache_key,
                    model_id=model_id,
                    stack=stack,
                    host_identity_digest=row.host_id,
                    requirements=requirements,
                )
                if cached is not None:
                    certificate, evidence, measured = cached
                    cache_hit = True
                else:
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
                            preferred_concurrency_hint=historical_preferred,
                            completion_url=completion_url,
                            http_client=execution_pool.model_json_http_client,
                            http_transport=execution_pool.model_http_transport,
                            task_group=qualification_group,
                            max_concurrency=qualification_concurrency,
                            resources=model_resources,
                            gpu_ids=row.gpu_ids,
                            command_runner=command_runner,
                            runtime_evidence_refs=applied.evidence_refs,
                            stack_digest=stack.digest(),
                            host_identity_digest=row.host_id,
                        )
                    finally:
                        execution_pool.close_model_io_group(
                            qualification_group,
                            cancel_pending=True,
                        )
                    _store_static_qualification_cache(
                        cache_path,
                        cache_key=cache_key,
                        model_id=model_id,
                        stack=stack,
                        host_identity_digest=row.host_id,
                        requirements=requirements,
                        evidence=evidence,
                        measured=measured,
                    )
        except BaseException as exc:
            if phase_trace is not None and qualification_phase is not None:
                phase_trace.fail(qualification_phase, exc)
            raise
        else:
            if phase_trace is not None and qualification_phase is not None:
                phase_trace.complete(
                    qualification_phase,
                    attributes={
                        "cache_hit": cache_hit,
                        "cache_key": cache_key,
                        "max_qualified_concurrency": getattr(
                            measured,
                            "max_qualified_concurrency",
                            None,
                        ),
                        "max_prefill_queued_tokens": getattr(
                            measured,
                            "max_prefill_queued_tokens",
                            None,
                        ),
                    },
                )
            return _QualifiedRuntimeRealization(
                stack=stack,
                request=request,
                lease=lease,
                rows=rows,
                applied_rows=applied_rows,
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
    state_root: Path,
    runtime_workdir: Path,
    requirements: tuple[RequiredModelRuntime, ...],
    assets: ModelAssetManager,
    resource_authority: UniversalResourceAuthority,
    compute_inventory: ComputeInventoryPort,
    gpu_runtime_observer: GpuRuntimeObserverPort | None,
    host_runtime_observer: HostRuntimeObserverPort | None,
    model_replica_pool: LocalModelReplicaPoolRuntime,
    deployment_runtime: ModelDeploymentRuntimePort,
    model_resources: ModelResourceViewPort,
    execution_pool: ResearchExecutionPool,
    phase_trace: CausalPhaseTrace | None = None,
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
            resource_authority=resource_authority,
            compute_inventory=compute_inventory,
            gpu_runtime_observer=gpu_runtime_observer,
            host_runtime_observer=host_runtime_observer,
            command_runner=command_runner,
            state_root=state_root,
        )
        # Crash recovery precedes topology selection.  Physical absence is
        # authoritative evidence that a BOUND warm realization cannot serve any
        # consumer; reconcile it before its stale claims distort placement.
        model_replica_pool.reconcile_absent_warm_realizations()

        # Retirement is durable logical truth, so a retired deployment can never
        # become a valid warm candidate again.  Reconcile its exact physical
        # Effect eagerly instead of waiting for a later placement failure.  This
        # keeps stale vLLM containers from pinning GPU memory indefinitely after
        # crash/restart windows while preserving exact identity/fencing checks in
        # ModelDeploymentRuntime.quiesce_retired().
        retirement_phase = (
            None
            if phase_trace is None
            else phase_trace.start(
                "model.bootstrap.retired-orphan-reconcile",
                attributes={"model_id": model_id},
            )
        )
        try:
            retired_outcomes = deployment_runtime.reconcile_retired_orphans()
        except BaseException as exc:
            if phase_trace is not None and retirement_phase is not None:
                phase_trace.fail(retirement_phase, exc)
            raise
        else:
            if phase_trace is not None and retirement_phase is not None:
                phase_trace.complete(
                    retirement_phase,
                    attributes={
                        "model_id": model_id,
                        "outcome_count": len(retired_outcomes),
                        "quiescent_count": sum(
                            1 for outcome in retired_outcomes if outcome.quiescent
                        ),
                    },
                )

        minimum_context_tokens = max(
            row.minimum_context_tokens for row in requirements
        )
        materialized: MaterializedModelStack | None = None
        placement_observation: ModelPlacementObservation | None = None
        while materialized is None:
            (
                warm_candidate,
                rejected_runtime_identity,
                placement_observation,
            ) = _warm_materialized_stack_candidate(
                model_id=model_id,
                materializer=materializer,
                model_resources=model_resources,
                deployment_runtime=deployment_runtime,
                runtime_workdir=runtime_workdir,
                minimum_context_tokens=minimum_context_tokens,
                observation=placement_observation,
            )
            selection_phase = (
                None
                if phase_trace is None
                else phase_trace.start(
                    "model.bootstrap.warm-select",
                    attributes={
                        "model_id": model_id,
                        "minimum_context_tokens": minimum_context_tokens,
                        "candidate_found": warm_candidate is not None,
                        "candidate_stack_digest": (
                            None if warm_candidate is None else warm_candidate.stack.digest()
                        ),
                        "candidate_tensor_parallel": (
                            None if warm_candidate is None else warm_candidate.stack.tensor_parallel
                        ),
                        "candidate_context_length": (
                            None if warm_candidate is None else warm_candidate.stack.identity.context_length
                        ),
                        "rejected_runtime_identity": rejected_runtime_identity,
                    },
                )
            )
            if phase_trace is not None and selection_phase is not None:
                phase_trace.complete(selection_phase)
            if warm_candidate is not None:
                materialized = warm_candidate
                break
            if (
                rejected_runtime_identity is None
                or not model_replica_pool.reclaim_stale_warm_realization(
                    rejected_runtime_identity
                )
            ):
                break
            # Reclaim mutates Authority and physical GPU pressure; the prior
            # placement observation cut is no longer valid.
            placement_observation = None
        warm_first = materialized is not None
        if materialized is None:
            fresh_phase = (
                None
                if phase_trace is None
                else phase_trace.start(
                    "model.bootstrap.fresh-stack.materialize",
                    attributes={
                        "model_id": model_id,
                        "minimum_context_tokens": minimum_context_tokens,
                    },
                )
            )
            try:
                while True:
                    try:
                        if placement_observation is None:
                            placement_observation = materializer.placement_observation()
                        materialized = materializer.materialize(
                            model_id,
                            minimum_context_tokens=minimum_context_tokens,
                            observation=placement_observation,
                        )
                        break
                    except ModelStackPlacementUnavailable:
                        reclaimed = model_replica_pool.reclaim_one_stale_warm_realization()
                        if reclaimed is not None:
                            placement_observation = None
                            continue
                        retired_outcomes = deployment_runtime.reconcile_retired_orphans()
                        reclaimed_retired_capacity = any(
                            outcome.quiescent
                            and outcome.summary
                            == "retired service physical effect compensated"
                            for outcome in retired_outcomes
                        )
                        if reclaimed_retired_capacity:
                            placement_observation = None
                            continue
                        raise
            except BaseException as exc:
                if phase_trace is not None and fresh_phase is not None:
                    phase_trace.fail(fresh_phase, exc)
                raise
            else:
                if phase_trace is not None and fresh_phase is not None:
                    phase_trace.complete(fresh_phase)
        stack = materialized.stack
        runtime_workdir.mkdir(parents=True, exist_ok=True)
        try:
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
                preferred_concurrency_hint=(
                    _warm_stack_concurrency_hint(stack)
                    if warm_first
                    else None
                ),
                phase_trace=phase_trace,
            )
        except ComputePlacementUnavailable:
            recovered = deployment_runtime.reconcile_retired_orphans()
            reclaimed_physical_capacity = any(
                outcome.quiescent
                and outcome.summary
                == "retired service physical effect compensated"
                for outcome in recovered
            )
            retry_succeeded = False
            if reclaimed_physical_capacity:
                try:
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
                        preferred_concurrency_hint=(
                            _warm_stack_concurrency_hint(stack)
                            if warm_first
                            else None
                        ),
                        phase_trace=phase_trace,
                    )
                except ComputePlacementUnavailable:
                    pass
                else:
                    retry_succeeded = True

            if not retry_succeeded:
                if not warm_first:
                    raise
                # A desired deployment can outlive its exact Authority closure.
                # If warm adoption cannot prove the resource generation, return
                # to ordinary fresh placement rather than weakening fencing.
                while True:
                    try:
                        materialized = materializer.materialize(model_id)
                        break
                    except ModelStackPlacementUnavailable:
                        reclaimed = (
                            model_replica_pool.reclaim_one_stale_warm_realization()
                        )
                        if reclaimed is None:
                            raise
                stack = materialized.stack
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
                    preferred_concurrency_hint=None,
                    phase_trace=phase_trace,
                )
        lease = realization.lease
        request = realization.request
        row = realization.row
        applied = realization.applied
        certificate = realization.certificate
        evidence = realization.evidence
        measured = realization.measured

        # Measured qualification constrains Noetrium runtime admission. The
        # already-running engine is a physical hard ceiling and must not be
        # retired/recreated merely to mirror a smaller measured scheduler
        # window in --max-num-seqs. One realization therefore remains bound to
        # one Authority closure from qualification through consumption.

        replica_rows = tuple(realization.rows)
        replica_applied_rows = tuple(realization.applied_rows)
        if len(replica_rows) != len(replica_applied_rows):
            raise RuntimeError(
                "qualified model replica topology/applied identity cardinality drift"
            )

        deployments = tuple(
            QualifiedDeploymentManifest(
                deployment_id=replica_row.deployment_id,
                stack=stack,
                certificate=certificate,
                placement=DeploymentPlacement(replica_row.gpu_ids),
                host_identity_digest=replica_row.host_id,
            )
            for replica_row in replica_rows
        )
        deployment_by_id = {
            deployment.deployment_id: deployment
            for deployment in deployments
        }
        routes = tuple(
            ModelEndpointRoute(
                deployment_id=replica_row.deployment_id,
                deployment_generation=deployment_by_id[
                    replica_row.deployment_id
                ].digest(),
                base_url=(
                    f"http://{replica_row.endpoint_host}:"
                    f"{replica_row.endpoint_port}"
                ),
            )
            for replica_row in replica_rows
        )
        heartbeats = tuple(
            ServiceHeartbeat(
                deployment_id=replica_row.deployment_id,
                stack_digest=stack.digest(),
                pid=replica_applied.pid,
                process_start_marker=replica_applied.process_start_marker,
                argv_digest=replica_applied.argv_digest,
                ready=True,
                qualification_digest=certificate.digest(),
                timestamp=time.time(),
            )
            for replica_row, replica_applied in zip(
                replica_rows,
                replica_applied_rows,
                strict=True,
            )
        )

        # Scientific role identity remains canonical and stable: roles bind to
        # replica 000. The qualified closure may additionally carry any number
        # of independently generation-bound same-stack replicas; the endpoint
        # authority discovers them as one runtime replica set without changing
        # downstream paper semantics.
        canonical_deployment = deployment_by_id[row.deployment_id]
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
                canonical_deployment,
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
                "canonical_deployment_id": row.deployment_id,
                "replica_placements": replica_rows,
                "applied_runtime_identities": replica_applied_rows,
                "static_qualification_evidence": evidence,
                "resource_measurements": measured,
            }
        )
        closure_path = qualified_model_closure_path(authority_root, model_id)
        group = execution_pool.open_model_io_group(
            "qualified-model-bootstrap:" + _slug(model_id)
        )
        deployment_ids = tuple(
            deployment.deployment_id for deployment in deployments
        )
        shared_static_evidence = (
            "static-qualification:sha256:" + certificate.evidence_digest,
            STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF,
            "model-stack-fingerprint:sha256:"
            + canonical_digest(materialized.fingerprint_ref),
            GPU_MEMORY_ACCOUNTING_EVIDENCE_REF,
        )
        publication_phase = (
            None if phase_trace is None else phase_trace.start(
                "model.bootstrap.publish-qualified-closure",
                attributes={
                    "model_id": model_id,
                    "replica_count": len(deployments),
                    "role_count": len(role_manifest.assignments),
                },
            )
        )
        try:
            receipt = qualify_and_publish_model_deployment_closure(
                closure_path,
                role_manifest=role_manifest,
                deployments=deployments,
                routes=routes,
                heartbeats=heartbeats,
                canary_probes=probes,
                runtime_manifest_digest=runtime_manifest_digest,
                max_heartbeat_age_seconds=120.0,
                task_group=group,
                admission_registry=execution_pool.model_admission,
                scheduling_authority=execution_pool.scheduling_authority,
                transports_by_deployment={
                    deployment_id: execution_pool.model_http_transport
                    for deployment_id in deployment_ids
                },
                extra_evidence_refs_by_deployment={
                    deployment_id: shared_static_evidence
                    for deployment_id in deployment_ids
                },
                replace_malformed_existing=True,
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
    "GPU_MEMORY_ACCOUNTING_EVIDENCE_REF",
    "RequiredModelRuntime",
    "STATIC_QUALIFICATION_PROTOCOL_EVIDENCE_REF",
    "bootstrap_required_qualified_model_runtime",
    "qualified_model_closure_path",
    "qualification_source_stack_digest",
]
