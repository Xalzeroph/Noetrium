from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from noetrium_platform.capabilities.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)

if TYPE_CHECKING:
    from noetrium_platform.research.execution.machines.capability_program import (
        CapabilityProgramBinding,
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
        program_binding: "CapabilityProgramBinding | None" = None,
    ) -> CapabilityInvocationPipelinePort: ...


__all__ = [
    "CapabilityInvocationPipelineFactoryPort",
    "CapabilityInvocationPipelinePort",
]
