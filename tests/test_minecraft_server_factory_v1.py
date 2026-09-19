from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._concurrency_support import make_task_group

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftRconEndpoint, MinecraftServerSpec
from noetrium_platform.capabilities.environment.minecraft.composition import (
    MinecraftServerServiceError,
    MinecraftServerServiceFactory,
    MinecraftServerServiceFactoryConfig,
    MinecraftServerReadinessProbe,
    MinecraftTcpReadinessProbe,
    build_server_service_contract,
)
from noetrium_platform.capabilities.environment.minecraft.providers.server_files import MinecraftServerPreparationError, sha256_file
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.service.runtime.environment import MaterializedServiceEnvironment


def _spec(root: Path) -> MinecraftServerSpec:
    jar = root / "server.jar"
    jar.write_bytes(b"frozen-minecraft-server-artifact")
    return MinecraftServerSpec(
        jar_path=str(jar),
        workdir=str(root / "world"),
        java_executable="/usr/bin/java",
        host="127.0.0.1",
        port=25566,
        level_name="branch-world",
    )


def _config(root: Path, *, accept_eula: bool) -> MinecraftServerServiceFactoryConfig:
    return MinecraftServerServiceFactoryConfig(
        environment=MaterializedServiceEnvironment.from_mapping(
            {"JAVA_HOME": "/usr"},
            "env:evidence",
        ),
        state_root=root / "state",
        intent_root=root / "intents",
        capture_root=root / "captures",
        operating_system=LocalOperatingSystemRoute(),
        accept_eula=accept_eula,
        process_backend=object(),
        task_group=make_task_group("minecraft-server-factory"),
    )


