from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_bytes

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftServerSpec,
    MinecraftWorldQuiescence,
)
from noetrium_platform.capabilities.environment.minecraft.providers.world_cut import (
    FilesystemMinecraftBranchCheckpointProvider,
    FilesystemMinecraftWorldCopier,
    FilesystemMinecraftWorldCutProvider,
    MinecraftBranchCheckpointError,
    MinecraftWorldCutError,
    ReflinkMinecraftWorldCopier,
)


class _QuiescenceDouble:
    def __init__(self, source_workdir: str) -> None:
        self.source_workdir = source_workdir
        self.saved: list[tuple[str, object]] = []
        self.resumed: list[tuple[str, str]] = []
        self.resume_error: BaseException | None = None

    def save_and_quiesce(self, *, session_id: str, context: object) -> MinecraftWorldQuiescence:
        self.saved.append((session_id, context))
        return MinecraftWorldQuiescence(
            source_workdir=self.source_workdir,
            level_name="research-world",
            server_contract_digest="a" * 64,
            process_identity_digest="b" * 64,
            save_evidence_ref="minecraft-save-evidence:test",
        )

    def resume(
        self,
        quiescence: MinecraftWorldQuiescence,
        *,
        session_id: str,
        context: object,
    ) -> None:
        del context
        self.resumed.append((session_id, quiescence.save_evidence_ref))
        if self.resume_error is not None:
            raise self.resume_error


