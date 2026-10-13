"""ASYNC task cleanup inherits its permit, never blocks on new worker admission."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from threading import Event
import time

from noetrium_platform.foundation.kernel.concurrency.providers.executors import (
    BoundedThreadExecutor,
)
from noetrium_platform.foundation.kernel.concurrency.runtime.execution import (
    _CompletionFencedHandle,
)


def test_saturated_worker_pool_accepts_inherited_cleanup_without_loop_block():
    started = Event()
    allow_unrelated = Event()
    released = Event()
    workers = BoundedThreadExecutor(
        max_workers=1, max_in_flight=1, thread_name_prefix="inherited-test"
    )

    def occupy():
        started.set()
        assert allow_unrelated.wait(3)

    occupant = workers.submit(occupy)
    assert started.wait(1)

    async def in_event_loop():
        raw = Future()
        fence = _CompletionFencedHandle(
            raw,
            lambda: released.set(),
            blocking_release_provider=workers,
        )
        begin = time.perf_counter()
        raw.set_result("done")
        return fence, time.perf_counter() - begin

    try:
        fence, elapsed = asyncio.run(in_event_loop())
        assert elapsed < .1, "full worker capacity must never stall the asyncio loop"
        assert not released.is_set(), "retirement is queued, not invented"
        assert not fence.done()
        assert workers._available == 0, (
            "cleanup inherits its parent permit instead of minting a new worker slot"
        )
    finally:
        allow_unrelated.set()

    assert occupant.result(timeout=2) is None
    assert fence.result(timeout=2) == "done"
    assert released.is_set()
    assert workers._available == 1
    workers.close()


def test_inherited_cleanup_does_not_charge_a_second_worker_slot():
    workers = BoundedThreadExecutor(
        max_workers=1, max_in_flight=1, thread_name_prefix="inherited-two"
    )
    try:
        inherited = workers.submit_inherited_retirement(lambda: 5)
        assert inherited.result(timeout=1) == 5
        normal = workers.submit(lambda: 11)
        assert normal.result(timeout=1) == 11
        assert workers._available == 1
    finally:
        workers.close()
