from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    InMemoryMachineJournal,
    MachineKind,
)
from noetrium_platform.research.execution.machines import (
    ProgramNodeResult,
    ResearchProgramBuilder,
    ResearchProgramHost,
)


def test_research_program_host_accepts_prebound_handler_registry() -> None:
    program = (
        ResearchProgramBuilder(
            program_id="host.registry",
            kind=MachineKind.MEMORY,
            version="1",
            state_schema="host.registry.state.v1",
            entrypoint="custom",
        )
        .node("custom", "paper.custom", next_node="return")
        .node("return", "core.return")
        .build()
    )
    def custom(request):
        return ProgramNodeResult(
            value={"handled": True},
            state_update={"handled": True},
        )

    # A pre-bound registry may carry the core vocabulary as well; Host copies
    # the registry per session rather than mutating caller-owned handler state.
    from noetrium_platform.research.execution.machines import core_program_handlers
    full = core_program_handlers()
    full.register(
        "paper.custom",
        custom,
        implementation_digest=canonical_digest({
            "operation": "paper.custom",
            "implementation_revision": 1,
        }),
    )

    host = ResearchProgramHost(
        host_id="host.registry",
        program=program,
        journal=InMemoryMachineJournal(),
        base_handlers=full,
        dependency_identity={"handler_set": full.operations()},
    )
    session = host.open_session(
        machine_id="memory:host-registry",
        instance_identity={"instance": "one"},
        binding=None,
    )
    session.start({}, command_id="start")
    run = session.run_until_blocked(command_id_prefix="drive")

    assert run.status.value == "completed"
    assert session.data["handled"] is True
    assert session.previous_value == {"handled": True}
    # Reopening must not mutate or conflict with the caller-owned registry.
    second = host.open_session(
        machine_id="memory:host-registry",
        instance_identity={"instance": "one"},
        binding=None,
    )
    assert second.status.value == "completed"
    assert second.data["handled"] is True
