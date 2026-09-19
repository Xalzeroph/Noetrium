from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineExecutor,
    MachineIdentity,
    MachineKind,
    ProgramLock,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ProgrammableMachineInterpreter,
    ResearchMachineSession,
    ResearchProgramBuilder,
    core_program_handlers,
    programmable_machine_family,
)


def _d(value: object) -> str:
    return canonical_digest(value)


def _lock() -> ProgramLock:
    return ProgramLock(
        code_digest=_d("code"),
        dependency_digest=_d("deps"),
        schema_digest=_d("schema"),
        interpreter_digest=_d("interpreter"),
        data_digest=_d("data"),
        config_digest=_d("config"),
    )


def _program():
    return (
        ResearchProgramBuilder(
            program_id="session.test",
            kind=MachineKind.RUNTIME,
            version="1",
            state_schema="session.test.state.v1",
            entrypoint="assign",
        )
        .node(
            "assign",
            "core.assign",
            configuration={"values": {"answer": 42}},
            next_node="return",
        )
        .node(
            "return",
            "core.return",
            configuration={"value": {"done": True}},
        )
        .build()
    )


def _executor(program, journal):
    return MachineExecutor(
        identity=MachineIdentity("runtime:session-test", MachineKind.RUNTIME, "1", "g1"),
        program=program.machine_program_ref(_lock()),
        journal=journal,
        family=programmable_machine_family(MachineKind.RUNTIME),
    )


def test_research_machine_session_drives_program_without_owning_state() -> None:
    program = _program()
    journal = InMemoryMachineJournal()
    interpreter = ProgrammableMachineInterpreter(program, core_program_handlers())
    session = ResearchMachineSession(_executor(program, journal), program, interpreter)

    assert session.revision == 0
    assert session.started is False
    session.start({"seed": 7}, command_id="start")
    result = session.run_until_blocked(command_id_prefix="drive")

    assert result.status.value == "completed"
    assert result.revision == 3
    assert session.data == {"seed": 7, "answer": 42}
    assert session.previous_value == {"done": True}
    assert len(journal.commits(session.machine_id)) == 3


def test_research_machine_session_reopens_from_same_journal_head() -> None:
    program = _program()
    journal = InMemoryMachineJournal()
    interpreter = ProgrammableMachineInterpreter(program, core_program_handlers())

    first = ResearchMachineSession(_executor(program, journal), program, interpreter)
    first.start({"seed": 7}, command_id="start")
    first.run_until_blocked(command_id_prefix="drive")

    second = ResearchMachineSession(_executor(program, journal), program, interpreter)
    assert second.started is True
    assert second.revision == 3
    assert second.status.value == "completed"
    assert second.data == {"seed": 7, "answer": 42}
    assert second.previous_value == {"done": True}
