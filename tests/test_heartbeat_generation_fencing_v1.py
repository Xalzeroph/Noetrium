from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    HeartbeatSpec,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)


def _runtime():
    return build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=8,
        ),
        blocking_io_thread_name_prefix="heartbeat-generation-test",
        timer_name="heartbeat-generation-test-timer",
    )


def test_heartbeat_logical_id_rejects_concurrent_owner() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("heartbeat-generation-owner")
    spec = HeartbeatSpec(
        heartbeat_id="lease:a",
        lane_id="lease-writer",
        interval_seconds=10.0,
    )
    first = runtime.heartbeats.register(group.group_id, spec, lambda _context: None)
    try:
        with pytest.raises(ValueError, match="already actively owned"):
            runtime.heartbeats.register(group.group_id, spec, lambda _context: None)
    finally:
        first.cancel()
        runtime.close()


def test_heartbeat_generation_reuse_fences_stale_handle() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("heartbeat-generation-reuse")
    spec = HeartbeatSpec(
        heartbeat_id="lease:a",
        lane_id="lease-writer",
        interval_seconds=10.0,
    )
    first = runtime.heartbeats.register(group.group_id, spec, lambda _context: None)
    first.cancel()

    second = runtime.heartbeats.register(group.group_id, spec, lambda _context: None)
    try:
        first.cancel()
        with pytest.raises(RuntimeError, match="stale heartbeat generation"):
            first.assert_healthy()
        second.assert_healthy()
        rows = runtime.topology_snapshot().heartbeats
        assert len(rows) == 1
        assert rows[0].heartbeat_id == "lease:a"
        assert rows[0].active is True
    finally:
        second.cancel()
        runtime.close()
