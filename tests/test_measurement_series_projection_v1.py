from tests_support import measurement_for_test
import pytest
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementValueKind,
)
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    StandardWorkloadMeasurementProjection,
)
from noetrium_platform.research.experimentation.workload.api import WorkloadTaskResult


def _row(task_id: str, success: bool, steps: int) -> WorkloadTaskResult:
    return WorkloadTaskResult(
        task_id=task_id,
        family="family",
        complete=True,
        success=success,
        utility=1.0 if success else 0.0,
        steps=steps,
        duration_s=0.1,
        lineage_id=task_id,
        failure_reason="" if success else "expected failure",
    )


def test_sequence_series_reducer_preserves_canonical_workload_order() -> None:
    definition = measurement_for_test(
        "task_id_series",
        schema_id="sequence.v1",
        value_kind=MeasurementValueKind.SEQUENCE.value,
        semantic_kind="task_id_series",
        source_path="task_id",
        reducer="series",
    )
    rows = (_row("task-a", True, 2), _row("task-b", False, 5), _row("task-c", True, 3))
    value = StandardWorkloadMeasurementProjection._declared_value(definition, rows)
    assert value.kind is MeasurementValueKind.SEQUENCE
    assert value.sequence == ("task-a", "task-b", "task-c")


def test_sequence_series_reducer_supports_boolean_and_numeric_sources() -> None:
    rows = (_row("task-a", True, 2), _row("task-b", False, 5))
    success = measurement_for_test(
        "success_series",
        schema_id="sequence.v1",
        value_kind=MeasurementValueKind.SEQUENCE.value,
        semantic_kind="task_success_series",
        source_path="success",
        reducer="series",
    )
    steps = measurement_for_test(
        "steps_series",
        schema_id="sequence.v1",
        value_kind=MeasurementValueKind.SEQUENCE.value,
        semantic_kind="task_steps_series",
        source_path="steps",
        reducer="series",
    )
    assert StandardWorkloadMeasurementProjection._declared_value(success, rows).sequence == (True, False)
    assert StandardWorkloadMeasurementProjection._declared_value(steps, rows).sequence == (2, 5)



def test_heterogeneous_workload_measures_only_observed_emitting_nodes() -> None:
    definition = measurement_for_test(
        "memory_node_count",
        value_kind=MeasurementValueKind.SCALAR.value,
        semantic_kind="memory_node_count",
        source_path="exports.result.active_node_count",
        reducer="last",
    )
    base = _row("gather", True, 2)
    first = _row("memory-a", True, 1)
    second = _row("memory-b", True, 3)
    from dataclasses import replace
    first = replace(first, exports={"result": {"active_node_count": 3}})
    second = replace(second, exports={"result": {"active_node_count": 5}})
    observed = StandardWorkloadMeasurementProjection._declared_value(
        definition, (base, first, base, second),
    )
    assert observed.scalar == 5.0

    total = measurement_for_test(
        "memory_node_count_sum",
        value_kind=MeasurementValueKind.SCALAR.value,
        semantic_kind="memory_node_count",
        source_path="exports.result.active_node_count",
        reducer="sum",
    )
    assert StandardWorkloadMeasurementProjection._declared_value(
        total, (base, first, base, second),
    ).scalar == 8.0


def test_declared_source_with_no_observed_emitter_fails_closed() -> None:
    definition = measurement_for_test(
        "not_recorded",
        value_kind=MeasurementValueKind.SCALAR.value,
        semantic_kind="resource_usage",
        source_path="exports.result.not_recorded",
        reducer="last",
    )
    with pytest.raises(KeyError, match="no observed source_path"):
        StandardWorkloadMeasurementProjection._declared_value(
            definition, (_row("gather", True, 2),),
        )
