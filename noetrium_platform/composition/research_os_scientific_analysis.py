from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Protocol

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    MachineKind,
    canonical_digest,
    freeze_json,
    strict_json_loads,
)
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.product.research_os import ResearchDefinition
from noetrium_platform.research.execution.machines.api import (
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramBuilder,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    MetricAggregation,
    MetricDefinition,
    MetricMissingPolicy,
    MetricPredicate,
    RawRecord,
)
from noetrium_platform.research.experimentation.projection import MetricEngine
from noetrium_platform.research.experimentation.workbench.api import (
    DataColumn,
    DataTable,
    MissingValuePolicy,
    MultipleComparisonMethod,
)
from noetrium_platform.research.experimentation.api import (
    AnalysisDefinition,
    AnalysisResult,
    MeasurementCut,
)
from noetrium_platform.research.experimentation.workbench.composition import (
    compose_standard_research_statistics,
)


_COMPILER_VERSION = "research-os-scientific-analysis.v2"


class ScientificArtifactReadPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def read(self, reference: ArtifactReference) -> bytes: ...


def _artifact_reference(value: object, field: str) -> ArtifactReference:
    row = _mapping(value, field)
    if "scope" in row:
        scope = _mapping(row["scope"], field + " scope")
        scope_kind = ScopeKind(str(scope["kind"]))
        scope_id = str(scope["scope_id"])
    else:
        scope_kind = ScopeKind(str(row["scope_kind"]))
        scope_id = str(row["scope_id"])
    return ArtifactReference(
        str(row["reference_id"]),
        ScopeIdentity(scope_kind, scope_id),
        str(row["artifact_id"]),
        int(row["generation"]),
    )


def _read_json_artifact(
    content: ScientificArtifactReadPort,
    value: object,
    field: str,
) -> JsonValue:
    return strict_json_loads(content.read(_artifact_reference(value, field)))


def _is_experiment_report_ref(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("schema") == "research-os.experiment-report-ref.v3"
        and isinstance(value.get("manifest"), Mapping)
    )


def _observation_row(value: object) -> dict[str, JsonValue]:
    observation = _mapping(value, "experiment observation")
    assignment = _mapping(observation["assignment"], "experiment assignment")
    workload = _mapping(assignment.get("workload", {}), "assignment workload")
    row: dict[str, JsonValue] = {
        "study_id": str(assignment["study_id"]),
        "variant_id": str(assignment["variant_id"]),
        "repetition": int(assignment["repetition"]),
        "seed": str(assignment["seed"]),
        "assignment_digest": str(assignment["assignment_digest"]),
        "task_id": (
            None if assignment.get("task_id") is None else str(assignment["task_id"])
        ),
        "workload_task_ids": "|".join(
            str(item)
            for item in _sequence(
                workload.get("task_ids", ()),
                "assignment workload task_ids",
            )
        ),
    }
    for pair in _sequence(observation.get("metrics", ()), "observation metrics"):
        values = _sequence(pair, "observation metric")
        if len(values) != 2:
            raise ValueError("observation metric rows must be pairs")
        row[str(values[0])] = freeze_json(values[1])
    return row


_MEASUREMENT_CARRIERS = {
    "scalar": "scalar",
    "boolean": "boolean",
    "categorical": "categorical",
    "structured": "structured",
    "sequence": "sequence",
    "distribution": "distribution",
    "matrix": "matrix",
    "text_judgement": "text_judgement",
    "content_reference": "content_reference",
}


def _measurement_row(
    record_value: object,
    assignment_by_digest: Mapping[str, Mapping[str, Any]],
) -> dict[str, JsonValue]:
    record = _mapping(record_value, "measurement record")
    value = _mapping(record["value"], "measurement value")
    kind = str(value["kind"])
    carrier = _MEASUREMENT_CARRIERS.get(kind)
    if carrier is None:
        raise ValueError(f"unsupported measurement value kind: {kind}")
    assignment_digest = str(record["assignment_digest"])
    assignment = assignment_by_digest.get(assignment_digest, {})
    return {
        "project_id": str(record["project_id"]),
        "study_id": str(record["study_id"]),
        "run_id": str(record["run_id"]),
        "variant_id": str(record["variant_id"]),
        "measurement_id": str(record["measurement_id"]),
        "schema_id": str(record["schema_id"]),
        "logical_time": str(record["logical_time"]),
        "assignment_digest": assignment_digest,
        "repetition": assignment.get("repetition"),
        "seed": assignment.get("seed"),
        "value_kind": kind,
        "value": freeze_json(value.get(carrier)),
        "record_digest": str(record["record_digest"]),
        "producer_id": str(record["producer_id"]),
    }


