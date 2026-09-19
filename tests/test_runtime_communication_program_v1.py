from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineCommand,
    MachineExecutor,
    MachineIdentity,
    MachineKind,
    ProgramLock,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    CommunicationRuntimeSpec,
    ProgrammableMachineInterpreter,
    MachineEvent,
    communication_initial_data,
    communication_runtime_handlers,
    compile_communication_runtime_program,
    programmable_machine_family,
)


def _digest(value: object) -> str:
    return canonical_digest(value)


def _lock() -> ProgramLock:
    return ProgramLock(
        code_digest=_digest("communication-code"),
        dependency_digest=_digest("communication-deps"),
        schema_digest=_digest("communication-schema"),
        interpreter_digest=_digest("communication-interpreter"),
        data_digest=_digest("communication-data"),
        config_digest=_digest("communication-config"),
    )


def _machine(journal: InMemoryMachineJournal, program):
    return MachineExecutor(
        identity=MachineIdentity("runtime:communication", MachineKind.RUNTIME, "1", "g1"),
        program=program.machine_program_ref(_lock()),
        journal=journal,
        family=programmable_machine_family(MachineKind.RUNTIME),
    )


def _command(machine, revision: int, command_id: str, payload: object):
    return MachineCommand(
        command_id=command_id,
        machine_id=machine.machine_id,
        expected_revision=revision,
        kind="program.step",
        payload=payload,
    )


def test_communication_state_is_recovered_from_machine_journal() -> None:
    journal = InMemoryMachineJournal()
    program = compile_communication_runtime_program()
    interpreter = ProgrammableMachineInterpreter(program, communication_runtime_handlers())
    machine = _machine(journal, program)
    machine.open({})
    start = machine.step(
        MachineCommand(
            command_id="start",
            machine_id=machine.machine_id,
            expected_revision=0,
            kind="program.start",
            payload={"initial_data": communication_initial_data(
                ("agent-a", "agent-b"),
                spec=CommunicationRuntimeSpec(max_participants=2, max_messages_per_inbox=4),
            )},
        ),
        interpreter,
    )
    assert start.revision == 1

    routed = machine.step(
        _command(
            machine,
            1,
            "route-1",
            {"event": MachineEvent(
                "message.route",
                {
                    "sender_id": "agent-a",
                    "recipient_ids": ("agent-b",),
                    "text": "hello",
                    "priority": 3,
                    "kind": "task",
                    "metadata": {},
                },
            ).as_payload()},
        ),
        interpreter,
    )
    assert routed.revision == 2

    restored = _machine(journal, program)
    snapshot = restored.open({})
    state = thaw_json(snapshot.state)["_program"]["data"]
    assert snapshot.revision == 2
    assert state["inboxes"]["agent-b"][0]["text"] == "hello"
    assert state["message_sequences"]["agent-b"] == 1


def test_priority_queue_and_consume_are_runtime_program_semantics() -> None:
    journal = InMemoryMachineJournal()
    program = compile_communication_runtime_program()
    interpreter = ProgrammableMachineInterpreter(program, communication_runtime_handlers())
    machine = _machine(journal, program)
    machine.open({})
    machine.step(
        MachineCommand(
            command_id="start",
            machine_id=machine.machine_id,
            expected_revision=0,
            kind="program.start",
            payload={"initial_data": communication_initial_data(("a", "b"))},
        ),
        interpreter,
    )

    revision = 1
    for index, priority in enumerate((1, 10, 4)):
        machine.step(
            _command(
                machine,
                revision,
                f"route-{index}",
                {"event": MachineEvent(
                    "message.route",
                    {
                        "sender_id": "a",
                        "recipient_ids": ("b",),
                        "text": f"m{index}",
                        "priority": priority,
                        "kind": "task",
                        "metadata": {},
                    },
                ).as_payload()},
            ),
            interpreter,
        )
        revision += 1

    consumed = machine.step(
        _command(
            machine,
            revision,
            "consume",
            {"event": MachineEvent(
                "message.consume",
                {"participant_id": "b", "limit": 2},
            ).as_payload()},
        ),
        interpreter,
    )
    state = thaw_json(consumed.state)["_program"]
    messages = state["previous_value"]["messages"]
    assert [row["text"] for row in messages] == ["m1", "m2"]
    assert [row["text"] for row in state["data"]["inboxes"]["b"]] == ["m0"]


def test_route_preflight_is_atomic_for_disconnected_recipient() -> None:
    journal = InMemoryMachineJournal()
    program = compile_communication_runtime_program()
    interpreter = ProgrammableMachineInterpreter(program, communication_runtime_handlers())
    machine = _machine(journal, program)
    machine.open({})
    initial = communication_initial_data(("a", "b", "c"))
    initial["peers"]["c"]["connected"] = False
    machine.step(
        MachineCommand(
            command_id="start",
            machine_id=machine.machine_id,
            expected_revision=0,
            kind="program.start",
            payload={"initial_data": initial},
        ),
        interpreter,
    )

    try:
        machine.step(
            _command(
                machine,
                1,
                "route",
                {"event": MachineEvent(
                    "message.route",
                    {
                        "sender_id": "a",
                        "recipient_ids": ("b", "c"),
                        "text": "broadcast",
                        "priority": 1,
                        "kind": "task",
                        "metadata": {},
                    },
                ).as_payload()},
            ),
            interpreter,
        )
    except RuntimeError as exc:
        assert "disconnected" in str(exc)
    else:
        raise AssertionError("disconnected recipient must fail before any route commit")

    assert machine.inspect().revision == 1
    state = thaw_json(machine.inspect().state)["_program"]["data"]
    assert state["inboxes"]["b"] == []
