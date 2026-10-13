"""Exact Docker-exec ownership cleanup must be event driven, not polled."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from noetrium_platform.composition.environment_capabilities import minecraft_local


pytestmark = pytest.mark.skipif(
    not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"),
    reason="Linux pidfd process-exit kernel primitives required",
)


def _owned_server(host: subprocess.Popen[str], timeout: float = 0.5):
    server = object.__new__(minecraft_local._DockerMinecraftServer)
    server._host_process = host
    server.contract = SimpleNamespace(stop_timeout_s=timeout)
    return server


def _forbid_sleep(*_args, **_kwargs):
    raise AssertionError("process cleanup must wait for a kernel event")


def test_owner_exit_reaps_without_periodic_probes(monkeypatch):
    monkeypatch.setattr(minecraft_local, "blocking_wait", _forbid_sleep)
    host = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(100)"])
    try:
        server = _owned_server(host)
        assert server._converge_host_process() == ()
        assert server._host_process is None
        assert host.poll() == -signal.SIGTERM
    finally:
        if host.poll() is None:
            host.kill()
            host.wait()


def test_owner_sigkill_escalates_on_authoritative_deadline(monkeypatch):
    monkeypatch.setattr(minecraft_local, "blocking_wait", _forbid_sleep)
    child_source = (
        "import signal,time,sys;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "print('ready',flush=True);"
        "time.sleep(100)"
    )
    host = subprocess.Popen(
        [sys.executable, "-c", child_source],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert host.stdout is not None
        assert host.stdout.readline().strip() == "ready"
        server = _owned_server(host, timeout=0.1)
        assert server._converge_host_process() == ()
        assert host.poll() == -signal.SIGKILL
    finally:
        if host.poll() is None:
            host.kill()
            host.wait()
        if host.stdout is not None:
            host.stdout.close()


def test_owner_already_exited_is_reaped_without_pidfd(monkeypatch):
    monkeypatch.setattr(minecraft_local, "blocking_wait", _forbid_sleep)
    host = subprocess.Popen([sys.executable, "-c", "pass"])
    host.wait()
    server = _owned_server(host)
    assert server._converge_host_process() == ()
    assert server._host_process is None


def test_uncertain_pidfd_failure_retains_live_process_identity(monkeypatch):
    from types import SimpleNamespace

    # Deliberately fail the first kernel ownership operation. The PID still
    # identifies a live, unreaped process; recovery must preserve the anchor.
    host = SimpleNamespace(pid=123456, poll=lambda: None)
    server = _owned_server(host)

    def refuse_open(*args):
        raise PermissionError("transient kernel denial")

    monkeypatch.setattr(minecraft_local.os, "pidfd_open", refuse_open)
    errors = server._converge_host_process()
    assert len(errors) == 1
    assert isinstance(errors[0], PermissionError)
    assert server._host_process is host


def test_recovered_java_liveness_is_one_exact_identity_observation(monkeypatch):
    from noetrium_platform.substrate.api import ServiceProcessIdentity

    server = object.__new__(minecraft_local._DockerMinecraftServer)
    process = ServiceProcessIdentity(111, "docker-exec:container-a:111:222")
    server.process = process
    server._host_process = None
    queries = []
    server._identity_alive = lambda requested: queries.append(requested) or False
    monkeypatch.setattr(minecraft_local, "blocking_wait", _forbid_sleep)
    assert server.alive(process) is False
    assert queries == [process]
    server._identity_alive = lambda requested: queries.append(requested) or True
    assert server.alive(process) is True
    assert queries == [process, process]


def test_java_readiness_failure_preserves_exit_receipt_before_world_teardown(tmp_path):
    from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
        MinecraftServerServiceError,
    )

    server = object.__new__(minecraft_local._DockerMinecraftServer)
    server.process = SimpleNamespace(pid=101, start_identity="container-gen")
    server._host_process = SimpleNamespace(poll=lambda: 137)
    server.spec = SimpleNamespace(rcon_endpoint=None, workdir=str(tmp_path))
    server._tcp_ready_evidence = lambda: (_ for _ in ()).throw(
        MinecraftServerServiceError("Minecraft exited before TCP readiness")
    )
    (tmp_path / "noetrium-minecraft-server.log").write_text(
        "Starting world\nJava failed while binding\n"
    )
    with pytest.raises(MinecraftServerServiceError, match="docker_exec_exit_status=137") as error:
        server._ready_evidence()
    assert "last_java_log_line=Java failed while binding" in str(error.value)
    assert isinstance(error.value.__cause__, MinecraftServerServiceError)


def test_java_readiness_failure_does_not_fabricate_exit_receipt(tmp_path):
    from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
        MinecraftServerServiceError,
    )

    server = object.__new__(minecraft_local._DockerMinecraftServer)
    server.process = SimpleNamespace(pid=101, start_identity="container-gen")
    server._host_process = SimpleNamespace(poll=lambda: None)
    server.spec = SimpleNamespace(rcon_endpoint=None, workdir=str(tmp_path))
    original = MinecraftServerServiceError("Minecraft has not bound yet")
    server._tcp_ready_evidence = lambda: (_ for _ in ()).throw(original)
    with pytest.raises(MinecraftServerServiceError) as raised:
        server._ready_evidence()
    assert raised.value is original


def test_rcon_readiness_failure_preserves_exit_receipt_without_log(tmp_path):
    from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
        MinecraftServerServiceError,
    )

    server = object.__new__(minecraft_local._DockerMinecraftServer)
    server.process = SimpleNamespace(pid=202, start_identity="container-gen")
    server._host_process = SimpleNamespace(poll=lambda: 143)
    server.spec = SimpleNamespace(rcon_endpoint=object(), workdir=str(tmp_path))
    server._rcon_password = "present"
    server.contract = SimpleNamespace()
    server._server_readiness_probe = SimpleNamespace(
        wait_ready=lambda *_: (_ for _ in ()).throw(
            MinecraftServerServiceError("RCON failed before readiness")
        ),
    )
    with pytest.raises(MinecraftServerServiceError, match="docker_exec_exit_status=143") as caught:
        server._ready_evidence()
    assert "last_java_log_line" not in str(caught.value)
