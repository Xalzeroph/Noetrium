from dataclasses import replace
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
        (AssignmentWorkload(("task-1",)),),
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


def test_serial_repetition_scheduler_prepares_exactly_one_unit_ahead() -> None:
    protocol = _protocol(repetitions=4)
    plan = _plan(protocol)
    prepared: list[int] = []
    prepare_calls: list[int] = []
    snapshots: list[tuple[int, ...]] = []

    class PipelinedAdapter:
        def prepare_bound(self, unit, bindings, plan_digest, *, execution_id):
            del bindings, execution_id
            assert plan_digest == plan.plan_digest
            prepare_calls.append(unit.repetition)
            if unit.repetition not in prepared:
                prepared.append(unit.repetition)

        def prepare_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            raise AssertionError(
                "serial repetition execution must prepare grouped units"
            )

        def execute_bound(self, unit, bindings, plan_digest, *, execution_id):
            del bindings, execution_id
            assert plan_digest == plan.plan_digest
            snapshots.append(tuple(prepared))
            return tuple(
                StudyMetricObservation(
                    assignment,
                    (("score", float(unit.repetition + 1)),),
                )
                for assignment in unit.assignments
            )

        def execute_bound_variant(
            self,
            assignment,
            binding,
            plan_digest,
            *,
            execution_id,
        ):
            raise AssertionError(
                "serial repetition execution must use grouped units"
            )

    report = _execute(plan, PipelinedAdapter())

    assert len(report.observations) == 8
    assert prepare_calls == [0, 1, 2, 3]
    assert snapshots == [
        (0, 1),
        (0, 1, 2),
        (0, 1, 2, 3),
        (0, 1, 2, 3),
    ]


def test_parallel_assignment_scheduler_prewarms_one_full_replacement_frontier() -> None:
    variants = (
        StudyVariantSpec("v0", VariantKind.CONTROL, "fixed", "0" * 64),
        StudyVariantSpec("v1", VariantKind.TREATMENT, "one", "1" * 64),
        StudyVariantSpec("v2", VariantKind.TREATMENT, "two", "2" * 64),
        StudyVariantSpec("v3", VariantKind.TREATMENT, "three", "3" * 64),
    )
    policy = replace(
        StudyConcurrencyPolicy.serial_shared_v1(
            repetition_timeout_seconds=3600.0
        ),
        parallel_assignments=True,
        max_parallel_assignments=2,
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
        policy,
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
