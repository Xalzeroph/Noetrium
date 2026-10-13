"""Minecraft TCP/RCON readiness retries are woken by real file changes."""
from __future__ import annotations

import time
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

from noetrium_platform.infrastructure.reliability.forensics.providers.directory_change_signal import (
    DirectoryChangeSignal,
)
from noetrium_platform.capabilities.environment.minecraft.composition import server_service as service


def test_log_modify_notifies_only_opted_in_directory_watch(tmp_path):
    log = tmp_path / "server.log"
    log.write_text("boot\n")
    entry = DirectoryChangeSignal(tmp_path)
    writes = DirectoryChangeSignal(tmp_path, notify_writes=True)
    try:
        entry.acknowledge()
        writes.acknowledge()
        with log.open("a") as out:
            out.write("online\n")
        assert writes.wait_changed_since(None, timeout_seconds=1.0)
        assert not entry.changed_since(None)
    finally:
        writes.close()
        entry.close()


def test_tcp_retry_wakes_on_server_log_without_periodic_sleeps(tmp_path, monkeypatch):
    log = tmp_path / "server.log"
    log.write_text("boot\n")
    attempts = []
    class Connection:
        def close(self):
            pass
    def connect(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionRefusedError("initially unavailable")
        return Connection()
    monkeypatch.setattr(service.socket, "create_connection", connect)
    monkeypatch.setattr(service, "blocking_wait", lambda *_: (_ for _ in ()).throw(AssertionError("polling")))
    probe = service.MinecraftTcpReadinessProbe(
        host="127.0.0.1", port=25565,
        wake_factory=lambda: DirectoryChangeSignal(tmp_path, notify_writes=True),
    )
    def publish():
        time.sleep(.045)
        with log.open("a") as stream:
            stream.write("ready\n")
    worker = Thread(target=publish)
    worker.start()
    try:
        result = probe.wait_ready(
            SimpleNamespace(pid=123, start_identity="start"),
            SimpleNamespace(readiness_timeout_s=1.0, digest=lambda: "service"),
            SimpleNamespace(alive=lambda process: True),
        )
    finally:
        worker.join(timeout=2)
    assert result.startswith("minecraft-tcp-ready:")
    assert len(attempts) == 2


def test_rcon_retry_wakes_from_log_and_requires_actual_receipt(tmp_path, monkeypatch):
    log = tmp_path / "server.log"
    log.write_text("boot\n")
    monkeypatch.setattr(service, "blocking_wait", lambda *_: (_ for _ in ()).throw(AssertionError("polling")))
    calls = []
    class Rcon:
        def execute(self, command, *, timeout_s):
            calls.append(command)
            if len(calls) == 1:
                raise ConnectionRefusedError("initially unavailable")
            return SimpleNamespace(evidence_ref="observed-rcon")
    probe = service.MinecraftServerReadinessProbe(
        tcp=SimpleNamespace(wait_ready=lambda *args: "attested-tcp"),
        rcon=Rcon(),
        wake_factory=lambda: DirectoryChangeSignal(tmp_path, notify_writes=True),
    )
    def publish():
        time.sleep(.045)
        with log.open("a") as stream:
            stream.write("RCON ready\n")
    worker = Thread(target=publish)
    worker.start()
    try:
        result = probe.wait_ready(
            SimpleNamespace(pid=123, start_identity="start"),
            SimpleNamespace(readiness_timeout_s=1.0, digest=lambda: "service"),
            SimpleNamespace(alive=lambda process: True),
        )
    finally:
        worker.join(timeout=2)
    assert result.startswith("minecraft-server-ready:")
    assert len(calls) == 2


def test_tcp_readiness_wakes_on_exact_host_process_exit_without_log_event(
    tmp_path, monkeypatch,
):
    import os
    import subprocess
    import sys

    import pytest
    from noetrium_platform.composition.environment_capabilities.minecraft_local import (
        _MinecraftReadinessWake,
    )

    if not hasattr(os, "pidfd_open"):
        pytest.skip("Linux pidfd required")
    log = tmp_path / "server.log"
    log.write_text("starting\n")
    attempts = []

    def always_refused(*args, **kwargs):
        attempts.append(1)
        raise ConnectionRefusedError("not bound")

    monkeypatch.setattr(service.socket, "create_connection", always_refused)
    monkeypatch.setattr(service, "blocking_wait", lambda *_: (_ for _ in ()).throw(
        AssertionError("no periodic probe on a silent server")
    ))
    host = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(.14)"])
    try:
        probe = service.MinecraftTcpReadinessProbe(
            host="127.0.0.1", port=25565,
            wake_factory=lambda: _MinecraftReadinessWake(tmp_path, host),
        )
        started = time.monotonic()
        with pytest.raises(service.MinecraftServerServiceError, match="exited before TCP"):
            probe.wait_ready(
                SimpleNamespace(pid=host.pid, start_identity="start"),
                SimpleNamespace(readiness_timeout_s=5.0, digest=lambda: "service"),
                SimpleNamespace(alive=lambda process: host.poll() is None),
            )
        assert time.monotonic() - started < 3.0
        assert len(attempts) >= 1
    finally:
        if host.poll() is None:
            host.kill()
        host.wait()
