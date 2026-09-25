from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from .workload import (
    WorkloadCheckpointBindingPort,
    WorkloadCheckpointBundle,
    WorkloadCheckpointManifest,
    WorkloadExecutionCut,
)


class WorkloadCheckpointPublicationPort(Protocol):
    """Publish an acceleration checkpoint bound to an explicit execution cut."""

    def published(self, manifest: WorkloadCheckpointManifest) -> None: ...


class WorkloadCheckpointCoordinatorPort(Protocol):
    def capture(
        self,
        *,
        binding: WorkloadCheckpointBindingPort,
        context: ExecutionContext,
        execution_cut: WorkloadExecutionCut,
    ) -> WorkloadCheckpointManifest: ...

    def restore(
        self,
        checkpoint_id: str,
        *,
        binding: WorkloadCheckpointBindingPort,
        context: ExecutionContext,
    ) -> WorkloadCheckpointBundle: ...


__all__ = [
    "WorkloadCheckpointCoordinatorPort",
    "WorkloadCheckpointPublicationPort",
]
