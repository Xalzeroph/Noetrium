from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.universal import UnitStepContext, UnitTransition

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Protocol

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    canonical_bytes,
    freeze_json,
    strict_json_loads,
)
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.governance.api import NoetriumUnit, ScopeKind, scope_unit, scope_kind, scope_id
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit
from noetrium_platform.foundation.kernel.kernel.inspection import MachineHistoryInspection
from noetrium_platform.foundation.kernel.kernel.causal_coverage import iter_causal_accepted_event_units
from noetrium_platform.foundation.kernel.kernel.journal import MachineJournalPort
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    require_study_assignment, study_assignment_text, study_assignment_repetition,
    study_assignment_digest, study_assignment_workload, assignment_workload_task_ids,
)
from noetrium_platform.research.execution.machines.api import UnitOperationBinding, NoetriumUnit, unit_operation, executable_unit
from noetrium_platform.research.experimentation.lifecycle.experiment.api import (
    raw_record,
)
from noetrium_platform.research.experimentation.projection import MetricEngine
from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
    metric_definition_digest,
    metric_definition_unit,
    metric_definition_value,
    metric_id,
    metric_predicate_unit,
)
from noetrium_platform.research.experimentation.workbench.api import (
    DataColumn,
    DataTable,
    MissingValuePolicy,
    MultipleComparisonMethod,
)
from noetrium_platform.research.experimentation.api import (
    analysis_definition_unit,
    analysis_definition_digest,
    analysis_output_schema_id,
    AnalysisResult,
    measurement_cut_digest,
    measurement_cut_unit,
)
from noetrium_platform.research.experimentation.workbench.composition import (
    compose_standard_research_statistics,
)


_COMPILER_VERSION = "research-scientific-analysis.v2"


def machine_journal_metric_records(
    inspection: MachineHistoryInspection,
) -> tuple[NoetriumUnit, ...]:
    """Project accepted Machine Events into the existing universal MetricEngine.

    This is a stateless scientific composition, not an alternate log/metric
    authority. Downstream Metric Definition Units can query all committed event
    fields long after the experiment, with exact source-commit provenance.
    """
    if not isinstance(inspection, MachineHistoryInspection):
        raise TypeError("scientific event metrics require verified Machine history")
    return tuple(
        _machine_event_metric_record(event)
        for event in inspection.iter_accepted_event_units()
    )


def machine_causal_metric_records(
    inspection: MachineHistoryInspection,
    journal: MachineJournalPort,
) -> tuple[NoetriumUnit, ...]:
    """Derive metrics from the *entire certified* parent/child Machine cut."""
    return tuple(
        _machine_event_metric_record(event)
        for event in iter_causal_accepted_event_units(inspection, journal)
    )


def _machine_event_metric_record(event: NoetriumUnit) -> NoetriumUnit:
    payload = event.attribute("payload")
    kind = (
        str(payload.get("type"))
        if isinstance(payload, Mapping) and payload.get("type") is not None
        else "untyped"
    )
    return raw_record(
        record_type="machine.accepted-event",
        record_id=event.unit_digest,
        caused_by=(str(event.attribute("source_commit_id")),),
        provenance={
            "authority": "machine-journal",
            "accepted_event_unit_digest": event.unit_digest,
            "source_commit_id": event.attribute("source_commit_id"),
        },
        payload={
            "envelope": {"schema_id": "noetrium.machine.accepted-event.v1"},
            "dimensions": {
                "machine_id": event.attribute("machine_id"),
                "event_kind": kind,
                "unit_digest": event.attribute("unit_digest"),
            },
            "data": {
                "event": payload,
                "revision": event.attribute("revision"),
                "event_index": event.attribute("event_index"),
            },
        },
    )


class ScientificArtifactReadPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def read(self, reference: ArtifactReference) -> bytes: ...


