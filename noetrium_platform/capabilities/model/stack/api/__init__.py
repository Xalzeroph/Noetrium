"""Stable composition-time contracts for AI infrastructure stacks."""

from .stack import (
    ModelArtifactClosure,
    ModelServingPolicy,
    ModelStackSpec,
    RuntimeBuildIdentity,
)
from .vllm import VllmEngineResourceArgs, parse_vllm_engine_resource_args

__all__ = [
    "ModelArtifactClosure",
    "ModelServingPolicy",
    "ModelStackSpec",
    "RuntimeBuildIdentity",
    "VllmEngineResourceArgs",
    "parse_vllm_engine_resource_args",
]
