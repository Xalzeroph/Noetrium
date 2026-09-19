import threading
import time

import pytest

from noetrium_platform.capabilities.model.serving.runtime import (
    ModelAdmissionClosed,
    ModelAdmissionController,
)
from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled


class _Cancellation:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return "test cancellation" if self.cancelled else None

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def checkpoint(self) -> None:
        if self.cancelled:
            raise TaskCancelled(self.reason or "cancelled")

    def cancel(self) -> None:
        self._event.set()


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not observed before timeout")


def test_waiter_can_be_cancelled_without_consuming_capacity() -> None:
    controller = ModelAdmissionController(1)
    first = controller.acquire()
    cancellation = _Cancellation()
    failure: list[BaseException] = []

    def wait() -> None:
        try:
            controller.acquire(cancellation=cancellation)
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=wait)
    thread.start()
    _wait_until(lambda: controller.snapshot().waiting == 1)
    cancellation.cancel()
    thread.join(1.0)

    assert not thread.is_alive()
    assert len(failure) == 1 and isinstance(failure[0], TaskCancelled)
    assert controller.snapshot().active == 1
    assert controller.snapshot().waiting == 0
    first.release()


def test_waiters_are_admitted_in_fifo_order() -> None:
    controller = ModelAdmissionController(1)
    blocker = controller.acquire()
    order: list[int] = []
    threads: list[threading.Thread] = []

    for index in range(3):
        # Use an explicit worker so lease release is deterministic.
        def worker(value=index) -> None:
            with controller.acquire(timeout_seconds=1.0):
                order.append(value)
        thread = threading.Thread(target=worker)
        thread.start()
        threads.append(thread)
        _wait_until(lambda expected=index + 1: controller.snapshot().waiting == expected)

    blocker.release()
    for thread in threads:
        thread.join(1.0)
        assert not thread.is_alive()

    assert order == [0, 1, 2]
    assert controller.snapshot().active == 0


def test_close_wakes_waiters_and_rejects_future_admission() -> None:
    controller = ModelAdmissionController(1)
    first = controller.acquire()
    failure: list[BaseException] = []

    def wait() -> None:
        try:
            controller.acquire()
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=wait)
    thread.start()
    _wait_until(lambda: controller.snapshot().waiting == 1)
    controller.close()
    thread.join(1.0)

    assert not thread.is_alive()
    assert len(failure) == 1 and isinstance(failure[0], ModelAdmissionClosed)
    with pytest.raises(ModelAdmissionClosed):
        controller.acquire()
    first.release()
    assert controller.snapshot().active == 0
    assert controller.closed is True


def test_admission_lease_release_is_thread_safe_and_idempotent() -> None:
    controller = ModelAdmissionController(1)
    lease = controller.acquire()
    barrier = threading.Barrier(3)
    failures: list[BaseException] = []

    def release() -> None:
        try:
            barrier.wait()
            lease.release()
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=release) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(1.0)

    assert failures == []
    assert controller.snapshot().active == 0
    lease.release()
    assert controller.snapshot().active == 0
