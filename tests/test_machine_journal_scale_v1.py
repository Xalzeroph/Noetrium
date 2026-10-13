from __future__ import annotations

from pathlib import Path
import json

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


_STATE_DIGEST_BY_COMMIT_ID: dict[str, str] = {}

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
        state_delta=MachineStateDelta((
            MachineStateMutation(("revision",), revision),
        )),
    )
    commit = MachineCommit(
        machine_id=machine_id,
        command_id=command_id,
        base_revision=revision - 1,
        revision=revision,
        proposal_digest=proposal.proposal_digest,
        command_digest=command.payload_digest,
        unit_digest="f" * 64,
        execution_lock_digest="e" * 64,
        before_state_digest=("0" * 64 if previous_commit_id is None else _STATE_DIGEST_BY_COMMIT_ID[previous_commit_id]),
        input_digest=command.payload_digest,
        state_delta_ref=proposal.state_delta_digest,
        state_delta=proposal.state_delta,
        state={"revision": revision},
        previous_commit_id=previous_commit_id,
    )
    _STATE_DIGEST_BY_COMMIT_ID[commit.commit_id] = commit.state_digest
    return commit


def test_small_hot_path_states_use_smallest_canonical_state_encoding(tmp_path: Path) -> None:
    journal = DirectoryMachineJournal(tmp_path)
    previous = None
    for revision in range(1, 4):
        commit = _commit(revision, previous_commit_id=previous)
        journal.append(commit)
        previous = commit.commit_id

    path = next((tmp_path / "machines").glob("*.journal"))
    rows = tuple(json.loads(line) for line in path.read_text("utf-8").splitlines())
    assert rows[0]["state_encoding"] == "snapshot"
    # After the initial causal anchor, a one-field revision update is smaller
    # as a canonical patch than as a repeated full snapshot.
    assert tuple(row["state_encoding"] for row in rows[1:]) == (
        "patch",
        "patch",
    )
    assert DirectoryMachineJournal(tmp_path).latest("scale-machine").revision == 3


def test_single_writer_200_appends_do_not_redecode_committed_prefix(
    tmp_path: Path,
    monkeypatch,
) -> None:
    decoded = 0
    original = journal_module._decode_commit

    def counted(value, *, previous_state=None):
        nonlocal decoded
        decoded += 1
        return original(value, previous_state=previous_state)

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


def test_observed_journal_deletion_or_truncation_fails_closed(
    tmp_path: Path,
) -> None:
    journal = DirectoryMachineJournal(tmp_path)
    first = _commit(1, previous_commit_id=None)
    journal.append(first)
    path = next((tmp_path / "machines").glob("*.journal"))
    original = path.read_bytes()

    path.write_bytes(b"")
    with pytest.raises(MachineIntegrityError, match="truncated"):
        journal.latest("scale-machine")

    path.write_bytes(original)
    restored = DirectoryMachineJournal(tmp_path)
    assert restored.latest("scale-machine") == first
    path.unlink()
    with pytest.raises(MachineIntegrityError, match="disappeared"):
        restored.latest("scale-machine")


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


def test_commit_lookup_routes_warm_hits_to_exact_machine_without_global_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    writer = DirectoryMachineJournal(tmp_path)
    targets = []
    for index in range(32):
        machine_id = f"lookup-machine-{index:03d}"
        commit = _commit(
            1,
            previous_commit_id=None,
            machine_id=machine_id,
        )
        writer.append(commit)
        targets.append(commit)

    cold = DirectoryMachineJournal(tmp_path)
    scans = 0
    original = cold._machine_ids

    def counted_machine_ids():
        nonlocal scans
        scans += 1
        return original()

    monkeypatch.setattr(cold, "_machine_ids", counted_machine_ids)
    target = targets[17]

    assert cold.get(target.commit_id) == target
    assert scans == 1
    assert cold.get(target.commit_id) == target
    assert scans == 1


def test_commit_lookup_route_revalidates_exact_carrier(
    tmp_path: Path,
) -> None:
    journal = DirectoryMachineJournal(tmp_path)
    commit = _commit(
        1,
        previous_commit_id=None,
        machine_id="indexed-machine",
    )
    journal.append(commit)
    assert journal.get(commit.commit_id) == commit

    path = journal._log_path("indexed-machine")
    raw = path.read_bytes()
    tampered = raw.replace(
        b'"machine_id":"indexed-machine"',
        b'"machine_id":"indeyed-machine"',
        1,
    )
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    with pytest.raises(MachineIntegrityError):
        journal.get(commit.commit_id)

def test_commit_lookup_routes_warm_hits_to_exact_machine_without_global_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    writer = DirectoryMachineJournal(tmp_path)
    targets = []
    for index in range(32):
        machine_id = f"lookup-machine-{index:03d}"
        commit = _commit(
            1,
            previous_commit_id=None,
            machine_id=machine_id,
        )
        writer.append(commit)
        targets.append(commit)

    cold = DirectoryMachineJournal(tmp_path)
    scans = 0
    original = cold._machine_ids

    def counted_machine_ids():
        nonlocal scans
        scans += 1
        return original()

    monkeypatch.setattr(cold, "_machine_ids", counted_machine_ids)
    target = targets[17]

    assert cold.get(target.commit_id) == target
    assert scans == 1
    assert cold.get(target.commit_id) == target
    assert scans == 1


def test_commit_lookup_route_does_not_bypass_carrier_revalidation(
    tmp_path: Path,
) -> None:
    journal = DirectoryMachineJournal(tmp_path)
    commit = _commit(
        1,
        previous_commit_id=None,
        machine_id="indexed-machine",
    )
    journal.append(commit)
    assert journal.get(commit.commit_id) == commit

    path = journal._log_path("indexed-machine")
    raw = path.read_bytes()
    tampered = raw.replace(
        b'"machine_id":"indexed-machine"',
        b'"machine_id":"indeyed-machine"',
        1,
    )
    assert len(tampered) == len(raw)
    path.write_bytes(tampered)

    with pytest.raises(MachineIntegrityError):
        journal.get(commit.commit_id)