def _artifact_reference(value: object, field: str) -> ArtifactReference:
    row = _mapping(value, field)
    raw_scope = _mapping(row["scope"], field + " scope")
    if raw_scope.get("schema") == "noetrium.unit.document.v2":
        # Trial's authoritative ArtifactReference stores a typed scope Unit.
        owner = decode_unit(canonical_bytes(raw_scope))
        owner_kind, owner_id = scope_kind(owner), scope_id(owner)
    else:
        # Experiment report manifests currently serialize their own scope
        # reference as canonical {kind, scope_id} (not a Unit document).
        owner_kind = ScopeKind(str(raw_scope["kind"]))
        owner_id = str(raw_scope["scope_id"])
    return ArtifactReference(
        str(row["reference_id"]),
        scope_unit(owner_kind, owner_id),
        str(row["artifact_id"]),
        int(row["generation"]),
    )


def _read_json_artifact(
    content: ScientificArtifactReadPort,
    value: object,
    field: str,
) -> JsonValue:
    reference = _mapping(value, field)
    payload = content.read(_artifact_reference(reference, field))
    expected = reference.get("content_sha256")
    if expected is not None and sha256(payload).hexdigest() != str(expected):
        raise ValueError(f"{field} content digest drifted from published reference")
    return strict_json_loads(payload)


def _is_experiment_report_ref(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("schema") == "research.experiment-report-ref.v4"
        and isinstance(value.get("manifest"), Mapping)
    )


def _assignment_row(document: object) -> dict[str, JsonValue]:
    """Decode exactly the typed StudyAssignment stored by the Trial producer."""
    assignment = require_study_assignment(
        decode_unit(canonical_bytes(_mapping(document, "experiment assignment Unit")))
    )
    workload = study_assignment_workload(assignment)
    return {
        "study_id": study_assignment_text(assignment, "study_id"),
        "variant_id": study_assignment_text(assignment, "variant_id"),
        "repetition": study_assignment_repetition(assignment),
        "seed": study_assignment_text(assignment, "seed"),
        "assignment_digest": study_assignment_digest(assignment),
        "task_id": None,
        "workload_task_ids": "|".join(assignment_workload_task_ids(workload)),
    }


def _observation_row(value: object, assignment: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    observation = _mapping(value, "experiment observation")
    row: dict[str, JsonValue] = dict(assignment)
    for pair in _sequence(observation.get("metrics", ()), "observation metrics"):
        values = _sequence(pair, "observation metric")
        if len(values) != 2:
            raise ValueError("observation metric rows must be pairs")
        metric_name = str(values[0])
        if metric_name in row:
            raise ValueError(
                f"scientific metric {metric_name!r} collides with Assignment identity"
            )
        row[metric_name] = freeze_json(values[1])
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
    assignment = assignment_by_digest.get(assignment_digest)
    if assignment is None:
        raise ValueError(
            "MeasurementRecord references Assignment absent from Experiment observations"
        )
    if (
        str(record["study_id"]) != str(assignment["study_id"])
        or str(record["variant_id"]) != str(assignment["variant_id"])
    ):
        raise ValueError(
            "MeasurementRecord scientific identity drifted from typed Assignment"
        )
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
    if manifest.get("schema") != "research.experiment-report-manifest.v4":
        raise ValueError("unsupported Experiment report manifest schema")
    evidence_graph = _mapping(
        _read_json_artifact(
            content,
            manifest["scientific_evidence_graph_artifact"],
            "scientific evidence graph artifact",
        ),
        "scientific evidence graph",
    )
    if evidence_graph.get("schema") != "noetrium.scientific-evidence-unit.v2":
        raise ValueError("unsupported scientific evidence Unit schema")
    if str(evidence_graph.get("graph_digest")) != str(
        manifest["scientific_evidence_graph_digest"]
    ):
        raise ValueError("scientific evidence graph digest drifted from manifest")
    for name in ("execution_binding_digest", "execution_cut_id", "content_authority_digest"):
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
    assignments = tuple(_assignment_row(row["assignment"]) for row in observations)
    rows = tuple(
        _observation_row(observation, assignment)
        for observation, assignment in zip(observations, assignments)
    )
    assignment_by_digest = {
        str(assignment["assignment_digest"]): assignment for assignment in assignments
    }
    if len(assignment_by_digest) != len(assignments):
        raise ValueError("Experiment observations repeat one Assignment identity")

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
    projected: dict[str, JsonValue] | None = None
    materialized_reports: list[Mapping[str, Any]] = []
    for key, value in payload.items():
        if not _is_experiment_report_ref(value):
            continue
        materialized = materialize_experiment_report_input(value, content)
        if projected is None:
            projected = dict(payload)
        projected[str(key)] = materialized
        materialized_reports.append(_mapping(materialized, "analysis input"))
    if projected is None:
        # Hot path for ordinary Method/Analysis Unit values: zero copy,
        # zero digest change, no content-authority access.
        return payload
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


def _symbol_parameters(definition: NoetriumUnit) -> Mapping[str, Any]:
    return _mapping(definition.parameters, "research scientific symbol parameters")


def _metric_definition(definition: NoetriumUnit) -> NoetriumUnit:
    config = _symbol_parameters(definition)
    spec = _mapping(config.get("derived_metric"), "derived metric specification")
    predicates = tuple(
        metric_predicate_unit(
            tuple(str(part) for part in _sequence(row["path"], "metric predicate path")),
            freeze_json(row["equals"]),
        )
        for row in (
            _mapping(item, "metric predicate")
            for item in _sequence(spec.get("predicates", ()), "metric predicates")
        )
    )
    return metric_definition_unit(
        str(spec["metric_id"]),
        aggregation=str(spec["aggregation"]),
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
        missing=str(spec.get("missing", "skip")),
        unit=None if spec.get("unit") is None else str(spec.get("unit")),
        description=str(spec.get("description", "")),
    )


def _raw_record(row: Mapping[str, Any]):
    body={"data":freeze_json(row.get("payload")),"envelope":freeze_json(dict(row)),"dimensions":freeze_json(row.get("dimensions",{}))}
    return raw_record(record_type=str(row["record_type"]),payload=body)


def _metric_payload_rows(payload: object) -> tuple[Mapping[str, Any], ...]:
    mapping = _mapping(payload, "declarative metric payload")
    rows = _sequence(mapping.get("raw_records"), "declarative metric raw_records")
    return tuple(_mapping(row, "declarative metric raw record") for row in rows)


def _metric_result(
    definition: NoetriumUnit,
    report: object,
) -> JsonValue:
    group_names = tuple(".".join(path) for path in metric_definition_value(definition, "group_by"))
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
        "metric_id": metric_id(definition),
        "raw_cut_digest": report.raw_cut_digest,
        "definitions_digest": report.definitions_digest,
        "group_by": group_names,
        "values": values,
        "report_digest": report.report_digest,
    }


