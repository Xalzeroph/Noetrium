from __future__ import annotations

from types import SimpleNamespace
import os
import subprocess

import pytest

from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftServer,
)


def test_minecraft_startup_failure_forensics_capture_bounded_tail(tmp_path) -> None:
    log = tmp_path / "noetrium-minecraft-server.log"
    prefix = "x" * 20000
    marker = "FAILED TO BIND TO PORT\njava.net.BindException: Address already in use\n"
    log.write_text(prefix + marker, encoding="utf-8")
    server = object.__new__(_DockerMinecraftServer)
    server.spec = SimpleNamespace(workdir=str(tmp_path))

    details = server._startup_log_failure_details(0)

    assert "docker_exec_exit_status=0" in details
    assert "startup_log_tail_sha256=" in details
    assert "last_java_log_line=java.net.BindException: Address already in use" in details
    assert "FAILED TO BIND TO PORT" in details
    assert "Address already in use" in details
    assert prefix not in details
    assert len(details) < 5000


@pytest.mark.skipif(not hasattr(os, "pidfd_open"), reason="Linux pidfd required")
def test_owned_minecraft_stop_waits_on_pidfd_without_polling(monkeypatch, tmp_path) -> None:
    child = subprocess.Popen(["sleep", "60"])
    process = SimpleNamespace(pid=101, start_identity="container-101")
    server = object.__new__(_DockerMinecraftServer)
    server.process = process
    server._host_process = child
    server.pid_path = tmp_path / "server.pid"
    server.contract = SimpleNamespace(
        stop_timeout_s=1.0, digest=lambda: "contract-digest"
    )
    server.capsule = SimpleNamespace(container_name="capsule-test")
    server._pristine_reservation = None
    server._identity_alive = lambda _process: child.poll() is None
    server._terminate_pid = lambda _process, *, signal: child.terminate()

    import noetrium_platform.composition.environment_capabilities.minecraft_local as runtime
    monkeypatch.setattr(
        runtime,
        "blocking_wait",
        lambda _seconds: (_ for _ in ()).throw(
            AssertionError("owned stop must not enter polling fallback")
        ),
    )
    try:
        outcome = server.stop()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()

    assert outcome.stopped is True
    assert server.process is None
    assert server._host_process is None
