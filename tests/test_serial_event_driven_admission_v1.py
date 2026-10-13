"""Serial mailbox capacity is one event-driven provider-owned fact."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskCancelled
from noetrium_platform.foundation.kernel.concurrency.providers.serial_lane import (
    SharedSerialExecutionLaneFactory,
)
from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import (
    _CancellationState,
)


class _ObservedCancellation(_CancellationState):
    def __init__(self) -> None:
        super().__init__()
        self.subscribed = Event()

    def subscribe_cancel(self, callback):
        unsubscribe = super().subscribe_cancel(callback)
        self.subscribed.set()
        return unsubscribe


def _saturated_lane():
    factory = SharedSerialExecutionLaneFactory(
        max_workers=1, shutdown_timeout_seconds=2.0,
    )
    lane = factory.create("shared-state", capacity=1)
    running = Event()
    release = Event()

    def block():
        running.set()
        assert release.wait(2.0)
        return "first"

    first = lane.submit(block)
    assert running.wait(1.0)
    second = lane.submit(lambda: "second")
    assert lane.topology_snapshot(owner_group_id="owner", closed=False).queued_work_items == 1
    return factory, lane, first, second, release


def test_cancelled_mailbox_wait_is_woken_by_subscription_not_a_retry_timer():
    factory, lane, first, second, release = _saturated_lane()
    token = _ObservedCancellation()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                lane.submit, lambda: "unexpected",
                deadline=Deadline.after(5.0), cancellation=token,
            )
            assert token.subscribed.wait(1.0)
            assert token.cancel("research owner cancelled")
            with pytest.raises(TaskCancelled, match="research owner cancelled"):
                pending.result(timeout=1.0)
        assert lane.topology_snapshot(owner_group_id="owner", closed=False).queued_work_items == 1
    finally:
        release.set()
        factory.close(deadline=Deadline.after(2.0))
    assert first.result(timeout=1.0) == "first"
    assert second.result(timeout=1.0) == "second"


def test_mailbox_wait_wakes_on_dequeue_without_a_timer():
    factory, lane, first, second, release = _saturated_lane()
    token = _ObservedCancellation()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                lane.submit, lambda: "third",
                deadline=Deadline.after(5.0), cancellation=token,
            )
            assert token.subscribed.wait(1.0)
            release.set()
            third = pending.result(timeout=2.0)
        assert third.result(timeout=2.0) == "third"
    finally:
        release.set()
        factory.close(deadline=Deadline.after(2.0))
    assert first.result(timeout=1.0) == "first"
    assert second.result(timeout=1.0) == "second"
