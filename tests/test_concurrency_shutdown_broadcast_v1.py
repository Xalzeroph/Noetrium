from __future__ import annotations

from threading import Event, Lock
from types import SimpleNamespace
import unittest

from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.foundation.kernel.concurrency.runtime.runtime import (
    StructuredConcurrencyRuntime,
)


class _Group:
    def __init__(self, peer=None) -> None:
        self.peer = peer
        self.cancelled = False
        self.closed = False

    def snapshot(self):
        return SimpleNamespace(converged=self.closed)

    def cancel(self, _reason: str) -> None:
        self.cancelled = True

    def close(self, *, cancel_pending: bool, deadline: Deadline) -> None:
        self.assert_peer_cancelled()
        self.closed = True

    def assert_peer_cancelled(self) -> None:
        if self.peer is not None and not self.peer.cancelled:
            raise AssertionError("later group reached join before cancellation broadcast")


class _HealthyHeartbeats:
    def assert_healthy(self) -> None:
        return None


class _Closable:
    def close(self, *args, **kwargs) -> None:
        return None


class ConcurrencyShutdownBroadcastTests(unittest.TestCase):
    def test_all_groups_receive_cancellation_before_first_join(self) -> None:
        first = _Group()
        second = _Group(peer=first)

        runtime = object.__new__(StructuredConcurrencyRuntime)
        runtime.budget = None
        runtime._blocking_io = _Closable()
        runtime._async_io = _Closable()
        runtime._retirement_io = _Closable()
        runtime._cpu = _Closable()
        runtime._timers = _Closable()
        runtime._serial_lane_factory = _Closable()
        runtime._owns_cpu_provider = True
        runtime._groups = {"first": first, "second": second}
        runtime._group_generation = 2
        runtime._serial_lanes = {}
        runtime._lock = Lock()
        runtime._closing = False
        runtime._closed = False
        runtime._converged = False
        runtime._close_complete = Event()
        runtime._close_failure = None
        runtime._permits = None
        runtime._heartbeat_scheduler = _HealthyHeartbeats()
        runtime._execution = None

        runtime.close(deadline=Deadline.after(1.0))

        self.assertTrue(first.cancelled)
        self.assertTrue(second.cancelled)
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)
        self.assertTrue(runtime._converged)


if __name__ == "__main__":
    unittest.main()
