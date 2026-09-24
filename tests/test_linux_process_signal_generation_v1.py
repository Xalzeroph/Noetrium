from __future__ import annotations

import signal

import pytest

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from noetrium_platform.infrastructure.lifecycle.service.runtime import linux_signal
from noetrium_platform.infrastructure.lifecycle.service.runtime.process_contracts import (
    ServiceProcessDrift,
)


class _RacingProcfs:
    def __init__(self) -> None:
        self.reads = 0

    def alive_pid(self, pid: int) -> bool:
        del pid
        return True

    def start_identity(self, pid: int) -> str:
        del pid
        self.reads += 1
        # poll() proves the old generation; the first pre-signal check still
        # sees it, then the PID is reused before final signal delivery.
        return "old-start" if self.reads <= 2 else "reused-start"


def test_exact_linux_signal_rejects_pid_reuse_after_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    procfs = _RacingProcfs()
    identity = ServiceProcessIdentity(4242, "old-start", 4242)
    process = linux_signal._ExactLinuxProcess(identity, procfs)

    assert process.poll() is None

    kill_calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(linux_signal.os, "getpgid", lambda pid: 4242)
    monkeypatch.setattr(
        linux_signal.os,
        "killpg",
        lambda pgid, sig: kill_calls.append((pgid, sig)),
    )

    with pytest.raises(ServiceProcessDrift, match="start identity drift"):
        process.terminate()

    assert kill_calls == []
    assert procfs.reads == 3


class _StableProcfs:
    def alive_pid(self, pid: int) -> bool:
        del pid
        return True

    def start_identity(self, pid: int) -> str:
        del pid
        return "stable-start"


def test_exact_linux_signal_delivers_only_after_generation_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = ServiceProcessIdentity(5252, "stable-start", 5252)
    process = linux_signal._ExactLinuxProcess(identity, _StableProcfs())
    kill_calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(linux_signal.os, "getpgid", lambda pid: 5252)
    monkeypatch.setattr(
        linux_signal.os,
        "killpg",
        lambda pgid, sig: kill_calls.append((pgid, sig)),
    )

    process.terminate()

    assert kill_calls == [(5252, signal.SIGTERM)]
