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
    ProgramHandlerRegistry,
    ProgramNodeResult,
    ProgrammableMachineInterpreter,
    ResearchMachineSession,
    RuntimeModuleBuilder,
    RuntimeProgramComposer,
    programmable_machine_family,
)


def _lock(program_digest: str) -> ProgramLock:
    def d(value: object) -> str:
        return canonical_digest(value)
    return ProgramLock(
        code_digest=program_digest,
        dependency_digest=d("runtime-modules"),
        schema_digest=d("runtime-module-state"),
        interpreter_digest=d("programmable-machine"),
        data_digest=d("runtime-module-data"),
        config_digest=d("runtime-module-config"),
    )


def _context_module(operation: str):
    return (
        RuntimeModuleBuilder.context(
            module_id="context",
            entrypoint="project",
        )
        .node("project", operation)
        .build()
    )


def _communication_module():
    return (
        RuntimeModuleBuilder.communication(
            module_id="communication",
            entrypoint="route",
        )
        .node("route", "paper.communication.route")
        .build()
    )


def _scheduling_module():
    return (
        RuntimeModuleBuilder.scheduling(
            module_id="scheduling",
            entrypoint="select",
        )
        .node("select", "paper.scheduling.select")
        .build()
    )


def _program(context_operation: str):
    return (
        RuntimeProgramComposer(
            program_id="paper.runtime.composed",
            version="1",
            state_schema="paper.runtime.composed.state.v1",
            entry_module="context",
        )
        .module(_context_module(context_operation))
        .module(_communication_module())
        .module(_scheduling_module())
        .link("context", "project", "communication")
        .link("communication", "route", "scheduling")
        .build()
    )


def test_runtime_modules_compose_to_one_runtime_program() -> None:
    program = _program("paper.context.project")
    assert program.entrypoint == "context.project"
    assert tuple(node.node_id for node in program.nodes) == (
        "communication.route",
        "context.project",
        "scheduling.select",
    )
    context = program.node("context.project")
    communication = program.node("communication.route")
    scheduling = program.node("scheduling.select")
    assert context.next_node == "communication.route"
    assert communication.next_node == "scheduling.select"
    assert scheduling.next_node is None
    assert context.configuration["runtime_concern"] == "context"
    assert communication.configuration["runtime_concern"] == "communication"
    assert scheduling.configuration["runtime_concern"] == "logical_scheduling"


def test_replacing_only_context_module_changes_composed_program_identity() -> None:
    first = _program("paper.context.project")
    second = _program("paper.context.project-v2")
    assert first.program_digest != second.program_digest

    first_non_context = tuple(
        (node.node_id, node.operation, node.next_node)
        for node in first.nodes
        if not node.node_id.startswith("context.")
    )
    second_non_context = tuple(
        (node.node_id, node.operation, node.next_node)
        for node in second.nodes
        if not node.node_id.startswith("context.")
    )
    assert first_non_context == second_non_context


def test_composed_runtime_executes_through_single_machine_journal() -> None:
    program = _program("paper.context.project")
    handlers = ProgramHandlerRegistry()

    def context(request):
        return ProgramNodeResult(
            value={"context": "projected"},
            state_update={"context": "projected"},
        )

    def communication(request):
        assert request.data["context"] == "projected"
        return ProgramNodeResult(
            value={"message": "routed"},
            state_update={"message": "routed"},
        )

    def scheduling(request):
        assert request.data["message"] == "routed"
        return ProgramNodeResult(
            value={"participant": "agent-a"},
            state_update={"participant": "agent-a"},
        )

    handlers.register(
        "paper.context.project",
        context,
        implementation_digest=canonical_digest({
            "operation": "paper.context.project",
            "implementation_revision": 1,
        }),
    )
    handlers.register(
        "paper.communication.route",
        communication,
        implementation_digest=canonical_digest({
            "operation": "paper.communication.route",
            "implementation_revision": 1,
        }),
    )
    handlers.register(
        "paper.scheduling.select",
        scheduling,
        implementation_digest=canonical_digest({
            "operation": "paper.scheduling.select",
            "implementation_revision": 1,
        }),
    )

    journal = InMemoryMachineJournal()
    machine = MachineExecutor(
        identity=MachineIdentity(
            "runtime:composed",
            MachineKind.RUNTIME,
            "1",
            "g1",
        ),
        program=program.machine_program_ref(_lock(program.program_digest)),
        journal=journal,
        family=programmable_machine_family(MachineKind.RUNTIME),
    )
    session = ResearchMachineSession(
        machine,
        program,
        ProgrammableMachineInterpreter(program, handlers),
    )
    session.start({}, command_id="start")
    result = session.run_until_blocked(
        command_id_prefix="runtime",
        max_steps=8,
    )

    assert result.status.value == "completed"
    assert session.data == {
        "context": "projected",
        "message": "routed",
        "participant": "agent-a",
    }
    assert len(journal.commits(machine.machine_id)) == 4
