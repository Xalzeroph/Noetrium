"""Stable composition-time contracts for AI infrastructure stacks."""

from .stack import ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
from .vllm import VllmEngineResourceArgs, parse_vllm_engine_resource_args

__all__ = [
    "ModelArtifactClosure",
    "ModelStackSpec",
    "RuntimeBuildIdentity",
    "VllmEngineResourceArgs",
    "parse_vllm_engine_resource_args",
]
