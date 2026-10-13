from __future__ import annotations

from resource_test_support import make_execution_pool

from noetrium_platform.capabilities.participant.api import participant_implementation_unit
from noetrium_platform.composition.method_runtime import (
    standard_method_evidence_factory,
    METHOD_RUNTIME_BINDER_DIGEST,
    bind_standard_method_runtime,
)
from noetrium_platform.composition.participant_workload import (
    ParticipantMethodBinding,
    ScheduledParticipantWorkloadBinding,
)
from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    ExecutionContext,
    InMemoryMachineJournal,
    OperationExecutor,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvent,
    MethodNodeResult,
    MethodNodeKind,
    method_operation,
    method_program,
    method_flow_relation,
)
from noetrium_platform.research.execution.workflow.runtime import KernelOperationDispatcher
from tests_support import task_for_test
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import participant_schedule_unit
from noetrium_platform.research.experimentation.workload.composition import (
    MethodRuntimeBindings,
    TaskFieldProjection,
)



class _ScientificControl:
    """Minimal test control with explicit scientific-clock activation."""

    def __init__(self) -> None:
        self._active = False

    @property
    def cancelled(self) -> bool:
        return UNBOUNDED_EXECUTION_CONTROL.cancelled

    @property
    def reason(self):
        return UNBOUNDED_EXECUTION_CONTROL.reason

    @property
    def deadline(self):
        return UNBOUNDED_EXECUTION_CONTROL.deadline

    @property
    def remaining_seconds(self):
        return UNBOUNDED_EXECUTION_CONTROL.remaining_seconds

    @property
    def scientific_time_active(self) -> bool:
        return self._active

    @property
    def scientific_deadline(self):
        return None

    def activate_scientific_time(self) -> None:
        self._active = True

    def wait(self, timeout=None) -> bool:
        return UNBOUNDED_EXECUTION_CONTROL.wait(timeout)

    def checkpoint(self) -> None:
        UNBOUNDED_EXECUTION_CONTROL.checkpoint()

    def subscribe_cancel(self, callback):
        return UNBOUNDED_EXECUTION_CONTROL.subscribe_cancel(callback)


def _execute_one(binding, task, context):
    return binding.execute_one(task, context, _ScientificControl())

_PARTICIPANT_CALLS: list[str] = []
_SCIENTIFIC_INPUTS_SEEN: list[dict] = []


def _participant_finish(request):
    assert request.context.run_id.startswith("participant-host-binding")
    _PARTICIPANT_CALLS.append(request.context.run_id)
    return MethodNodeResult(value={**dict(request.input_value), "success": True, "steps": 0})


def _scientific_inputs_finish(request):
    _SCIENTIFIC_INPUTS_SEEN.append(dict(request.context.participant_context))
    return MethodNodeResult(value={**dict(request.input_value), "success": True, "steps": 0})


def _program():
    identity = participant_implementation_unit("method", "participant.host-binding", "1", "1", "1")
    return method_program(
        identity,
        entrypoint="finish",
        operations=(method_operation(
            "finish",
            "participant.host-binding.finish",
            kind=MethodNodeKind.RETURN,
            handler=_participant_finish,
        ),),
    )


