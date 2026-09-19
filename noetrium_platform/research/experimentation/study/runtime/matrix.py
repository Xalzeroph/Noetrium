from __future__ import annotations

from noetrium_platform.research.experimentation.experiment.api.contracts import (
    canonical_digest, require_sha256,
    ExperimentDefinition as UniversalExperimentDefinition,
    ExperimentDoctorPort,
    ExperimentLifecycleState as UniversalExperimentLifecycleState,
    ExperimentPlan as UniversalExperimentPlan,
    ExperimentRunReport as UniversalExperimentRunReport,
    ExperimentUnit as UniversalExperimentUnit,
    ExperimentUnitKind as UniversalExperimentUnitKind,
    FindingSeverity as UniversalFindingSeverity,
    ObservationEnvelope as UniversalObservationEnvelope,
    ObservationKind as UniversalObservationKind,
    ObservationSinkPort as UniversalObservationSinkPort,
    RawRecord as UniversalRawRecord,
    RawRecordStorePort as UniversalRawRecordStorePort,
    MetricAggregation as UniversalMetricAggregation,
    MetricDefinition as UniversalMetricDefinition,
    MetricMissingPolicy as UniversalMetricMissingPolicy,
    MetricPredicate as UniversalMetricPredicate,
    MetricReport as UniversalMetricReport,
    MetricValue as UniversalMetricValue,
    DoctorFinding as UniversalDoctorFinding,
    UnitOutcome as UniversalUnitOutcome,
    UnitOutcomeState as UniversalUnitOutcomeState,
)
from dataclasses import dataclass

from collections.abc import Mapping
import math
from threading import RLock

from ..api import (
    StudyAssignment,
    StudyMatrixExecutionReport,
)

class StudyMatrixUniversalProjection:
    """Project matrix assignments into family-neutral experiment units.

    The projection deliberately preserves assignment identity and does not
    expose benchmark/task assumptions to the universal planner.
    """

    @staticmethod
    def plan(
        experiment_id: str,
        definition_digest: str,
        assignments: tuple[StudyAssignment, ...],
    ) -> UniversalExperimentPlan:
        if type(experiment_id) is not str or not experiment_id.strip():
            raise ValueError("experiment_id must be non-empty")
        require_sha256(definition_digest, "definition_digest")
        if type(assignments) is not tuple or not assignments:
            raise ValueError("assignments must be a non-empty tuple")
        if any(not isinstance(item, StudyAssignment) for item in assignments):
            raise TypeError("assignments must contain StudyAssignment")
        units = tuple(
            UniversalExperimentUnit(
                unit_id=f"assignment:{item.assignment_digest}",
                kind=UniversalExperimentUnitKind.TASK if item.task_id is not None else UniversalExperimentUnitKind.GENERIC,
                input_digest=canonical_digest({
                    "task_id": item.task_id,
                    "study_id": item.study_id,
                }),
                condition_digest=canonical_digest({
                    "variant_id": item.variant_id,
                    "repetition": item.repetition,
                }),
                seed=item.seed,
                ordinal=ordinal,
            )
            for ordinal, item in enumerate(assignments)
        )
        return UniversalExperimentPlan(
            experiment_id=experiment_id,
            definition_digest=definition_digest,
            units=units,
            planner_id="study-matrix-universal-projection-v1",
        )


class StaticUnitPlanner:
    """Reference planner; family-specific planners can implement the same port."""

    def plan(self, definition: UniversalExperimentDefinition, units: tuple[UniversalExperimentUnit, ...]) -> UniversalExperimentPlan:
        if any(unit.kind is not definition.unit_kind for unit in units):
            raise ValueError("unit kind does not match experiment definition")
        return UniversalExperimentPlan(definition.experiment_id, definition.definition_digest, units)


