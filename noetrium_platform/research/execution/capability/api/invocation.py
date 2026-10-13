from __future__ import annotations

from collections.abc import Callable
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from noetrium_platform.capabilities.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)

if TYPE_CHECKING:
    from noetrium_platform.research.execution.machines.api import (
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
        control: ExecutionControlPort,
        execute: Callable[[CapabilityRequest, ExecutionControlPort], CapabilityResult],
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
