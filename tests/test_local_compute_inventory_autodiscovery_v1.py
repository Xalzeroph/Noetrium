from __future__ import annotations

from dataclasses import replace

from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeDeviceHealth,
    ComputeHostSchedulingState,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
)
from noetrium_platform.infrastructure.resources.compute.runtime import InMemoryComputeInventory
from noetrium_platform.infrastructure.resources.compute.composition import (
    discover_local_compute_host,
    reconcile_local_compute_host,
)


class FakeGpuObserver:
    def snapshot(self) -> GpuRuntimeSnapshot:
        return GpuRuntimeSnapshot(
            True,
            devices=(
                GpuDeviceStatus("1", "GPU-b", "RTX", 49140, 0, 49140, 0),
                GpuDeviceStatus("0", "GPU-a", "RTX", 49140, 0, 49140, 0),
            ),
        )


def test_local_compute_inventory_uses_stable_gpu_uuid_and_auto_capacity() -> None:
    host = discover_local_compute_host(
        gpu_runtime_observer=FakeGpuObserver(),
        host_id="node-test",
    )

    assert host.host_id == "node-test"
    assert host.cpu_cores >= 1
    assert host.memory_bytes >= 1
    assert tuple(row.gpu_id for row in host.gpus) == ("GPU-a", "GPU-b")
    assert tuple(dict(row.labels)["runtime_index"] for row in host.gpus) == ("0", "1")
    assert all(row.memory_bytes == 49140 * 1024 * 1024 for row in host.gpus)


def test_local_compute_inventory_fails_closed_when_gpu_inventory_unavailable() -> None:
    class Missing:
        def snapshot(self) -> GpuRuntimeSnapshot:
            return GpuRuntimeSnapshot(False, detail="nvidia-smi missing")

    try:
        discover_local_compute_host(
            gpu_runtime_observer=Missing(),
            host_id="node-test",
        )
    except RuntimeError as exc:
        assert "nvidia-smi missing" in str(exc)
    else:
        raise AssertionError("expected unavailable GPU inventory to fail closed")



def test_local_compute_fingerprint_refresh_preserves_operator_policy() -> None:
    class MutableGpuObserver:
        def __init__(self) -> None:
            self.index = "0"

        def snapshot(self) -> GpuRuntimeSnapshot:
            return GpuRuntimeSnapshot(
                True,
                devices=(
                    GpuDeviceStatus(
                        self.index,
                        "GPU-stable",
                        "RTX",
                        49140,
                        0,
                        49140,
                        0,
                    ),
                ),
            )

    observer = MutableGpuObserver()
    inventory = InMemoryComputeInventory()
    discovered = discover_local_compute_host(
        gpu_runtime_observer=observer,
        host_id="node-refresh",
    )
    inventory.register_host(discovered)

    gpu = discovered.gpus[0]
    configured = replace(
        discovered,
        gpus=(
            replace(
                gpu,
                labels=tuple(sorted((*gpu.labels, ("operator-domain", "rack-a")))),
                health=ComputeDeviceHealth.DEGRADED,
                reserved_memory_bytes=1024,
            ),
        ),
        labels=tuple(sorted((*discovered.labels, ("operator-policy", "keep")))),
        scheduling_state=ComputeHostSchedulingState.DRAINING,
    )
    inventory.replace_host(discovered, configured)

    observer.index = "7"
    refreshed = reconcile_local_compute_host(
        inventory=inventory,
        gpu_runtime_observer=observer,
        host_id="node-refresh",
    )

    assert refreshed.scheduling_state is ComputeHostSchedulingState.DRAINING
    assert dict(refreshed.labels)["operator-policy"] == "keep"
    assert refreshed.gpus[0].gpu_id == "GPU-stable"
    assert refreshed.gpus[0].health is ComputeDeviceHealth.DEGRADED
    assert refreshed.gpus[0].reserved_memory_bytes == 1024
    assert dict(refreshed.gpus[0].labels)["operator-domain"] == "rack-a"
    assert dict(refreshed.gpus[0].labels)["runtime_index"] == "7"
