from __future__ import annotations

import os
from pathlib import Path

import pytest

from noetrium_platform.composition.concurrency import (
    build_execution_concurrency_runtime,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)


class _HealthySharedHostObserver:
    def snapshot(self) -> HostRuntimeSnapshot:
        return HostRuntimeSnapshot(
            True,
            (
                HostRuntimeStatus(
                    "shared-node",
                    True,
                    effective_cpu_cores=64.0,
                    cpu_load_1m=0.0,
                    available_memory_bytes=64 * 1024**3,
                    cpu_pressure_some_avg10_percent=0.0,
                    memory_pressure_some_avg10_percent=0.0,
                    io_pressure_some_avg10_percent=0.0,
                    available_pids=4096,
                ),
            ),
        )


def _cpu_worker_priority() -> tuple[int, int]:
    nice = os.getpriority(os.PRIO_PROCESS, 0)
    oom = int(Path("/proc/self/oom_score_adj").read_text("utf-8").strip())
    return int(nice), oom


@pytest.mark.skipif(
    os.name != "posix" or not Path("/proc/self/oom_score_adj").is_file(),
    reason="Linux/POSIX cooperative worker priority proof",
)
def test_shared_host_cpu_worker_yields_without_capping_idle_capacity() -> None:
    runtime = build_execution_concurrency_runtime(
        concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_blocking_io_in_flight=2,
            max_async_io_in_flight=2,
            max_cpu_workers=1,
            max_cpu_in_flight=1,
            max_serial_workers=1,
        ),
        host_runtime_observer=_HealthySharedHostObserver(),
    )
    group = runtime.open_task_group(
        "shared-host-cpu-worker-priority",
        resource_id="shared-host-cpu-worker-priority",
    )
    try:
        handle = group.submit(
            ExecutionSpec(
                task_id="observe-worker-priority",
                lane_kind=ExecutionLaneKind.CPU,
            ),
            _cpu_worker_priority,
        )
        nice, oom_score_adj = handle.result(timeout=15.0)
        assert nice >= 5
        assert oom_score_adj >= 500
    finally:
        runtime.close_task_group(group, cancel_pending=True)
        runtime.close()
