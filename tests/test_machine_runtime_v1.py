from __future__ import annotations

from typing import cast

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    DeliveryStatus,
    InMemoryMachineInbox,
    InMemoryMachineJournal,
    InMemoryMachineOutbox,
    InMemoryMachineSnapshotStore,
    MachineCommand,
    MachineConflict,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineRuntime,
    TransitionProposal,
    canonical_digest,
)


class IncrementInterpreter:
    def propose(self, command, state):
        count = cast(int, state.state.get("count", 0))
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta={"count": count + 1},
            event_payloads=({"type": "increment", "command_id": command.command_id},),
            emitted_commands=(MachineCommand(
                command_id=f"child-{command.command_id}",
                machine_id="agent-1",
                expected_revision=0,
                kind="observe",
                payload={"source": command.command_id},
                scope=("run:run-1", "agent:agent-1"),
            ),),
        )


def make_runtime(journal, snapshot_store=None, outbox=None):
    identity = MachineIdentity(
        machine_id="run-1",
        kind=MachineKind.RUN,
        implementation_version="1",
        generation_id="generation-1",
    )
    program = MachineProgramRef(
        program_digest=canonical_digest({"program": "increment"}),
        schema_id="run.schema.v1",
        program_kind="run",
        program_version="1",
    )
    return MachineRuntime(
        identity=identity,
        program=program,
        journal=journal,
        snapshot_store=snapshot_store,
        outbox=outbox,
    )


def command(revision: int, command_id: str) -> MachineCommand:
    return MachineCommand(
        command_id=command_id,
        machine_id="run-1",
        expected_revision=revision,
        kind="increment",
        payload={"amount": 1},
        scope=("run:run-1",),
    )


def test_runtime_commits_and_replays_idempotently() -> None:
    journal = InMemoryMachineJournal()
    snapshot_store = InMemoryMachineSnapshotStore()
    runtime = make_runtime(journal, snapshot_store)
    assert runtime.open({"count": 0}).revision == 0
    assert runtime.checkpoint().revision == 0
    interpreter = IncrementInterpreter()
    first = runtime.step(command(0, "command-1"), interpreter)
    assert first.revision == 1
    assert first.state["count"] == 1
    assert runtime.step(command(0, "command-1"), interpreter) == first
    with pytest.raises(MachineConflict):
        runtime.step(command(0, "command-1-different"), interpreter)


def test_runtime_recovers_authoritative_head_after_restart() -> None:
    journal = InMemoryMachineJournal()
    first_runtime = make_runtime(journal)
    first_runtime.open({"count": 0})
    first = first_runtime.step(command(0, "command-1"), IncrementInterpreter())

    restarted = make_runtime(journal)
    snapshot = restarted.open({"count": 999})
    assert snapshot.revision == first.revision
    assert snapshot.state["count"] == 1
    assert restarted.inspect().last_commit_id == first.commit_id


def test_runtime_reconciles_outbox_and_inbox_deduplicates() -> None:
    journal = InMemoryMachineJournal()
    outbox = InMemoryMachineOutbox()
    runtime = make_runtime(journal, outbox=outbox)
    runtime.open({"count": 0})
    first = runtime.step(command(0, "command-1"), IncrementInterpreter())
    pending = outbox.pending()
    assert len(pending) == 1
    assert runtime.reconcile_outbox() == pending
    inbox = InMemoryMachineInbox()
    assert inbox.accept(pending[0]) is True
    assert inbox.accept(pending[0]) is False
    receipt = DeliveryReceipt(
        envelope_id=pending[0].envelope_id,
        envelope_digest=pending[0].envelope_digest,
        status=DeliveryStatus.DELIVERED,
        attempt=1,
    )
    outbox.mark(receipt)
    assert outbox.pending() == ()
    assert first.emitted_commands[0].command_id == pending[0].command.command_id
