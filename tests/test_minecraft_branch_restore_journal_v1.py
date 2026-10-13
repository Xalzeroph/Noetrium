from __future__ import annotations

import json

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftWorldCut
from noetrium_platform.capabilities.environment.minecraft.providers.branch_restore_wal import (
    MinecraftBranchCheckpointError,
    MinecraftBranchRestoreWal,
)


GENERATION = "c" * 64
CONTRACT = "a" * 64
MANIFEST = "b" * 64


def _cut() -> MinecraftWorldCut:
    return MinecraftWorldCut(
        cut_id="minecraft-cut:wal",
        snapshot_ref="snapshot:wal",
        manifest_ref="manifest:wal",
        level_name="research-world",
        server_contract_digest=CONTRACT,
        process_identity_digest="d" * 64,
        manifest_digest=MANIFEST,
        save_evidence_ref="save:wal",
    )


def _wal(tmp_path) -> tuple[MinecraftBranchRestoreWal, object]:
    workdir = tmp_path / "branch-server"
    workdir.mkdir()
    path = tmp_path / ".branch-server.checkpoint-restore.json"
    wal = MinecraftBranchRestoreWal(
        path=path,
        environment_generation=GENERATION,
        server_workdir=str(workdir),
        level_name="research-world",
        contract_digest=lambda: CONTRACT,
    )
    return wal, workdir


def test_wal_round_trip_and_clear(tmp_path) -> None:
    wal, workdir = _wal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"
    document = wal.publish(
        wal.build(cut=_cut(), backup=backup, phase="prepared")
    )

    assert wal.load() == document
    assert wal.set_phase(document, "committed")["phase"] == "committed"
    wal.clear()
    assert wal.load() is None


def test_wal_rejects_record_digest_tamper(tmp_path) -> None:
    wal, workdir = _wal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"
    wal.publish(wal.build(cut=_cut(), backup=backup, phase="prepared"))
    document = json.loads(wal.path.read_text(encoding="utf-8"))
    document["cut_id"] = "minecraft-cut:tampered"
    wal.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(MinecraftBranchCheckpointError, match="digest mismatch"):
        wal.load()


def test_wal_rejects_backup_outside_workdir_parent(tmp_path) -> None:
    wal, _workdir = _wal(tmp_path)
    backup = tmp_path / "outside" / ".branch-server.checkpoint-backup-test"
    wal.publish(wal.build(cut=_cut(), backup=backup, phase="prepared"))

    with pytest.raises(MinecraftBranchCheckpointError, match="backup path is invalid"):
        wal.load()


def test_wal_rejects_environment_identity_drift(tmp_path) -> None:
    wal, workdir = _wal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"
    document = wal.build(cut=_cut(), backup=backup, phase="prepared")
    document["environment_generation"] = "e" * 64
    wal.publish(document)

    with pytest.raises(MinecraftBranchCheckpointError, match="generation mismatch"):
        wal.load()


def test_wal_rejects_unknown_phase_before_publish(tmp_path) -> None:
    wal, workdir = _wal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"

    with pytest.raises(ValueError, match="unsupported restore phase"):
        wal.build(cut=_cut(), backup=backup, phase="unknown")