def materialize_experiment_report_input(
    report_ref: object,
    content: ScientificArtifactReadPort,
) -> JsonValue:
    report = _mapping(report_ref, "experiment report reference")
    if not _is_experiment_report_ref(report):
        raise ValueError("scientific input is not an Experiment report reference")
    if str(report["content_authority_digest"]) != content.identity_digest:
        raise ValueError("Experiment report content authority identity drifted")

    manifest = _mapping(
        _read_json_artifact(content, report["manifest"], "experiment report manifest"),
        "experiment report manifest",
    )
    for name in ("closure_digest", "execution_cut_id", "content_authority_digest"):
        if str(manifest[name]) != str(report[name]):
            raise ValueError(f"Experiment report {name} drifted from manifest")

    observations = tuple(
        _mapping(row, "experiment observation")
        for row in _sequence(
            _read_json_artifact(
                content,
                manifest["observations_artifact"],
                "experiment observations artifact",
            ),
            "experiment observations",
        )
    )
    aggregates = tuple(
        freeze_json(row)
        for row in _sequence(
            _read_json_artifact(
                content,
                manifest["aggregates_artifact"],
                "experiment aggregates artifact",
            ),
            "experiment aggregates",
        )
    )
    rows = tuple(_observation_row(row) for row in observations)
    assignment_by_digest = {
        str(_mapping(row["assignment"], "experiment assignment")["assignment_digest"]):
        _mapping(row["assignment"], "experiment assignment")
        for row in observations
    }

    receipts: list[JsonValue] = []
    measurement_records: list[JsonValue] = []
    seen_receipts: set[str] = set()
    for observation in observations:
        raw_reference = observation.get("trial_receipt_reference")
        if raw_reference is None:
            continue
        reference = _artifact_reference(raw_reference, "trial receipt reference")
        if reference.artifact_id in seen_receipts:
            continue
        seen_receipts.add(reference.artifact_id)
        receipt = _mapping(
            strict_json_loads(content.read(reference)),
            "trial receipt",
        )
        if str(receipt["receipt_digest"]) != str(observation["trial_receipt_digest"]):
            raise ValueError("Trial receipt digest drifted from Study observation")
        records = tuple(
            _mapping(row, "measurement record")
            for row in _sequence(receipt.get("measurements", ()), "trial measurements")
        )
        expected = tuple(
            str(item)
            for item in _sequence(
                observation.get("measurement_record_digests", ()),
                "observation measurement_record_digests",
            )
        )
        actual = tuple(str(row["record_digest"]) for row in records)
        if expected != actual:
            raise ValueError("MeasurementRecord lineage drifted from Trial receipt")
        receipts.append(freeze_json(receipt))
        measurement_records.extend(freeze_json(row) for row in records)

    measurement_rows = tuple(
        _measurement_row(row, assignment_by_digest)
        for row in measurement_records
    )
    result: dict[str, JsonValue] = {
        "schema": "research.analysis-input.v1",
        "report_ref": freeze_json(report),
        "manifest": freeze_json(manifest),
        "rows": rows,
        "aggregates": aggregates,
        "trial_receipts": tuple(receipts),
        "measurement_records": tuple(measurement_records),
        "measurement_rows": measurement_rows,
    }
    result["input_digest"] = canonical_digest(result)
    return freeze_json(result)


