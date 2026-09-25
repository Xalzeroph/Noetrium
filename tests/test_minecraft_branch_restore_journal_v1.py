from __future__ import annotations

import json

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftWorldCut
from noetrium_platform.capabilities.environment.minecraft.providers.branch_restore_journal import (
    MinecraftBranchCheckpointError,
    MinecraftBranchRestoreJournal,
)


GENERATION = "c" * 64
CONTRACT = "a" * 64
MANIFEST = "b" * 64


def _cut() -> MinecraftWorldCut:
    return MinecraftWorldCut(
        cut_id="minecraft-cut:journal",
        snapshot_ref="snapshot:journal",
        manifest_ref="manifest:journal",
        level_name="research-world",
        server_contract_digest=CONTRACT,
        process_identity_digest="d" * 64,
        manifest_digest=MANIFEST,
        save_evidence_ref="save:journal",
    )


def _journal(tmp_path) -> tuple[MinecraftBranchRestoreJournal, object]:
    workdir = tmp_path / "branch-server"
    workdir.mkdir()
    path = tmp_path / ".branch-server.checkpoint-restore.json"
    journal = MinecraftBranchRestoreJournal(
        path=path,
        environment_generation=GENERATION,
        server_workdir=str(workdir),
        level_name="research-world",
        contract_digest=lambda: CONTRACT,
    )
    return journal, workdir


def test_journal_round_trip_and_clear(tmp_path) -> None:
    journal, workdir = _journal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"
    document = journal.publish(
        journal.build(cut=_cut(), backup=backup, phase="prepared")
    )

    assert journal.load() == document
    assert journal.set_phase(document, "committed")["phase"] == "committed"
    journal.clear()
    assert journal.load() is None


def test_journal_rejects_record_digest_tamper(tmp_path) -> None:
    journal, workdir = _journal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"
    journal.publish(journal.build(cut=_cut(), backup=backup, phase="prepared"))
    document = json.loads(journal.path.read_text(encoding="utf-8"))
    document["cut_id"] = "minecraft-cut:tampered"
    journal.path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(MinecraftBranchCheckpointError, match="digest mismatch"):
        journal.load()


def test_journal_rejects_backup_outside_workdir_parent(tmp_path) -> None:
    journal, _workdir = _journal(tmp_path)
    backup = tmp_path / "outside" / ".branch-server.checkpoint-backup-test"
    journal.publish(journal.build(cut=_cut(), backup=backup, phase="prepared"))

    with pytest.raises(MinecraftBranchCheckpointError, match="backup path is invalid"):
        journal.load()


def test_journal_rejects_environment_identity_drift(tmp_path) -> None:
    journal, workdir = _journal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"
    document = journal.build(cut=_cut(), backup=backup, phase="prepared")
    document["environment_generation"] = "e" * 64
    journal.publish(document)

    with pytest.raises(MinecraftBranchCheckpointError, match="generation mismatch"):
        journal.load()


def test_journal_rejects_unknown_phase_before_publish(tmp_path) -> None:
    journal, workdir = _journal(tmp_path)
    backup = workdir.parent / f".{workdir.name}.checkpoint-backup-test"

    with pytest.raises(ValueError, match="unsupported restore phase"):
        journal.build(cut=_cut(), backup=backup, phase="unknown")