def compile_declarative_metric_program(
    definition: NoetriumUnit,
) -> tuple[NoetriumUnit, tuple[UnitOperationBinding, ...]]:
    metric = _metric_definition(definition)
    implementation_digest = canonical_digest(
        {
            "compiler": _COMPILER_VERSION,
            "kind": "derived-metric",
            "symbol_digest": definition.symbol_digest,
            "metric_definition_digest": metric_definition_digest(metric),
        }
    )
    operation_name = f"research.metric:{definition.symbol_id}"

    def handle(request: UnitStepContext, _binding: object) -> UnitTransition:
        records = tuple(_raw_record(row) for row in _metric_payload_rows(request.payload))
        report = MetricEngine.evaluate(records, (metric,))
        return UnitTransition.goto(value=_metric_result(metric, report))

    program = executable_unit(
        f"research:evaluation:{definition.symbol_id}",
        domain="evaluation",
        version=_COMPILER_VERSION,
        state_schema="json",
        entrypoint="invoke",
        members=(unit_operation(
            "invoke",
            operation_name,
            configuration={
                "symbol_id": definition.symbol_id,
                "symbol_digest": definition.symbol_digest,
                "metric_definition_digest": metric_definition_digest(metric),
            },
        ),),
    )
    return (
        program,
        (UnitOperationBinding(operation_name, handle, implementation_digest),),
    )


def _study_measurement_result(
    definition: NoetriumUnit,
    payload: object,
) -> JsonValue:
    spec = _mapping(
        _symbol_parameters(definition).get("measurement"),
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
        "symbol_digest": definition.symbol_digest,
    }
    result["report_digest"] = canonical_digest(result)
    return freeze_json(result)


