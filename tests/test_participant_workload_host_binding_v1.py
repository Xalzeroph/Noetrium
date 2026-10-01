from __future__ import annotations

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.composition.method_runtime import (
    standard_method_evidence_factory,
    standard_method_runtime_binder,
)
from noetrium_platform.composition.participant_workload import (
    ParticipantMethodRuntime,
    ScheduledParticipantWorkloadBinding,
)
from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    OperationExecutor,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeResult,
    MethodProgramBuilder,
)
from noetrium_platform.research.execution.workflow.runtime import KernelOperationDispatcher
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTaskSpec,
    ParticipantSchedule,
)
from noetrium_platform.research.experimentation.workload.composition import (
    MethodRuntimeBindings,
    TaskFieldProjection,
)


def _program(calls: list[str] | None = None):
    identity = MethodProgramIdentity(MethodIdentity("participant.host-binding", "1", "1", "1"))

    def finish(request):
        assert request.context.run_id.startswith("participant-host-binding")
        if calls is not None:
            calls.append(request.context.run_id)
        return MethodNodeResult(value=request.input_value)

    return (
        MethodProgramBuilder(identity, entrypoint="finish")
        .return_node("finish", "participant.host-binding.finish", finish)
        .build()
    )


def test_parallel_participant_method_child_keeps_program_host_binding(tmp_path) -> None:
    program = _program()
    runtime = MethodRuntimeBindings(
        runtime_binder=standard_method_runtime_binder(),
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    participants = tuple(
        ParticipantMethodRuntime(role, "agent", treatment, program, runtime)
        for role, treatment in (("left", "control"), ("right", "treatment"))
    )
    pool = ResearchExecutionPool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=ParticipantSchedule((("left", "right"),)),
            participants=participants,
            journal=InMemoryMachineJournal(),
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        result = binding.execute_one(
            ExperimentTaskSpec("task-host-binding", "fixture", "prove host propagation"),
            ExecutionContext("participant-host-binding", "trace", "root"),
        )
        assert result.success is True
        assert tuple(role for role, _receipt in result.participant_receipts) == (
            "left",
            "right",
        )
        assert all(
            receipt.status == "succeeded"
            for _role, receipt in result.participant_receipts
        )
    finally:
        pool.close()


def test_repeated_participant_task_uses_fresh_terminal_replay_attempts(tmp_path) -> None:
    calls: list[str] = []
    program = _program(calls)
    runtime = MethodRuntimeBindings(
        runtime_binder=standard_method_runtime_binder(),
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    journal = InMemoryMachineJournal()
    pool = ResearchExecutionPool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=ParticipantSchedule((("sem_agent",),)),
            participants=(
                ParticipantMethodRuntime(
                    "sem_agent", "agent", "sem", program, runtime
                ),
            ),
            journal=journal,
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        task = ExperimentTaskSpec(
            "task-retry", "fixture", "run the same durable task again"
        )
        context = ExecutionContext(
            "participant-host-binding-retry", "trace", "root"
        )
        first = binding.execute_one(task, context)
        second = binding.execute_one(task, context)
        assert first.success and second.success
        assert len(calls) == 2
        assert first.participant_receipts[0][1].run_id == second.participant_receipts[0][1].run_id
        assert first.participant_receipts[0][1].run_digest != second.participant_receipts[0][1].run_digest
    finally:
        pool.close()


def test_participant_method_preserves_inherited_scientific_inputs(tmp_path) -> None:
    seen = []

    identity = MethodProgramIdentity(
        MethodIdentity("participant.scientific-inputs", "1", "1", "1")
    )

    def finish(request):
        seen.append(dict(request.context.participant_context))
        return MethodNodeResult(value=request.input_value)

    program = (
        MethodProgramBuilder(identity, entrypoint="finish")
        .return_node("finish", "participant.scientific-inputs.finish", finish)
        .build()
    )
    runtime = MethodRuntimeBindings(
        runtime_binder=standard_method_runtime_binder(),
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    pool = ResearchExecutionPool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=ParticipantSchedule((("sem_agent",),)),
            participants=(
                ParticipantMethodRuntime(
                    "sem_agent", "agent", "sem", program, runtime
                ),
            ),
            journal=InMemoryMachineJournal(),
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        result = binding.execute_one(
            ExperimentTaskSpec("task-inputs", "fixture", "consume prior experiment"),
            ExecutionContext(
                "participant-scientific-inputs",
                "trace",
                "root",
                participant_context={
                    "scientific_inputs": {
                        "source_architecture": {"generation": 3}
                    }
                },
            ),
        )
        assert result.success is True
        assert len(seen) == 1
        assert seen[0]["scientific_inputs"] == {
            "source_architecture": {"generation": 3}
        }
        assert seen[0]["role"] == "sem_agent"
        assert seen[0]["treatment_id"] == "sem"
    finally:
        pool.close()
