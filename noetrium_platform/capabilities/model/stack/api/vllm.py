from __future__ import annotations

from dataclasses import dataclass
import math


_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class VllmEngineResourceArgs:
    """Resource- and admission-relevant values frozen inside vLLM engine_args."""

    gpu_memory_utilization: float | None = None
    cpu_offload_gb_per_gpu: float = 0.0
    kv_cache_memory_bytes: int | None = None
    kv_offloading_size_gb: float = 0.0
    mm_processor_cache_gb: float | None = None
    api_server_count: int | None = None
    max_num_seqs: int | None = None
    max_num_queued_requests: int | None = None

    @property
    def cpu_offload_bytes_per_gpu(self) -> int:
        return math.ceil(self.cpu_offload_gb_per_gpu * _GIB)

    @property
    def kv_offloading_bytes(self) -> int:
        return math.ceil(self.kv_offloading_size_gb * _GIB)

    def multimodal_cache_bytes(self, *, data_parallel_size: int) -> int:
        if self.mm_processor_cache_gb is None:
            return 0
        if type(data_parallel_size) is not int or data_parallel_size <= 0:
            raise ValueError("vLLM data_parallel_size must be positive")
        api_servers = (
            data_parallel_size
            if self.api_server_count is None
            else self.api_server_count
        )
        return math.ceil(
            self.mm_processor_cache_gb
            * _GIB
            * (api_servers + data_parallel_size)
        )


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


def _finite_float(
    value: str,
    *,
    field: str,
    minimum: float,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"vLLM {field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(f"vLLM {field} must be finite and >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"vLLM {field} must be <= {maximum}")
    return parsed


def _positive_human_integer(value: str, *, field: str) -> int:
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
        numeric = float(raw)
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


def parse_vllm_engine_resource_args(
    engine_args: tuple[str, ...],
) -> VllmEngineResourceArgs:
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
    kv_cache_raw = _option_value(engine_args, ("--kv-cache-memory-bytes",))
    kv_offload_raw = _option_value(engine_args, ("--kv-offloading-size",))
    mm_cache_raw = _option_value(engine_args, ("--mm-processor-cache-gb",))
    api_server_count_raw = _option_value(
        engine_args,
        ("--api-server-count", "-asc"),
    )
    max_num_seqs_raw = _option_value(engine_args, ("--max-num-seqs",))
    max_queued_raw = _option_value(engine_args, ("--max-num-queued-reqs",))

    return VllmEngineResourceArgs(
        gpu_memory_utilization=(
            None
            if gpu_fraction_raw is None
            else _finite_float(
                gpu_fraction_raw,
                field="gpu-memory-utilization",
                minimum=0.0,
                maximum=1.0,
            )
        ),
        cpu_offload_gb_per_gpu=(
            0.0
            if cpu_offload_raw is None
            else _finite_float(
                cpu_offload_raw,
                field="cpu-offload-gb",
                minimum=0.0,
            )
        ),
        kv_cache_memory_bytes=(
            None
            if kv_cache_raw is None
            else _positive_human_integer(
                kv_cache_raw,
                field="kv-cache-memory-bytes",
            )
        ),
        kv_offloading_size_gb=(
            0.0
            if kv_offload_raw is None
            else _finite_float(
                kv_offload_raw,
                field="kv-offloading-size",
                minimum=0.0,
            )
        ),
        mm_processor_cache_gb=(
            None
            if mm_cache_raw is None
            else _finite_float(
                mm_cache_raw,
                field="mm-processor-cache-gb",
                minimum=0.0,
            )
        ),
        api_server_count=(
            None
            if api_server_count_raw is None
            else _positive_human_integer(
                api_server_count_raw,
                field="api-server-count",
            )
        ),
        max_num_seqs=(
            None
            if max_num_seqs_raw is None
            else _positive_human_integer(
                max_num_seqs_raw,
                field="max-num-seqs",
            )
        ),
        max_num_queued_requests=(
            None
            if max_queued_raw is None
            else _positive_human_integer(
                max_queued_raw,
                field="max-num-queued-reqs",
            )
        ),
    )


__all__ = [
    "VllmEngineResourceArgs",
    "parse_vllm_engine_resource_args",
]