def materialize_research_scientific_inputs(
    payload: JsonValue,
    content: ScientificArtifactReadPort,
) -> JsonValue:
    if _is_experiment_report_ref(payload):
        return materialize_experiment_report_input(payload, content)
    if not isinstance(payload, Mapping):
        return payload
    projected = dict(payload)
    materialized_reports: list[Mapping[str, Any]] = []
    for key, value in payload.items():
        if not _is_experiment_report_ref(value):
            continue
        materialized = materialize_experiment_report_input(value, content)
        projected[str(key)] = materialized
        materialized_reports.append(_mapping(materialized, "analysis input"))
    if len(materialized_reports) == 1:
        report = materialized_reports[0]
        for key in (
            "rows",
            "aggregates",
            "trial_receipts",
            "measurement_records",
            "measurement_rows",
        ):
            projected[key] = report[key]
        projected["scientific_input_digest"] = report["input_digest"]
    return freeze_json(projected)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    return value


def _plain(value: object) -> JsonValue:
    if value is None or type(value) in {str, int, float, bool}:
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            item.name: _plain(getattr(value, item.name))
            for item in fields(value)
            if item.init or hasattr(value, item.name)
        }
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_plain(item) for item in value)
    raise TypeError(f"scientific result is not JSON-projectable: {type(value)!r}")


def _definition_config(definition: ResearchDefinition) -> Mapping[str, Any]:
    return _mapping(definition.config, "research scientific definition config")


def _metric_definition(definition: ResearchDefinition) -> MetricDefinition:
    config = _definition_config(definition)
    spec = _mapping(config.get("derived_metric"), "derived metric specification")
    predicates = tuple(
        MetricPredicate(
            tuple(str(part) for part in _sequence(row["path"], "metric predicate path")),
            freeze_json(row["equals"]),
        )
        for row in (
            _mapping(item, "metric predicate")
            for item in _sequence(spec.get("predicates", ()), "metric predicates")
        )
    )
    return MetricDefinition(
        metric_id=str(spec["metric_id"]),
        aggregation=MetricAggregation(str(spec["aggregation"])),
        record_types=tuple(
            str(item)
            for item in _sequence(spec.get("record_types", ()), "metric record types")
        ),
        schema_ids=tuple(
            str(item)
            for item in _sequence(spec.get("schema_ids", ()), "metric schema ids")
        ),
        value_path=tuple(
            str(item)
            for item in _sequence(spec.get("value_path", ()), "metric value path")
        ),
        group_by=tuple(
            tuple(str(part) for part in _sequence(path, "metric group path"))
            for path in _sequence(spec.get("group_by", ()), "metric group paths")
        ),
        predicates=predicates,
        missing=MetricMissingPolicy(str(spec.get("missing", "skip"))),
        unit=(
            None
            if spec.get("unit") is None
            else str(spec.get("unit"))
        ),
        description=str(spec.get("description", "")),
    )


def _raw_record(row: Mapping[str, Any]) -> RawRecord:
    encoded = row.get("raw_payload_b64")
    if type(encoded) is not str or not encoded:
        raise ValueError(
            "declarative raw metric input requires raw_payload_b64 to preserve exact bytes"
        )
    raw_payload = base64.b64decode(encoded.encode("ascii"), validate=True)
    return RawRecord(
        experiment_id=str(row["experiment_id"]),
        run_id=str(row["run_id"]),
        unit_id=str(row["unit_id"]),
        sequence=int(row["sequence"]),
        occurred_at=str(row["occurred_at"]),
        recorded_at=str(row["recorded_at"]),
        producer_id=str(row["producer_id"]),
        schema_id=str(row["schema_id"]),
        record_type=str(row["record_type"]),
        raw_payload=raw_payload,
        payload=freeze_json(row.get("payload")),
        stream_id=str(row.get("stream_id", "")),
        attempt_id=str(row.get("attempt_id", "")),
        parent_record_digests=tuple(
            str(item)
            for item in _sequence(
                row.get("parent_record_digests", ()),
                "raw record parent_record_digests",
            )
        ),
        causation_id=(
            None if row.get("causation_id") is None else str(row["causation_id"])
        ),
        correlation_id=str(row.get("correlation_id", "")),
        trace_id=None if row.get("trace_id") is None else str(row["trace_id"]),
        span_id=None if row.get("span_id") is None else str(row["span_id"]),
        event_name=str(row.get("event_name", "")),
        operation_id=str(row.get("operation_id", "")),
        status=str(row.get("status", "unknown")),
        outcome=None if row.get("outcome") is None else str(row["outcome"]),
        monotonic_ns=(
            None if row.get("monotonic_ns") is None else int(row["monotonic_ns"])
        ),
        clock_source=str(row.get("clock_source", "wall")),
        clock_uncertainty_ns=(
            None
            if row.get("clock_uncertainty_ns") is None
            else int(row["clock_uncertainty_ns"])
        ),
        producer_version=str(row.get("producer_version", "unknown")),
        producer_instance_id=str(row.get("producer_instance_id", "")),
        dimensions=freeze_json(row.get("dimensions", {})),
        source_location=freeze_json(row.get("source_location", {})),
        privacy=freeze_json(row.get("privacy", {})),
        sampled=bool(row.get("sampled", True)),
        sampling_rate=float(row.get("sampling_rate", 1.0)),
        content_type=str(row.get("content_type", "application/octet-stream")),
        content_encoding=str(row.get("content_encoding", "identity")),
        lineage_digests=tuple(
            str(item)
            for item in _sequence(
                row.get("lineage_digests", ()),
                "raw record lineage_digests",
            )
        ),
    )


