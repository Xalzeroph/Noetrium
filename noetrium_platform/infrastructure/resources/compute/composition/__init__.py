from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeHost,
    ComputeSchedulerPort,
    GpuRuntimeObserverPort,
    HostRuntimeObserverPort,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    InMemoryComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
)


@dataclass(frozen=True, slots=True)
class InMemoryComputeStack:
    """Fully wired in-memory compute stack for one composition boundary.

    Compute placement and capacity stay inside the compute facet while lease,
    ownership, and fencing truth are owned by the injected ResourceLeaseAuthority.
    Returning the assembled stack is useful to composition roots and diagnostics;
    ordinary downstream code should depend on ``ComputeSchedulerPort`` instead.
    """

    inventory: InMemoryComputeInventory
    resource_authority: InMemoryResourceLeaseRegistry
    scheduler: InMemoryComputeScheduler


def bind_in_memory_compute_scheduler(
    inventory: InMemoryComputeInventory,
    *,
    resource_authority: InMemoryResourceLeaseRegistry | None = None,
    gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
    host_runtime_observer: HostRuntimeObserverPort | None = None,
) -> InMemoryComputeScheduler:
    """Bind an existing inventory to the canonical resource authority boundary.

    The default authority is created here, at the composition root, never inside
    the scheduler runtime. Callers that need one shared lease/fencing domain can
    inject the same authority explicitly across multiple resource facets.
    """

    resources = resource_authority or InMemoryResourceLeaseRegistry()
    return InMemoryComputeScheduler(
        inventory,
        ownership=resources,
        leases=resources,
        gpu_runtime_observer=gpu_runtime_observer,
        host_runtime_observer=host_runtime_observer,
    )


def compose_in_memory_compute_stack(
    hosts: Iterable[ComputeHost] = (),
    *,
    resource_authority: InMemoryResourceLeaseRegistry | None = None,
    gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
    host_runtime_observer: HostRuntimeObserverPort | None = None,
) -> InMemoryComputeStack:
    """Assemble inventory, ResourceLeaseAuthority, and compute scheduler once."""

    inventory = InMemoryComputeInventory()
    for host in hosts:
        inventory.register_host(host)
    resources = resource_authority or InMemoryResourceLeaseRegistry()
    scheduler = bind_in_memory_compute_scheduler(
        inventory,
        resource_authority=resources,
        gpu_runtime_observer=gpu_runtime_observer,
        host_runtime_observer=host_runtime_observer,
    )
    return InMemoryComputeStack(inventory, resources, scheduler)


def compose_in_memory_compute_scheduler(
    hosts: Iterable[ComputeHost] = (),
    *,
    resource_authority: InMemoryResourceLeaseRegistry | None = None,
    gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
    host_runtime_observer: HostRuntimeObserverPort | None = None,
) -> ComputeSchedulerPort:
    """High-level research-facing recipe returning only the stable scheduler port."""

    return compose_in_memory_compute_stack(
        hosts,
        resource_authority=resource_authority,
        gpu_runtime_observer=gpu_runtime_observer,
        host_runtime_observer=host_runtime_observer,
    ).scheduler


__all__ = [
    "InMemoryComputeStack",
    "bind_in_memory_compute_scheduler",
    "compose_in_memory_compute_scheduler",
    "compose_in_memory_compute_stack",
]
