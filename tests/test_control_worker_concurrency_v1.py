from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
from threading import Thread
import time

from scripts import control_worker


def test_resident_worker_accepts_fast_request_while_slow_request_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    socket_path = tmp_path / "control.sock"

    monkeypatch.setattr(
        control_worker,
        "_preload_runtime",
        lambda: ((), "gpu"),
    )
    monkeypatch.setattr(control_worker, "_source_drift", lambda _baseline: None)
    monkeypatch.setattr(
        control_worker,
        "_runtime_is_fresh",
        lambda _argv, _gpu: True,
    )

    def dispatch(argv: tuple[str, ...]) -> int:
        if argv == ("slow",):
            time.sleep(1.0)
            return 0
        if argv == ("fast",):
            return 0
        raise AssertionError(argv)

    monkeypatch.setattr(control_worker, "_dispatch", dispatch)

    server_pid = os.fork()
    if server_pid == 0:
        raise SystemExit(control_worker.serve(socket_path))

    try:
        deadline = time.monotonic() + 3.0
        while not socket_path.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("resident control socket was not created")
            time.sleep(0.01)
        assert control_worker.probe(socket_path) == 0

        slow_result: list[int] = []
        slow = Thread(
            target=lambda: slow_result.append(
                control_worker.request(socket_path, ("slow",))
            )
        )
        slow.start()
        time.sleep(0.15)

        started = time.monotonic()
        fast_result = control_worker.request(socket_path, ("fast",))
        fast_elapsed = time.monotonic() - started

        assert fast_result == 0
        assert fast_elapsed < 0.5
        assert slow.is_alive()

        slow.join(timeout=3.0)
        assert not slow.is_alive()
        assert slow_result == [0]
    finally:
        try:
            os.kill(server_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.waitpid(server_pid, 0)


def test_request_disconnect_detaches_durable_execution(tmp_path: Path) -> None:
    lease = tmp_path / "request-owner.lock"
    owner_fd = os.open(lease, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    fcntl.flock(owner_fd, fcntl.LOCK_EX)
    left, right = __import__("socket").socketpair()
    child_pid = os.fork()
    if child_pid == 0:
        time.sleep(0.6)
        os._exit(0)

    waiter = Thread(
        target=lambda: control_worker._wait_child_or_cancel(
            left, child_pid, lease
        )
    )
    waiter.start()
    time.sleep(0.1)
    right.close()
    fcntl.flock(owner_fd, fcntl.LOCK_UN)
    os.close(owner_fd)
    time.sleep(0.15)
    assert waiter.is_alive()
    waiter.join(timeout=2.0)
    assert not waiter.is_alive()
    left.close()


def test_explicit_cancel_marker_cancels_exact_request(tmp_path: Path) -> None:
    lease = tmp_path / "request-owner.lock"
    lease.touch()
    left, right = __import__("socket").socketpair()
    child_pid = os.fork()
    if child_pid == 0:
        try:
            while True:
                time.sleep(10.0)
        finally:
            os._exit(0)

    waiter = Thread(
        target=lambda: control_worker._wait_child_or_cancel(
            left, child_pid, lease
        )
    )
    waiter.start()
    time.sleep(0.15)
    Path(str(lease) + ".cancel").touch()
    waiter.join(timeout=3.0)
    try:
        assert not waiter.is_alive()
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("explicitly cancelled control execution remained alive")
    finally:
        left.close()
        right.close()