def _metric_payload_rows(payload: object) -> tuple[Mapping[str, Any], ...]:
    mapping = _mapping(payload, "declarative metric payload")
    rows = _sequence(mapping.get("raw_records"), "declarative metric raw_records")
    return tuple(_mapping(row, "declarative metric raw record") for row in rows)


def _metric_result(
    definition: MetricDefinition,
    report: object,
) -> JsonValue:
    group_names = tuple(".".join(path) for path in definition.group_by)
    values = tuple(
        {
            "metric_id": row.metric_id,
            "group": {
                name: _plain(value)
                for name, value in zip(group_names, row.group_key, strict=True)
            },
            "value": _plain(row.value),
            "sample_size": row.sample_size,
            "record_digests": row.record_digests,
            "value_digest": row.value_digest,
        }
        for row in report.values
    )
    return {
        "metric_id": definition.metric_id,
        "raw_cut_digest": report.raw_cut_digest,
        "definitions_digest": report.definitions_digest,
        "group_by": group_names,
        "values": values,
        "report_digest": report.report_digest,
    }


def compile_declarative_metric_program(
    definition: ResearchDefinition,
) -> tuple[ResearchProgram, tuple[ResearchHostOperation, ...]]:
    metric = _metric_definition(definition)
    implementation_digest = canonical_digest(
        {
            "compiler": _COMPILER_VERSION,
            "kind": "derived-metric",
            "definition_digest": definition.definition_digest,
            "metric_definition_digest": metric.definition_digest,
        }
    )
    operation_name = f"research-os.metric:{definition.definition_id}"

    def handle(request: ProgramNodeRequest, _binding: object) -> ProgramNodeResult:
        records = tuple(_raw_record(row) for row in _metric_payload_rows(request.payload))
        report = MetricEngine.evaluate(records, (metric,))
        return ProgramNodeResult(value=_metric_result(metric, report))

    builder = ResearchProgramBuilder(
        program_id=f"research-os:evaluation:{definition.definition_id}",
        kind=MachineKind.EVALUATION,
        version=_COMPILER_VERSION,
        state_schema="json",
        entrypoint="invoke",
    )
    builder.node(
        "invoke",
        operation_name,
        configuration={
            "definition_id": definition.definition_id,
            "definition_digest": definition.definition_digest,
            "metric_definition_digest": metric.definition_digest,
        },
    )
    return (
        builder.build(),
        (ResearchHostOperation(operation_name, handle, implementation_digest),),
    )


