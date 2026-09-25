from __future__ import annotations

from typing import Protocol

from .contracts import JavaRuntimeProvisioningRequest, JavaRuntimeProvisioningResult


class JavaRuntimeProvisioningPort(Protocol):
    def provision(
        self,
        request: JavaRuntimeProvisioningRequest,
    ) -> JavaRuntimeProvisioningResult: ...


__all__ = ["JavaRuntimeProvisioningPort"]