def test_parallel_participant_method_child_keeps_program_host_binding(tmp_path) -> None:
    _PARTICIPANT_CALLS.clear()
    program = _program()
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    participants = tuple(
        ParticipantMethodBinding(role, "agent", treatment, program, runtime)
        for role, treatment in (("left", "control"), ("right", "treatment"))
    )
    pool = make_execution_pool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=participant_schedule_unit((("left", "right"),)),
            participants=participants,
            journal=InMemoryMachineJournal(),
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        result = _execute_one(binding,
            task_for_test("task-host-binding", "fixture", "prove host propagation"),
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
    _PARTICIPANT_CALLS.clear()
    program = _program()
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    journal = InMemoryMachineJournal()
    pool = make_execution_pool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=participant_schedule_unit((("demo_agent",),)),
            participants=(
                ParticipantMethodBinding(
                    "demo_agent", "agent", "demo", program, runtime
                ),
            ),
            journal=journal,
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        task = task_for_test(
            "task-retry", "fixture", "run the same durable task again"
        )
        context = ExecutionContext(
            "participant-host-binding-retry", "trace", "root"
        )
        first = _execute_one(binding, task, context)
        second = _execute_one(binding, task, context)
        assert first.success and second.success
        assert len(_PARTICIPANT_CALLS) == 2
        assert first.participant_receipts[0][1].run_id == second.participant_receipts[0][1].run_id
        assert first.participant_receipts[0][1].run_digest != second.participant_receipts[0][1].run_digest
    finally:
        pool.close()


def test_participant_method_preserves_inherited_scientific_inputs(tmp_path) -> None:
    _SCIENTIFIC_INPUTS_SEEN.clear()

    identity = participant_implementation_unit("method", "participant.scientific-inputs", "1", "1", "1")
    program = method_program(
        identity,
        entrypoint="finish",
        operations=(method_operation(
            "finish",
            "participant.scientific-inputs.finish",
            kind=MethodNodeKind.RETURN,
            handler=_scientific_inputs_finish,
        ),),
    )
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    pool = make_execution_pool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=participant_schedule_unit((("demo_agent",),)),
            participants=(
                ParticipantMethodBinding(
                    "demo_agent", "agent", "demo", program, runtime
                ),
            ),
            journal=InMemoryMachineJournal(),
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        result = _execute_one(binding,
            task_for_test("task-inputs", "fixture", "consume prior experiment"),
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
        assert len(_SCIENTIFIC_INPUTS_SEEN) == 1
        assert _SCIENTIFIC_INPUTS_SEEN[0]["scientific_inputs"] == {
            "source_architecture": {"generation": 3}
        }
        assert _SCIENTIFIC_INPUTS_SEEN[0]["role"] == "demo_agent"
        assert _SCIENTIFIC_INPUTS_SEEN[0]["treatment_id"] == "demo"
    finally:
        pool.close()


def test_participant_terminal_releases_exact_method_invocation_run(tmp_path) -> None:
    program = _program()
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    pool = make_execution_pool()
    released: list[str] = []
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=participant_schedule_unit((("demo_agent",),)),
            participants=(
                ParticipantMethodBinding(
                    "demo_agent", "agent", "demo", program, runtime
                ),
            ),
            journal=InMemoryMachineJournal(),
            execution_pool=pool,
            run_finalizer=released.append,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        result = _execute_one(binding,
            task_for_test(
                "task-release-run",
                "fixture",
                "release raw writer at exact method terminal",
            ),
            ExecutionContext(
                "participant-host-binding-release",
                "trace",
                "root",
            ),
        )
        assert result.success is True
        method_run_id = result.participant_receipts[0][1].run_id
        assert released == [method_run_id]
        assert ":task-release-run:invocation:" in method_run_id
    finally:
        pool.close()


def _participant_loop(_request):
    return MethodNodeResult(value={"loop": True}, next_node="loop")


def test_participant_limit_reached_is_task_level_scientific_failure(tmp_path) -> None:
    identity = participant_implementation_unit(
        "method", "participant.limit-reached", "1", "1", "1"
    )
    program = method_program(
        identity,
        entrypoint="loop",
        operations=(method_operation(
            "loop",
            "participant.limit-reached.loop",
            kind=MethodNodeKind.COMPUTE,
            handler=_participant_loop,
            max_visits=1,
        ),),
        relations=(method_flow_relation("loop", "loop"),),
    )
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content-limit")
        ),
        state_root=tmp_path / "state-limit",
    )
    pool = make_execution_pool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=participant_schedule_unit((("demo_agent",),)),
            participants=(
                ParticipantMethodBinding(
                    "demo_agent", "agent", "demo", program, runtime
                ),
            ),
            journal=InMemoryMachineJournal(),
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        result = _execute_one(
            binding,
            task_for_test(
                "task-limit", "fixture", "reach scientific execution limit"
            ),
            ExecutionContext(
                "participant-host-binding-limit",
                "trace",
                "root",
            ),
        )
        assert result.success is False
        assert result.failure_scope == "task"
        assert len(result.participant_receipts) == 1
        assert result.participant_receipts[0][1].status == "limit_reached"
        assert result.failure_reason
        assert "node visit limit reached" in result.failure_reason
    finally:
        pool.close()


