from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.research.experimentation.experiment.api import ExperimentDefinition

from .contracts import ResourceAllocationReceipt, ResourcePolicy


class ResourceAllocationLeasePort(Protocol):
    @property
    def receipt(self) -> ResourceAllocationReceipt: ...
    def assert_healthy(self) -> None: ...
    def assert_healthy(self) -> None: ...
    def release(self) -> None: ...


class ExperimentResourceBinderPort(Protocol):
    def bind(
        self,
        definition: ExperimentDefinition,
        policy: ResourcePolicy,
        *,
        allocation_id: str,
        owner_scope: ScopeIdentity,
        placement_scope: ScopeIdentity | None = None,
    ) -> ResourceAllocationLeasePort: ...


__all__ = ["ExperimentResourceBinderPort", "ResourceAllocationLeasePort"]
