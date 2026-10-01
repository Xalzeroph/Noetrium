from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from multiprocessing import get_context
import time
from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import (
    ContentAddressedSingleFlight,
    SingleFlightCache,
)


def _cross_process_singleflight_worker(
    root: str,
    entered: str,
    release: str,
    trace: str,
    role: str,
) -> None:
    singleflight = ContentAddressedSingleFlight(Path(root))
    entered_path = Path(entered)
    release_path = Path(release)
    trace_path = Path(trace)
    if role == "second":
        deadline = time.monotonic() + 10.0
        while not entered_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("first producer never entered")
            time.sleep(0.01)
    with singleflight.producer("environment-runtime", "same-realization"):
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(role + "-enter\n")
            handle.flush()
        if role == "first":
            entered_path.touch()
            deadline = time.monotonic() + 10.0
            while not release_path.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("single-flight release was not published")
                time.sleep(0.01)
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write("first-exit\n")
                handle.flush()


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

def test_content_addressed_single_flight_has_one_lock_domain_per_realization(
    tmp_path: Path,
):
    first = ContentAddressedSingleFlight(tmp_path)
    second = ContentAddressedSingleFlight(tmp_path)
    assert first.lock_path("model", "abc") == second.lock_path("model", "abc")
    assert first.lock_path("model", "abc") != first.lock_path("model", "def")
    assert first.lock_path("model", "abc") != first.lock_path("environment", "abc")


def test_content_addressed_single_flight_serializes_independent_callers(
    tmp_path: Path,
):
    first = ContentAddressedSingleFlight(tmp_path)
    second = ContentAddressedSingleFlight(tmp_path)
    entered = Event()
    release = Event()
    order: list[str] = []

    def producer_one():
        with first.producer("model", "same"):
            order.append("first-enter")
            entered.set()
            assert release.wait(5)
            order.append("first-exit")

    def producer_two():
        assert entered.wait(3)
        with second.producer("model", "same"):
            order.append("second-enter")

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(producer_one)
        b = executor.submit(producer_two)
        assert entered.wait(3)
        time.sleep(0.1)
        assert order == ["first-enter"]
        release.set()
        a.result(timeout=3)
        b.result(timeout=3)

    assert order == ["first-enter", "first-exit", "second-enter"]


def test_content_addressed_single_flight_serializes_processes(tmp_path: Path):
    root = tmp_path / "locks"
    entered = tmp_path / "entered"
    release = tmp_path / "release"
    trace = tmp_path / "trace.txt"
    context = get_context("spawn")
    first = context.Process(
        target=_cross_process_singleflight_worker,
        args=(str(root), str(entered), str(release), str(trace), "first"),
    )
    second = context.Process(
        target=_cross_process_singleflight_worker,
        args=(str(root), str(entered), str(release), str(trace), "second"),
    )
    first.start()
    second.start()
    deadline = time.monotonic() + 10.0
    while not entered.exists():
        if time.monotonic() >= deadline:
            first.terminate()
            second.terminate()
            raise TimeoutError("first process never acquired single-flight fence")
        time.sleep(0.01)
    time.sleep(0.15)
    assert trace.read_text(encoding="utf-8").splitlines() == ["first-enter"]
    release.touch()
    first.join(10.0)
    second.join(10.0)
    assert first.exitcode == 0
    assert second.exitcode == 0
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "first-enter",
        "first-exit",
        "second-enter",
    ]
