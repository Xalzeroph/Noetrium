
from __future__ import annotations

from pathlib import Path

import pytest

import noetrium_platform.foundation.kernel.kernel.journal as journal_module
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    MachineCommand,
    MachineCommit,
    MachineIntegrityError,
    MachineStateDelta,
    MachineStateMutation,
    TransitionProposal,
)


def _commit(
    revision: int,
    *,
    previous_commit_id: str | None,
    machine_id: str = "anchor-machine",
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
        state_delta=MachineStateDelta((
            MachineStateMutation(("revision",), revision),
        )),
    )
    return MachineCommit(
        machine_id=machine_id,
        command_id=command_id,
        base_revision=revision - 1,
        revision=revision,
        proposal_digest=proposal.proposal_digest,
        command_digest=command.payload_digest,
        program_digest="f" * 64,
        program_lock_digest="e" * 64,
        state={"revision": revision},
        previous_commit_id=previous_commit_id,
    )


def _populate(root: Path, revisions: int = 520) -> tuple[MachineCommit, ...]:
    journal = DirectoryMachineJournal(root)
    rows: list[MachineCommit] = []
    previous = None
    for revision in range(1, revisions + 1):
        commit = _commit(revision, previous_commit_id=previous)
        journal.append(commit)
        rows.append(commit)
        previous = commit.commit_id
    return tuple(rows)


def test_cold_head_uses_recovery_anchor_and_decodes_only_tail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _populate(tmp_path)
    decoded = 0
    original = journal_module._decode_commit

    def counted(value, *, previous_state=None):
        nonlocal decoded
        decoded += 1
        return original(value, previous_state=previous_state)

    monkeypatch.setattr(journal_module, "_decode_commit", counted)
    cold = DirectoryMachineJournal(tmp_path)
    latest, _has_emitted = cold.head("anchor-machine")

    assert latest is not None
    assert latest.revision == 520
    # revision 512 is the anchor; only the anchor plus 8 tail commits need
    # semantic decode. The validated prefix is committed by its SHA-256.
    assert decoded <= 9


def test_prefix_command_lookup_falls_back_to_full_history(
    tmp_path: Path,
) -> None:
    rows = _populate(tmp_path)
    cold = DirectoryMachineJournal(tmp_path)
    assert cold.latest("anchor-machine") == rows[-1]

    historical = cold.command_commit("anchor-machine", "command-0100")
    assert historical == rows[99]
    assert cold.commits("anchor-machine") == rows


def test_stale_or_corrupt_anchor_never_weakens_journal_validation(
    tmp_path: Path,
) -> None:
    _populate(tmp_path)
    anchor = next((tmp_path / "recovery-anchors").glob("*.json"))
    anchor.write_bytes(b'{"corrupt":true}')

    cold = DirectoryMachineJournal(tmp_path)
    latest = cold.latest("anchor-machine")
    assert latest is not None
    assert latest.revision == 520

    journal_path = next((tmp_path / "machines").glob("*.journal"))
    raw = journal_path.read_bytes()
    tampered = raw.replace(
        b'"machine_id":"anchor-machine"',
        b'"machine_id":"anch0r-machine"',
        1,
    )
    assert len(tampered) == len(raw)
    journal_path.write_bytes(tampered)

    with pytest.raises(MachineIntegrityError):
        DirectoryMachineJournal(tmp_path).latest("anchor-machine")
