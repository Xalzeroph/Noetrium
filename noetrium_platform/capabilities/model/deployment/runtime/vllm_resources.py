from __future__ import annotations

from dataclasses import replace

from noetrium_platform.capabilities.model.stack.api import (
    ModelStackSpec,
    parse_vllm_engine_resource_args,
)
from noetrium_platform.substrate.api import ComputeRequirement, GpuSharingMode


def reconcile_vllm_compute_requirement(
    stack: ModelStackSpec,
    requirement: ComputeRequirement,
) -> ComputeRequirement:
    """Translate frozen vLLM engine demand into generic compute capacity."""

    if not isinstance(stack, ModelStackSpec):
        raise TypeError("vLLM resource reconciliation requires ModelStackSpec")
    if not isinstance(requirement, ComputeRequirement):
        raise TypeError("vLLM resource reconciliation requires ComputeRequirement")
    if stack.identity.engine.lower() != "vllm":
        raise ValueError("vLLM resource reconciliation requires a vLLM model stack")

    intent = parse_vllm_engine_resource_args(stack.engine_args)
    fraction = requirement.required_gpu_memory_fraction

    # Explicit KV-cache bytes override vLLM's gpu-memory-utilization for cache
    # sizing. Do not pretend that the fraction still describes the engine's
    # total live VRAM demand. Shared placement then needs an independently
    # measured/reserved total requirement from ComputeRequirement.
    if intent.kv_cache_memory_bytes is None:
        if (
            intent.gpu_memory_utilization is not None
            and intent.gpu_memory_utilization > 0.0
        ):
            fraction = max(
                0.0 if fraction is None else float(fraction),
                intent.gpu_memory_utilization,
            )

    if (
        requirement.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
        and requirement.required_gpu_free_memory_bytes <= 0
        and fraction is None
    ):
        raise ValueError(
            "shared vLLM placement requires measured total VRAM demand when "
            "gpu-memory-utilization cannot define it"
        )

    additional_host_memory = (
        intent.cpu_offload_bytes_per_gpu * requirement.gpu_count
        + intent.kv_offloading_bytes
        + intent.multimodal_cache_bytes(
            data_parallel_size=stack.data_parallel
        )
    )
    return replace(
        requirement,
        memory_bytes=requirement.memory_bytes + additional_host_memory,
        required_gpu_memory_fraction=fraction,
    )


__all__ = ["reconcile_vllm_compute_requirement"]
