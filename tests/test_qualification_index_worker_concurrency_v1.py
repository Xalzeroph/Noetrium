from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time

from noetrium_platform.capabilities.model.qualification.providers import qualification_index_worker as worker


def _run_parallel(fn, count: int = 8):
    with ThreadPoolExecutor(max_workers=count) as executor:
        return tuple(executor.map(lambda _: fn(), range(count)))


def test_simple_index_same_key_is_single_flight(monkeypatch) -> None:
    calls = 0
    guard = threading.Lock()

    def fetch(url, accept, limit):
        nonlocal calls
        del url, accept, limit
        with guard:
            calls += 1
        time.sleep(0.02)
        return b'<a href="pkg-1.0-py3-none-any.whl">pkg</a>'

    monkeypatch.setattr(worker, "_fetch_url", fetch)
    cache = {}
    results = _run_parallel(lambda: worker._simple("https://index/simple", "pkg", cache))

    assert calls == 1
    assert all(result == results[0] for result in results)
    assert results[0][1] is None


def test_metadata_same_href_is_single_flight(monkeypatch) -> None:
    calls = 0
    guard = threading.Lock()

    def fetch(url, accept, limit):
        nonlocal calls
        del url, accept, limit
        with guard:
            calls += 1
        time.sleep(0.02)
        return b"Metadata-Version: 2.1\nRequires-Dist: dep>=1\n\n"

    monkeypatch.setattr(worker, "_fetch_url", fetch)
    cache = {}

    def read():
        artifact = {"_href": "https://index/pkg.whl", "metadata_sha256": None}
        return worker._read_metadata(artifact, cache)

    results = _run_parallel(read)
    assert calls == 1
    assert all(result == (("dep>=1",), None) for result in results)


def test_simple_index_different_keys_remain_parallel(monkeypatch) -> None:
    active = 0
    max_active = 0
    guard = threading.Lock()
    entered = threading.Barrier(2)

    def fetch(url, accept, limit):
        nonlocal active, max_active
        del accept, limit
        with guard:
            active += 1
            max_active = max(max_active, active)
        entered.wait(timeout=1.0)
        time.sleep(0.01)
        with guard:
            active -= 1
        name = "a" if "/a/" in url else "b"
        return f'<a href="{name}-1.0-py3-none-any.whl">{name}</a>'.encode()

    monkeypatch.setattr(worker, "_fetch_url", fetch)
    cache = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(worker._simple, "https://index/simple", "a", cache)
        second = executor.submit(worker._simple, "https://index/simple", "b", cache)
        first.result(timeout=2.0)
        second.result(timeout=2.0)

    assert max_active >= 2


def test_blocking_map_preserves_input_order_under_platform_concurrency() -> None:
    release = threading.Event()
    entered = threading.Barrier(2)

    def work(value: int) -> int:
        if value < 2:
            entered.wait(timeout=1.0)
            release.set()
        assert release.wait(timeout=1.0)
        return value * 10

    assert worker._blocking_map("ordered-test", work, (0, 1, 2)) == (0, 10, 20)


def test_blocking_map_waits_for_physical_completion_before_raising() -> None:
    slow_started = threading.Event()
    slow_completed = threading.Event()

    def work(value: str) -> str:
        if value == "fail":
            assert slow_started.wait(timeout=1.0)
            raise RuntimeError("boom")
        slow_started.set()
        time.sleep(0.03)
        slow_completed.set()
        return value

    try:
        worker._blocking_map("failure-test", work, ("fail", "slow"))
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("blocking map must propagate the first task failure")
    assert slow_completed.is_set()
