from __future__ import annotations

import time

import pytest

from tests.test_minecraft_jsonl_transport_v1 import _ExitedProcess, _transport
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_transport import MinecraftBridgeError


def test_read_detects_dead_process_without_waiting_full_command_timeout() -> None:
    transport = _transport(_ExitedProcess("", "provider-crashed\n"))
    # Isolate the read-side liveness guarantee from the stdout drain sentinel:\n    # a real lost sentinel must still be bounded by process.poll().
    transport._process = _ExitedProcess("", "provider-crashed\n")  # type: ignore[attr-defined]
    started = time.monotonic()
    with pytest.raises(MinecraftBridgeError, match="BRIDGE_EXITED"):
        transport.read(timeout_s=5.0)
    elapsed = time.monotonic() - started
    assert elapsed < 0.75

class _CancelledControl:
    deadline = None
    remaining_seconds = None
    cancelled = True
    reason = "test-interrupt"

    def wait(self, timeout=None):
        del timeout
        return True

    def checkpoint(self):
        from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled
        raise TaskCancelled("test-interrupt")


def test_read_observes_execution_control_without_waiting_transport_timeout() -> None:
    process = _ExitedProcess("", "")
    process.poll = lambda: None  # type: ignore[method-assign]
    transport = _transport(process)
    transport._process = process  # type: ignore[attr-defined]
    started = time.monotonic()
    with pytest.raises(Exception, match="test-interrupt"):
        transport.read(timeout_s=30.0, control=_CancelledControl())
    assert time.monotonic() - started < 0.5
