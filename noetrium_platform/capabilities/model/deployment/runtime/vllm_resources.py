from __future__ import annotations

from dataclasses import dataclass, replace
import math

from noetrium_platform.capabilities.model.stack.api import ModelStackSpec
from noetrium_platform.substrate.api import ComputeRequirement


_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class VllmResourceIntent:
    """Resource-relevant vLLM engine arguments frozen by ModelStackSpec."""

    gpu_memory_utilization: float | None = None
    cpu_offload_gb_per_gpu: float = 0.0
    max_num_seqs: int | None = None
    max_num_queued_requests: int | None = None

    @property
    def cpu_offload_bytes_per_gpu(self) -> int:
        return math.ceil(self.cpu_offload_gb_per_gpu * _GIB)


def _option_value(
    args: tuple[str, ...],
    names: tuple[str, ...],
) -> str | None:
    found: str | None = None
    index = 0
    while index < len(args):
        token = args[index]
        matched: str | None = None
        value: str | None = None
        for name in names:
            if token == name:
                matched = name
                if index + 1 >= len(args):
                    raise ValueError(f"vLLM engine argument requires a value: {name}")
                value = args[index + 1]
                if value.startswith("--"):
                    raise ValueError(f"vLLM engine argument requires a value: {name}")
                index += 1
                break
            prefix = name + "="
            if token.startswith(prefix):
                matched = name
                value = token[len(prefix):]
                break
        if matched is not None:
            if value is None or value == "":
                raise ValueError(f"vLLM engine argument requires a value: {matched}")
            if found is not None:
                raise ValueError(
                    "vLLM engine resource argument is duplicated or aliased twice: "
                    + "/".join(names)
                )
            found = value
        index += 1
    return found


def _finite_float(value: str, *, field: str, minimum: float, maximum: float | None = None) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"vLLM {field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(f"vLLM {field} must be finite and >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"vLLM {field} must be <= {maximum}")
    return parsed


def _positive_int(value: str, *, field: str) -> int:
    multipliers = {
        "k": 1000,
        "m": 1000**2,
        "g": 1000**3,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
    }
    suffix = value[-1:] if value else ""
    raw = value[:-1] if suffix in multipliers else value
    try:
        numeric = float(raw) if suffix in multipliers else float(value)
    except ValueError as exc:
        raise ValueError(
            f"vLLM {field} must be a positive human-readable integer"
        ) from exc
    scaled = numeric * multipliers.get(suffix, 1)
    if (
        not math.isfinite(scaled)
        or scaled <= 0
        or not float(scaled).is_integer()
    ):
        raise ValueError(
            f"vLLM {field} must resolve to a positive integer"
        )
    return int(scaled)


def parse_vllm_resource_intent(engine_args: tuple[str, ...]) -> VllmResourceIntent:
    if not isinstance(engine_args, tuple) or any(
        not isinstance(item, str) or not item
        for item in engine_args
    ):
        raise TypeError("vLLM engine_args must be a tuple of non-empty strings")

    gpu_fraction_raw = _option_value(
        engine_args,
        ("--gpu-memory-utilization", "--device-memory-utilization"),
    )
    cpu_offload_raw = _option_value(engine_args, ("--cpu-offload-gb",))
    max_num_seqs_raw = _option_value(engine_args, ("--max-num-seqs",))
    max_queued_raw = _option_value(engine_args, ("--max-num-queued-reqs",))

    gpu_fraction = (
        None
        if gpu_fraction_raw is None
        else _finite_float(
            gpu_fraction_raw,
            field="gpu-memory-utilization",
            minimum=0.0,
            maximum=1.0,
        )
    )
    cpu_offload = (
        0.0
        if cpu_offload_raw is None
        else _finite_float(
            cpu_offload_raw,
            field="cpu-offload-gb",
            minimum=0.0,
        )
    )
    return VllmResourceIntent(
        gpu_memory_utilization=gpu_fraction,
        cpu_offload_gb_per_gpu=cpu_offload,
        max_num_seqs=(
            None
            if max_num_seqs_raw is None
            else _positive_int(max_num_seqs_raw, field="max-num-seqs")
        ),
        max_num_queued_requests=(
            None
            if max_queued_raw is None
            else _positive_int(
                max_queued_raw,
                field="max-num-queued-reqs",
            )
        ),
    )


def reconcile_vllm_compute_requirement(
    stack: ModelStackSpec,
    requirement: ComputeRequirement,
) -> ComputeRequirement:
    """Derive physical compute reservation from the frozen vLLM stack.

    Engine arguments remain scientific/runtime identity. This function only
    translates their unavoidable physical demand into the generic compute
    authority so placement and serving cannot disagree about capacity.
    """

    if not isinstance(stack, ModelStackSpec):
        raise TypeError("vLLM resource reconciliation requires ModelStackSpec")
    if not isinstance(requirement, ComputeRequirement):
        raise TypeError("vLLM resource reconciliation requires ComputeRequirement")
    if stack.identity.engine.lower() != "vllm":
        raise ValueError("vLLM resource reconciliation requires a vLLM model stack")

    intent = parse_vllm_resource_intent(stack.engine_args)
    fraction = requirement.required_gpu_memory_fraction
    if (
        intent.gpu_memory_utilization is not None
        and intent.gpu_memory_utilization > 0.0
    ):
        fraction = max(
            0.0 if fraction is None else float(fraction),
            intent.gpu_memory_utilization,
        )

    offload_bytes = intent.cpu_offload_bytes_per_gpu * requirement.gpu_count
    return replace(
        requirement,
        memory_bytes=requirement.memory_bytes + offload_bytes,
        required_gpu_memory_fraction=fraction,
    )


def validate_vllm_admission_capacity(
    stack: ModelStackSpec,
    capacity: int,
) -> None:
    """Reject platform admission that can exceed an explicit vLLM queue valve."""

    if type(capacity) is not int or capacity <= 0:
        raise ValueError("vLLM admission capacity must be positive")
    intent = parse_vllm_resource_intent(stack.engine_args)
    if (
        intent.max_num_queued_requests is not None
        and capacity > intent.max_num_queued_requests
    ):
        raise ValueError(
            "qualified platform concurrency exceeds vLLM max-num-queued-reqs: "
            f"{capacity}>{intent.max_num_queued_requests}"
        )


__all__ = [
    "VllmResourceIntent",
    "parse_vllm_resource_intent",
    "reconcile_vllm_compute_requirement",
    "validate_vllm_admission_capacity",
]
