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
    MachineEvent,
    ObjectiveDirection,
    OptimizationObjective,
    OptimizationPresetSpec,
    ProgrammableMachineInterpreter,
    ResearchMachineSession,
    compile_optimization_program,
    optimization_handlers,
    optimization_initial_data,
    programmable_machine_family,
)


def _d(value: object) -> str:
    return canonical_digest(value)


def _session(journal: InMemoryMachineJournal) -> ResearchMachineSession:
    program = compile_optimization_program()
    lock = ProgramLock(
        code_digest=program.program_digest,
        dependency_digest=_d("optimization-deps"),
        schema_digest=_d(program.state_schema),
        interpreter_digest=_d("optimization-interpreter"),
        data_digest=_d("optimization-data"),
        config_digest=_d("optimization-config"),
    )
    machine = MachineExecutor(
        identity=MachineIdentity("optimization:test", MachineKind.OPTIMIZATION, "1", "g1"),
        program=program.machine_program_ref(lock),
        journal=journal,
        family=programmable_machine_family(MachineKind.OPTIMIZATION),
    )
    return ResearchMachineSession(
        machine,
        program,
        ProgrammableMachineInterpreter(program, optimization_handlers()),
    )


def _event(session, kind: str, payload: dict, command_id: str):
    return session.step(
        {"event": MachineEvent(kind, payload).as_payload()},
        command_id=command_id,
    )


def test_optimization_machine_is_restartable_and_selects_by_declared_objectives() -> None:
    journal = InMemoryMachineJournal()
    session = _session(journal)
    spec = OptimizationPresetSpec(
        objectives=(
            OptimizationObjective("quality", ObjectiveDirection.MAXIMIZE),
            OptimizationObjective("cost", ObjectiveDirection.MINIMIZE),
        ),
        max_evaluations=4,
        max_generations=3,
    )
    session.start(
        optimization_initial_data("opt-1", spec),
        command_id="optimization:start",
    )
    for candidate_id in ("a", "b"):
        _event(
            session,
            "optimization.candidate.register",
            {"candidate_id": candidate_id, "definition": {"name": candidate_id}},
            f"register:{candidate_id}",
        )
    _event(
        session,
        "optimization.candidate.observe",
        {"candidate_id": "a", "metrics": {"quality": 0.7, "cost": 5.0}},
        "observe:a",
    )
    _event(
        session,
        "optimization.candidate.observe",
        {"candidate_id": "b", "metrics": {"quality": 0.8, "cost": 9.0}},
        "observe:b",
    )

    reopened = _session(journal)
    assert reopened.data["evaluated_count"] == 2
    _event(reopened, "optimization.select", {}, "select")
    assert reopened.previous_value["incumbent_id"] == "b"

    commit = _event(reopened, "optimization.finalize", {}, "finalize")
    assert commit.accepted_status.value == "completed"
    assert reopened.previous_value["incumbent_id"] == "b"


def test_optimization_machine_enforces_evaluation_budget_as_state_semantics() -> None:
    journal = InMemoryMachineJournal()
    session = _session(journal)
    spec = OptimizationPresetSpec(
        objectives=(OptimizationObjective("score", ObjectiveDirection.MAXIMIZE),),
        max_evaluations=1,
    )
    session.start(optimization_initial_data("opt-2", spec), command_id="start")
    for candidate_id in ("a", "b"):
        _event(
            session,
            "optimization.candidate.register",
            {"candidate_id": candidate_id, "definition": {"name": candidate_id}},
            f"register:{candidate_id}",
        )
    _event(
        session,
        "optimization.candidate.observe",
        {"candidate_id": "a", "metrics": {"score": 1.0}},
        "observe:a",
    )
    try:
        _event(
            session,
            "optimization.candidate.observe",
            {"candidate_id": "b", "metrics": {"score": 2.0}},
            "observe:b",
        )
    except ValueError as exc:
        assert "budget" in str(exc)
    else:
        raise AssertionError("evaluation beyond budget must fail")
    assert session.data["evaluated_count"] == 1
