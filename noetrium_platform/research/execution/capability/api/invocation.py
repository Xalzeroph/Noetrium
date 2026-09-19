from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityPolicySet,
    CapabilityRequest,
    CapabilityResult,
)


@runtime_checkable
class CapabilityInvocationPipelinePort(Protocol):
    def invoke(
        self,
        *,
        invocation_id: str,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        execute: Callable[[CapabilityRequest], CapabilityResult],
    ) -> CapabilityResult: ...


@runtime_checkable
class CapabilityInvocationPipelineFactoryPort(Protocol):
    def create(
        self,
        policy: CapabilityPolicySet | None = None,
    ) -> CapabilityInvocationPipelinePort: ...


__all__ = [
    "CapabilityInvocationPipelineFactoryPort",
    "CapabilityInvocationPipelinePort",
]
