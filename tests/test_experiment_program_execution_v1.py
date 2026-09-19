from dataclasses import replace
from threading import Lock
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
from noetrium_platform.research.experimentation.study.api import (
    ExperimentPlan,
    StudyConcurrencyPolicy,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
)
from noetrium_platform.research.experimentation.study.runtime import (
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
        ("standard",),
        concurrency_policy or StudyConcurrencyPolicy.serial_shared_v1(
            repetition_timeout_seconds=3600.0
        ),
    )


def _plan(protocol: StudyProtocol | None = None) -> ExperimentPlan:
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
    return ExperimentPlan.compile(protocol, bindings, assignments)


def _execute(plan: ExperimentPlan, adapter, *, task_group=None):
    return ExperimentProgramBinding(
        compile_experiment_program(plan),
        adapter,
        BasicStudyMetricAggregator(),
        task_group=task_group,
    ).execute()


class _BoundAdapter:
    def execute_bound(self, unit, bindings, plan_digest):
        del bindings, plan_digest
        return tuple(
            StudyMetricObservation(
                assignment,
                (("score", float(unit.repetition + 1)),),
            )
            for assignment in unit.assignments
        )

    def execute_bound_variant(self, assignment, binding, plan_digest):
        del binding, plan_digest
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
        def execute_bound(self, unit, bindings, plan_digest):
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

        def execute_bound_variant(self, assignment, binding, plan_digest):
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
        ExperimentPlan,
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
        ExperimentPlan.compile(protocol, tuple(reversed(bindings)), assignments)


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
    forward = ExperimentPlan.compile(protocol, bindings, assignments)
    reverse = ExperimentPlan.compile(protocol, bindings, tuple(reversed(assignments)))
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
        def execute_bound(self, unit, bindings, plan_digest):
            raise AssertionError("parallel assignments must use bound assignment execution")

        def execute_bound_variant(self, assignment, binding, plan_digest):
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
        def execute_bound(self, unit, bindings, plan_digest):
            return ()

    with pytest.raises(TypeError, match="BoundStudyExecutionPort"):
        _execute(_plan(), IncompleteAdapter())
