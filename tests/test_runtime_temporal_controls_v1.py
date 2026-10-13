from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path

import pytest

from noetrium_platform.infrastructure.resources.compute.providers.nvidia_smi import NvidiaSmiGpuRuntimeObserver
from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime.command_runner import AsyncProcessCommandRunner
from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime.local_command import AsyncLocalCommandRunner
from noetrium_platform.infrastructure.lifecycle.server.identity.api.contracts import ServerConnectionProfile
from noetrium_platform.infrastructure.lifecycle.server.identity.providers.ssh_connection import SSHServerConnection
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.readiness import (
    HttpEndpointReadinessProbe,
    ProcessAliveReadinessProbe,
    ServiceReadinessTimeout,
)
from noetrium_platform.infrastructure.lifecycle.session.runtime.tmux_subprocess import SubprocessTmuxCommandRunner
from noetrium_platform.infrastructure.lifecycle.session.runtime.tmux_transport import TmuxPersistentSessionControl
from noetrium_platform.infrastructure.lifecycle.toolchain.api import JavaRuntimePlatform, JavaRuntimeProvisioningRequest
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


NONFINITE = (math.nan, math.inf, -math.inf)


def _absolute(name: str) -> str:
    return str((Path.cwd() / name).resolve())


def _service_contract(**overrides) -> ServiceLaunchContract:
    executable = _absolute("fake-service")
    values = dict(
        service_id="service-a",
        generation="gen-1",
        executable=executable,
        argv=(executable,),
        cwd=_absolute("fake-cwd"),
        environment_digest="0" * 64,
        artifact_digest="1" * 64,
        runtime_identity_digest="2" * 64,
        readiness_timeout_s=5.0,
        stop_timeout_s=5.0,
        heartbeat_interval_s=1.0,
    )
    values.update(overrides)
    return ServiceLaunchContract(**values)


