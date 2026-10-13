from __future__ import annotations

from typing import Protocol, runtime_checkable
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from noetrium_platform.capabilities.environment.api import (
    ActionRequest, ActionResult, EnvironmentSession, Observation, ExecutionContext,
)


@runtime_checkable
class WebWorldPort(EnvironmentSession, Protocol):
    @property
    def spec(self) -> NoetriumUnit: ...

    def observe(self, context: ExecutionContext) -> Observation: ...

    def act(self, request: ActionRequest, control: ExecutionControlPort) -> ActionResult: ...

    def close(self) -> None: ...


__all__ = ["WebWorldPort"]
