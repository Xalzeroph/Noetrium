from __future__ import annotations

from pathlib import Path

import pytest

import noetrium_platform.foundation.kernel.kernel.journal as journal_module
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    MachineCommand,
    MachineCommit,
    MachineIntegrityError,
    TransitionProposal,
)


def _commit(
    revision: int,
    *,
    previous_commit_id: str | None,
    machine_id: str = "scale-machine",
) -> MachineCommit:
    command_id = f"command-{revision:04d}"
    command = MachineCommand(
        command_id=command_id,
        machine_id=machine_id,
        expected_revision=revision - 1,
        kind="step",
        payload={"revision": revision},
        scope=(f"run:{machine_id}",),
    )
    proposal = TransitionProposal(
        machine_id=machine_id,
        command_id=command_id,
        base_revision=revision - 1,
        state_delta={"revision": revision},
    )
    return MachineCommit(
        machine_id=machine_id,
        command_id=command_id,
        base_revision=revision - 1,
        revision=revision,
        proposal_digest=proposal.proposal_digest,
        command_digest=command.payload_digest,
        state={"revision": revision},
        previous_commit_id=previous_commit_id,
    )


def test_single_writer_200_appends_do_not_redecode_committed_prefix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    decoded = 0
    original = journal_module._decode_commit

    def counted(value):
        nonlocal decoded
        decoded += 1
        return original(value)

    monkeypatch.setattr(journal_module, "_decode_commit", counted)
    journal = DirectoryMachineJournal(tmp_path)
    previous = None
    for revision in range(1, 201):
        commit = _commit(
            revision,
            previous_commit_id=previous,
        )
        accepted = journal.append(commit)
        assert accepted == commit
        previous = commit.commit_id

    assert decoded == 0
    assert journal.latest("scale-machine").revision == 200
    assert decoded == 0
    assert len(journal.commits("scale-machine")) == 200


def test_same_instance_detects_external_same_size_journal_tamper(
    tmp_path: Path,
) -> None:
    journal = DirectoryMachineJournal(tmp_path)
    first = _commit(1, previous_commit_id=None)
    journal.append(first)
    assert journal.latest("scale-machine") == first

    path = next((tmp_path / "machines").glob("*.journal"))
    raw = path.read_bytes()
    tampered = raw.replace(
        b'"machine_id":"scale-machine"',
        b'"machine_id":"scalz-machine"',
        1,
    )
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    with pytest.raises(MachineIntegrityError):
        journal.latest("scale-machine")


def test_two_journal_instances_revalidate_foreign_append_and_remain_idempotent(
    tmp_path: Path,
) -> None:
    first_writer = DirectoryMachineJournal(tmp_path)
    first = _commit(1, previous_commit_id=None)
    assert first_writer.append(first) == first

    second_writer = DirectoryMachineJournal(tmp_path)
    assert second_writer.latest("scale-machine") == first
    assert second_writer.append(first) == first

    second = _commit(
        2,
        previous_commit_id=first.commit_id,
    )
    assert second_writer.append(second) == second

    assert first_writer.latest("scale-machine") == second
    assert first_writer.get(first.commit_id) == first
    assert first_writer.get(second.commit_id) == second
    assert tuple(
        commit.revision
        for commit in first_writer.commits("scale-machine")
    ) == (1, 2)
