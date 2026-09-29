"""Stable composition-time contracts for AI infrastructure stacks."""

from .stack import (
    ModelArtifactClosure,
    ModelServingPolicy,
    ModelStackSpec,
    RuntimeBuildIdentity,
)
from .vllm import (
    MAX_VLLM_GPU_MEMORY_UTILIZATION,
    VllmEngineResourceArgs,
    parse_vllm_engine_resource_args,
    vllm_gpu_memory_utilization_for_target_bytes,
)

__all__ = [
    "ModelArtifactClosure",
    "ModelServingPolicy",
    "ModelStackSpec",
    "RuntimeBuildIdentity",
    "MAX_VLLM_GPU_MEMORY_UTILIZATION",
    "VllmEngineResourceArgs",
    "parse_vllm_engine_resource_args",
    "vllm_gpu_memory_utilization_for_target_bytes",
]
