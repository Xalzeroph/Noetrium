from __future__ import annotations

import pytest
import time

from noetrium_platform.infrastructure.resources.authority.runtime.heartbeat import (
    LeaseHeartbeatError,
    LeaseHeartbeatFactory,
)


class _Group:
    group_id = "heartbeat-recovery-test"


class _Scheduled:
    task_id = "heartbeat-recovery"
    def __init__(self) -> None:
        self.cancelled = False
    def cancel(self) -> None:
        self.cancelled = True
    def assert_healthy(self) -> None:
        return None


class _Scheduler:
    def __init__(self) -> None:
        self.fn = None
        self.handle = _Scheduled()
    def register(self, _owner_group_id, _spec, fn, /, *args, **kwargs):
        assert not args
        assert kwargs.get("deadline") is None
        self.fn = fn
        return self.handle
    def assert_healthy(self) -> None:
        return None
    def snapshot(self):
        return ()


class _Context:
    cancelled = False
    reason = None
    deadline = None
    remaining_seconds = None
    group_id = "heartbeat-recovery-test"
    task_id = "heartbeat-recovery"
    lane_kind = None
    def wait(self, _timeout=None) -> bool:
        return False
    def checkpoint(self) -> None:
        return None


def test_transient_renewal_failure_recovers_without_retiring_member() -> None:
    scheduler = _Scheduler()
    calls = 0

    def renew(rows: tuple[str, ...]) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transient authority storage interruption")
        return rows

    factory = LeaseHeartbeatFactory(
        renew=renew,
        row_identity=lambda row: row,
        heartbeat_namespace="resource:test",
        task_group=_Group(),
        heartbeat_scheduler=scheduler,
        lane_id="resource-lease-writer",
        interval_seconds=30.0,
        policy=object(),
    )
    guard = factory.create(("lease:a",))
    guard.start()
    assert scheduler.fn is not None

    scheduler.fn(_Context())
    with pytest.raises(LeaseHeartbeatError, match="member renewal failed"):
        guard.assert_healthy()
    assert factory.active_member_count == 1

    scheduler.fn(_Context())
    guard.assert_healthy()
    assert factory.active_member_count == 1

    guard.close()
    factory.close()


def test_persistent_renewal_failure_remains_fail_closed_and_retryable() -> None:
    scheduler = _Scheduler()
    calls = 0

    def renew(rows: tuple[str, ...]) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        raise RuntimeError("generation fenced")

    factory = LeaseHeartbeatFactory(
        renew=renew,
        row_identity=lambda row: row,
        heartbeat_namespace="resource:test",
        task_group=_Group(),
        heartbeat_scheduler=scheduler,
        lane_id="resource-lease-writer",
        interval_seconds=30.0,
        policy=object(),
    )
    guard = factory.create(("lease:a",))
    guard.start()
    assert scheduler.fn is not None

    scheduler.fn(_Context())
    with pytest.raises(LeaseHeartbeatError, match="generation fenced"):
        guard.assert_healthy()
    scheduler.fn(_Context())
    with pytest.raises(LeaseHeartbeatError, match="generation fenced"):
        guard.assert_healthy()
    assert calls == 2
    assert factory.active_member_count == 1

    guard.close()
    factory.close()


def test_expired_authority_row_fails_closed_even_when_scheduler_is_healthy() -> None:
    scheduler = _Scheduler()
    now = time.time()
    factory = LeaseHeartbeatFactory(
        renew=lambda rows: rows,
        row_identity=lambda row: row[0],
        row_expiry_epoch_s=lambda row: row[1],
        heartbeat_namespace="resource:expiry-test",
        task_group=_Group(),
        heartbeat_scheduler=scheduler,
        lane_id="resource-lease-writer",
        interval_seconds=30.0,
        policy=object(),
    )
    future = factory.create((("lease:future", now + 60.0),))
    future.start()
    future.assert_healthy()
    future.close()
    expired = factory.create((("lease:expired", now - 0.001),))
    expired.start()
    with pytest.raises(LeaseHeartbeatError, match="authority expired"):
        expired.assert_healthy()
    expired.close()
    factory.close()



def test_closed_guard_retains_final_authoritative_rows_for_idempotent_cleanup() -> None:
    scheduler = _Scheduler()
    renew_count = 0

    def renew(rows):
        nonlocal renew_count
        renew_count += 1
        return tuple((row[0], row[1] + 1) for row in rows)

    factory = LeaseHeartbeatFactory(
        renew=renew,
        row_identity=lambda row: row[0],
        heartbeat_namespace="resource:closed-row-test",
        task_group=_Group(),
        heartbeat_scheduler=scheduler,
        lane_id="resource-lease-writer",
        interval_seconds=30.0,
        policy=object(),
    )
    guard = factory.create((("lease:a", 1),))
    guard.start()
    assert scheduler.fn is not None
    scheduler.fn(_Context())
    assert guard.handles == (("lease:a", 2),)

    guard.close()
    assert guard.handles == (("lease:a", 2),)
    # Repeated cleanup must preserve the final row without consulting a member
    # that the coordinator has intentionally removed from its live workset.
    guard.close()
    assert guard.handles == (("lease:a", 2),)
    assert factory.active_member_count == 0
    factory.close()

def test_closed_guard_is_removed_from_live_member_workset() -> None:
    scheduler = _Scheduler()
    factory = LeaseHeartbeatFactory(
        renew=lambda rows: rows,
        row_identity=lambda row: row,
        heartbeat_namespace="resource:live-workset-test",
        task_group=_Group(),
        heartbeat_scheduler=scheduler,
        lane_id="resource-lease-writer",
        interval_seconds=30.0,
        policy=object(),
    )
    never_started = factory.create(("lease:never-started",))
    never_started.close()

    started = factory.create(("lease:started",))
    started.start()
    assert factory.active_member_count == 1
    started.close()
    assert factory.active_member_count == 0
    assert factory.active_member_identities == ()
    # Closed members are no longer retained as a hidden historical registry.
    assert factory._coordinator._rows_by_member == {}
    factory.close()
