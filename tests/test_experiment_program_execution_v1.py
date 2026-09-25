from dataclasses import replace
from threading import Lock
import time
from unittest.mock import patch

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    TaskFailurePolicy,
)
from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentWorkloadFailure,
    FailureDisposition,
    FailureScope,
    StudyExecutionPlan,
    StudyConcurrencyPolicy,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.lifecycle.study.algorithms import (
    BasicStudyMetricAggregator,
    DeterministicStudyAssignment,
)
from noetrium_platform.research.experimentation.api.program import (
    ExperimentProgramBinding,
    compile_experiment_program,
    experiment_report_from_data,
)


def _protocol(
    *,
    repetitions: int = 2,
    concurrency_policy: StudyConcurrencyPolicy | None = None,
) -> StudyProtocol:
    return StudyProtocol(
        "study-matrix",
        "workload-matrix",
        (
            StudyVariantSpec("control", VariantKind.CONTROL, "fixed", "a" * 64),
            StudyVariantSpec("treatment", VariantKind.TREATMENT, "candidate", "b" * 64),
        ),
        repetitions,
        "c" * 64,
        ("score",),
        "d" * 64,
        ("standard",),
        concurrency_policy or StudyConcurrencyPolicy.serial_shared_v1(
            repetition_timeout_seconds=3600.0
        ),
    )


def _plan(protocol: StudyProtocol | None = None) -> StudyExecutionPlan:
    protocol = protocol or _protocol()
    bindings = tuple(
        VariantBinding(
            variant,
            "e" * 64,
            f"provider-{variant.variant_id}",
            "none",
            variant.kind.value,
        )
        for variant in protocol.variants
    )
    assignments = DeterministicStudyAssignment().assignments(protocol)
    return StudyExecutionPlan.compile(protocol, bindings, assignments)


def _execute(plan: StudyExecutionPlan, adapter, *, task_group=None):
    return ExperimentProgramBinding(
        compile_experiment_program(plan),
        adapter,
        BasicStudyMetricAggregator(),
        execution_binding_digest="e" * 64,
        execution_id="f" * 64,
        task_group=task_group,
    ).execute()


class _BoundAdapter:
    def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
        del bindings, plan_digest, execution_id
        return tuple(
            StudyMetricObservation(
                assignment,
                (("score", float(unit.repetition + 1)),),
            )
            for assignment in unit.assignments
        )

    def execute_bound_variant(self, assignment, binding, plan_digest, *, execution_id):
        del binding, plan_digest, execution_id
        return StudyMetricObservation(
            assignment,
            (("score", float(assignment.repetition + 1)),),
        )


def test_experiment_program_consumes_only_frozen_plan_authority() -> None:
    plan = _plan()
    report = _execute(plan, _BoundAdapter())

    assert report.protocol_digest == plan.protocol_digest
    assert report.plan_digest == plan.plan_digest
    assert report.binding_digest == plan.binding_digest
    assert len(report.observations) == 4
    assert {(item.variant_id, item.count) for item in report.aggregates} == {
        ("control", 2),
        ("treatment", 2),
    }


def test_parallel_repetition_policy_uses_structured_concurrency_and_deterministic_merge() -> None:
    protocol = _protocol(
        repetitions=4,
        concurrency_policy=replace(
            StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
            max_parallel_repetitions=2,
        ),
    )
    plan = _plan(protocol)
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=4,
        )
    )
    group = runtime.open_task_group(
        "study-parallel-execution",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    active = 0
    max_active = 0
    lock = Lock()

    class ParallelAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            nonlocal active, max_active
            del bindings
            assert plan_digest == plan.plan_digest
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.04)
                return tuple(
                    StudyMetricObservation(
                        assignment,
                        (("score", float(unit.repetition + 1)),),
                    )
                    for assignment in unit.assignments
                )
            finally:
                with lock:
                    active -= 1

        def execute_bound_variant(self, assignment, binding, plan_digest, *, execution_id):
            raise AssertionError("serial-variant plan must use repetition execution")

    try:
        report = _execute(plan, ParallelAdapter(), task_group=group)
        assert max_active == 2
        assert [item.assignment.repetition for item in report.observations] == [
            0, 0, 1, 1, 2, 2, 3, 3
        ]
        assert [item.assignment.variant_id for item in report.observations[:2]] == [
            "control", "treatment"
        ]
    finally:
        group.close()
        runtime.close()


def test_scientific_concurrency_policy_is_part_of_protocol_identity() -> None:
    serial = _protocol()
    parallel = _protocol(
        concurrency_policy=replace(
            StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
            max_parallel_repetitions=2,
        )
    )
    assert serial.protocol_digest != parallel.protocol_digest


