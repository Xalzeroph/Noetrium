from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.composition.shared_host_pressure import (
    LocalSharedNetworkPressureObserver,
    ResourceCompetitionAdmissionGate,
    ResourceCompetitionPolicy,
    SharedNetworkPressureStatus,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)
from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionRejected,
)
from noetrium_platform.research.execution.policy.composition import (
    build_admission_scheduling_policy,
    build_execution_admission,
)


class _HealthyHost:
    def snapshot(self) -> HostRuntimeSnapshot:
        return HostRuntimeSnapshot(
            True,
            (
                HostRuntimeStatus(
                    "shared-node",
                    True,
                    effective_cpu_cores=16.0,
                    cpu_load_1m=0.0,
                    available_memory_bytes=32 * 1024**3,
                    cpu_pressure_some_avg10_percent=0.0,
                    memory_pressure_some_avg10_percent=0.0,
                    io_pressure_some_avg10_percent=0.0,
                    available_pids=2048,
                    available_fds=4096,
                ),
            ),
        )


class _Network:
    def __init__(self, utilization: float | None) -> None:
        self.utilization = utilization

    def snapshot(self) -> SharedNetworkPressureStatus:
        return SharedNetworkPressureStatus(
            True,
            max_utilization_percent=self.utilization,
        )


def _gate(network: _Network) -> ResourceCompetitionAdmissionGate:
    base = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=8),
        scheduling=build_admission_scheduling_policy(priority_aging_seconds=0.01),
    )
    gate = ResourceCompetitionAdmissionGate(
        base,
        _HealthyHost(),
        network_observer=network,
        policy=ResourceCompetitionPolicy(
            min_available_memory_bytes=0,
            min_available_pids=0,
            min_available_fds=0,
            min_storage_free_bytes=0,
            min_storage_free_inodes=0,
            max_network_utilization_percent=80.0,
        ),
    )
    gate.register_group(
        "work",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    return gate


def test_network_saturation_gates_io_without_blocking_cpu_only_work() -> None:
    gate = _gate(_Network(95.0))

    cpu = gate.acquire(
        "work",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    cpu.release()

    with pytest.raises(AdmissionRejected, match="network-pressure"):
        gate.acquire(
            "work",
            ExecutionLaneKind.ASYNC_IO,
            deadline=None,
            cancellation=None,
        )


def test_unknown_link_capacity_fails_closed_for_new_io() -> None:
    gate = _gate(_Network(None))
    with pytest.raises(AdmissionRejected, match="network-runtime-unavailable"):
        gate.acquire(
            "work",
            ExecutionLaneKind.BLOCKING_IO,
            deadline=None,
            cancellation=None,
        )


def test_default_policy_does_not_yield_or_fail_closed_on_soft_link_telemetry() -> None:
    base = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=8),
        scheduling=build_admission_scheduling_policy(priority_aging_seconds=0.01),
    )
    gate = ResourceCompetitionAdmissionGate(
        base,
        _HealthyHost(),
        network_observer=_Network(None),
        policy=ResourceCompetitionPolicy(),
    )
    gate.register_group(
        "aggressive",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )

    lease = gate.acquire(
        "aggressive",
        ExecutionLaneKind.ASYNC_IO,
        deadline=None,
        cancellation=None,
    )
    lease.release()


def _netdev(rx_bytes: int, tx_bytes: int) -> str:
    return (
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|"
        "bytes    packets errs drop fifo colls carrier compressed\n"
        f"  eth0: {rx_bytes} 0 0 0 0 0 0 0 {tx_bytes} 0 0 0 0 0 0 0\n"
        "    lo: 999999999 0 0 0 0 0 0 0 999999999 0 0 0 0 0 0 0\n"
    )


def test_local_network_observer_measures_real_counter_delta_against_link_speed(
    tmp_path: Path,
) -> None:
    proc_net_dev = tmp_path / "net-dev"
    sys_class_net = tmp_path / "class-net"
    speed = sys_class_net / "eth0" / "speed"
    speed.parent.mkdir(parents=True)
    speed.write_text("100\n", encoding="utf-8")
    proc_net_dev.write_text(_netdev(0, 0), encoding="utf-8")

    now = [10.0]
    observer = LocalSharedNetworkPressureObserver(
        proc_net_dev=proc_net_dev,
        sys_class_net=sys_class_net,
        clock=lambda: now[0],
        minimum_sample_seconds=0.05,
    )

    warm = observer.snapshot()
    assert not warm.available
    assert warm.max_utilization_percent is None
    assert warm.detail == "network-pressure-warming"

    # 10 MB in one second on a 100 Mbit/s link is 80% utilization.
    proc_net_dev.write_text(_netdev(10_000_000, 0), encoding="utf-8")
    now[0] = 11.0
    measured = observer.snapshot()
    assert measured.available
    assert measured.max_utilization_percent == pytest.approx(80.0)
