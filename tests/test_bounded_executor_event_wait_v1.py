"""Executor capacity waits use observable transitions rather than timer polling."""
from __future__ import annotations

from threading import Event, Thread
import time

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskCancelled
from noetrium_platform.foundation.kernel.concurrency.providers import BoundedThreadExecutor
from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import _CancellationState


def _occupied():
    executor = BoundedThreadExecutor(
        max_workers=1, max_in_flight=1, thread_name_prefix="event-capacity-test",
    )
    release = Event()
    running = Event()

    def block():
        running.set()
        assert release.wait(5)
        return "first"

    first = executor.submit(block)
    assert running.wait(1)
    return executor, first, release


def test_cancelled_capacity_wait_has_no_periodic_rechecks(monkeypatch) -> None:
    executor, first, release = _occupied()
    cancellation = _CancellationState()
    entered = Event()
    calls: list[float | None] = []
    original_wait = executor._condition.wait

    def observe(timeout=None):
        calls.append(timeout)
        entered.set()
        return original_wait(timeout)

    monkeypatch.setattr(executor._condition, "wait", observe)
    failures: list[BaseException] = []

    def contender() -> None:
        try:
            executor.submit(lambda: "second", cancellation=cancellation)
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=contender, daemon=True)
    thread.start()
    try:
        assert entered.wait(1)
        time.sleep(0.18)
        assert calls == [None]
        cancellation.cancel("cancelled while waiting for physical capacity")
        thread.join(timeout=0.6)
        assert not thread.is_alive()
        assert len(failures) == 1
        assert isinstance(failures[0], TaskCancelled)
    finally:
        release.set()
        first.result(2)
        executor.close()


def test_physical_capacity_release_wakes_pending_submit_immediately() -> None:
    executor, first, release = _occupied()
    completed = Event()
    failures: list[BaseException] = []
    results = []

    def contender() -> None:
        try:
            value = executor.submit(lambda: "second")
            results.append(value.result(2))
            completed.set()
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=contender, daemon=True)
    thread.start()
    try:
        time.sleep(0.08)
        release.set()
        assert completed.wait(1.0)
        assert results == ["second"]
        assert not failures
    finally:
        release.set()
        first.result(2)
        thread.join(2)
        executor.close()


def test_capacity_deadline_waits_for_remaining_time_not_poll_interval(monkeypatch) -> None:
    executor, first, release = _occupied()
    calls: list[float | None] = []
    original_wait = executor._condition.wait

    def observe(timeout=None):
        calls.append(timeout)
        return original_wait(timeout)

    monkeypatch.setattr(executor._condition, "wait", observe)
    try:
        with pytest.raises(TimeoutError, match="capacity wait deadline"):
            executor.submit(lambda: "never", deadline=Deadline.after(0.14))
        assert len(calls) == 1
        assert 0.08 < calls[0] <= 0.14
    finally:
        release.set()
        first.result(2)
        executor.close()


def test_uncontended_submission_has_no_cancellation_listener_overhead(monkeypatch) -> None:
    executor = BoundedThreadExecutor(
        max_workers=1, max_in_flight=1,
        thread_name_prefix="no-registration-on-fast-path",
    )
    cancellation = _CancellationState()

    def forbid_subscription(_callback):
        raise AssertionError("uncontended admission unexpectedly subscribed to cancellation")

    monkeypatch.setattr(cancellation, "subscribe_cancel", forbid_subscription)
    try:
        assert executor.submit(lambda: 17, cancellation=cancellation).result(2) == 17
    finally:
        executor.close()
