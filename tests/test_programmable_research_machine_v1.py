from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineCommand,
    MachineIdentity,
    MachineKind,
    MachineExecutor,
    ProgramLock,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ChildFailurePolicy,
    ChildResearchHostRegistry,
    ChildResearchMachineExecutor,
    ChildResearchMachineRequest,
    RegisteredChildResearchMachineExecutor,
    ProgramNodeResult,
    ProgrammableMachineInterpreter,
    ResearchProgramBuilder,
    ResearchProgramHost,
    core_program_handlers,
    programmable_machine_family,
)


def _digest(value: object) -> str:
    return canonical_digest(value)


def _lock() -> ProgramLock:
    return ProgramLock(
        code_digest=_digest("code"), dependency_digest=_digest("deps"),
        schema_digest=_digest("schema"), interpreter_digest=_digest("interp"),
        data_digest=_digest("data"), config_digest=_digest("config"),
    )


def test_runtime_program_can_define_paper_specific_execution_semantics() -> None:
    program = (
        ResearchProgramBuilder(
            program_id="paper.runtime",
            kind=MachineKind.RUNTIME,
            version="1",
            state_schema="paper.runtime.state.v1",
            entrypoint="turn",
        )
        .node("turn", "paper.turn")
        .build()
    )
    handlers = core_program_handlers()

    def turn(request):
        count = request.data.get("count", 0)
        return ProgramNodeResult(
            value=count + 1,
            state_update={"count": count + 1},
            next_node="turn" if count == 0 else None,
        )

    handlers.register(
        "paper.turn",
        turn,
        implementation_digest=canonical_digest({
            "operation": "paper.turn",
            "implementation_revision": 1,
        }),
    )
    family = programmable_machine_family(MachineKind.RUNTIME)
    machine = MachineExecutor(
        identity=MachineIdentity("runtime:paper", MachineKind.RUNTIME, "1", "g1"),
        program=program.machine_program_ref(_lock()),
        journal=InMemoryMachineJournal(),
        family=family,
    )
    interpreter = ProgrammableMachineInterpreter(program, handlers)
    machine.open({})
    machine.step(MachineCommand(
        command_id="start", machine_id=machine.machine_id, expected_revision=0,
        kind="program.start", payload={"initial_data": {"count": 0}},
    ), interpreter)
    first = machine.step(MachineCommand(
        command_id="step1", machine_id=machine.machine_id, expected_revision=1,
        kind="program.step", payload={"event": "tick"},
    ), interpreter)
    assert first.accepted_status.value == "runnable"
    second = machine.step(MachineCommand(
        command_id="step2", machine_id=machine.machine_id, expected_revision=2,
        kind="program.step", payload={"event": "tick"},
    ), interpreter)
    assert second.accepted_status.value == "completed"
    assert second.state["_program"]["data"]["count"] == 2


def test_all_programmable_domains_share_one_kernel_command_abi() -> None:
    expected = ("program.start", "program.step", "program.resume")
    for kind in (
        MachineKind.EXPERIMENT, MachineKind.RUN, MachineKind.RUNTIME,
        MachineKind.PARTICIPANT, MachineKind.MEMORY, MachineKind.ENVIRONMENT,
        MachineKind.EVALUATION, MachineKind.OPTIMIZATION,
    ):
        assert programmable_machine_family(kind).command_kinds == expected



