from threading import Event, Lock, Thread
import time
from unittest.mock import patch

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    TaskFailurePolicy,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal
from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    StudyExecutionPlan,
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
)


def _protocol(*, repetitions: int = 2) -> StudyProtocol:
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
        (AssignmentWorkload(("task-1",)),),
        ("standard",),
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


def _execute(
    plan: StudyExecutionPlan,
    adapter,
    *,
    task_group=None,
    frontier_capacity: int | None = None,
):
    return ExperimentProgramBinding(
        compile_experiment_program(plan),
        adapter,
        BasicStudyMetricAggregator(),
        execution_binding_digest="e" * 64,
        execution_id="f" * 64,
        task_group=task_group,
        frontier_capacity=(
            len(plan.assignments) if frontier_capacity is None else frontier_capacity
        ),
    ).execute(journal=InMemoryMachineJournal())


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


def test_platform_frontier_controls_experiment_parallelism_and_deterministic_merge() -> None:
    plan = _plan(_protocol(repetitions=4))
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=8,
        )
    )
    group = runtime.open_task_group(
        "study-platform-frontier",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    active = 0
    max_active = 0
    lock = Lock()

    class ParallelAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("platform-managed batches execute independent assignments")

        def execute_bound_variant(self, assignment, binding, plan_digest, *, execution_id):
            nonlocal active, max_active
            del binding, execution_id
            assert plan_digest == plan.plan_digest
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.04)
                return StudyMetricObservation(
                    assignment, (("score", float(assignment.repetition + 1)),)
                )
            finally:
                with lock:
                    active -= 1

    try:
        report = _execute(
            plan, ParallelAdapter(), task_group=group, frontier_capacity=2
        )
        assert max_active == 2
        assert [item.assignment.repetition for item in report.observations] == [
            0, 0, 1, 1, 2, 2, 3, 3
        ]
    finally:
        group.close()
        runtime.close()

def test_runtime_frontier_is_not_part_of_scientific_protocol_identity() -> None:
    plan = _plan(_protocol(repetitions=2))
    compiled = compile_experiment_program(plan)
    assert compiled.plan.protocol.protocol_digest == plan.protocol.protocol_digest
    # Runtime frontier is supplied only when binding execution, so changing it
    # cannot alter the frozen scientific plan/protocol digest.
    one = ExperimentProgramBinding(
        compiled, _BoundAdapter(), BasicStudyMetricAggregator(),
        execution_binding_digest="e" * 64, execution_id="f" * 64,
        frontier_capacity=1,
    )
    many = ExperimentProgramBinding(
        compiled, _BoundAdapter(), BasicStudyMetricAggregator(),
        execution_binding_digest="e" * 64, execution_id="f" * 64,
        frontier_capacity=8,
    )
    assert one.compiled.plan.protocol.protocol_digest == many.compiled.plan.protocol.protocol_digest

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


def test_platform_frontier_uses_bound_variant_entrypoint() -> None:
    plan = _plan(_protocol(repetitions=2))
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
            raise AssertionError("platform-managed assignments must use bound assignment execution")

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
        report = _execute(
            plan, BoundVariantAdapter(), task_group=group, frontier_capacity=2
        )
    finally:
        group.close()
        runtime.close()

    assert max_active == 2
    assert len(report.observations) == 4

def test_experiment_program_rejects_incomplete_bound_provider_before_execution() -> None:
    class IncompleteAdapter:
        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            return ()

    with pytest.raises(TypeError, match="BoundStudyExecutionPort"):
        _execute(_plan(), IncompleteAdapter())


def test_single_slot_platform_frontier_prepares_one_assignment_ahead() -> None:
    plan = _plan(_protocol(repetitions=2))
    prepared: list[str] = []
    snapshots: list[tuple[str, ...]] = []

    class PipelinedAdapter:
        def prepare_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("platform-managed execution prepares assignments")

        def prepare_bound_variant(self, assignment, binding, plan_digest, *, execution_id):
            del binding, execution_id
            assert plan_digest == plan.plan_digest
            prepared.append(assignment.assignment_digest)

        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("platform-managed execution uses variant entrypoint")

        def execute_bound_variant(self, assignment, binding, plan_digest, *, execution_id):
            del binding, execution_id
            snapshots.append(tuple(prepared))
            return StudyMetricObservation(assignment, (("score", 1.0),))

    report = _execute(plan, PipelinedAdapter(), frontier_capacity=1)
    assert len(report.observations) == 4
    assert len(prepared) == 4
    assert len(set(prepared)) == 4
    assert len(snapshots[0]) == 2

