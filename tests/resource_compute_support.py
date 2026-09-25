from __future__ import annotations

from typing import Any

from noetrium_platform.infrastructure.resources.compute.api import (
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
)
from noetrium_platform.infrastructure.resources.compute.composition import (
    bind_in_memory_compute_scheduler,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    InMemoryComputeScheduler,
)


class IdleGpuRuntimeObserver:
    def __init__(self, *gpu_ids: str) -> None:
        self._gpu_ids = tuple(gpu_ids)

    def snapshot(self) -> GpuRuntimeSnapshot:
        return GpuRuntimeSnapshot(
            True,
            devices=tuple(
                GpuDeviceStatus(
                    gpu_id,
                    gpu_id,
                    "test-gpu",
                    1024 * 1024,
                    0,
                    1024 * 1024,
                    0,
                )
                for gpu_id in self._gpu_ids
            ),
            processes=(),
            processes_complete=True,
        )


def idle_gpu_runtime_observer(*gpu_ids: str) -> IdleGpuRuntimeObserver:
    return IdleGpuRuntimeObserver(*gpu_ids)


def in_memory_compute_scheduler(
    inventory: InMemoryComputeInventory,
    **kwargs: Any,
) -> InMemoryComputeScheduler:
    """Use the production composition boundary in isolated compute tests."""

    return bind_in_memory_compute_scheduler(inventory, **kwargs)


__all__ = [
    "IdleGpuRuntimeObserver",
    "idle_gpu_runtime_observer",
    "in_memory_compute_scheduler",
]