def _portable_metadata_writer(path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _source_world(tmp_path):
    source = tmp_path / "source-world"
    level = source / "research-world"
    level.mkdir(parents=True)
    (source / "server.properties").write_text("level-name=research-world\n", encoding="utf-8")
    (source / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (level / "level.dat").write_bytes(b"level-dat")
    (level / "region").mkdir()
    (level / "region" / "r.0.0.mca").write_bytes(b"region")
    (source / "logs").mkdir()
    (source / "logs" / "latest.log").write_bytes(b"volatile log")
    (source / "crash-reports").mkdir()
    (source / "crash-reports" / "crash.txt").write_bytes(b"volatile crash")
    (level / "session.lock").write_bytes(b"volatile lock")
    return source


def _provider(tmp_path, source):
    quiescence = _QuiescenceDouble(str(source))
    provider = FilesystemMinecraftWorldCutProvider(
        quiescence=quiescence,
        snapshot_root=tmp_path / "cuts",
        branch_root=tmp_path / "branches",
        metadata_writer=_portable_metadata_writer,
    )
    return provider, quiescence


def test_world_cut_capture_materializes_verified_branch_and_releases_it(tmp_path) -> None:
    source = _source_world(tmp_path)
    provider, control = _provider(tmp_path, source)

    cut = provider.capture(session_id="session-1", context=None)

    assert control.saved == [("session-1", None)]
    assert control.resumed == [("session-1", "minecraft-save-evidence:test")]
    manifest = json.loads((tmp_path / "cuts").rglob("manifest.json").__next__().read_text())
    paths = {row["path"] for row in manifest["files"]}
    assert "research-world/level.dat" in paths
    assert "logs/latest.log" not in paths
    assert "research-world/session.lock" not in paths

    branch = provider.materialize_branch(
        cut,
        branch_id="candidate-1",
        destination_workdir=str(tmp_path / "branches" / "candidate-1"),
    )
    assert (tmp_path / "branches" / "candidate-1" / "research-world" / "level.dat").read_bytes() == b"level-dat"
    assert not (tmp_path / "branches" / "candidate-1" / "logs").exists()
    assert provider.release_branch(branch) == branch.cleanup_ref
    assert not (tmp_path / "branches" / "candidate-1").exists()


def test_reflink_copier_requires_reflink_and_never_silently_falls_back(tmp_path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 1, "", "reflink unsupported")

    copier = ReflinkMinecraftWorldCopier(
        cp_executable="cp",
        runner=runner,
        platform_name="posix",
    )
    with pytest.raises(MinecraftWorldCutError, match="REFLINK_COPY_FAILED"):
        copier.copy(tmp_path / "source", tmp_path / "destination")
    assert "--reflink=always" in calls[0][0]
    assert "--reflink=auto" not in calls[0][0]


def test_reflink_copier_uses_only_explicit_fallback_and_reports_capability_failure(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "world.dat").write_bytes(b"world")
    reasons: list[str] = []

    def runner(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(command, 1, "", "Operation not supported")

    copier = ReflinkMinecraftWorldCopier(
        cp_executable="cp",
        runner=runner,
        platform_name="posix",
        fallback_copier=FilesystemMinecraftWorldCopier(),
        fallback_reporter=reasons.append,
    )
    destination = tmp_path / "destination"
    copier.copy(source, destination)

    assert (destination / "world.dat").read_bytes() == b"world"
    assert reasons == ["Operation not supported"]


def test_reflink_copier_rejects_non_posix_target_explicitly(tmp_path) -> None:
    copier = ReflinkMinecraftWorldCopier(platform_name="nt")
    with pytest.raises(MinecraftWorldCutError, match="REFLINK_UNSUPPORTED_PLATFORM"):
        copier.copy(tmp_path / "source", tmp_path / "destination")


def test_reflink_copier_prunes_nested_volatile_entries_after_verified_copy(tmp_path) -> None:
    def runner(command, **kwargs):
        del kwargs
        destination = Path(command[-1])
        (destination / "nested" / "logs").mkdir(parents=True)
        (destination / "nested" / "logs" / "latest.log").write_text("volatile")
        (destination / "nested" / "session.lock").write_text("volatile")
        (destination / "research-world").mkdir()
        (destination / "research-world" / "level.dat").write_bytes(b"level")
        return subprocess.CompletedProcess(command, 0, "", "")

    destination = tmp_path / "destination"
    ReflinkMinecraftWorldCopier(
        cp_executable="cp",
        runner=runner,
        platform_name="posix",
    ).copy(tmp_path / "source", destination)

    assert not (destination / "nested" / "logs").exists()
    assert not (destination / "nested" / "session.lock").exists()


def test_world_cut_default_metadata_writer_matches_controller_platform(tmp_path) -> None:
    source = _source_world(tmp_path)
    control = _QuiescenceDouble(str(source))
    provider = FilesystemMinecraftWorldCutProvider(
        quiescence=control,
        snapshot_root=tmp_path / "cuts",
        branch_root=tmp_path / "branches",
    )

    cut = provider.capture(session_id="session-1", context=None)

    assert cut.manifest_digest
    assert control.resumed == [("session-1", "minecraft-save-evidence:test")]


def test_world_cut_rejects_tampered_snapshot_before_branch_copy(tmp_path) -> None:
    source = _source_world(tmp_path)
    provider, _control = _provider(tmp_path, source)
    cut = provider.capture(session_id="session-1", context=None)

    payload = tmp_path / "cuts" / "cuts"
    payload_file = next(payload.rglob("payload/research-world/level.dat"))
    payload_file.write_bytes(b"tampered")

    with pytest.raises(MinecraftWorldCutError, match="SNAPSHOT_CONTENT_MISMATCH"):
        provider.materialize_branch(
            cut,
            branch_id="candidate-1",
            destination_workdir=str(tmp_path / "branches" / "candidate-1"),
        )
    assert not (tmp_path / "branches" / "candidate-1").exists()


def test_world_cut_preserves_capture_error_when_resume_succeeds(tmp_path) -> None:
    source = tmp_path / "source-world"
    source.mkdir()
    provider, control = _provider(tmp_path, source)

    with pytest.raises(MinecraftWorldCutError, match="SOURCE_LEVEL_MISSING"):
        provider.capture(session_id="session-1", context=None)
    assert control.resumed == [("session-1", "minecraft-save-evidence:test")]


def test_world_cut_reports_resume_failure_without_claiming_capture_success(tmp_path) -> None:
    source = _source_world(tmp_path)
    provider, control = _provider(tmp_path, source)
    control.resume_error = RuntimeError("server did not resume")

    with pytest.raises(MinecraftWorldCutError, match="RESUME_FAILED") as raised:
        provider.capture(session_id="session-1", context=None)
    assert raised.value.code == "RESUME_FAILED"

class _CheckpointContractDouble:
    def digest(self) -> str:
        return "a" * 64


class _CheckpointReadyObservation:
    def __init__(self, ready_at: float) -> None:
        self.ready_at = ready_at


class _CheckpointEndpointBindingDouble:
    def __init__(self) -> None:
        self.calls: list[_CheckpointReadyObservation] = []

    def bind_ready(self, readiness) -> None:
        self.calls.append(readiness)


class _CheckpointServerDouble:
    def __init__(self, *, stop_error: BaseException | None = None) -> None:
        self.contract = _CheckpointContractDouble()
        self.calls: list[str] = []
        self.stop_error = stop_error

    def stop(self) -> None:
        self.calls.append("stop")
        if self.stop_error is not None:
            raise self.stop_error

    def start(self) -> None:
        self.calls.append("start")

    def verify_ready(self):
        self.calls.append("ready")
        return _CheckpointReadyObservation(1000.0 + self.calls.count("start"))


def _branch_checkpoint_fixture(tmp_path):
    source = _source_world(tmp_path)
    world_cuts, _control = _provider(tmp_path, source)
    cut = world_cuts.capture(session_id="checkpoint-source", context=None)
    workdir = tmp_path / "branch-server"
    shutil.copytree(source, workdir)
    (workdir / "research-world" / "level.dat").write_bytes(b"branch-current")
    jar = tmp_path / "server.jar"
    jar.write_bytes(b"jar")
    spec = MinecraftServerSpec(
        jar_path=str(jar),
        workdir=str(workdir),
        java_executable=str(tmp_path / "java"),
        level_name="research-world",
    )
    server = _CheckpointServerDouble()
    provider = FilesystemMinecraftBranchCheckpointProvider(
        server=server,
        server_spec=spec,
        world_cuts=world_cuts,
        environment_generation="c" * 64,
        endpoint_binding=_CheckpointEndpointBindingDouble(),
    )
    payload = canonical_bytes(
        {
            "schema_version": provider._SCHEMA,
            "environment_generation": "c" * 64,
            "server_contract_digest": "a" * 64,
            "server_workdir": str(workdir),
            "level_name": "research-world",
            "cut": cut,
        }
    )
    return provider, server, spec, world_cuts, cut, payload, workdir


def test_branch_checkpoint_restore_publishes_commit_before_deleting_backup(tmp_path) -> None:
    provider, server, _spec, _world_cuts, _cut, payload, workdir = _branch_checkpoint_fixture(tmp_path)

    provider.restore(payload, session_id="branch-session", context=None)

    assert (workdir / "research-world" / "level.dat").read_bytes() == b"level-dat"
    assert server.calls == ["stop", "start", "ready"]
    assert len(provider._endpoint_binding.calls) == 1
    assert provider._endpoint_binding.calls[0].ready_at == 1001.0
    assert not provider._restore_journal_path.exists()
    assert not tuple(workdir.parent.glob(f".{workdir.name}.checkpoint-backup-*"))


def test_branch_checkpoint_reconstructs_precommit_crash_by_rolling_back_backup(tmp_path) -> None:
    provider, _server, spec, world_cuts, cut, _payload, workdir = _branch_checkpoint_fixture(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-crash"
    document = provider._publish_restore_document(
        provider._restore_document(cut=cut, backup=backup, phase="prepared")
    )
    workdir.rename(backup)
    workdir.mkdir()
    (workdir / "partial.txt").write_text("partial", encoding="utf-8")
    provider._set_restore_phase(document, "backup_published")

    recovered_server = _CheckpointServerDouble()
    recovered = FilesystemMinecraftBranchCheckpointProvider(
        server=recovered_server,
        server_spec=spec,
        world_cuts=world_cuts,
        environment_generation="c" * 64,
        endpoint_binding=_CheckpointEndpointBindingDouble(),
    )

    assert (workdir / "research-world" / "level.dat").read_bytes() == b"branch-current"
    assert not (workdir / "partial.txt").exists()
    assert not backup.exists()
    assert not recovered._restore_journal_path.exists()
    assert recovered_server.calls == ["stop", "start", "ready"]
    assert len(recovered._endpoint_binding.calls) == 1
    assert recovered._endpoint_binding.calls[0].ready_at == 1001.0


def test_branch_checkpoint_reconstructs_postcommit_crash_without_rollback(tmp_path) -> None:
    provider, _server, spec, world_cuts, cut, _payload, workdir = _branch_checkpoint_fixture(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-committed"
    document = provider._publish_restore_document(
        provider._restore_document(cut=cut, backup=backup, phase="prepared")
    )
    workdir.rename(backup)
    snapshot, _manifest = world_cuts._read_cut(cut)
    world_cuts.copier.copy(snapshot, workdir)
    document = provider._set_restore_phase(document, "backup_published")
    provider._set_restore_phase(document, "committed")

    recovered_server = _CheckpointServerDouble()
    recovered = FilesystemMinecraftBranchCheckpointProvider(
        server=recovered_server,
        server_spec=spec,
        world_cuts=world_cuts,
        environment_generation="c" * 64,
        endpoint_binding=_CheckpointEndpointBindingDouble(),
    )

    assert (workdir / "research-world" / "level.dat").read_bytes() == b"level-dat"
    assert not backup.exists()
    assert not recovered._restore_journal_path.exists()
    assert recovered_server.calls == []
    assert recovered._endpoint_binding.calls == []


def test_branch_checkpoint_rejects_restore_journal_identity_drift_before_mutation(tmp_path) -> None:
    provider, _server, spec, world_cuts, cut, _payload, workdir = _branch_checkpoint_fixture(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-drift"
    document = provider._restore_document(cut=cut, backup=backup, phase="prepared")
    document["environment_generation"] = "d" * 64
    provider._publish_restore_document(document)
    recovered_server = _CheckpointServerDouble()

    with pytest.raises(MinecraftBranchCheckpointError, match="generation mismatch"):
        FilesystemMinecraftBranchCheckpointProvider(
            server=recovered_server,
            server_spec=spec,
            world_cuts=world_cuts,
            environment_generation="c" * 64,
            endpoint_binding=_CheckpointEndpointBindingDouble(),
        )

    assert recovered_server.calls == []
    assert (workdir / "research-world" / "level.dat").read_bytes() == b"branch-current"

def test_branch_checkpoint_recovers_crash_after_rename_before_phase_advance(tmp_path) -> None:
    provider, _server, spec, world_cuts, cut, _payload, workdir = _branch_checkpoint_fixture(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-prephase"
    provider._publish_restore_document(
        provider._restore_document(cut=cut, backup=backup, phase="prepared")
    )
    workdir.rename(backup)

    recovered_server = _CheckpointServerDouble()
    recovered = FilesystemMinecraftBranchCheckpointProvider(
        server=recovered_server,
        server_spec=spec,
        world_cuts=world_cuts,
        environment_generation="c" * 64,
        endpoint_binding=_CheckpointEndpointBindingDouble(),
    )

    assert (workdir / "research-world" / "level.dat").read_bytes() == b"branch-current"
    assert not backup.exists()
    assert not recovered._restore_journal_path.exists()
    assert recovered_server.calls == ["stop", "start", "ready"]


def test_branch_checkpoint_recovery_stop_failure_never_mutates_filesystem(tmp_path) -> None:
    provider, _server, spec, world_cuts, cut, _payload, workdir = _branch_checkpoint_fixture(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-stop-failure"
    provider._publish_restore_document(
        provider._restore_document(cut=cut, backup=backup, phase="prepared")
    )
    workdir.rename(backup)

    recovered_server = _CheckpointServerDouble(stop_error=RuntimeError("cannot stop"))
    with pytest.raises(MinecraftBranchCheckpointError, match="filesystem state was not touched"):
        FilesystemMinecraftBranchCheckpointProvider(
            server=recovered_server,
            server_spec=spec,
            world_cuts=world_cuts,
            environment_generation="c" * 64,
            endpoint_binding=_CheckpointEndpointBindingDouble(),
        )

    assert not workdir.exists()
    assert (backup / "research-world" / "level.dat").read_bytes() == b"branch-current"
    assert provider._restore_journal_path.exists()
    assert recovered_server.calls == ["stop"]


def test_branch_checkpoint_rejects_restore_journal_phase_corruption(tmp_path) -> None:
    provider, _server, spec, world_cuts, cut, _payload, workdir = _branch_checkpoint_fixture(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-corrupt"
    provider._publish_restore_document(
        provider._restore_document(cut=cut, backup=backup, phase="prepared")
    )
    document = json.loads(provider._restore_journal_path.read_text(encoding="utf-8"))
    document["phase"] = "committed"
    provider._restore_journal_path.write_bytes(canonical_bytes(document))
    recovered_server = _CheckpointServerDouble()

    with pytest.raises(MinecraftBranchCheckpointError, match="digest mismatch"):
        FilesystemMinecraftBranchCheckpointProvider(
            server=recovered_server,
            server_spec=spec,
            world_cuts=world_cuts,
            environment_generation="c" * 64,
            endpoint_binding=_CheckpointEndpointBindingDouble(),
        )

    assert recovered_server.calls == []
    assert (workdir / "research-world" / "level.dat").read_bytes() == b"branch-current"
