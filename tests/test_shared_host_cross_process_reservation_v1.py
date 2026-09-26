from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path
import time

from noetrium_platform.composition.shared_host_pressure import (
    ResourceCompetitionAdmissionGate,
    ResourceCompetitionDemand,
    ResourceCompetitionPolicy,
    ResourceCompetitionReservationLedger,
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


class _FixedHostObserver:
    def snapshot(self) -> HostRuntimeSnapshot:
        return HostRuntimeSnapshot(
            True,
            (
                HostRuntimeStatus(
                    "cross-process-host",
                    True,
                    effective_cpu_cores=8.0,
                    cpu_load_1m=0.0,
                    available_memory_bytes=100,
                    cpu_pressure_some_avg10_percent=0.0,
                    memory_pressure_some_avg10_percent=0.0,
                    io_pressure_some_avg10_percent=0.0,
                    available_pids=100,
                    available_fds=100,
                ),
            ),
        )


def _gate(directory: str) -> ResourceCompetitionAdmissionGate:
    admission = build_execution_admission(
        budget=AdmissionBudget(max_total_in_flight=1, max_waiting=2),
        scheduling=build_admission_scheduling_policy(
            priority_aging_seconds=0.01
        ),
    )
    gate = ResourceCompetitionAdmissionGate(
        admission,
        _FixedHostObserver(),
        policy=ResourceCompetitionPolicy(
            min_available_memory_bytes=0,
            min_available_pids=0,
            min_available_fds=0,
            min_storage_free_bytes=0,
            min_storage_free_inodes=0,
            min_storage_free_fraction=0.0,
        ),
        reservations=ResourceCompetitionReservationLedger(
            Path(directory)
        ),
    )
    gate.register_group(
        "g",
        identity=AdmissionIdentity(),
        intent=AdmissionIntent(queue_wait_timeout_seconds=0.0),
    )
    gate.set_group_demand(
        "g",
        ResourceCompetitionDemand(memory_bytes_per_permit=60),
    )
    return gate


def _race_worker(
    directory: str,
    barrier,
    release_event,
    results,
) -> None:
    gate = _gate(directory)
    barrier.wait(timeout=10.0)
    try:
        lease = gate.acquire(
            "g",
            ExecutionLaneKind.CPU,
            deadline=None,
            cancellation=None,
        )
    except AdmissionRejected:
        results.put("rejected")
        return
    results.put("admitted")
    release_event.wait(timeout=10.0)
    lease.release()


def _crash_worker(directory: str, marker: str) -> None:
    gate = _gate(directory)
    gate.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    Path(marker).write_text("admitted")
    os._exit(0)


def test_host_scoped_reservations_fence_parallel_processes(tmp_path) -> None:
    ctx = mp.get_context("spawn")
    directory = str(tmp_path / "authority")
    barrier = ctx.Barrier(2)
    release_event = ctx.Event()
    results = ctx.Queue()
    processes = tuple(
        ctx.Process(
            target=_race_worker,
            args=(directory, barrier, release_event, results),
        )
        for _ in range(2)
    )
    for process in processes:
        process.start()

    observed = sorted(results.get(timeout=15.0) for _ in range(2))
    assert observed == ["admitted", "rejected"]

    release_event.set()
    for process in processes:
        process.join(timeout=15.0)
        assert process.exitcode == 0


def test_host_scoped_reservation_is_reclaimed_after_process_crash(
    tmp_path,
) -> None:
    ctx = mp.get_context("spawn")
    directory = tmp_path / "authority"
    marker = tmp_path / "crash-admitted"
    process = ctx.Process(
        target=_crash_worker,
        args=(str(directory), str(marker)),
    )
    process.start()

    deadline = time.monotonic() + 15.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    process.join(timeout=15.0)
    assert process.exitcode == 0

    gate = _gate(str(directory))
    lease = gate.acquire(
        "g",
        ExecutionLaneKind.CPU,
        deadline=None,
        cancellation=None,
    )
    lease.release()

    assert tuple(directory.glob("owner-*.json")) == ()
