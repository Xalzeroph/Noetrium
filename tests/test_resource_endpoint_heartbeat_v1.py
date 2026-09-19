from __future__ import annotations

from dataclasses import replace
from threading import Event

import pytest

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocation,
    EndpointAllocationState,
    EndpointLeasePolicy,
    EndpointProtocol,
    NetworkEndpoint,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.resources.allocation.runtime import (
    EndpointLeaseHeartbeatError,
    EndpointLeaseHeartbeatGuard,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


class _RenewingAllocations:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.renewed = Event()
        self.calls = 0
        self.value = EndpointAllocation(
            allocation_id="a",
            endpoint=NetworkEndpoint("127.0.0.1", 25565, EndpointProtocol.TCP),
            lease_id="lease-a",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "a"),
            purpose="heartbeat",
            request_digest="d" * 64,
            lease_expires_at_epoch_s=100.0,
        )

    def renew(self, allocation_id: str, *, ttl_seconds: float | None = None) -> EndpointAllocation:
        return self.renew_many((allocation_id,), ttl_seconds=ttl_seconds)[0]

    def renew_many(self, allocation_ids: tuple[str, ...], *, ttl_seconds: float | None = None) -> tuple[EndpointAllocation, ...]:
        self.calls += 1
        self.renewed.set()
        if self.fail:
            raise RuntimeError("renew failed")
        return tuple(
            replace(
                self.value,
                allocation_id=allocation_id,
                lease_expires_at_epoch_s=(self.value.lease_expires_at_epoch_s or 0) + 1,
            )
            for allocation_id in allocation_ids
        )

    def allocate(self, request):  # pragma: no cover - not used
        return self.value

    def release(self, allocation_id: str):  # pragma: no cover - not used
        return replace(self.value, state=EndpointAllocationState.RELEASED)

    def get(self, allocation_id: str):  # pragma: no cover - not used
        return self.value

    def active(self):  # pragma: no cover - not used
        return (self.value,)


def _runtime():
    return build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            default_queue_capacity=8,
        ),
        blocking_io_thread_name_prefix="heartbeat-test-io",
        timer_name="heartbeat-test-timer",
    )


def test_endpoint_lease_heartbeat_renews_until_closed() -> None:
    allocations = _RenewingAllocations()
    runtime = _runtime()
    group = runtime.open_task_group("heartbeat-test")
    guard = EndpointLeaseHeartbeatGuard(
        allocations=allocations,
        allocation_ids=("a",),
        task_group=group,
        heartbeat_scheduler=runtime.heartbeats,
        lane_id="endpoint-lease-writer",
        lane_capacity=8,
        policy=EndpointLeasePolicy(ttl_seconds=0.2, renewal_interval_seconds=0.01),
    )
    try:
        guard.start()
        assert allocations.renewed.wait(timeout=1)
        guard.assert_healthy()
        guard.close()
        assert allocations.calls >= 1
        snapshot = runtime.topology_snapshot()
        assert snapshot.serial_lanes[0].owner_group_id == "heartbeat-test"
    finally:
        runtime.close()


def test_endpoint_lease_heartbeat_failure_is_fail_closed() -> None:
    allocations = _RenewingAllocations(fail=True)
    runtime = _runtime()
    group = runtime.open_task_group("heartbeat-failure-test")
    guard = EndpointLeaseHeartbeatGuard(
        allocations=allocations,
        allocation_ids=("a",),
        task_group=group,
        heartbeat_scheduler=runtime.heartbeats,
        lane_id="endpoint-lease-writer-failure",
        lane_capacity=8,
        policy=EndpointLeasePolicy(ttl_seconds=0.2, renewal_interval_seconds=0.01),
    )
    guard.start()
    assert allocations.renewed.wait(timeout=1)
    with pytest.raises(EndpointLeaseHeartbeatError, match="renew failed"):
        guard.assert_healthy()
    with pytest.raises(EndpointLeaseHeartbeatError, match="renew failed"):
        guard.close()
    with pytest.raises(ExceptionGroup):
        runtime.close()
