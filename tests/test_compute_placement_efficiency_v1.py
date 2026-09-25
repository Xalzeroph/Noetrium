from __future__ import annotations

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputeRequirement,
)
from noetrium_platform.infrastructure.resources.compute.runtime import (
    InMemoryComputeInventory,
    SQLiteComputeScheduler,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock
from tests.resource_compute_support import (
    idle_gpu_runtime_observer,
    in_memory_compute_scheduler,
)


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.PROJECT, "placement-project")


def test_cpu_only_work_preserves_accelerator_hosts() -> None:
    scope = _scope()
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost(
        "a-gpu", scope, 32, 256,
        gpus=(ComputeGPU("gpu-0", 80, "H100"),),
    ))
    inventory.register_host(ComputeHost("z-cpu", scope, 32, 256))
    scheduler = in_memory_compute_scheduler(inventory)
    allocation = scheduler.allocate(
        "cpu-only", scope, ComputeRequirement(cpu_cores=4, memory_bytes=16)
    )
    assert allocation.host_id == "z-cpu"
    assert allocation.gpu_ids == ()


def test_gpu_work_uses_smallest_sufficient_device() -> None:
    scope = _scope()
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost(
        "gpu-host", scope, 32, 256,
        gpus=(
            ComputeGPU("gpu-large", 80, "H100"),
            ComputeGPU("gpu-small", 48, "L40S"),
        ),
    ))
    scheduler = in_memory_compute_scheduler(
        inventory,
        gpu_runtime_observer=idle_gpu_runtime_observer(
            "gpu-large",
            "gpu-small",
        ),
    )
    allocation = scheduler.allocate(
        "gpu-fit",
        scope,
        ComputeRequirement(
            cpu_cores=4, memory_bytes=16, gpu_count=1,
            minimum_gpu_memory_bytes=40,
        ),
    )
    assert allocation.gpu_ids == ("gpu-small",)


def test_best_fit_packs_cpu_memory_before_spreading() -> None:
    scope = _scope()
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("a-large", scope, 64, 256))
    inventory.register_host(ComputeHost("z-tight", scope, 8, 32))
    scheduler = in_memory_compute_scheduler(inventory)
    allocation = scheduler.allocate(
        "best-fit", scope, ComputeRequirement(cpu_cores=4, memory_bytes=16)
    )
    assert allocation.host_id == "z-tight"


def test_sqlite_scheduler_uses_same_gpu_best_fit_policy(tmp_path) -> None:
    scope = _scope()
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost(
        "gpu-host", scope, 32, 256,
        gpus=(
            ComputeGPU("gpu-large", 80, "H100"),
            ComputeGPU("gpu-small", 48, "L40S"),
        ),
    ))
    scheduler = SQLiteComputeScheduler(
        tmp_path / "compute.sqlite3",
        inventory,
        clock=ManualLeaseClock(
            elapsed_seconds=1.0,
            wall_epoch_seconds=100.0,
        ),
        gpu_runtime_observer=idle_gpu_runtime_observer(
            "gpu-large",
            "gpu-small",
        ),
    )
    allocation = scheduler.allocate(
        "gpu-fit",
        scope,
        ComputeRequirement(
            cpu_cores=4, memory_bytes=16, gpu_count=1,
            minimum_gpu_memory_bytes=40,
        ),
    )
    assert allocation.gpu_ids == ("gpu-small",)



def test_exact_host_allow_and_deny_constraints_override_best_fit() -> None:
    scope = _scope()
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("a-tight", scope, 8, 32))
    inventory.register_host(ComputeHost("z-large", scope, 64, 256))
    scheduler = in_memory_compute_scheduler(inventory)

    allowed = scheduler.allocate(
        "allowed-host",
        scope,
        ComputeRequirement(
            cpu_cores=4,
            memory_bytes=16,
            allowed_host_ids=("z-large",),
        ),
    )
    assert allowed.host_id == "z-large"

    forbidden = scheduler.allocate(
        "forbidden-host",
        scope,
        ComputeRequirement(
            cpu_cores=2,
            memory_bytes=8,
            forbidden_host_ids=("a-tight",),
        ),
    )
    assert forbidden.host_id == "z-large"
