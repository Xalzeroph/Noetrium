"""Minecraft launch waits for the authority-owned PID publication event."""
from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftServer,
    _MinecraftChildProcessAbsent,
)


def test_java_pid_publication_wakes_from_atomic_rename_without_timer_probes(tmp_path):
    pid_path = tmp_path / "server.pid"
    attempts = []
    published = []

    def identity():
        attempts.append(time.monotonic())
        try:
            value = pid_path.read_text()
        except FileNotFoundError as exc:
            raise _MinecraftChildProcessAbsent("pending") from exc
        return SimpleNamespace(pid=int(value), start_identity="exact-generation")

    def publish():
        time.sleep(.15)
        temporary = pid_path.with_suffix(".tmp")
        temporary.write_text("321")
        os.replace(temporary, pid_path)
        published.append(True)

    thread = Thread(target=publish)
    def spawn(*args, **kwargs):
        thread.start()
        return SimpleNamespace(poll=lambda: None)

    capsule = SimpleNamespace(
        assert_healthy=lambda: None,
        docker_executable="docker",
        container_name="ephemeral",
    )
    contract = SimpleNamespace(
        readiness_timeout_s=2.0, digest=lambda: "contract-digest"
    )
    mock = SimpleNamespace(
        process=None, pid_path=pid_path, capsule=capsule,
        container_name=capsule.container_name,
        spec=SimpleNamespace(workdir=str(tmp_path)),
        contract=contract, process_supervisor=SimpleNamespace(spawn_interactive=spawn),
        _resource_bound_command=lambda: ("java", "-jar", "server.jar"),
        _host_process=None, _process_identity=identity,
    )
    try:
        receipt = _DockerMinecraftServer.start(mock)
    finally:
        thread.join(timeout=2)
    assert published and receipt.process.pid == 321
    assert len(attempts) <= 3

def test_java_pid_wait_wakes_on_owner_exit_without_file_mutations(tmp_path):
    import subprocess
    import sys
    import pytest

    if not hasattr(os, "pidfd_open"):
        pytest.skip("the current kernel does not expose process-exit event descriptors")

    pid_path = tmp_path / "never-published.pid"
    child_processes = []
    def spawn(*args, **kwargs):
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(.05)"])
        child_processes.append(child)
        return child

    def missing_identity():
        raise _MinecraftChildProcessAbsent("pending")

    capsule = SimpleNamespace(
        assert_healthy=lambda: None,
        docker_executable="docker",
        container_name="ephemeral",
    )
    mock = SimpleNamespace(
        process=None, pid_path=pid_path, capsule=capsule,
        container_name=capsule.container_name,
        spec=SimpleNamespace(workdir=str(tmp_path)),
        contract=SimpleNamespace(
            readiness_timeout_s=2.0, digest=lambda: "exact-service"
        ),
        process_supervisor=SimpleNamespace(spawn_interactive=spawn),
        _resource_bound_command=lambda: ("java", "-jar", "server.jar"),
        _host_process=None, _process_identity=missing_identity,
        _cleanup_failed_start=lambda: (),
    )
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="docker-exec exited before Java PID"):
            _DockerMinecraftServer.start(mock)
    finally:
        for child in child_processes:
            child.wait(timeout=2)
    assert time.monotonic() - started < 1.0
