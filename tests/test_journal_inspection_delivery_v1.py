from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    InMemoryMachineOutbox,
    JournalInspectionService,
    MachineCommand,
    MachineCommit,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    ProgramLock,
    canonical_digest,
)


def _program() -> MachineProgramRef:
    lock = ProgramLock(
        code_digest=canonical_digest({"code": 1}),
        dependency_digest=canonical_digest({"deps": 1}),
        schema_digest=canonical_digest({"schema": 1}),
        interpreter_digest=canonical_digest({"interpreter": 1}),
        data_digest=canonical_digest({"data": 1}),
        config_digest=canonical_digest({"config": 1}),
    )
    return MachineProgramRef(
        program_digest=canonical_digest({"program": 1}),
        schema_id="inspection.v1",
        program_kind="run",
        program_version="1",
        program_lock=lock,
    )


def test_inspection_projects_pending_child_delivery_from_source_machine() -> None:
    identity = MachineIdentity(
        machine_id="parent-machine",
        kind=MachineKind.RUN,
        implementation_version="1",
        generation_id="generation-1",
    )
    program = _program()
    child = MachineCommand(
        command_id="child-command",
        machine_id="different-target-machine",
        expected_revision=0,
        kind="step",
        payload={"value": 1},
        scope=("run:different-target-machine",),
    )
    commit = MachineCommit(
        machine_id=identity.machine_id,
        command_id="parent-command",
        base_revision=0,
        revision=1,
        proposal_digest=canonical_digest({"proposal": 1}),
        command_digest=canonical_digest({"command": 1}),
        program_digest=program.program_digest,
        program_lock_digest=program.program_lock.lock_digest,
        state={"done": True},
        emitted_commands=(child,),
    )
    journal = InMemoryMachineJournal()
    outbox = InMemoryMachineOutbox()
    assert journal.append(commit) == commit
    outbox.enqueue(commit)

    inspection = JournalInspectionService(
        identity=identity,
        program=program,
        journal=journal,
        outbox=outbox,
    ).inspect(identity.machine_id)

    assert inspection.pending_command_ids == ("child-command",)