def test_experiment_program_uses_binding_index_not_repeated_linear_lookup() -> None:
    plan = _plan()
    with patch.object(
        StudyExecutionPlan,
        "binding_for",
        side_effect=AssertionError("matrix execution performed a linear binding scan"),
    ):
        report = _execute(plan, _BoundAdapter())
    assert len(report.observations) == len(plan.assignments)


def test_plan_rejects_binding_order_that_diverges_from_protocol() -> None:
    protocol = _protocol()
    bindings = tuple(
        VariantBinding(
            variant,
            "e" * 64,
            f"provider-{variant.variant_id}",
            "none",
            variant.kind.value,
        )
        for variant in protocol.variants
    )
    assignments = DeterministicStudyAssignment().assignments(protocol)
    with pytest.raises(ValueError, match="variant order"):
        StudyExecutionPlan.compile(protocol, tuple(reversed(bindings)), assignments)


def test_assignment_order_is_frozen_plan_authority() -> None:
    protocol = _protocol()
    bindings = tuple(
        VariantBinding(
            variant,
            "e" * 64,
            f"provider-{variant.variant_id}",
            "none",
            variant.kind.value,
        )
        for variant in protocol.variants
    )
    assignments = DeterministicStudyAssignment().assignments(protocol)
    forward = StudyExecutionPlan.compile(protocol, bindings, assignments)
    reverse = StudyExecutionPlan.compile(protocol, bindings, tuple(reversed(assignments)))
    assert forward.assignment_digest != reverse.assignment_digest
    assert forward.plan_digest != reverse.plan_digest


def test_parallel_assignment_policy_uses_bound_variant_entrypoint() -> None:
    protocol = _protocol(
        concurrency_policy=replace(
            StudyConcurrencyPolicy.serial_shared_v1(repetition_timeout_seconds=3600.0),
            parallel_assignments=True,
            max_parallel_assignments=2,
        )
    )
    plan = _plan(protocol)
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=4,
        )
    )
    group = runtime.open_task_group(
        "compiled-variant-execution",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    active = 0
    max_active = 0
    lock = Lock()

    class BoundVariantAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("parallel assignments must use bound assignment execution")

        def execute_bound_variant(self, assignment, binding, plan_digest, *, execution_id):
            nonlocal active, max_active
            assert binding.variant.variant_id == assignment.variant_id
            assert plan_digest == plan.plan_digest
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.04)
                return StudyMetricObservation(assignment, (("score", 1.0),))
            finally:
                with lock:
                    active -= 1

    try:
        report = _execute(plan, BoundVariantAdapter(), task_group=group)
    finally:
        group.close()
        runtime.close()

    assert max_active == 2
    assert [
        (item.assignment.repetition, item.assignment.variant_id)
        for item in report.observations
    ] == [
        (0, "control"),
        (0, "treatment"),
        (1, "control"),
        (1, "treatment"),
    ]


def test_experiment_program_rejects_incomplete_bound_provider_before_execution() -> None:
    class IncompleteAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            return ()

    with pytest.raises(TypeError, match="BoundStudyExecutionPort"):
        _execute(_plan(), IncompleteAdapter())


def _parallel_retry_protocol(
    *,
    max_assignment_attempts: int = 3,
) -> StudyProtocol:
    return _protocol(
        repetitions=1,
        concurrency_policy=replace(
            StudyConcurrencyPolicy.serial_shared_v1(
                repetition_timeout_seconds=3600.0
            ),
            parallel_assignments=True,
            max_parallel_assignments=2,
            max_assignment_attempts=max_assignment_attempts,
        ),
    )


