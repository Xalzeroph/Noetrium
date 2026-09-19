from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from noetrium_platform.infrastructure.lifecycle.service.runtime.environment import (
    MaterializedServiceEnvironment,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.preflight import (
    LocalServiceLaunchPreflight,
    ServiceLaunchPreflightError,
)



def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def service_contract(tmp_path: Path) -> ServiceLaunchContract:
    environment = MaterializedServiceEnvironment.from_mapping({"PATH": "/usr/bin"}, "env:test")
    return ServiceLaunchContract(
        service_id="test.service",
        generation="test-v1",
        executable="/bin/sh",
        argv=("/bin/sh", "-c", "true"),
        cwd=str(tmp_path),
        environment_digest=environment.digest,
        artifact_digest=digest("artifact"),
        runtime_identity_digest=digest("runtime"),
        readiness_timeout_s=1.0,
        stop_timeout_s=1.0,
        heartbeat_interval_s=1.0,
    )


def test_service_preflight_reports_missing_runtime_inputs(tmp_path: Path) -> None:
    contract = service_contract(tmp_path)
    environment = MaterializedServiceEnvironment.from_mapping({"PATH": "/usr/bin"}, "env:test")
    required = tmp_path / "server.properties"
    report = LocalServiceLaunchPreflight(required_paths=(str(required),)).inspect(contract, environment)
    assert not report.ready
    assert "required service resource is missing" in report.errors[0]
    with pytest.raises(ServiceLaunchPreflightError):
        LocalServiceLaunchPreflight(required_paths=(str(required),)).validate(contract, environment)


def test_service_preflight_accepts_complete_runtime_inputs(tmp_path: Path) -> None:
    required = tmp_path / "server.properties"
    required.write_text("motd=test", encoding="utf-8")
    contract = service_contract(tmp_path)
    environment = MaterializedServiceEnvironment.from_mapping({"PATH": "/usr/bin"}, "env:test")
    report = LocalServiceLaunchPreflight(required_paths=(str(required),)).validate(contract, environment)
    assert report.ready
    assert all(passed for _, passed in report.checks)


def test_service_preflight_requires_absolute_paths() -> None:
    with pytest.raises(ValueError, match="absolute"):
        LocalServiceLaunchPreflight(required_paths=("relative/server.properties",))


def test_minecraft_preflight_derives_prepared_server_files(tmp_path: Path) -> None:
    from noetrium_platform.capabilities.environment.minecraft.api import MinecraftServerSpec
    from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
        build_minecraft_server_preflight,
    )

    spec = MinecraftServerSpec(
        jar_path=str(tmp_path / "server.jar"),
        workdir=str(tmp_path),
        java_executable="/usr/bin/java",
    )
    preflight = build_minecraft_server_preflight(spec)
    assert preflight.required_paths == (
        str(tmp_path / "eula.txt"),
        str(tmp_path / "server.properties"),
    )
