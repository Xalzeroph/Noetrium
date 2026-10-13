from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.api.interaction import EnvironmentCapabilityDescriptor
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonInput
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from .contracts import (
    EmbodiedActionCommand,
    EmbodiedCaptureReceipt,
    EmbodiedEventProjection,
)


@runtime_checkable
class EmbodiedEnvironmentPort(Protocol):
    @property
    def spec(self) -> NoetriumUnit: ...

    def reset(
        self, episode: NoetriumUnit, context: ExecutionContext
    ) -> tuple[EmbodiedEventProjection, ...]: ...

    def step(
        self, command: EmbodiedActionCommand, context: ExecutionContext
    ) -> tuple[EmbodiedEventProjection, ...]: ...

    def close(self) -> None: ...


@runtime_checkable
class EmbodiedTrajectorySinkPort(Protocol):
    def capture(
        self, event: EmbodiedEventProjection, context: ExecutionContext
    ) -> EmbodiedCaptureReceipt: ...


@runtime_checkable
class EmbodiedCheckpointPort(Protocol):
    def capture(self, *, episode: NoetriumUnit) -> bytes: ...

    def restore(self, payload: bytes, *, episode: NoetriumUnit) -> None: ...


@runtime_checkable
class EmbodiedQueryPort(Protocol):
    def query(
        self,
        query_type: str,
        payload: JsonInput,
        context: ExecutionContext,
    ) -> tuple[EmbodiedEventProjection, ...]: ...


@runtime_checkable
class EmbodiedCapabilityPort(Protocol):
    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]: ...


__all__ = [
    "EmbodiedCapabilityPort",
    "EmbodiedCheckpointPort",
    "EmbodiedEnvironmentPort",
    "EmbodiedQueryPort",
    "EmbodiedTrajectorySinkPort",
]
