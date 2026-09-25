from __future__ import annotations

import math
from pathlib import Path

import pytest

from noetrium_platform.infrastructure.resources.compute.providers.nvidia_smi import NvidiaSmiGpuRuntimeObserver
from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime.command_runner import AsyncProcessCommandRunner
from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime.local_command import AsyncLocalCommandRunner
from noetrium_platform.infrastructure.lifecycle.server.identity.api.contracts import ServerConnectionProfile
from noetrium_platform.infrastructure.lifecycle.server.identity.providers.ssh_connection import SSHServerConnection
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from noetrium_platform.infrastructure.lifecycle.service.runtime.readiness import HttpEndpointReadinessProbe, ProcessAliveReadinessProbe
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
