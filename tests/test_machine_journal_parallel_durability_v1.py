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
    return MachineCommit(
        machine_id=machine_id,
        command_id=command.command_id,
        base_revision=0,
        revision=1,
        proposal_digest=proposal.proposal_digest,
        command_digest=command.payload_digest,
        program_digest="f" * 64,
        program_lock_digest="e" * 64,
        state={"revision": 1},
        previous_commit_id=None,
        accepted_status=MachineStatus.COMPLETED,
    )


def test_different_machines_cross_durability_barrier_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    journal = DirectoryMachineJournal(tmp_path / "journal")
    original = journal_module.durable_append_bytes
    barrier = Barrier(2)
    state_lock = Lock()
    active = 0
    peak_active = 0

    def controlled(path: Path, payload: bytes) -> None:
        nonlocal active, peak_active
        with state_lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            barrier.wait(timeout=5.0)
            original(path, payload)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(journal_module, "durable_append_bytes", controlled)
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