def compile_declarative_study_measurement_program(
    definition: NoetriumUnit,
) -> tuple[NoetriumUnit, tuple[UnitOperationBinding, ...]]:
    spec = _mapping(
        _symbol_parameters(definition).get("measurement"),
        "measurement specification",
    )
    operation_name = f"research.measurement:{definition.symbol_id}"
    implementation_digest = canonical_digest(
        {
            "compiler": _COMPILER_VERSION,
            "kind": "study-measurement",
            "symbol_digest": definition.symbol_digest,
            "measurement_spec": freeze_json(spec),
        }
    )

    def handle(request: UnitStepContext, _binding: object) -> UnitTransition:
        return UnitTransition.goto(value=_study_measurement_result(definition, request.payload))

    program = executable_unit(
        f"research:evaluation:{definition.symbol_id}",
        domain="evaluation",
        version=_COMPILER_VERSION,
        state_schema="json",
        entrypoint="invoke",
        members=(unit_operation(
            "invoke",
            operation_name,
            configuration={
                "symbol_id": definition.symbol_id,
                "symbol_digest": definition.symbol_digest,
                "measurement_spec": freeze_json(spec),
            },
        ),),
    )
    return (
        program,
        (UnitOperationBinding(operation_name, handle, implementation_digest),),
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


def _table(payload: object, definition: NoetriumUnit) -> DataTable:
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
        f"research:{definition.symbol_id}",
        columns,
        values,
        source_digest=canonical_digest(tuple(freeze_json(dict(row)) for row in rows)),
        metadata=(
            ("source_format", "research_json_rows"),
            ("symbol_id", definition.symbol_id),
        ),
    )


def _analysis_spec(definition: NoetriumUnit) -> Mapping[str, Any]:
    config = _symbol_parameters(definition)
    return _mapping(config.get("analysis"), "analysis specification")


def _analysis_value(
    definition: NoetriumUnit,
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
    cut = measurement_cut_unit(record_digests=record_digests)
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
            "symbol_digest": definition.symbol_digest,
        }
    )
    analysis_definition = analysis_definition_unit(
        analysis_id=definition.symbol_id,
        projector_id="research-json-table",
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
        analysis_digest=analysis_definition_digest(analysis_definition),
        input_cut_digest=measurement_cut_digest(cut),
        output_schema_id=analysis_output_schema_id(analysis_definition),
        output_content_digest=output_content_digest,
    )
    return {
        "analysis_id": definition.symbol_id,
        "research_symbol_digest": definition.symbol_digest,
        "analysis_digest": analysis_definition_digest(analysis_definition),
        "input_cut_digest": cut.cut_digest,
        "table_digest": table.table_digest,
        "summaries": plain_summaries,
        "inference_method": inference_method,
        "inference": plain_inference,
        "output_content_digest": output_content_digest,
        "analysis_result_digest": analysis_result.result_digest,
    }


def compile_declarative_analysis_program(
    definition: NoetriumUnit,
) -> tuple[NoetriumUnit, tuple[UnitOperationBinding, ...]]:
    spec = _analysis_spec(definition)
    implementation_digest = canonical_digest(
        {
            "compiler": _COMPILER_VERSION,
            "kind": "analysis",
            "symbol_digest": definition.symbol_digest,
            "analysis_spec": freeze_json(spec),
        }
    )
    operation_name = f"research.analysis:{definition.symbol_id}"

    def handle(request: UnitStepContext, _binding: object) -> UnitTransition:
        return UnitTransition.goto(value=_analysis_value(definition, request.payload))

    program = executable_unit(
        f"research:analysis:{definition.symbol_id}",
        domain="analysis",
        version=_COMPILER_VERSION,
        state_schema="json",
        entrypoint="invoke",
        members=(unit_operation(
            "invoke",
            operation_name,
            configuration={
                "symbol_id": definition.symbol_id,
                "symbol_digest": definition.symbol_digest,
                "analysis_spec": freeze_json(spec),
            },
        ),),
    )
    return (
        program,
        (UnitOperationBinding(operation_name, handle, implementation_digest),),
    )


__all__ = [
    "ScientificArtifactReadPort",
    "compile_declarative_analysis_program",
    "compile_declarative_metric_program",
    "compile_declarative_study_measurement_program",
    "materialize_experiment_report_input",
    "materialize_research_scientific_inputs",
]
