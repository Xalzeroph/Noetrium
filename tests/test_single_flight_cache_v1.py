from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time

from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache


def test_single_flight_cache_can_cache_none_exactly_once():
    cache: SingleFlightCache[object | None] = SingleFlightCache()
    calls = 0

    def build():
        nonlocal calls
        calls += 1
        return None

    assert cache.get_or_create("none", build) is None
    assert cache.get_or_create("none", build) is None
    assert calls == 1


def test_single_flight_cache_coalesces_concurrent_builders():
    cache: SingleFlightCache[object] = SingleFlightCache()
    calls = 0
    lock = Lock()
    entered = Event()
    release = Event()
    value = object()

    def build():
        nonlocal calls
        with lock:
            calls += 1
        entered.set()
        if not release.wait(5):
            raise TimeoutError("single-flight test gate did not open")
        return value

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [
            executor.submit(cache.get_or_create, "shared", build)
            for _ in range(16)
        ]
        assert entered.wait(3)
        time.sleep(0.1)
        with lock:
            assert calls == 1
        release.set()
        rows = [future.result(timeout=3) for future in futures]

    assert all(row is value for row in rows)


def test_bounded_single_flight_cache_evicts_lru_completed_values():
    cache: SingleFlightCache[int] = SingleFlightCache(max_entries=2)

    assert cache.get_or_create("a", lambda: 1) == 1
    assert cache.get_or_create("b", lambda: 2) == 2
    assert cache.get_or_create("a", lambda: 99) == 1
    assert cache.get_or_create("c", lambda: 3) == 3

    calls = 0

    def rebuild_b():
        nonlocal calls
        calls += 1
        return 20

    assert cache.get_or_create("b", rebuild_b) == 20
    assert calls == 1
    assert len(cache) == 2