def _participant_cost_finish(request):
    # Evaluator-only execution cost evidence. The second scheduled role must not
    # receive the first role's cost projection through participant_context.
    assert "evaluator_execution_costs" not in request.context.participant_context
    return MethodNodeResult(
        value={
            "role": request.context.participant_context.get("role"),
            "success": True,
            "steps": 0,
        },
        events=(
            MethodEvent("model.invocation", {
                "request_id": "cost-request",
                "input_tokens": 11,
                "output_tokens": 4,
            }),
            MethodEvent("capability.evidence", {
                "evidence": {
                    "environment_diagnostics": {
                        "physical_child_effect_count": 3,
                    },
                },
            }),
        ),
    )


def test_partial_measurement_reads_only_accepted_child_journal(tmp_path) -> None:
    identity = participant_implementation_unit(
        "method", "participant.partial-costs", "1", "1", "1"
    )
    program = method_program(
        identity,
        entrypoint="finish",
        operations=(method_operation(
            "finish",
            "participant.partial-costs.finish",
            kind=MethodNodeKind.RETURN,
            handler=_participant_cost_finish,
        ),),
    )
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content-partial-costs")
        ),
        state_root=tmp_path / "state-partial-costs",
    )
    journal = DirectoryMachineJournal(tmp_path / "partial-journal")
    pool = make_execution_pool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=participant_schedule_unit((("demo_agent",),)),
            participants=(ParticipantMethodBinding(
                "demo_agent", "agent", "demo", program, runtime
            ),),
            journal=journal,
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        task = task_for_test(
            "task-partial-costs", "fixture", "measure accepted partial work"
        )
        context = ExecutionContext(
            "participant-partial-costs", "trace", "root"
        )
        control = _ScientificControl()
        task_binding = binding._task_binding(
            task, context, control, parent_machine_id="partial-parent-machine"
        )
        role, _base_request = task_binding.requests[0]
        assert role == "demo_agent"
        request = task_binding.request_for(role, participant_context={})
        executed = task_binding.activation_runtime.execute(request)
        assert executed.execution.step_count == 1

        measurement = binding._accepted_partial_measurement(task_binding)
        assert measurement is not None
        assert measurement.steps == 1
        assert measurement.diagnostics["model_tokens"] == 15
        assert measurement.diagnostics["physical_child_effects"] == 3
        # Two handler events plus the durable node event are all replayed; only
        # the two cost-bearing events contribute to evaluator accounting.
        assert measurement.diagnostics["partial_accepted_event_count"] == 3
        cuts = measurement.diagnostics["partial_participant_machine_cuts"]
        assert len(cuts) == 1
        assert cuts[0][0] == "demo_agent"
        assert cuts[0][1] == request.child_machine_id
    finally:
        pool.close()


def test_scheduled_participant_workload_aggregates_evaluator_costs_without_context_leak(tmp_path) -> None:
    identity = participant_implementation_unit(
        "method", "participant.execution-costs", "1", "1", "1"
    )
    program = method_program(
        identity,
        entrypoint="finish",
        operations=(method_operation(
            "finish",
            "participant.execution-costs.finish",
            kind=MethodNodeKind.RETURN,
            handler=_participant_cost_finish,
        ),),
    )
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content-costs")
        ),
        state_root=tmp_path / "state-costs",
    )
    pool = make_execution_pool()
    try:
        binding = ScheduledParticipantWorkloadBinding(
            schedule=participant_schedule_unit((("left",), ("right",))),
            participants=(
                ParticipantMethodBinding("left", "agent", "left", program, runtime),
                ParticipantMethodBinding("right", "agent", "right", program, runtime),
            ),
            journal=InMemoryMachineJournal(),
            execution_pool=pool,
            input_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"), ("objective", "objective")),
            ),
        )
        result = _execute_one(
            binding,
            task_for_test("task-costs", "fixture", "measure execution costs"),
            ExecutionContext("participant-costs", "trace", "root"),
        )
        assert result.success is True
        assert result.diagnostics["model_tokens"] == 30
        assert result.diagnostics["physical_child_effects"] == 6
        assert "evaluator_execution_costs" not in result.exports["participants"]["left"]["diagnostics"]
        assert "model_tokens" not in result.exports["participants"]["left"]["diagnostics"]
    finally:
        pool.close()