class InMemoryObservationProjection(UniversalObservationSinkPort):
    """Disposable ordered observation projection; never a raw-fact authority."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._observations: list[UniversalObservationEnvelope] = []
        self._last_sequence: dict[tuple[str, str], int] = {}

    def append(self, observation: UniversalObservationEnvelope) -> None:
        with self._lock:
            key = (observation.run_id, observation.unit_id)
            last = self._last_sequence.get(key, -1)
            if observation.sequence != last + 1:
                raise ValueError(f"observation sequence gap or duplicate for {key!r}")
            self._last_sequence[key] = observation.sequence
            self._observations.append(observation)

    def snapshot(self) -> tuple[UniversalObservationEnvelope, ...]:
        with self._lock:
            return tuple(self._observations)


def _metric_path(value: object, path: tuple[str, ...]) -> tuple[bool, object]:
    current = value
    for part in path:
        if isinstance(current, Mapping):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, (tuple, list)) and part.isdecimal():
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _metric_record_path(record: UniversalRawRecord, path: tuple[str, ...]) -> tuple[bool, object]:
    """Resolve payload paths and explicit envelope/dimension namespaces.

    Existing payload paths remain concise; envelope and extensible dimensions
    are addressed as envelope.* and dimensions.* so every captured fact can
    become a metric without changing the raw ledger.
    """
    if path and path[0] == "envelope":
        envelope = {
            "experiment_id": record.experiment_id, "run_id": record.run_id,
            "unit_id": record.unit_id, "sequence": record.sequence,
            "stream_id": record.stream_id, "attempt_id": record.attempt_id,
            "causation_id": record.causation_id, "correlation_id": record.correlation_id,
            "trace_id": record.trace_id, "span_id": record.span_id,
            "occurred_at": record.occurred_at, "recorded_at": record.recorded_at,
            "monotonic_ns": record.monotonic_ns, "clock_source": record.clock_source,
            "clock_uncertainty_ns": record.clock_uncertainty_ns,
            "producer_id": record.producer_id, "producer_version": record.producer_version,
            "schema_id": record.schema_id, "record_type": record.record_type,
            "event_name": record.event_name, "operation_id": record.operation_id,
            "status": record.status, "outcome": record.outcome,
            "raw_payload_digest": record.raw_payload_digest,
            "record_digest": record.record_digest,
            "content_type": record.content_type, "content_encoding": record.content_encoding,
            "sampled": record.sampled, "sampling_rate": record.sampling_rate,
        }
        return _metric_path(envelope, path[1:])
    if path and path[0] == "dimensions":
        return _metric_path(record.dimensions, path[1:])
    present, value = _metric_path(record.payload, path)
    if present:
        return present, value
    return _metric_path(record.dimensions, path)


def _metric_number(value: object, metric_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"metric {metric_id} requires numeric values")
    if not math.isfinite(float(value)):
        raise ValueError(f"metric {metric_id} requires finite numeric values")
    return float(value)


def _metric_aggregate(
    aggregation: UniversalMetricAggregation,
    values: list[object],
    metric_id: str,
) -> object:
    if aggregation is UniversalMetricAggregation.COUNT:
        return len(values)
    if aggregation is UniversalMetricAggregation.FIRST:
        return values[0] if values else None
    if aggregation is UniversalMetricAggregation.LAST:
        return values[-1] if values else None
    if aggregation is UniversalMetricAggregation.DISTINCT_COUNT:
        return len({canonical_digest(item) for item in values})
    numbers = [_metric_number(item, metric_id) for item in values]
    if aggregation is UniversalMetricAggregation.SUM:
        return sum(numbers)
    if not numbers:
        return 0.0
    if aggregation is UniversalMetricAggregation.MEAN:
        return sum(numbers) / len(numbers)
    if aggregation is UniversalMetricAggregation.MIN:
        return min(numbers)
    if aggregation is UniversalMetricAggregation.MAX:
        return max(numbers)
    if aggregation is UniversalMetricAggregation.STDDEV:
        mean = sum(numbers) / len(numbers)
        return math.sqrt(sum((item - mean) ** 2 for item in numbers) / len(numbers))
    ordered = sorted(numbers)
    rank = (len(ordered) - 1) * (0.50 if aggregation is UniversalMetricAggregation.P50 else 0.95)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


_MISSING_METRIC_VALUE = object()


def _metric_record_matches(
    record: UniversalRawRecord,
    definition: UniversalMetricDefinition,
) -> bool:
    if definition.record_types and record.record_type not in definition.record_types:
        return False
    if definition.schema_ids and record.schema_id not in definition.schema_ids:
        return False
    return all(
        _metric_record_path(record, predicate.path)[0]
        and _metric_record_path(record, predicate.path)[1] == predicate.equals
        for predicate in definition.predicates
    )


def _metric_group_values(
    record: UniversalRawRecord,
    definition: UniversalMetricDefinition,
) -> tuple[object, ...] | None:
    values: list[object] = []
    for path in definition.group_by:
        present, value = _metric_record_path(record, path)
        if not present:
            return None
        values.append(value)
    return tuple(values)


def _metric_value(
    record: UniversalRawRecord,
    definition: UniversalMetricDefinition,
) -> object:
    if definition.aggregation is UniversalMetricAggregation.COUNT:
        return 1
    present, value = _metric_record_path(record, definition.value_path)
    if present:
        return value
    if definition.missing is UniversalMetricMissingPolicy.FAIL:
        raise ValueError(f"metric {definition.metric_id} has a missing value field")
    if definition.missing is UniversalMetricMissingPolicy.ZERO:
        return 0
    return _MISSING_METRIC_VALUE


def _metric_values_for_definition(
    records: tuple[UniversalRawRecord, ...],
    definition: UniversalMetricDefinition,
) -> list[UniversalMetricValue]:
    groups: dict[str, tuple[tuple[object, ...], list[object], list[UniversalRawRecord]]] = {}
    for record in records:
        if not _metric_record_matches(record, definition):
            continue
        key_values = _metric_group_values(record, definition)
        if key_values is None:
            if definition.missing is UniversalMetricMissingPolicy.FAIL:
                raise ValueError(f"metric {definition.metric_id} has a missing group field")
            continue
        value = _metric_value(record, definition)
        if value is _MISSING_METRIC_VALUE:
            continue
        group_key = canonical_digest(key_values)
        row = groups.setdefault(group_key, (key_values, [], []))
        row[1].append(value)
        row[2].append(record)
    if not groups:
        empty_value = (
            0
            if definition.aggregation
            in (UniversalMetricAggregation.COUNT, UniversalMetricAggregation.DISTINCT_COUNT)
            else _metric_aggregate(definition.aggregation, [], definition.metric_id)
        )
        return [UniversalMetricValue(definition.metric_id, (), empty_value, 0, ())]
    values: list[UniversalMetricValue] = []
    for key_values, group_values, group_records in groups.values():
        values.append(
            UniversalMetricValue(
                definition.metric_id,
                key_values,
                _metric_aggregate(definition.aggregation, group_values, definition.metric_id),
                len(group_values),
                tuple(sorted(record.record_digest for record in group_records)),
            )
        )
    return values


class MetricEngine:
    """Compile no code; evaluate typed metric declarations over an immutable cut."""

    @staticmethod
    def evaluate(
        records: tuple[UniversalRawRecord, ...],
        definitions: tuple[UniversalMetricDefinition, ...],
    ) -> UniversalMetricReport:
        if type(records) is not tuple or any(type(item) is not UniversalRawRecord for item in records):
            raise TypeError("metric engine records must contain RawRecord")
        if type(definitions) is not tuple or not definitions:
            raise ValueError("metric engine definitions must be a non-empty tuple")
        ids = tuple(item.metric_id for item in definitions)
        if len(ids) != len(set(ids)):
            raise ValueError("metric definitions must have unique metric ids")
        record_ids = tuple(item.record_digest for item in records)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("metric engine raw cut contains duplicate records")
        values: list[UniversalMetricValue] = []
        for definition in definitions:
            values.extend(_metric_values_for_definition(records, definition))
        values.sort(key=lambda item: (item.metric_id, canonical_digest(item.group_key)))
        return UniversalMetricReport(
            canonical_digest(record_ids),
            canonical_digest(tuple(item.definition_digest for item in definitions)),
            tuple(values),
        )


@dataclass(frozen=True, slots=True)
class DoctorReport:
    findings: tuple[UniversalDoctorFinding, ...]

    @property
    def healthy(self) -> bool:
        return not any(item.blocking for item in self.findings)


class ExperimentDoctor(ExperimentDoctorPort):
    def inspect(self, plan: UniversalExperimentPlan, observations: tuple[UniversalObservationEnvelope, ...]) -> tuple[UniversalDoctorFinding, ...]:
        expected = {unit.unit_id for unit in plan.units}
        seen = {item.unit_id for item in observations}
        findings: list[UniversalDoctorFinding] = []
        for unit_id in sorted(expected - seen):
            findings.append(UniversalDoctorFinding(
                "unit.missing", UniversalFindingSeverity.ERROR, unit_id,
                "planned experiment unit produced no observation",
                blocking=True, recovery_action="retry_unit",
            ))
        unknown = sorted(seen - expected)
        for unit_id in unknown:
            findings.append(UniversalDoctorFinding(
                "unit.unknown", UniversalFindingSeverity.CRITICAL, unit_id,
                "observation references a unit absent from the frozen plan",
                blocking=True,
            ))
        by_stream: dict[tuple[str, str], list[UniversalObservationEnvelope]] = {}
        for item in observations:
            if item.experiment_id != plan.experiment_id:
                findings.append(UniversalDoctorFinding(
                    "observation.experiment_mismatch", UniversalFindingSeverity.CRITICAL,
                    item.unit_id, "observation belongs to another experiment",
                    blocking=True,
                ))
            by_stream.setdefault((item.run_id, item.unit_id), []).append(item)
        seen_digests: set[str] = set()
        for stream, items in by_stream.items():
            sequences = sorted(item.sequence for item in items)
            if len(sequences) != len(set(sequences)):
                findings.append(UniversalDoctorFinding(
                    "observation.duplicate_sequence", UniversalFindingSeverity.ERROR,
                    stream[1], "observation stream contains duplicate sequence numbers",
                    blocking=True, recovery_action="deduplicate_stream",
                ))
            expected_sequences = list(range(len(sequences)))
            if sequences != expected_sequences:
                findings.append(UniversalDoctorFinding(
                    "observation.sequence_gap", UniversalFindingSeverity.ERROR,
                    stream[1], "observation stream is not contiguous from sequence zero",
                    blocking=True, recovery_action="replay_missing_events",
                ))
            for item in items:
                if item.observation_digest in seen_digests:
                    findings.append(UniversalDoctorFinding(
                        "observation.duplicate", UniversalFindingSeverity.ERROR,
                        item.unit_id, "duplicate observation digest detected",
                        blocking=True, recovery_action="deduplicate_stream",
                    ))
                seen_digests.add(item.observation_digest)
        return tuple(findings)

    def report(self, plan: UniversalExperimentPlan, observations: tuple[UniversalObservationEnvelope, ...]) -> DoctorReport:
        return DoctorReport(self.inspect(plan, observations))



class UniversalExperimentKernel:
    def __init__(self, planner: StaticUnitPlanner | None = None, doctor: UniversalExperimentDoctor | None = None) -> None:
        self.planner = planner or StaticUnitPlanner()
        self.doctor = doctor or ExperimentDoctor()

    def compile(self, definition: UniversalExperimentDefinition, units: tuple[UniversalExperimentUnit, ...]) -> UniversalExperimentPlan:
        return self.planner.plan(definition, units)

    def inspect(self, plan: UniversalExperimentPlan, observations: tuple[UniversalObservationEnvelope, ...]) -> UniversalDoctorReport:
        return self.doctor.report(plan, observations)



def project_experiment_run_report(
    plan: UniversalExperimentPlan,
    run_id: str,
    outcomes: tuple[UniversalUnitOutcome, ...],
    observations: tuple[UniversalObservationEnvelope, ...],
    *,
    doctor: ExperimentDoctor | None = None,
) -> UniversalExperimentRunReport:
    """Project committed unit outcomes and an observation cut into a terminal report.

    This function never executes units and owns no lifecycle state. Execution truth
    must already be committed by the execution/workload authorities.
    """
    if type(outcomes) is not tuple:
        raise TypeError("experiment report outcomes must be an immutable tuple")
    expected_ids = tuple(unit.unit_id for unit in plan.units)
    actual_ids = tuple(outcome.unit_id for outcome in outcomes)
    if actual_ids != expected_ids:
        raise ValueError("experiment report outcomes must exactly match the planned unit order")
    findings = (doctor or ExperimentDoctor()).inspect(plan, observations)
    failed = any(item.state is not UniversalUnitOutcomeState.SUCCEEDED for item in outcomes)
    blocked = any(item.blocking for item in findings)
    if not failed and not blocked:
        terminal = UniversalExperimentLifecycleState.COMPLETED
    elif any(item.state is UniversalUnitOutcomeState.SUCCEEDED for item in outcomes):
        terminal = UniversalExperimentLifecycleState.PARTIAL
    else:
        terminal = UniversalExperimentLifecycleState.FAILED
    return UniversalExperimentRunReport(
        plan.experiment_id, run_id, plan.plan_digest, terminal, outcomes, findings
    )


UniversalExperimentDoctor = ExperimentDoctor
UniversalDoctorReport = DoctorReport

__all__ = [
    "StudyMatrixUniversalProjection", "StaticUnitPlanner",
    "InMemoryObservationProjection", "DoctorReport", "ExperimentDoctor",
    "UniversalExperimentKernel", "MetricEngine", "project_experiment_run_report",
]
