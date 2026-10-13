"""Completion subscriptions must never wait for durable I/O on an asyncio loop."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
import time

from noetrium_platform.foundation.kernel.concurrency.runtime.execution import (
    _CompletionFencedHandle,
)


class _Provider:
    def __init__(self, pool):
        self.pool = pool

    def submit_inherited_retirement(self, fn):
        return self.pool.submit(fn)


def test_raw_event_loop_completion_does_not_block_on_slow_permit_release():
    async def run(pool):
        raw = Future()
        started = Event()
        allow_release = Event()
        loop = asyncio.get_running_loop()
        notified = loop.create_future()
        completions = []

        def release():
            started.set()
            assert allow_release.wait(.7)

        fence = _CompletionFencedHandle(
            raw, release, blocking_release_provider=_Provider(pool)
        )

        def on_done(accepted):
            completions.append(accepted)
            loop.call_soon_threadsafe(
                lambda: notified.set_result("done") if not notified.done() else None
            )

        fence.add_done_callback(on_done)
        begin = time.perf_counter()
        raw.set_result("model-completed")
        # Old implementation called release_visible.wait() inside the raw
        # Future completion callback, blocking the current asyncio thread.
        assert time.perf_counter() - begin < .15
        assert started.wait(.15)
        assert not notified.done()
        await asyncio.sleep(.01)
        assert not notified.done()
        allow_release.set()
        assert await asyncio.wait_for(notified, .5) == "done"
        assert fence.result(timeout=0) == "model-completed"
        assert completions == [fence]
        immediate = []
        fence.add_done_callback(lambda handle: immediate.append(handle))
        assert immediate == [fence]

    with ThreadPoolExecutor(max_workers=1) as pool:
        asyncio.run(run(pool))


def test_two_racing_subscribers_are_not_lost_or_duplicated():
    from threading import Thread

    future = Future()
    allow_release = Event()
    observed = []
    fence = _CompletionFencedHandle(future, lambda: allow_release.wait(1))
    first = Thread(target=lambda: future.set_result("done"))
    first.start()

    # One callback registered before release, one after release.
    fence.add_done_callback(lambda _: observed.append("before"))
    allow_release.set()
    first.join(2)
    assert not first.is_alive()
    fence.add_done_callback(lambda _: observed.append("after"))
    assert observed == ["before", "after"]


def test_completion_observer_failures_are_typed_auxiliary_and_not_lost():
    raw=Future()
    events=[]
    fence=_CompletionFencedHandle(raw,lambda:events.append('released'))
    def broken(_handle):
        events.append('observer-failed')
        raise ValueError('precise-observer-failure')
    fence.add_done_callback(broken)
    fence.add_done_callback(lambda _:events.append('next-observer'))
    raw.set_result('primary-done')
    assert fence.result(timeout=.5)=='primary-done'
    assert events==['released','observer-failed','next-observer']
    assert len(fence.completion_observer_failures())==1
    assert isinstance(fence.completion_observer_failures()[0],ValueError)
    assert str(fence.completion_observer_failures()[0])=='precise-observer-failure'
    fence.add_done_callback(broken)
    assert len(fence.completion_observer_failures())==2
