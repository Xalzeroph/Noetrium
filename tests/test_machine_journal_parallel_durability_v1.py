from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

import noetrium_platform.foundation.kernel.kernel.journal as journal_module
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    MachineCommand,
    MachineCommit,
    MachineStateDelta,
    MachineStateMutation,
    MachineStatus,
    TransitionProposal,
)


def _commit(machine_id: str) -> MachineCommit:
    command = MachineCommand(
        command_id=f"{machine_id}:command:1",
        machine_id=machine_id,
        expected_revision=0,
        kind="step",
        payload={"revision": 1},
        scope=(f"run:{machine_id}",),
    )
    proposal = TransitionProposal(
        machine_id=machine_id,
        command_id=command.command_id,
        base_revision=0,
        state_delta=MachineStateDelta(
            (MachineStateMutation(("revision",), 1),)
        ),
        accepted_status=MachineStatus.COMPLETED,
    )
    commit = MachineCommit(
        machine_id=machine_id,
        command_id=command.command_id,
        base_revision=0,
        revision=1,
        proposal_digest=proposal.proposal_digest,
        command_digest=command.payload_digest,
        unit_digest="f" * 64,
        execution_lock_digest="e" * 64,
        before_state_digest="0" * 64,
        input_digest=command.payload_digest,
        state_delta_ref=proposal.state_delta_digest,
        state_delta=proposal.state_delta,
        state={"revision": 1},
        previous_commit_id=None,
        accepted_status=MachineStatus.COMPLETED,
    )
    return commit


def test_different_machines_cross_durability_barrier_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    journal = DirectoryMachineJournal(tmp_path / "journal")
    original = journal_module.PersistentAppendFile.sync
    barrier = Barrier(2)
    state_lock = Lock()
    active = 0
    peak_active = 0

    def controlled(self) -> None:
        nonlocal active, peak_active
        with state_lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            barrier.wait(timeout=5.0)
            original(self)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(journal_module.PersistentAppendFile, "sync", controlled)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(journal.append, _commit("machine-a")),
            executor.submit(journal.append, _commit("machine-b")),
        ]
        for future in futures:
            future.result(timeout=10.0)

    assert peak_active == 2
    assert journal.latest("machine-a") == _commit("machine-a")
    assert journal.latest("machine-b") == _commit("machine-b")
