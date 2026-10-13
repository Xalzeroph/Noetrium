from __future__ import annotations

from noetrium_platform.composition.research_experiment_trial_execution import (
    _study_scalar_metric_names,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementValueKind,
)
from tests_support import measurement_for_test, measurement_protocol_for_test


def test_study_scalar_projection_ignores_non_scalar_measurement_families() -> None:
    protocol = measurement_protocol_for_test(
        measurement_for_test(
            "success_rate",
            schema_id="scalar.v1",
            value_kind=MeasurementValueKind.SCALAR.value,
        ),
        measurement_for_test(
            "architecture_snapshot",
            schema_id="structured.v1",
            value_kind=MeasurementValueKind.STRUCTURED.value,
        ),
        measurement_for_test(
            "task_steps_series",
            schema_id="sequence.v1",
            value_kind=MeasurementValueKind.SEQUENCE.value,
        ),
        measurement_for_test(
            "memory_treatment",
            schema_id="categorical.v1",
            value_kind=MeasurementValueKind.CATEGORICAL.value,
        ),
        protocol_id="mixed-measurements.v1",
    )

    assert _study_scalar_metric_names(protocol) == ("success_rate",)
