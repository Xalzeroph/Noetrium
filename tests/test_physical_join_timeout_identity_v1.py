"""Physical join deadlines are never classified by a racy done() sample."""
from __future__ import annotations

from concurrent.futures import Future
from threading import Event, Thread

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import PhysicalJoinTimeout
from noetrium_platform.foundation.kernel.concurrency.providers.executors import _FutureHandle
from noetrium_platform.foundation.kernel.concurrency.runtime.execution import _CompletionFencedHandle


def test_child_raised_timeout_is_the_original_exception() -> None:
    future: Future[int] = Future()
    failure = TimeoutError("child provider deadline")
    future.set_exception(failure)
    handle = _FutureHandle(future)
    with pytest.raises(TimeoutError) as raised:
        handle.result(timeout=0.01)
    assert raised.value is failure
    assert not isinstance(raised.value, PhysicalJoinTimeout)


def test_future_result_timeout_remains_physical_if_completion_races() -> None:
    class _RacedFuture(Future[int]):
        def result(self, timeout=None):
            if not self.done():
                self.set_result(42)
            raise TimeoutError("caller wait expired before completion")

    handle = _FutureHandle(_RacedFuture())
    with pytest.raises(PhysicalJoinTimeout):
        handle.result(timeout=0.001)
    assert handle.done()


def test_release_fence_timeout_remains_physical_after_future_is_done() -> None:
    future: Future[int] = Future()
    release_started, release_allowed = Event(), Event()

    def release() -> None:
        release_started.set()
        assert release_allowed.wait(3)

    fenced = _CompletionFencedHandle(_FutureHandle(future), release)
    worker = Thread(target=lambda: future.set_result(7), daemon=True)
    worker.start()
    try:
        assert release_started.wait(1)
        assert future.done()
        with pytest.raises(PhysicalJoinTimeout, match="capacity-release fence"):
            fenced.result(timeout=0.005)
    finally:
        release_allowed.set()
        worker.join(3)
    assert fenced.result(timeout=1) == 7
