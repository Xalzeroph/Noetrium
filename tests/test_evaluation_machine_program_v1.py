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
    ProgrammableMachineInterpreter,
    ResearchMachineSession,
    programmable_machine_family,
)
from noetrium_platform.research.experimentation.evaluation.runtime import (
    compile_paired_evaluation_program,
    paired_evaluation_handlers,
    paired_evaluation_initial_data,
)


def _d(value: object) -> str:
    return canonical_digest(value)


def _lock(program) -> ProgramLock:
    return ProgramLock(
        code_digest=program.program_digest,
        dependency_digest=_d("evaluation-deps"),
        schema_digest=_d(program.state_schema),
        interpreter_digest=_d("evaluation-interpreter"),
        data_digest=_d("evaluation-data"),
        config_digest=_d("evaluation-config"),
    )


def _session(journal: InMemoryMachineJournal) -> ResearchMachineSession:
    program = compile_paired_evaluation_program()
    machine = MachineExecutor(
        identity=MachineIdentity("evaluation:test", MachineKind.EVALUATION, "1", "g1"),
        program=program.machine_program_ref(_lock(program)),
        journal=journal,
        family=programmable_machine_family(MachineKind.EVALUATION),
    )
    return ResearchMachineSession(
        machine,
        program,
        ProgrammableMachineInterpreter(program, paired_evaluation_handlers()),
    )


def _receipt(branch_id: str, score: float) -> dict[str, object]:
    return {
        "branch_id": branch_id,
        "source_checkpoint_id": "checkpoint-1",
        "workload_id": "workload-1",
        "environment_generation": "environment-v1",
        "task_manifest_digest": "a" * 64,
        "branch_writes": (),
        "lifetime_writes": (),
        "private_to_method_flows": (),
        "metrics": (("score", score), ("cost", 10.0)),
    }


def test_paired_evaluation_is_journal_backed_and_restartable() -> None:
    journal = InMemoryMachineJournal()
    session = _session(journal)
    session.start(
        paired_evaluation_initial_data(
            evaluation_id="eval-1",
            source_execution_digest="b" * 64,
        ),
        command_id="evaluation:start",
    )
    session.step(
        {
            "event": MachineEvent(
                "evaluation.compare",
                {
                    "control": _receipt("control", 0.4),
                    "candidate": _receipt("candidate", 0.7),
                },
            ).as_payload()
        },
        command_id="evaluation:compare:1",
    )
    assert session.data["comparison_count"] == 1
    assert session.data["valid_comparison_count"] == 1

    reopened = _session(journal)
    assert reopened.revision == session.revision
    assert reopened.data["comparison_count"] == 1

    reopened.step(
        {"event": MachineEvent("evaluation.aggregate", {}).as_payload()},
        command_id="evaluation:aggregate",
    )
    aggregate = reopened.previous_value
    assert aggregate["valid_pair_count"] == 1
    assert aggregate["mean_metric_deltas"][0][0] == "cost"
    assert aggregate["mean_metric_deltas"][0][1] == 0.0
    assert aggregate["mean_metric_deltas"][1][0] == "score"
    assert abs(aggregate["mean_metric_deltas"][1][1] - 0.3) < 1e-12

    commit = reopened.step(
        {"event": MachineEvent("evaluation.finalize", {}).as_payload()},
        command_id="evaluation:finalize",
    )
    assert commit.accepted_status.value == "completed"
    assert reopened.previous_value["comparison_count"] == 1


def test_paired_evaluation_records_invalid_comparability_without_scoring_delta() -> None:
    journal = InMemoryMachineJournal()
    session = _session(journal)
    session.start(
        paired_evaluation_initial_data(
            evaluation_id="eval-2",
            source_execution_digest="c" * 64,
        ),
        command_id="evaluation:start",
    )
    candidate = _receipt("candidate", 0.7)
    candidate["workload_id"] = "different-workload"
    session.step(
        {
            "event": MachineEvent(
                "evaluation.compare",
                {
                    "control": _receipt("control", 0.4),
                    "candidate": candidate,
                },
            ).as_payload()
        },
        command_id="evaluation:compare:invalid",
    )
    result = session.previous_value
    assert result["valid"] is False
    assert "workload_id mismatch" in result["violations"]
    assert result["metric_deltas"] == []
    assert session.data["valid_comparison_count"] == 0