def test_parent_program_commits_authoritative_child_machine_link() -> None:
    journal = InMemoryMachineJournal()
    child_program = (
        ResearchProgramBuilder(
            program_id="paper.optimizer",
            kind=MachineKind.OPTIMIZATION,
            version="1",
            state_schema="paper.optimizer.state.v1",
            entrypoint="return",
        )
        .node(
            "return",
            "core.return",
            configuration={"value": {"candidate": "best"}},
        )
        .build()
    )
    child_host = ResearchProgramHost(
        host_id="paper.optimizer.host",
        program=child_program,
        operations=(),
        journal=journal,
        max_steps=4,
    )
    child_executor = ChildResearchMachineExecutor(child_host)

    parent_program = (
        ResearchProgramBuilder(
            program_id="paper.runtime-with-search",
            kind=MachineKind.RUNTIME,
            version="1",
            state_schema="paper.runtime-with-search.state.v1",
            entrypoint="search",
        )
        .node("search", "paper.search")
        .build()
    )
    handlers = core_program_handlers()

    def search(request):
        child = child_executor.execute(
            parent_machine_id=request.snapshot.machine_id,
            child_machine_id="optimization:paper:child-1",
            instance_identity={"candidate_space": "paper"},
            binding={},
            initial_data={"seed": 7},
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
        )
        return ProgramNodeResult(
            value={
                "child_status": child.status.value,
                "child_result": child.result,
            },
            child_links=(child.link,),
        )

    handlers.register(
        "paper.search",
        search,
        implementation_digest=canonical_digest({
            "operation": "paper.search",
            "implementation_revision": 1,
        }),
    )
    parent = MachineExecutor(
        identity=MachineIdentity(
            "runtime:paper-parent",
            MachineKind.RUNTIME,
            "1",
            "g1",
        ),
        program=parent_program.machine_program_ref(_lock()),
        journal=journal,
        family=programmable_machine_family(MachineKind.RUNTIME),
    )
    interpreter = ProgrammableMachineInterpreter(parent_program, handlers)
    parent.open({})
    parent.step(
        MachineCommand(
            command_id="parent:start",
            machine_id=parent.machine_id,
            expected_revision=0,
            kind="program.start",
            payload={"initial_data": {}},
        ),
        interpreter,
    )
    commit = parent.step(
        MachineCommand(
            command_id="parent:search",
            machine_id=parent.machine_id,
            expected_revision=1,
            kind="program.step",
            payload={},
        ),
        interpreter,
    )

    assert commit.accepted_status.value == "completed"
    assert len(commit.child_links) == 1
    link = commit.child_links[0]
    assert link.parent_machine_id == parent.machine_id
    assert link.child_machine_id == "optimization:paper:child-1"
    assert link.child_program_digest == child_program.program_digest
    assert link.child_transition_start == 1
    assert link.child_transition_end == 2
    assert link.child_result_ref is not None
    assert link.failure_policy == "fail_parent"
    assert len(journal.commits(link.child_machine_id)) == 2



def test_registered_child_host_invocation_is_data_driven() -> None:
    journal = InMemoryMachineJournal()
    child_program = (
        ResearchProgramBuilder(
            program_id="paper.registered-optimizer",
            kind=MachineKind.OPTIMIZATION,
            version="1",
            state_schema="paper.registered-optimizer.state.v1",
            entrypoint="return",
        )
        .node(
            "return",
            "core.return",
            configuration={"value": {"score": 0.9}},
        )
        .build()
    )
    host = ResearchProgramHost(
        host_id="optimizer.registered",
        program=child_program,
        operations=(),
        journal=journal,
        max_steps=4,
    )
    registry = ChildResearchHostRegistry()
    registry.register(
        host,
        lambda request: {"request": request.host_id},
        binding_factory_digest=canonical_digest({
            "factory": "optimizer.registered.binding",
            "implementation_revision": 1,
        }),
    )
    executor = RegisteredChildResearchMachineExecutor(registry)
    request = ChildResearchMachineRequest(
        host_id="optimizer.registered",
        parent_machine_id="method:parent",
        child_machine_id="optimization:registered:1",
        instance_identity={"search_space": "agent-design"},
        initial_data={"seed": 1},
        failure_policy=ChildFailurePolicy.COLLECT,
    )

    restored = ChildResearchMachineRequest.from_payload(request.as_payload())
    assert restored == request
    child = executor.execute(restored)
    assert child.status.value == "completed"
    assert child.result == {"score": 0.9}
    assert child.link.parent_machine_id == "method:parent"
    assert child.link.failure_policy == "collect"
    assert registry.host_ids() == ("optimizer.registered",)
    assert len(registry.identity_digest) == 64
    assert executor.identity_digest != registry.identity_digest