def test_server_factory_prepares_files_and_builds_exact_service_contract_without_starting(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    controller = MinecraftServerServiceFactory(_config(tmp_path, accept_eula=True)).create(
        spec,
        environment_generation="e" * 64,
    )

    assert controller.contract.artifact_digest == sha256_file(spec.jar_path)
    assert len(controller.contract.generation) == 64
    assert (Path(spec.workdir) / "eula.txt").read_text(encoding="utf-8") == "eula=true\n"
    properties = (Path(spec.workdir) / "server.properties").read_text(encoding="utf-8")
    assert "gamemode=survival" in properties
    assert "force-gamemode=true" in properties


def test_server_command_uses_explicit_recursive_libraries_for_non_fat_vanilla_server(tmp_path: Path) -> None:
    libraries = tmp_path / "libraries" / "example"
    libraries.mkdir(parents=True)
    dependency = libraries / "dependency.jar"
    dependency.write_bytes(b"dependency")
    spec = _spec(tmp_path)
    spec = replace(spec, libraries_dir=str(tmp_path / "libraries"))

    command = spec.command()

    assert command[3] == "-cp"
    assert str(Path(spec.jar_path)) in command[4]
    assert str(dependency) in command[4]
    assert command[5:7] == ("net.minecraft.server.Main", "nogui")


def test_server_factory_requires_explicit_eula_policy(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with pytest.raises(MinecraftServerPreparationError, match="EULA_ACCEPTANCE_REQUIRED"):
        MinecraftServerServiceFactory(_config(tmp_path, accept_eula=False)).create(
            spec,
            environment_generation="e" * 64,
        )


def test_server_factory_sanitizes_rcon_secret_provider_failure(tmp_path: Path) -> None:
    spec = replace(_spec(tmp_path), rcon_endpoint=MinecraftRconEndpoint())
    config = replace(
        _config(tmp_path, accept_eula=True),
        rcon_password_provider=lambda: (_ for _ in ()).throw(RuntimeError("secret-value")),
    )
    with pytest.raises(MinecraftServerServiceError) as caught:
        MinecraftServerServiceFactory(config).create(spec, environment_generation="e" * 64)
    assert "secret-value" not in str(caught.value)
    assert "secret is unavailable" in str(caught.value)


def test_server_readiness_requires_rcon_after_tcp_and_retries_connection_refused(tmp_path: Path) -> None:
    class Tcp:
        def wait_ready(self, process, contract, backend):
            del process, contract, backend
            return "tcp-ready"

    class Rcon:
        def __init__(self) -> None:
            self.attempts = 0

        def execute(self, command, *, timeout_s):
            assert command == "list"
            assert timeout_s > 0
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionRefusedError("RCON listener is still starting")
            return SimpleNamespace(evidence_ref="rcon-ready")

    class Backend:
        def alive(self, process):
            del process
            return True

    spec = _spec(tmp_path)
    contract = build_server_service_contract(
        spec,
        environment_digest="a" * 64,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
        readiness_timeout_s=2,
    )
    probe = MinecraftServerReadinessProbe(
        tcp=Tcp(),  # type: ignore[arg-type]
        rcon=Rcon(),  # type: ignore[arg-type]
        poll_interval_s=0.001,
    )

    evidence = probe.wait_ready(SimpleNamespace(pid=1, start_identity="start"), contract, Backend())

    assert evidence.startswith("minecraft-server-ready:")
    assert probe.rcon.attempts == 2  # type: ignore[attr-defined]


def test_tcp_readiness_runs_network_connect_on_async_io_lane(monkeypatch, tmp_path: Path) -> None:
    class Writer:
        def __init__(self) -> None:
            self.closed = False
            self.waited = False

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            self.waited = True

    writer = Writer()
    calls: list[tuple[str, int]] = []

    async def open_connection(host: str, port: int):
        calls.append((host, port))
        return object(), writer

    monkeypatch.setattr(
        "noetrium_platform.capabilities.environment.minecraft.composition.server_service.asyncio.open_connection",
        open_connection,
    )

    class Backend:
        def alive(self, process):
            del process
            return True

    spec = _spec(tmp_path)
    contract = build_server_service_contract(
        spec,
        environment_digest="a" * 64,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
        readiness_timeout_s=1,
    )
    probe = MinecraftTcpReadinessProbe(
        host=spec.host,
        port=spec.port,
        task_group=make_task_group("minecraft-tcp-readiness"),
        poll_interval_s=0.001,
    )

    evidence = probe.wait_ready(
        SimpleNamespace(pid=7, start_identity="start"),
        contract,
        Backend(),
    )

    assert evidence.startswith("minecraft-tcp-ready:")
    assert calls == [(spec.host, spec.port)]
    assert writer.closed is True
    assert writer.waited is True



def test_tcp_readiness_identity_is_unique_across_probe_instances_sharing_one_group(tmp_path: Path, monkeypatch) -> None:
    async def open_connection(host: str, port: int):
        class Writer:
            def close(self) -> None: pass
            async def wait_closed(self) -> None: pass
        return object(), Writer()

    monkeypatch.setattr(
        "noetrium_platform.capabilities.environment.minecraft.composition.server_service.asyncio.open_connection",
        open_connection,
    )

    class Backend:
        def alive(self, process):
            del process
            return True

    spec = _spec(tmp_path)
    contract = build_server_service_contract(
        spec,
        environment_digest="a" * 64,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
        readiness_timeout_s=1,
    )
    group = make_task_group("minecraft-shared-readiness")
    first = MinecraftTcpReadinessProbe(host=spec.host, port=25566, task_group=group, poll_interval_s=0.001)
    second = MinecraftTcpReadinessProbe(host=spec.host, port=25567, task_group=group, poll_interval_s=0.001)

    first_evidence = first.wait_ready(SimpleNamespace(pid=7, start_identity="first"), contract, Backend())
    second_evidence = second.wait_ready(SimpleNamespace(pid=8, start_identity="second"), contract, Backend())

    assert first_evidence.startswith("minecraft-tcp-ready:")
    assert second_evidence.startswith("minecraft-tcp-ready:")
    assert first_evidence != second_evidence