def test_parallel_assignment_scheduler_prewarms_one_full_replacement_frontier() -> None:
    variants = (
        StudyVariantSpec("v0", VariantKind.CONTROL, "fixed", "0" * 64),
        StudyVariantSpec("v1", VariantKind.TREATMENT, "one", "1" * 64),
        StudyVariantSpec("v2", VariantKind.TREATMENT, "two", "2" * 64),
        StudyVariantSpec("v3", VariantKind.TREATMENT, "three", "3" * 64),
    )
    protocol = StudyProtocol(
        "lookahead-study",
        "lookahead-workload",
        variants,
        1,
        "c" * 64,
        ("score",),
        "d" * 64,
        (AssignmentWorkload(("task-1",)),),
        ("standard",),
    )
    plan = _plan(protocol)
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=8,
        )
    )
    group = runtime.open_task_group(
        "lookahead-assignment-execution",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    gate = Event()
    two_active = Event()
    lock = Lock()
    active = 0
    prepared: list[str] = []
    prepare_calls: list[str] = []
    report_box: list[object] = []
    failure_box: list[BaseException] = []

    class PipelinedVariantAdapter:
        def prepare_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError(
                "parallel assignment execution must prepare variants"
            )

        def prepare_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            del execution_id
            assert plan_digest == plan.plan_digest
            assert binding.variant.variant_id == assignment.variant_id
            with lock:
                prepare_calls.append(assignment.variant_id)
                if assignment.variant_id not in prepared:
                    prepared.append(assignment.variant_id)

        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError(
                "parallel assignment execution must use variant entrypoint"
            )

        def execute_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            nonlocal active
            del binding, execution_id
            assert plan_digest == plan.plan_digest
            with lock:
                active += 1
                if active == 2:
                    two_active.set()
            try:
                assert gate.wait(3.0)
                return StudyMetricObservation(
                    assignment,
                    (("score", 1.0),),
                )
            finally:
                with lock:
                    active -= 1

    def run() -> None:
        try:
            report_box.append(
                _execute(
                    plan,
                    PipelinedVariantAdapter(),
                    task_group=group,
                    frontier_capacity=2,
                )
            )
        except BaseException as exc:
            failure_box.append(exc)

    thread = Thread(target=run)
    thread.start()
    try:
        assert two_active.wait(2.0)
        with lock:
            assert prepared == ["v0", "v1", "v2", "v3"]
            assert prepare_calls == ["v0", "v1", "v2", "v3"]
        gate.set()
        thread.join(5.0)
        assert not thread.is_alive()
        assert not failure_box
        assert len(report_box) == 1
        assert len(report_box[0].observations) == 4
    finally:
        gate.set()
        thread.join(5.0)
        group.close()
        runtime.close()


def test_prepare_failure_waits_for_all_active_assignment_workers_to_converge() -> None:
    plan = _plan(_protocol(repetitions=3))
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=8,
        )
    )
    group = runtime.open_task_group(
        "prepare-failure-worker-convergence",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    slow_started = Event()
    release_slow = Event()
    slow_finished = Event()
    prepare_failed = Event()
    prepare_calls: list[str] = []
    failure_box: list[BaseException] = []
    execution_calls = 0
    execution_lock = Lock()

    class FailingPreparationAdapter:
        def prepare_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("platform-managed execution prepares assignments")

        def prepare_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            del binding, execution_id
            assert plan_digest == plan.plan_digest
            prepare_calls.append(assignment.assignment_digest)
            if len(prepare_calls) == 5:
                prepare_failed.set()
                raise RuntimeError("replacement frontier preparation failed")

        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            raise AssertionError("platform-managed execution uses variant entrypoint")

        def execute_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            nonlocal execution_calls
            del binding, execution_id
            assert plan_digest == plan.plan_digest
            with execution_lock:
                execution_calls += 1
                call_number = execution_calls
            if call_number == 1:
                slow_started.set()
                try:
                    assert release_slow.wait(3.0)
                finally:
                    slow_finished.set()
            return StudyMetricObservation(assignment, (("score", 1.0),))

    def run() -> None:
        try:
            _execute(
                plan,
                FailingPreparationAdapter(),
                task_group=group,
                frontier_capacity=2,
            )
        except BaseException as exc:
            failure_box.append(exc)

    thread = Thread(target=run)
    thread.start()
    try:
        assert slow_started.wait(2.0)
        assert prepare_failed.wait(2.0)
        time.sleep(0.05)
        assert thread.is_alive(), "scheduler returned while an admitted worker was still live"
        assert not slow_finished.is_set()
        release_slow.set()
        thread.join(5.0)
        assert not thread.is_alive()
        assert slow_finished.is_set()
        assert len(failure_box) == 1
        assert "replacement frontier preparation failed" in str(failure_box[0])
    finally:
        release_slow.set()
        thread.join(5.0)
        group.close()
        runtime.close()