def test_static_child_host_authoring_derives_binding_identity_and_executor() -> None:
    journal = InMemoryMachineJournal()
    child_program = (
        ResearchProgramBuilder(
            program_id="paper.static-child",
            kind=MachineKind.MEMORY,
            version="1",
            state_schema="paper.static-child.state.v1",
            entrypoint="return",
        )
        .node(
            "return",
            "core.return",
            configuration={"value": {"stored": True}},
        )
        .build()
    )
    host = ResearchProgramHost(
        host_id="memory.static-child",
        program=child_program,
        operations=(),
        journal=journal,
        max_steps=4,
    )

    class _StaticBinding:
        @property
        def identity_digest(self) -> str:
            return canonical_digest({
                "binding": "paper.static-child",
                "implementation_revision": 1,
            })

    registry = ChildResearchHostRegistry()
    registry.register_static(host, _StaticBinding())
    executor = registry.executor()
    child = executor.execute(
        ChildResearchMachineRequest(
            host_id="memory.static-child",
            parent_machine_id="method:parent",
            child_machine_id="memory:static-child:1",
            instance_identity={"paper": "fixture"},
            initial_data={},
        )
    )

    assert child.status.value == "completed"
    assert child.result == {"stored": True}
    assert registry.host_ids() == ("memory.static-child",)
    assert len(registry.identity_digest) == 64
    assert len(executor.identity_digest) == 64


def test_incremental_child_optimization_machine_commits_one_event_per_link() -> None:
    from noetrium_platform.research.execution.machines import (
        MachineEvent,
        ObjectiveDirection,
        OptimizationObjective,
        OptimizationPresetSpec,
        default_optimization_host,
        optimization_initial_data,
    )

    journal = InMemoryMachineJournal()
    preset = OptimizationPresetSpec(
        objectives=(
            OptimizationObjective("score", ObjectiveDirection.MAXIMIZE),
        ),
        max_evaluations=2,
        max_generations=3,
    )
    host = default_optimization_host(
        journal=journal,
        preset=preset,
    )
    executor = ChildResearchMachineExecutor(host)
    initial_data = optimization_initial_data("aflow-search", preset)
    common = {
        "parent_machine_id": "method:aflow-parent",
        "child_machine_id": "optimization:aflow-search",
        "instance_identity": {
            "method": "aflow",
            "optimization_id": "aflow-search",
        },
        "binding": {},
        "initial_data": initial_data,
        "failure_policy": ChildFailurePolicy.FAIL_PARENT,
        "command_id_prefix": "aflow-child",
    }

    register = executor.step_once(
        **common,
        payload={
            "event": MachineEvent(
                "optimization.candidate.register",
                {
                    "candidate_id": "w0",
                    "definition": {"workflow": "blank"},
                },
            ).as_payload(),
        },
    )
    assert register.status.value == "runnable"
    assert register.link.child_transition_start == 1
    assert register.link.child_transition_end == 2
    assert register.execution.data["candidates"]["w0"]["evaluated"] is False

    observe = executor.step_once(
        **common,
        payload={
            "event": MachineEvent(
                "optimization.candidate.observe",
                {
                    "candidate_id": "w0",
                    "metrics": {"score": 0.25},
                },
            ).as_payload(),
        },
    )
    assert observe.status.value == "runnable"
    assert observe.link.child_transition_start == 3
    assert observe.link.child_transition_end == 3
    assert observe.execution.data["evaluated_count"] == 1

    select = executor.step_once(
        **common,
        payload={
            "event": MachineEvent(
                "optimization.select",
                {},
            ).as_payload(),
        },
    )
    assert select.link.child_transition_start == 4
    assert select.result["incumbent_id"] == "w0"

    final = executor.step_once(
        **common,
        payload={
            "event": MachineEvent(
                "optimization.finalize",
                {},
            ).as_payload(),
        },
    )
    assert final.status.value == "completed"
    assert final.link.child_transition_start == 5
    assert final.link.child_transition_end == 5
    assert final.link.child_result_ref is not None
    assert len(journal.commits("optimization:aflow-search")) == 5