def _study_measurement_result(
    definition: ResearchDefinition,
    payload: object,
) -> JsonValue:
    spec = _mapping(
        _definition_config(definition).get("measurement"),
        "measurement specification",
    )
    measurement_id = str(spec["measurement_id"])
    value_kind = str(spec["value_kind"])
    mapping = _mapping(payload, "study measurement payload")
    source_rows = tuple(
        _mapping(row, "measurement row")
        for row in _sequence(
            mapping.get("measurement_rows", ()),
            "study measurement rows",
        )
    )
    values: list[JsonValue] = []
    for row in source_rows:
        if str(row.get("measurement_id")) != measurement_id:
            continue
        group = {
            key: freeze_json(row[key])
            for key in (
                "project_id",
                "study_id",
                "run_id",
                "variant_id",
                "assignment_digest",
                "repetition",
                "seed",
                "logical_time",
            )
            if key in row
        }
        values.append(
            {
                "metric_id": measurement_id,
                "group": group,
                "value_kind": value_kind,
                "value": freeze_json(row.get("value")),
                "record_digest": row.get("record_digest"),
                "record_digests": (
                    ()
                    if row.get("record_digest") is None
                    else (str(row["record_digest"]),)
                ),
            }
        )
    if not values:
        for raw in _sequence(mapping.get("rows", ()), "study observation rows"):
            row = _mapping(raw, "study observation row")
            if measurement_id not in row:
                continue
            group = {
                key: freeze_json(row[key])
                for key in (
                    "study_id",
                    "variant_id",
                    "repetition",
                    "seed",
                    "assignment_digest",
                    "task_id",
                    "workload_task_ids",
                )
                if key in row
            }
            values.append(
                {
                    "metric_id": measurement_id,
                    "group": group,
                    "value_kind": value_kind,
                    "value": freeze_json(row[measurement_id]),
                    "record_digest": None,
                    "record_digests": (),
                }
            )
    if not values:
        raise ValueError(
            f"Experiment report contains no measurement {measurement_id!r}"
        )
    result: dict[str, JsonValue] = {
        "metric_id": measurement_id,
        "value_kind": value_kind,
        "values": tuple(values),
        "definition_digest": definition.definition_digest,
    }
    result["report_digest"] = canonical_digest(result)
    return freeze_json(result)


def compile_declarative_study_measurement_program(
    definition: ResearchDefinition,
) -> tuple[ResearchProgram, tuple[ResearchHostOperation, ...]]:
    spec = _mapping(
        _definition_config(definition).get("measurement"),
        "measurement specification",
    )
    operation_name = f"research-os.measurement:{definition.definition_id}"
    implementation_digest = canonical_digest(
        {
            "compiler": _COMPILER_VERSION,
            "kind": "study-measurement",
            "definition_digest": definition.definition_digest,
            "measurement_spec": freeze_json(spec),
        }
    )

    def handle(request: ProgramNodeRequest, _binding: object) -> ProgramNodeResult:
        return ProgramNodeResult(
            value=_study_measurement_result(definition, request.payload)
        )

    builder = ResearchProgramBuilder(
        program_id=f"research-os:evaluation:{definition.definition_id}",
        kind=MachineKind.EVALUATION,
        version=_COMPILER_VERSION,
        state_schema="json",
        entrypoint="invoke",
    )
    builder.node(
        "invoke",
        operation_name,
        configuration={
            "definition_id": definition.definition_id,
            "definition_digest": definition.definition_digest,
            "measurement_spec": freeze_json(spec),
        },
    )
    return (
        builder.build(),
        (ResearchHostOperation(operation_name, handle, implementation_digest),),
    )


def _rows_from_payload(payload: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, Mapping):
        if "rows" in payload:
            values = _sequence(payload["rows"], "analysis rows")
            return tuple(_mapping(row, "analysis row") for row in values)
        if "values" in payload:
            values = _sequence(payload["values"], "analysis metric values")
            rows: list[Mapping[str, Any]] = []
            for item in values:
                row = _mapping(item, "analysis metric value")
                group = _mapping(row.get("group", {}), "analysis metric group")
                rows.append(
                    {
                        **dict(group),
                        "metric_id": row.get("metric_id"),
                        "value": row.get("value"),
                        "sample_size": row.get("sample_size"),
                        "_record_digests": tuple(
                            str(item)
                            for item in _sequence(
                                row.get("record_digests", ()),
                                "analysis metric record_digests",
                            )
                        ),
                    }
                )
            return tuple(rows)
    if isinstance(payload, Sequence) and not isinstance(
        payload,
        (str, bytes, bytearray),
    ):
        return tuple(_mapping(row, "analysis row") for row in payload)
    raise TypeError(
        "analysis payload must provide rows or declarative metric values"
    )


