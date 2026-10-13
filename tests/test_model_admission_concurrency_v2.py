from model_admission_test_support import make_model_admission_controller

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
        self._lock = threading.Lock()
        self._listeners = []

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

    def subscribe_cancel(self, callback):
        with self._lock:
            if self._event.is_set():
                already_cancelled = True
            else:
                already_cancelled = False
                self._listeners.append(callback)
        if already_cancelled:
            callback()
        def unsubscribe():
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)
        return unsubscribe

    def cancel(self) -> None:
        with self._lock:
            self._event.set()
            listeners = tuple(self._listeners)
            self._listeners.clear()
        for callback in listeners:
            callback()


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not observed before timeout")


def test_waiter_can_be_cancelled_without_consuming_capacity() -> None:
    controller = make_model_admission_controller(1)
    # A blocked request must wake on cancellation, not on the fallback poll.
    controller._CROSS_PROCESS_RECHECK_SECONDS = 30.0
    first = controller.acquire()
    cancellation = _Cancellation()
    failure: list[BaseException] = []

    def wait() -> None:
        try:
            controller.acquire(cancellation=cancellation)
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    _wait_until(lambda: controller.snapshot().waiting == 1)
    cancellation.cancel()
    thread.join(1.0)

    assert not thread.is_alive()
    assert len(failure) == 1 and isinstance(failure[0], TaskCancelled)
    assert controller.snapshot().active == 1
    assert controller.snapshot().waiting == 0
    first.release()


def test_waiters_all_make_progress_without_over_admission() -> None:
    controller = make_model_admission_controller(1)
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

    assert sorted(order) == [0, 1, 2]
    assert controller.snapshot().active == 0


def test_close_fails_closed_with_live_claim_and_rejects_after_convergence() -> None:
    controller = make_model_admission_controller(1)
    first = controller.acquire()

    with pytest.raises(RuntimeError, match="claims remain"):
        controller.close()

    assert controller.closed is False
    first.release()
    controller.close()

    assert controller.closed is True
    with pytest.raises(ModelAdmissionClosed):
        controller.acquire(timeout_seconds=0.0)


def test_admission_lease_release_is_thread_safe_and_idempotent() -> None:
    controller = make_model_admission_controller(1)
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