@pytest.mark.parametrize("invalid", NONFINITE)
def test_process_command_cleanup_timeout_must_be_finite(invalid: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        AsyncProcessCommandRunner(object(), cleanup_timeout_seconds=invalid)


@pytest.mark.parametrize("invalid", NONFINITE)
def test_local_command_timeouts_must_be_finite(invalid: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        AsyncLocalCommandRunner(object(), default_timeout_seconds=invalid)
    runner = AsyncLocalCommandRunner(object())
    with pytest.raises(ValueError, match="finite and positive"):
        runner.run(("never-executed",), timeout_seconds=invalid)


@pytest.mark.parametrize("invalid", NONFINITE)
def test_service_contract_time_controls_must_be_finite(invalid: float) -> None:
    for field in ("readiness_timeout_s", "stop_timeout_s", "heartbeat_interval_s"):
        with pytest.raises(ValueError, match="finite and positive"):
            _service_contract(**{field: invalid})


@pytest.mark.parametrize("invalid", NONFINITE)
def test_readiness_probe_time_controls_must_be_finite(invalid: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        ProcessAliveReadinessProbe(object(), poll_interval_s=invalid)
    with pytest.raises(ValueError, match="finite and positive"):
        HttpEndpointReadinessProbe(object(), "http://127.0.0.1", poll_interval_s=invalid)
    with pytest.raises(ValueError, match="finite and positive"):
        HttpEndpointReadinessProbe(object(), "http://127.0.0.1", request_timeout_s=invalid)


def test_readiness_probes_forward_contract_deadline_to_execution_lane() -> None:
    class Handle:
        def result(self):
            return "ready"

    class Group:
        def __init__(self) -> None:
            self.deadlines = []

        def submit(self, spec, fn, *args, deadline=None, **kwargs):
            self.deadlines.append(deadline)
            return Handle()

    group = Group()
    process = ServiceProcessIdentity(123, "proc-123")
    contract = _service_contract(readiness_timeout_s=0.5)
    liveness = object()

    assert (
        ProcessAliveReadinessProbe(group).wait_ready(
            process,
            contract,
            liveness,
        )
        == "ready"
    )
    assert (
        HttpEndpointReadinessProbe(
            group,
            "http://127.0.0.1:1/health",
        ).wait_ready(
            process,
            contract,
            liveness,
        )
        == "ready"
    )
    assert len(group.deadlines) == 2
    for deadline in group.deadlines:
        assert deadline is not None
        assert 0.0 < deadline.remaining_seconds <= contract.readiness_timeout_s


def test_http_readiness_timeout_preserves_last_probe_diagnostics() -> None:
    class Context:
        remaining_seconds = 0.0

        def checkpoint(self) -> None:
            return None

    class Alive:
        def alive(self, process) -> bool:
            return True

    process = ServiceProcessIdentity(123, "proc-123")
    contract = _service_contract(readiness_timeout_s=0.5)
    probe = HttpEndpointReadinessProbe(
        object(),
        "http://127.0.0.1:1/health",
    )

    with pytest.raises(ServiceReadinessTimeout) as raised:
        asyncio.run(
            probe._wait_ready_async(
                Context(),
                process,
                contract,
                Alive(),
            )
        )
    diagnostics = raised.value.diagnostics
    assert diagnostics["component_id"] == "service.readiness"
    assert diagnostics["service_id"] == contract.service_id
    assert diagnostics["readiness_kind"] == "http"
    assert diagnostics["readiness_timeout_s"] == 0.5
    assert diagnostics["probe_attempts"] == 0
    assert diagnostics["last_observation"] == "not-ready"
    assert diagnostics["process_pid"] == 123
    assert diagnostics["process_start_identity"] == "proc-123"


def test_http_readiness_does_not_wait_forever_for_peer_tcp_close() -> None:
    async def scenario() -> None:
        release = asyncio.Event()

        async def handler(reader, writer) -> None:
            try:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: keep-alive\r\n\r\n"
                )
                await writer.drain()
                await release.wait()
            finally:
                writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        probe = HttpEndpointReadinessProbe(
            object(),
            f"http://127.0.0.1:{port}/health",
            request_timeout_s=0.05,
        )
        started = time.monotonic()
        try:
            status = await asyncio.wait_for(probe._status(), timeout=0.5)
            assert status == 200
            assert time.monotonic() - started < 0.5
        finally:
            release.set()
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", NONFINITE)
def test_tmux_time_controls_must_be_finite(invalid: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        SubprocessTmuxCommandRunner(object(), timeout_s=invalid)
    with pytest.raises(ValueError, match="finite and positive"):
        TmuxPersistentSessionControl(command_timeout_s=invalid, runner=object())


@pytest.mark.parametrize("invalid", NONFINITE)
def test_server_profile_transport_time_controls_must_be_finite(invalid: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        ServerConnectionProfile("server-a", "example.invalid", 22, "ubuntu", connect_timeout_seconds=invalid)
    with pytest.raises(ValueError, match="finite and positive"):
        ServerConnectionProfile("server-a", "example.invalid", 22, "ubuntu", control_persist_seconds=invalid)


@pytest.mark.parametrize("invalid", NONFINITE)
def test_ssh_command_override_timeout_must_be_finite(invalid: float) -> None:
    profile = ServerConnectionProfile("server-a", "example.invalid", 22, "ubuntu")
    connection = SSHServerConnection(profile, operating_system=object(), runner=lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError, match="finite and positive"):
        connection.execute("true", timeout_seconds=invalid)


@pytest.mark.parametrize("invalid", NONFINITE)
def test_java_runtime_acquisition_timeout_must_be_finite(invalid: float) -> None:
    root = Path.cwd().resolve()
    with pytest.raises(ValueError, match="finite and positive"):
        JavaRuntimeProvisioningRequest(
            feature_version=21,
            platform=JavaRuntimePlatform("linux", "x64"),
            archive_path=str(root / "runtime.tar.gz"),
            destination=str(root / "java-home"),
            receipt_path=str(root / "runtime-receipt.json"),
            scope=PLATFORM_SCOPE,
            timeout_s=invalid,
        )


@pytest.mark.parametrize("invalid", NONFINITE)
def test_nvidia_smi_timeout_must_be_finite(invalid: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        NvidiaSmiGpuRuntimeObserver(object(), command_timeout_seconds=invalid)
