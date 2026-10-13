"""One event-driven ASYNC_IO capacity authority, including close-race rollback."""
from __future__ import annotations

import asyncio
from threading import Event, Thread
import time

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled
from noetrium_platform.foundation.kernel.concurrency.providers import AsyncIoExecutor
from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import _CancellationState


def test_capacity_cancellation_wakes_async_waiter_without_polling(monkeypatch) -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    started = Event()
    release = asyncio.Event()

    async def long_task() -> int:
        started.set()
        await release.wait()
        return 5

    first = executor.submit(long_task)
    assert started.wait(2)
    token = _CancellationState()
    entered = Event()
    waits: list[float | None] = []
    wait_fn = executor._condition.wait

    def observed_wait(timeout=None):
        waits.append(timeout)
        entered.set()
        return wait_fn(timeout)

    monkeypatch.setattr(executor._condition, "wait", observed_wait)
    errors: list[BaseException] = []

    def contender() -> None:
        try:
            executor.submit(lambda: asyncio.sleep(0), cancellation=token)
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=contender, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        time.sleep(0.16)
        assert waits == [None]
        token.cancel("cancelled while ASYNC_IO capacity occupied")
        thread.join(1)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], TaskCancelled)
    finally:
        executor._loop.call_soon_threadsafe(release.set)
        assert first.result(3) == 5
        executor.close()


def test_release_wakes_queued_async_batch_submission() -> None:
    executor = AsyncIoExecutor(max_in_flight=2)
    started = Event()
    release = asyncio.Event()
    done = Event()
    results: list[int] = []
    failures: list[BaseException] = []

    async def hold() -> int:
        started.set()
        await release.wait()
        return 3

    first = executor.submit_atomic_batch((hold, hold))
    assert started.wait(2)

    def contender() -> None:
        try:
            future = executor.submit(lambda: asyncio.sleep(0, result=7))
            results.append(future.result(timeout=3))
            done.set()
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=contender, daemon=True)
    thread.start()
    try:
        time.sleep(0.06)
        executor._loop.call_soon_threadsafe(release.set)
        assert done.wait(2)
        assert results == [7] and failures == []
    finally:
        executor._loop.call_soon_threadsafe(release.set)
        thread.join(3)
        for future in first:
            assert future.result(3) == 3
        executor.close()


@pytest.mark.parametrize("operation", ("single", "try-single", "batch"))
def test_close_race_returns_every_reserved_async_slot(monkeypatch, operation: str) -> None:
    executor = AsyncIoExecutor(max_in_flight=2)
    ensure = executor._ensure_started
    visits = 0

    def close_after_second_start_check():
        nonlocal visits
        loop = ensure()
        visits += 1
        if visits == 2:
            with executor._condition:
                executor._closed = True
                executor._condition.notify_all()
        return loop

    monkeypatch.setattr(executor, "_ensure_started", close_after_second_start_check)
    try:
        with pytest.raises(RuntimeError, match="closed"):
            if operation == "single":
                executor.submit(lambda: asyncio.sleep(0))
            elif operation == "try-single":
                executor.try_submit(lambda: asyncio.sleep(0))
            else:
                executor.submit_atomic_batch((
                    lambda: asyncio.sleep(0),
                    lambda: asyncio.sleep(0),
                ))
        assert executor._available == 2
        assert executor._futures == set()
    finally:
        with executor._condition:
            executor._closed = False
        executor.close()


def test_uncontended_async_submission_avoids_cancel_registration(monkeypatch) -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    token = _CancellationState()
    def forbid(_callback):
        raise AssertionError("no capacity wait should need subscription")
    monkeypatch.setattr(token, "subscribe_cancel", forbid)
    try:
        future = executor.submit(lambda: asyncio.sleep(0, result=11), cancellation=token)
        assert future.result(3) == 11
    finally:
        executor.close()


def test_async_physical_join_timeout_is_distinct_from_child_timeout() -> None:
    from noetrium_platform.foundation.kernel.concurrency.api import PhysicalJoinTimeout

    executor = AsyncIoExecutor(max_in_flight=1)
    release = asyncio.Event()
    started = Event()

    async def fail() -> int:
        raise TimeoutError("child-owned network timeout")

    async def wait() -> int:
        started.set()
        await release.wait()
        return 9

    try:
        child = executor.submit(fail)
        with pytest.raises(TimeoutError, match="child-owned network timeout") as raised:
            child.result(2)
        assert not isinstance(raised.value, PhysicalJoinTimeout)

        physically_waiting = executor.submit(wait)
        assert started.wait(2)
        with pytest.raises(PhysicalJoinTimeout):
            physically_waiting.result(0.02)
        assert not physically_waiting.done()
        executor._loop.call_soon_threadsafe(release.set)
        assert physically_waiting.result(3) == 9
    finally:
        executor._loop.call_soon_threadsafe(release.set)
        executor.close()


def test_async_physical_release_failure_is_visible_after_successful_source(monkeypatch) -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    release = executor._release

    def broken_release(handle) -> None:
        release(handle)
        raise RuntimeError("injected physical release verification failure")

    monkeypatch.setattr(executor, "_release", broken_release)
    try:
        result = executor.submit(lambda: asyncio.sleep(0, result=31))
        with pytest.raises(RuntimeError, match="physical release verification"):
            result.result(timeout=2)
        assert result.done()
        assert executor._available == 1
    finally:
        executor.close()


def test_async_source_and_physical_release_failures_are_both_evidenced(monkeypatch) -> None:
    executor = AsyncIoExecutor(max_in_flight=1)
    release = executor._release

    def broken_release(handle) -> None:
        release(handle)
        raise RuntimeError("physical release failed")

    monkeypatch.setattr(executor, "_release", broken_release)

    async def source_failure():
        raise ValueError("physical source failed")

    try:
        result = executor.submit(source_failure)
        with pytest.raises(BaseExceptionGroup) as raised:
            result.result(timeout=2)
        assert {type(exc) for exc in raised.value.exceptions} == {
            ValueError, RuntimeError,
        }
        assert result.done()
        assert executor._available == 1
    finally:
        executor.close()


@pytest.mark.parametrize("operation", ("single", "try-single", "batch"))
def test_close_between_async_reservation_and_dispatch_returns_slots(
    monkeypatch, operation: str,
) -> None:
    executor = AsyncIoExecutor(max_in_flight=2)
    original = executor._cancelled
    close_requested = False

    def close_at_dispatch(cancellation):
        nonlocal close_requested
        if not close_requested and executor._available < executor._max_in_flight:
            close_requested = True
            executor.close(wait=False)
        return original(cancellation)

    monkeypatch.setattr(executor, "_cancelled", close_at_dispatch)
    try:
        with pytest.raises(RuntimeError, match="closed"):
            if operation == "single":
                executor.submit(lambda: asyncio.sleep(0))
            elif operation == "try-single":
                executor.try_submit(lambda: asyncio.sleep(0))
            else:
                executor.submit_atomic_batch((
                    lambda: asyncio.sleep(0),
                    lambda: asyncio.sleep(0),
                ))
        assert close_requested
        assert executor._available == executor._max_in_flight
        assert executor._futures == set()
    finally:
        executor.close(wait=True)
