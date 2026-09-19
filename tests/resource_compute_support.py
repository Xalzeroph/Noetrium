from __future__ import annotations

from typing import Any

from noetrium_platform.infrastructure.resources.compute.composition import (
    bind_in_memory_compute_scheduler,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    InMemoryComputeScheduler,
)


def in_memory_compute_scheduler(
    inventory: InMemoryComputeInventory,
    **kwargs: Any,
) -> InMemoryComputeScheduler:
    """Use the production composition boundary in isolated compute tests."""

    return bind_in_memory_compute_scheduler(inventory, **kwargs)


__all__ = ["in_memory_compute_scheduler"]