def _column_type(values: tuple[object, ...]) -> str:
    present = tuple(value for value in values if value is not None)
    if not present:
        return "unknown"
    if all(type(value) is bool for value in present):
        return "boolean"
    if all(type(value) is int for value in present):
        return "integer"
    if all(
        not isinstance(value, bool) and isinstance(value, (int, float))
        for value in present
    ):
        return "float"
    if all(type(value) is str for value in present):
        return "text"
    return "unknown"


def _table(payload: object, definition: ResearchDefinition) -> DataTable:
    rows = _rows_from_payload(payload)
    if not rows:
        raise ValueError("analysis input contains no rows")
    names = tuple(
        sorted(
            {
                str(key)
                for row in rows
                for key in row
                if not str(key).startswith("_")
            }
        )
    )
    columns = tuple(
        DataColumn(
            name,
            _column_type(tuple(row.get(name) for row in rows)),
            any(name not in row or row.get(name) is None for row in rows),
        )
        for name in names
    )
    values = tuple(
        tuple(freeze_json(row.get(name)) for name in names)
        for row in rows
    )
    return DataTable(
        f"research-os:{definition.definition_id}",
        columns,
        values,
        source_digest=canonical_digest(tuple(freeze_json(dict(row)) for row in rows)),
        metadata=(
            ("source_format", "research_os_json_rows"),
            ("definition_id", definition.definition_id),
        ),
    )


def _analysis_spec(definition: ResearchDefinition) -> Mapping[str, Any]:
    config = _definition_config(definition)
    return _mapping(config.get("analysis"), "analysis specification")


