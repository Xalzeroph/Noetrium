from threading import Thread
import time

from noetrium_platform.research.execution.policy.api import AdmissionBudget, AdmissionIdentity
from noetrium_platform.research.execution.policy.runtime import HierarchicalAdmissionAuthority
from noetrium_platform.research.execution.policy.runtime import FairPrioritySchedulingPolicy
from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ExecutionLaneKind


class _CountingAdmissionAuthority(HierarchicalAdmissionAuthority):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.can_admit_calls = 0

    def _can_admit(self, group_id, lane_kind, permit_count=1):
        self.can_admit_calls += 1
        return super()._can_admit(group_id, lane_kind, permit_count)


def test_selection_cache_avoids_repeated_full_scan_inside_poll_bucket():
    authority = _CountingAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=32, max_in_flight_per_group=1),
        scheduling=FairPrioritySchedulingPolicy(priority_aging_seconds=1.0),
    )
    authority.register_group("group", identity=AdmissionIdentity())
    blocker = authority.acquire("group", ExecutionLaneKind.BLOCKING_IO, deadline=None, cancellation=None)
    errors: list[BaseException] = []

    def wait_once() -> None:
        try:
            lease = authority.acquire(
                "group", ExecutionLaneKind.BLOCKING_IO,
                deadline=Deadline.after(2.0), cancellation=None,
            )
            lease.release()
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=wait_once) for _ in range(20)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and authority.snapshot().waiting != len(threads):
        time.sleep(0.002)
    assert authority.snapshot().waiting == len(threads)

    with authority._condition:
        authority.can_admit_calls = 0
        for _ in range(100):
            authority._selected_waiter()
        assert authority.can_admit_calls <= len(threads) * 2

        # Lazy ordering-key refreshes must remain bounded by the number of
        # currently live scheduling shapes, not by historical grant/release
        # count.
        waiter = next(iter(authority._waiters.values()))
        for _ in range(1000):
            authority._push_waiter_order(waiter, time.monotonic())
        assert len(authority._selection_heap) > 64
        authority._selected_waiter()
        assert len(authority._selection_heap) <= max(
            64, len(authority._waiters_by_shape) * 4
        )

    blocker.release()
    for thread in threads:
        thread.join(2.0)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert authority.snapshot().waiting == 0
    assert authority.snapshot().in_flight == 0
    authority.close()
