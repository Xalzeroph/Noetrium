from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    InMemoryMachineJournal,
    MachineCommand,
    MachineCommit,
    MachineConflict,
    MachineIntegrityError,
    TransitionProposal,
)


def make_commit(
    *,
    machine_id: str = "machine-1",
    command_id: str = "command-1",
    base_revision: int = 0,
    state: dict[str, object] | None = None,
    previous_commit_id: str | None = None,
) -> MachineCommit:
    command = MachineCommand(
        command_id=command_id,
        machine_id=machine_id,
        expected_revision=base_revision,
        kind="step",
        payload={"input": command_id},
        scope=(f"run:{machine_id}",),
    )
    proposal = TransitionProposal(
        machine_id=machine_id,
        command_id=command.command_id,
        base_revision=base_revision,
        state_delta=state or {"revision": base_revision + 1},
    )
    return MachineCommit(
        machine_id=machine_id,
        command_id=command.command_id,
        base_revision=base_revision,
        revision=base_revision + 1,
        proposal_digest=proposal.proposal_digest,
        command_digest=command.payload_digest,
        state=state or {"revision": base_revision + 1},
        previous_commit_id=previous_commit_id,
    )


def test_in_memory_journal_is_monotonic_and_idempotent() -> None:
    journal = InMemoryMachineJournal()
    first = make_commit()
    assert journal.append(first) == first
    assert journal.append(first) == first
    with pytest.raises(MachineConflict):
        journal.append(make_commit(command_id="other", base_revision=0))


def test_in_memory_journal_accepts_next_revision() -> None:
    journal = InMemoryMachineJournal()
    first = journal.append(make_commit())
    second = make_commit(
        command_id="command-2",
        base_revision=first.revision,
        state={"revision": 2},
        previous_commit_id=first.commit_id,
    )
    assert journal.append(second).revision == 2
    assert [item.revision for item in journal.commits("machine-1")] == [1, 2]


def test_directory_journal_survives_new_instance(tmp_path: Path) -> None:
    first = make_commit()
    journal = DirectoryMachineJournal(tmp_path)
    assert journal.append(first) == first
    restored = DirectoryMachineJournal(tmp_path)
    assert restored.latest("machine-1") == first
    assert restored.get(first.commit_id) == first


def test_directory_journal_rejects_non_canonical_record(tmp_path: Path) -> None:
    journal = DirectoryMachineJournal(tmp_path)
    first = make_commit()
    journal.append(first)
    path = next((tmp_path / "machines").glob("*.journal"))
    path.write_bytes(path.read_bytes().replace(b'"machine_id"', b' "machine_id"', 1))
    with pytest.raises(MachineIntegrityError):
        DirectoryMachineJournal(tmp_path).latest("machine-1")
