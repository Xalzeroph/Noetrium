from __future__ import annotations

from dataclasses import replace

from noetrium_platform.capabilities.model.stack.api import (
    ModelStackSpec,
    parse_vllm_engine_resource_args,
)
from noetrium_platform.substrate.api import ComputeRequirement


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


__all__ = ["reconcile_vllm_compute_requirement"]
