from __future__ import annotations

from types import SimpleNamespace

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftRconEndpoint, MinecraftServerSpec
from noetrium_platform.capabilities.environment.minecraft.composition import (
    LocalMinecraftExperimentHostFactory,
    MinecraftExperimentHostInputs,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


class RecordingSourceServer:
    def __init__(self) -> None:
        self.contract = SimpleNamespace(digest=lambda: "a" * 64)
        self.process = {"pid": 101, "start_identity": "source-1"}
        self.started = False
        self.stopped = False
        self.create_generation: str | None = None

    def start(self) -> SimpleNamespace:
        self.started = True
        return SimpleNamespace(process=self.process)

    def reconcile(self) -> SimpleNamespace:
        # The host must retain the exact start identity if reconciliation is
        # temporarily incomplete; quiescence depends on that identity.
        return SimpleNamespace(process=None)

    def stop(self) -> SimpleNamespace:
        self.stopped = True
        return SimpleNamespace(stopped=True)


class RecordingSourceFactory:
    def __init__(self, server: RecordingSourceServer) -> None:
        self.server = server

    def create(self, spec, *, environment_generation: str) -> RecordingSourceServer:
        del spec
        self.server.create_generation = environment_generation
        return self.server


def _inputs(tmp_path):
    source_workdir = tmp_path / "source"
    source_workdir.mkdir()
    server_spec = MinecraftServerSpec(
        jar_path=str(tmp_path / "server.jar"),
        workdir=str(source_workdir),
        java_executable=str(tmp_path / "java"),
        rcon_endpoint=MinecraftRconEndpoint(port=25575),
    )
    server = RecordingSourceServer()
    return (
        server,
        MinecraftExperimentHostInputs(
            source_server_spec=server_spec,
            source_console=SimpleNamespace(),
            source_server_factory=RecordingSourceFactory(server),
            branch_server_factory=SimpleNamespace(),
            endpoint_allocations=SimpleNamespace(),
            environment_factory=SimpleNamespace(),
            snapshot_root=tmp_path / "snapshots",
            branch_root=tmp_path / "branches",
            source_environment_generation="source-generation-v1",
        ),
    )


def test_local_mc_experiment_host_composes_source_cut_and_branch_authorities(tmp_path) -> None:
    server, inputs = _inputs(tmp_path)

    host = LocalMinecraftExperimentHostFactory(inputs).open()

    assert host.world_cuts is not None
    assert host.branch_runtime_factory is not None
    assert server.create_generation == "source-generation-v1"

    host.start_source()
    assert host.process_identity_digest() == canonical_digest(server.process)
    host.stop_source()
    assert server.started is True
    assert server.stopped is True


def test_local_mc_experiment_host_rejects_source_without_rcon(tmp_path) -> None:
    _, inputs = _inputs(tmp_path)
    with pytest.raises(ValueError, match="RCON endpoint"):
        MinecraftExperimentHostInputs(
            source_server_spec=MinecraftServerSpec(
                jar_path=inputs.source_server_spec.jar_path,
                workdir=inputs.source_server_spec.workdir,
                java_executable=inputs.source_server_spec.java_executable,
            ),
            source_console=inputs.source_console,
            source_server_factory=inputs.source_server_factory,
            branch_server_factory=inputs.branch_server_factory,
            endpoint_allocations=inputs.endpoint_allocations,
            environment_factory=inputs.environment_factory,
            snapshot_root=inputs.snapshot_root,
            branch_root=inputs.branch_root,
            source_environment_generation=inputs.source_environment_generation,
        )
