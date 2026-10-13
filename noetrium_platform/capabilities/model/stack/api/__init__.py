"""Stable composition-time contracts for AI infrastructure stacks."""

from .launch import ModelStackLaunchSettings, model_stack_launch_settings
from .stack import (
    DEFAULT_MODEL_SCHEDULER_POLICY,
    ModelArtifactClosure,
    ModelServingPolicy,
    FrozenModelStack,
    RuntimeBuildIdentity,
)
from .vllm import (
    MAX_VLLM_GPU_MEMORY_UTILIZATION,
    VllmEngineResourceArgs,
    parse_vllm_engine_resource_args,
    vllm_gpu_memory_utilization_for_target_bytes,
)

__all__ = [
    "DEFAULT_MODEL_SCHEDULER_POLICY",
    "ModelStackLaunchSettings",
    "model_stack_launch_settings",
    "ModelArtifactClosure",
    "ModelServingPolicy",
    "FrozenModelStack",
    "RuntimeBuildIdentity",
    "MAX_VLLM_GPU_MEMORY_UTILIZATION",
    "VllmEngineResourceArgs",
    "parse_vllm_engine_resource_args",
    "vllm_gpu_memory_utilization_for_target_bytes",
]
