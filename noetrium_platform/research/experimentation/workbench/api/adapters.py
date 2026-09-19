"""Pure semantic projections from authoritative experiment records into DataTable.

These adapters belong to the workbench API because they do not bind a file format or
scientific backend; provider packages may re-export them for compatibility.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import (
    MeasurementRecord, MeasurementValueKind, StudyMetricObservation,
)
from .contracts import DataColumn, DataTable


class StudyObservationTableAdapter:
    """Project-independent projection from study repetitions to long-form data."""

    def to_table(
        self,
        observations: tuple[StudyMetricObservation, ...],
        *,
        table_id: str = "study-observations",
    ) -> DataTable:
        if type(observations) is not tuple or any(
            type(item) is not StudyMetricObservation for item in observations
        ):
            raise TypeError("study observations must be a tuple of StudyMetricObservation")
        if not observations:
            raise ValueError("study observations cannot be empty")
        metric_names = tuple(sorted({
            name for observation in observations for name, _ in observation.metrics
        }))
        metric_by_observation = [dict(observation.metrics) for observation in observations]
        columns = (
            DataColumn("study_id", "text", False),
            DataColumn("variant_id", "text", False),
            DataColumn("repetition", "int", False),
            DataColumn("seed", "text", False),
            DataColumn("task_id", "text", True),
            DataColumn("assignment_digest", "text", False),
        ) + tuple(DataColumn(name, "float", True) for name in metric_names)
        rows = tuple(
            (
                observation.assignment.study_id,
                observation.assignment.variant_id,
                observation.assignment.repetition,
                observation.assignment.seed,
                observation.assignment.task_id,
                observation.assignment.assignment_digest,
            ) + tuple(metric_by_observation[index].get(name) for name in metric_names)
            for index, observation in enumerate(observations)
        )
        return DataTable(
            table_id,
            columns,
            rows,
            source_digest=canonical_digest(tuple(
                observation.assignment.assignment_digest for observation in observations
            )),
            metadata=(("source_format", "study_metric_observations"),),
        )


class MeasurementRecordTableAdapter:
    """Lossless scalar-measurement projection for shared analysis and plotting."""

    def to_table(
        self,
        records: tuple[MeasurementRecord, ...],
        *,
        table_id: str = "measurement-records",
    ) -> DataTable:
        if type(records) is not tuple or any(type(item) is not MeasurementRecord for item in records):
            raise TypeError("measurement records must be a tuple of MeasurementRecord")
        if not records:
            raise ValueError("measurement records cannot be empty")
        if any(record.value.kind is not MeasurementValueKind.SCALAR for record in records):
            raise ValueError("measurement record projection only accepts scalar measurements")
        columns = (
            DataColumn("project_id", "text", False),
            DataColumn("study_id", "text", False),
            DataColumn("run_id", "text", False),
            DataColumn("variant_id", "text", False),
            DataColumn("measurement_id", "text", False),
            DataColumn("logical_time", "text", False),
            DataColumn("value", "float", False),
            DataColumn("assignment_digest", "text", False),
            DataColumn("producer_id", "text", False),
            DataColumn("record_digest", "text", False),
        )
        rows = tuple(
            (
                record.project_id, record.study_id, record.run_id, record.variant_id,
                record.measurement_id, record.logical_time, record.value.scalar,
                record.assignment_digest, record.producer_id, record.record_digest,
            )
            for record in records
        )
        return DataTable(
            table_id,
            columns,
            rows,
            source_digest=canonical_digest(tuple(record.record_digest for record in records)),
            metadata=(("source_format", "scalar_measurement_records"),),
        )


__all__ = ["MeasurementRecordTableAdapter", "StudyObservationTableAdapter"]