def _parallel_group():
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=4,
        )
    )
    group = runtime.open_task_group(
        "selective-retry",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    return runtime, group


def test_partial_batch_success_is_durable_and_retry_runs_only_failed_assignment() -> None:
    plan = _plan(_parallel_retry_protocol())
    compiled = compile_experiment_program(plan)
    runtime, group = _parallel_group()
    journal = InMemoryMachineJournal()
    calls: dict[str, int] = {}

    class FlakyAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("parallel assignment plan must use variant execution")

        def execute_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            del binding, plan_digest, execution_id
            calls[assignment.variant_id] = calls.get(assignment.variant_id, 0) + 1
            if assignment.variant_id == "treatment" and calls["treatment"] == 1:
                raise ExperimentWorkloadFailure(
                    "environment",
                    "transient_transport",
                    "temporary transport failure",
                    scope=FailureScope.TASK,
                    disposition=FailureDisposition.RETRYABLE,
                )
            return StudyMetricObservation(
                assignment,
                (("score", 1.0),),
            )

    binding = ExperimentProgramBinding(
        compiled,
        FlakyAdapter(),
        BasicStudyMetricAggregator(),
        execution_binding_digest="e" * 64,
        execution_id="f" * 64,
        task_group=group,
    )
    try:
        first = binding.open_session(journal=journal)
        first.start(
            compiled.initial_data(),
            command_id=f"{first.machine_id}:start",
        )
        attempt = first.step(command_id=f"{first.machine_id}:attempt:1")
        assert attempt.accepted_status is MachineStatus.RUNNABLE
        assert first.data["batch_cursor"] == 0
        assert len(first.data["observations"]) == 1
        assert first.data["assignment_attempts"]
        assert len(first.data["attempt_failures"]) == 1

        # Simulate process loss: discard the session and reopen exclusively from
        # the authoritative Machine Journal.
        reopened = binding.open_session(journal=journal)
        assert len(reopened.data["observations"]) == 1
        assert reopened.data["batch_cursor"] == 0

        run = reopened.run_until_blocked(
            command_id_prefix=f"{reopened.machine_id}:resume",
            max_steps=3,
        )
        assert run.status is MachineStatus.COMPLETED
        report = experiment_report_from_data(compiled, reopened.data)
    finally:
        group.close()
        runtime.close()

    assert calls == {"control": 1, "treatment": 2}
    assert tuple(
        row.assignment.variant_id for row in report.observations
    ) == ("control", "treatment")
    assert len(report.aggregates) == 2


def test_retryable_failure_exhaustion_commits_history_then_fails_machine() -> None:
    plan = _plan(_parallel_retry_protocol(max_assignment_attempts=2))
    compiled = compile_experiment_program(plan)
    runtime, group = _parallel_group()
    journal = InMemoryMachineJournal()
    calls: dict[str, int] = {}

    class ExhaustingAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("parallel assignment plan must use variant execution")

        def execute_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            del binding, plan_digest, execution_id
            calls[assignment.variant_id] = calls.get(assignment.variant_id, 0) + 1
            if assignment.variant_id == "treatment":
                raise ExperimentWorkloadFailure(
                    "model",
                    "transient_provider",
                    "provider unavailable",
                    scope=FailureScope.TASK,
                    disposition=FailureDisposition.RETRYABLE,
                )
            return StudyMetricObservation(assignment, (("score", 1.0),))

    binding = ExperimentProgramBinding(
        compiled,
        ExhaustingAdapter(),
        BasicStudyMetricAggregator(),
        execution_binding_digest="e" * 64,
        execution_id="f" * 64,
        task_group=group,
    )
    try:
        session = binding.open_session(journal=journal)
        session.start(compiled.initial_data(), command_id="retry-exhaust:start")
        first = session.step(command_id="retry-exhaust:1")
        assert first.accepted_status is MachineStatus.RUNNABLE
        second = session.step(command_id="retry-exhaust:2")
        assert second.accepted_status is MachineStatus.FAILED
        assert len(session.data["observations"]) == 1
        assert len(session.data["attempt_failures"]) == 2
        assert session.data["attempt_failures"][-1]["retry_exhausted"] is True
    finally:
        group.close()
        runtime.close()

    assert calls == {"control": 1, "treatment": 2}


def test_unknown_failure_is_terminal_but_successful_sibling_remains_durable() -> None:
    plan = _plan(_parallel_retry_protocol())
    compiled = compile_experiment_program(plan)
    runtime, group = _parallel_group()
    journal = InMemoryMachineJournal()
    calls: dict[str, int] = {}

    class BrokenAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("parallel assignment plan must use variant execution")

        def execute_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            del binding, plan_digest, execution_id
            calls[assignment.variant_id] = calls.get(assignment.variant_id, 0) + 1
            if assignment.variant_id == "treatment":
                raise RuntimeError("programming defect")
            return StudyMetricObservation(assignment, (("score", 1.0),))

    binding = ExperimentProgramBinding(
        compiled,
        BrokenAdapter(),
        BasicStudyMetricAggregator(),
        execution_binding_digest="e" * 64,
        execution_id="f" * 64,
        task_group=group,
    )
    try:
        session = binding.open_session(journal=journal)
        session.start(compiled.initial_data(), command_id="terminal:start")
        commit = session.step(command_id="terminal:1")
        assert commit.accepted_status is MachineStatus.FAILED
        assert len(session.data["observations"]) == 1
        assert session.data["attempt_failures"][0]["disposition"] == "terminal"
        assert session.data["attempt_failures"][0]["retry_exhausted"] is False
    finally:
        group.close()
        runtime.close()

    assert calls == {"control": 1, "treatment": 1}


def test_retry_policy_is_part_of_scientific_protocol_identity() -> None:
    first = _parallel_retry_protocol(max_assignment_attempts=2)
    second = _parallel_retry_protocol(max_assignment_attempts=3)
    assert first.protocol_digest != second.protocol_digest