def _analysis_value(
    definition: ResearchDefinition,
    payload: object,
) -> JsonValue:
    spec = _analysis_spec(definition)
    table = _table(payload, definition)
    statistics = compose_standard_research_statistics()
    missing = MissingValuePolicy(str(spec.get("missing", "reject")))
    value = str(spec.get("value", "value"))
    group_by = tuple(
        str(item)
        for item in _sequence(spec.get("group_by", ()), "analysis group_by")
    )
    summaries = statistics.summarize(
        table,
        value,
        group_by=group_by,
        missing=missing,
    )
    inference_method = str(spec.get("inference", "none"))
    inference: object = None
    if inference_method == "normal_mean":
        inference = statistics.mean_inference(table, value, missing=missing)
    elif inference_method == "bootstrap_mean":
        inference = statistics.bootstrap_mean(
            table,
            value,
            replicates=int(spec.get("replicates", 2000)),
            seed=int(spec.get("seed", 0)),
            missing=missing,
        )
    elif inference_method == "group_compare":
        inference = statistics.compare(
            table,
            value,
            str(spec["comparison_group"]),
            baseline=spec.get("baseline"),
            candidate=spec.get("candidate"),
            missing=missing,
        )
    elif inference_method == "compare_many":
        inference = statistics.compare_many(
            table,
            value,
            str(spec["comparison_group"]),
            baseline=spec.get("baseline"),
            candidates=tuple(
                _sequence(spec.get("candidates", ()), "analysis candidates")
            ),
            missing=missing,
            correction=MultipleComparisonMethod(
                str(spec.get("multiple_comparison", "holm"))
            ),
            alpha=float(spec.get("alpha", 0.05)),
        )
    elif inference_method == "paired_compare":
        inference = statistics.paired_compare(
            table,
            value,
            str(spec["comparison_group"]),
            pair_column=str(spec["pair_by"]),
            baseline=spec.get("baseline"),
            candidate=spec.get("candidate"),
            missing=missing,
        )
    elif inference_method == "permutation_compare":
        inference = statistics.permutation_compare(
            table,
            value,
            str(spec["comparison_group"]),
            baseline=spec.get("baseline"),
            candidate=spec.get("candidate"),
            replicates=int(spec.get("replicates", 2000)),
            seed=int(spec.get("seed", 0)),
            missing=missing,
        )
    elif inference_method != "none":
        raise ValueError(f"unsupported analysis inference: {inference_method}")
    plain_summaries = _plain(summaries)
    plain_inference = _plain(inference)

    source_rows = _rows_from_payload(payload)
    explicit_record_digests = tuple(
        sorted(
            {
                str(digest)
                for row in source_rows
                for digest in (
                    tuple(row.get("_record_digests", ()))
                    if isinstance(row.get("_record_digests", ()), (tuple, list))
                    else ()
                )
            }
        )
    )
    record_digests = (
        explicit_record_digests
        if explicit_record_digests
        else tuple(
            sorted(
                canonical_digest(freeze_json(dict(row)))
                for row in source_rows
            )
        )
    )
    cut = MeasurementCut(record_digests=record_digests)
    configuration_digest = canonical_digest(freeze_json(spec))
    comparison_digest = canonical_digest(
        {
            "comparison_group": spec.get("comparison_group"),
            "baseline": spec.get("baseline"),
            "candidate": spec.get("candidate"),
            "candidates": spec.get("candidates", ()),
            "pair_by": spec.get("pair_by"),
            "inference": inference_method,
            "replicates": spec.get("replicates"),
            "seed": spec.get("seed"),
            "multiple_comparison": spec.get("multiple_comparison"),
            "alpha": spec.get("alpha"),
            "missing": spec.get("missing"),
        }
    )
    implementation_digest = canonical_digest(
        {
            "compiler": _COMPILER_VERSION,
            "definition_digest": definition.definition_digest,
        }
    )
    analysis_definition = AnalysisDefinition(
        analysis_id=definition.definition_id,
        projector_id="research-os-json-table",
        projector_version=_COMPILER_VERSION,
        implementation_digest=implementation_digest,
        configuration_digest=configuration_digest,
        input_cut=cut,
        grouping_dimensions=group_by,
        filter_rules_digest=canonical_digest(()),
        comparison_rules_digest=comparison_digest,
        output_schema_id="research.analysis.result.v2",
    )
    output = {
        "summaries": plain_summaries,
        "inference_method": inference_method,
        "inference": plain_inference,
        "table_digest": table.table_digest,
    }
    output_content_digest = canonical_digest(output)
    analysis_result = AnalysisResult(
        analysis_digest=analysis_definition.analysis_digest,
        input_cut_digest=cut.cut_digest,
        output_schema_id=analysis_definition.output_schema_id,
        output_content_digest=output_content_digest,
    )
    return {
        "analysis_id": definition.definition_id,
        "research_definition_digest": definition.definition_digest,
        "analysis_digest": analysis_definition.analysis_digest,
        "input_cut_digest": cut.cut_digest,
        "table_digest": table.table_digest,
        "summaries": plain_summaries,
        "inference_method": inference_method,
        "inference": plain_inference,
        "output_content_digest": output_content_digest,
        "analysis_result_digest": analysis_result.result_digest,
    }


def compile_declarative_analysis_program(
    definition: ResearchDefinition,
) -> tuple[ResearchProgram, tuple[ResearchHostOperation, ...]]:
    spec = _analysis_spec(definition)
    implementation_digest = canonical_digest(
        {
            "compiler": _COMPILER_VERSION,
            "kind": "analysis",
            "definition_digest": definition.definition_digest,
            "analysis_spec": freeze_json(spec),
        }
    )
    operation_name = f"research-os.analysis:{definition.definition_id}"

    def handle(request: ProgramNodeRequest, _binding: object) -> ProgramNodeResult:
        return ProgramNodeResult(value=_analysis_value(definition, request.payload))

    builder = ResearchProgramBuilder(
        program_id=f"research-os:analysis:{definition.definition_id}",
        kind=MachineKind.ANALYSIS,
        version=_COMPILER_VERSION,
        state_schema="json",
        entrypoint="invoke",
    )
    builder.node(
        "invoke",
        operation_name,
        configuration={
            "definition_id": definition.definition_id,
            "definition_digest": definition.definition_digest,
            "analysis_spec": freeze_json(spec),
        },
    )
    return (
        builder.build(),
        (ResearchHostOperation(operation_name, handle, implementation_digest),),
    )


__all__ = [
    "ScientificArtifactReadPort",
    "compile_declarative_analysis_program",
    "compile_declarative_metric_program",
    "compile_declarative_study_measurement_program",
    "materialize_experiment_report_input",
    "materialize_research_scientific_inputs",
]
