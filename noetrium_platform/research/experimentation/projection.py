from __future__ import annotations

from collections.abc import Mapping
import math

from noetrium_platform.foundation.kernel.record import (
    record_digest,
    record_payload,
    record_type,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
    metric_aggregation,
    metric_definition_digest,
    metric_definition_value,
    metric_id,
    metric_predicates,
    metric_definition_unit,
    metric_predicate_unit,
    require_metric_definition,
)
from noetrium_platform.research.experimentation.lifecycle.experiment.api import (
    MetricAggregation as UniversalMetricAggregation,
    MetricMissingPolicy as UniversalMetricMissingPolicy,
    MetricReport as UniversalMetricReport,
    MetricValue as UniversalMetricValue,
    raw_record,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    StudyMetricAggregate,
    StudyMetricObservation,
    study_assignment_digest,
    study_assignment_text,
    study_protocol_metric_names,
    study_protocol_text,
)



def _metric_aggregation_of(definition: NoetriumUnit) -> UniversalMetricAggregation:
    return UniversalMetricAggregation(metric_aggregation(require_metric_definition(definition)))


def _metric_missing_of(definition: NoetriumUnit) -> UniversalMetricMissingPolicy:
    return UniversalMetricMissingPolicy(str(metric_definition_value(definition, "missing")))


def _metric_tuple(definition: NoetriumUnit, name: str) -> tuple:
    return tuple(metric_definition_value(definition, name))


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


def _metric_record_path(
    record: NoetriumUnit,
    path: tuple[str, ...],
) -> tuple[bool, object]:
    payload = record_payload(record)
    envelope = payload.get("envelope", {})
    dimensions = payload.get("dimensions", {})
    data = payload.get("data", {})
    if path and path[0] == "envelope":
        return _metric_path(envelope, path[1:])
    if path and path[0] == "dimensions":
        return _metric_path(dimensions, path[1:])
    present, value = _metric_path(data, path)
    return (present, value) if present else _metric_path(dimensions, path)


def _metric_number(value: object, metric_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"metric {metric_id} requires numeric values")
    if not math.isfinite(float(value)):
        raise ValueError(f"metric {metric_id} requires finite numeric values")
    return float(value)


def _online_numeric_stats(numbers: list[float]) -> tuple[int, float, float]:
    """Welford single-pass statistics: O(n) time, O(1) auxiliary state."""

    count = 0
    mean = 0.0
    m2 = 0.0
    for value in numbers:
        count += 1
        delta = value - mean
        mean += delta / count
        m2 += delta * (value - mean)
    return count, mean, m2


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
    if aggregation in (
        UniversalMetricAggregation.MEAN,
        UniversalMetricAggregation.STDDEV,
        UniversalMetricAggregation.SAMPLE_VARIANCE,
        UniversalMetricAggregation.STANDARD_ERROR,
    ):
        count, mean, m2 = _online_numeric_stats(numbers)
        if aggregation is UniversalMetricAggregation.MEAN:
            return mean
        if aggregation is UniversalMetricAggregation.STDDEV:
            return math.sqrt(m2 / count)
        sample_variance = m2 / (count - 1) if count > 1 else 0.0
        if aggregation is UniversalMetricAggregation.SAMPLE_VARIANCE:
            return sample_variance
        return math.sqrt(sample_variance / count)
    if aggregation is UniversalMetricAggregation.MIN:
        return min(numbers)
    if aggregation is UniversalMetricAggregation.MAX:
        return max(numbers)
    ordered = sorted(numbers)
    rank = (len(ordered) - 1) * (
        0.50 if aggregation is UniversalMetricAggregation.P50 else 0.95
    )
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


_MISSING_METRIC_VALUE = object()


def _metric_record_selection(
    record: NoetriumUnit,
    definition: NoetriumUnit,
) -> tuple[bool, bool]:
    """Return (matched, unknown): one selector shared by metrics and proof."""
    types = _metric_tuple(definition, "record_types")
    if types and record_type(record) not in types:
        return False, False
    schemas = _metric_tuple(definition, "schema_ids")
    if schemas and record_payload(record).get("envelope", {}).get("schema_id") not in schemas:
        return False, False
    missing = False
    for predicate in metric_predicates(definition):
        present, value = _metric_record_path(
            record, tuple(predicate.parameters["path"])
        )
        if present and value != predicate.parameters["equals"]:
            return False, False
        if not present:
            missing = True
    return not missing, missing


def _metric_record_matches(
    record: NoetriumUnit,
    definition: NoetriumUnit,
) -> bool:
    return _metric_record_selection(record, definition)[0]


def _metric_group_values(
    record: NoetriumUnit,
    definition: NoetriumUnit,
) -> tuple[object, ...] | None:
    values: list[object] = []
    for path in _metric_tuple(definition, "group_by"):
        present, value = _metric_record_path(record, path)
        if not present:
            return None
        values.append(value)
    return tuple(values)


def _metric_value(
    record: NoetriumUnit,
    definition: NoetriumUnit,
) -> object:
    if _metric_aggregation_of(definition) is UniversalMetricAggregation.COUNT:
        return 1
    present, value = _metric_record_path(record, _metric_tuple(definition, "value_path"))
    if present:
        return value
    if _metric_missing_of(definition) is UniversalMetricMissingPolicy.FAIL:
        raise ValueError(f"metric {metric_id(definition)} has a missing value field")
    if _metric_missing_of(definition) is UniversalMetricMissingPolicy.ZERO:
        return 0
    return _MISSING_METRIC_VALUE


def _metric_values_for_definition(
    records: tuple[NoetriumUnit, ...],
    definition: NoetriumUnit,
) -> list[UniversalMetricValue]:
    groups: dict[
        str,
        tuple[tuple[object, ...], list[object], list[NoetriumUnit]],
    ] = {}
    for record in records:
        if not _metric_record_matches(record, definition):
            continue
        key_values = _metric_group_values(record, definition)
        if key_values is None:
            if _metric_missing_of(definition) is UniversalMetricMissingPolicy.FAIL:
                raise ValueError(
                    f"metric {metric_id(definition)} has a missing group field"
                )
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
            if _metric_aggregation_of(definition)
            in (
                UniversalMetricAggregation.COUNT,
                UniversalMetricAggregation.DISTINCT_COUNT,
            )
            else _metric_aggregate(
                _metric_aggregation_of(definition),
                [],
                metric_id(definition),
            )
        )
        return [
            UniversalMetricValue(
                metric_id(definition),
                (),
                empty_value,
                0,
                (),
            )
        ]
    values: list[UniversalMetricValue] = []
    for key_values, group_values, group_records in groups.values():
        values.append(
            UniversalMetricValue(
                metric_id(definition),
                key_values,
                _metric_aggregate(
                    _metric_aggregation_of(definition),
                    group_values,
                    metric_id(definition),
                ),
                len(group_values),
                tuple(sorted(record_digest(record) for record in group_records)),
            )
        )
    return values


class MetricEngine:
    """Evaluate metric declarations over an immutable cut of record Units."""

    @staticmethod
    def evaluate(
        records: tuple[NoetriumUnit, ...],
        definitions: tuple[NoetriumUnit, ...],
    ) -> UniversalMetricReport:
        if type(records) is not tuple or any(
            type(item) is not NoetriumUnit for item in records
        ):
            raise TypeError("metric engine records must contain NoetriumUnit")
        if type(definitions) is not tuple or not definitions:
            raise ValueError("metric engine definitions must be a non-empty tuple")
        ids = tuple(metric_id(item) for item in definitions)
        if len(ids) != len(set(ids)):
            raise ValueError("metric definitions must have unique metric ids")
        record_ids = tuple(record_digest(item) for item in records)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("metric engine raw cut contains duplicate records")
        values: list[UniversalMetricValue] = []
        for definition in definitions:
            values.extend(_metric_values_for_definition(records, definition))
        values.sort(
            key=lambda item: (
                item.metric_id,
                canonical_digest(item.group_key),
            )
        )
        return UniversalMetricReport(
            canonical_digest(record_ids),
            canonical_digest(
                tuple(metric_definition_digest(item) for item in definitions)
            ),
            tuple(values),
        )


    @staticmethod
    def coverage_unit(
        records: tuple[NoetriumUnit, ...],
        definitions: tuple[NoetriumUnit, ...],
    ) -> NoetriumUnit:
        """Certify field availability on one finite immutable record cut.

        Metric missing='skip' can silently omit records. This independent
        proof reports such omissions; it never asserts unobserved world truth.
        """
        if type(records) is not tuple or any(
            type(x) is not NoetriumUnit for x in records
        ):
            raise TypeError("metric coverage requires immutable record Units")
        if type(definitions) is not tuple or not definitions:
            raise ValueError("metric coverage requires Metric Definition Units")
        ids = tuple(metric_id(x) for x in definitions)
        if len(set(ids)) != len(ids):
            raise ValueError("metric coverage definition identities repeat")
        digests = tuple(record_digest(x) for x in records)
        if len(set(digests)) != len(digests):
            raise ValueError("metric coverage record identities repeat")
        coverage = []
        for definition in definitions:
            selected = predicate_missing = group_missing = value_missing = 0
            for record in records:
                matches, unresolved = _metric_record_selection(record, definition)
                if unresolved:
                    predicate_missing += 1
                    continue
                if not matches:
                    continue
                selected += 1
                if any(
                    not _metric_record_path(record, path)[0]
                    for path in _metric_tuple(definition, "group_by")
                ):
                    group_missing += 1
                if (
                    _metric_aggregation_of(definition) is not UniversalMetricAggregation.COUNT
                    and not _metric_record_path(
                        record, _metric_tuple(definition, "value_path")
                    )[0]
                ):
                    value_missing += 1
            coverage.append({
                "metric_id": metric_id(definition),
                "selected_record_count": selected,
                "missing_predicate_count": predicate_missing,
                "missing_group_count": group_missing,
                "missing_value_count": value_missing,
            })
        complete = all(
            not (row["missing_predicate_count"]
                 or row["missing_group_count"]
                 or row["missing_value_count"])
            for row in coverage
        )
        from noetrium_platform.foundation.kernel.structure import structure_unit
        return structure_unit(
            "metric-coverage:" + canonical_digest((digests, tuple(
                metric_definition_digest(d) for d in definitions
            ))),
            traits=("research.metric-coverage.v1",),
            parameters={
                "coverage_scope": "supplied-immutable-record-cut",
                "raw_cut_digest": canonical_digest(digests),
                "definitions_digest": canonical_digest(tuple(
                    metric_definition_digest(d) for d in definitions
                )),
                "per_metric": tuple(coverage),
                "complete_relative_to_cut": complete,
                "external_truth_verified": False,
            },
        )


_STUDY_METRIC_RECORD_TYPE = "study.metric-observation"
_STUDY_METRIC_SCHEMA_ID = "noetrium.study.metric-observation.v1"
_STUDY_METRIC_STATS = (
    UniversalMetricAggregation.COUNT,
    UniversalMetricAggregation.MEAN,
    UniversalMetricAggregation.SAMPLE_VARIANCE,
    UniversalMetricAggregation.STANDARD_ERROR,
)


def _study_metric_records(
    protocol: NoetriumUnit,
    observations: tuple[StudyMetricObservation, ...],
    *,
    expected_assignment_count: int,
) -> tuple[NoetriumUnit, ...]:
    if type(expected_assignment_count) is not int or expected_assignment_count <= 0:
        raise ValueError("expected_assignment_count must be a positive integer")
    if type(observations) is not tuple or any(
        type(row) is not StudyMetricObservation for row in observations
    ):
        raise TypeError("study metric observations must be typed tuple")
    if len(observations) != expected_assignment_count:
        raise ValueError("study metric projection received incomplete observation matrix")

    study_id = study_protocol_text(protocol, "study_id")
    expected_names = tuple(study_protocol_metric_names(protocol))
    expected_name_set = set(expected_names)
    records: list[NoetriumUnit] = []
    seen_assignments: set[str] = set()
    for observation in observations:
        assignment_digest = study_assignment_digest(observation.assignment)
        if assignment_digest in seen_assignments:
            raise ValueError(
                f"study contains duplicate assignment observation: {assignment_digest}"
            )
        seen_assignments.add(assignment_digest)
        if study_assignment_text(observation.assignment, "study_id") != study_id:
            raise ValueError("study observation belongs to another study")
        metrics = dict(observation.metrics)
        if (set(metrics) | set(observation.unobserved_metric_names)) != expected_name_set:
            missing = sorted(expected_name_set - set(metrics) - set(observation.unobserved_metric_names))
            extra = sorted((set(metrics) | set(observation.unobserved_metric_names)) - expected_name_set)
            raise ValueError(
                "study observation metric schema is incomplete: "
                f"missing={missing!r} extra={extra!r}"
            )
        variant_id = study_assignment_text(observation.assignment, "variant_id")
        for metric_name in expected_names:
            if metric_name not in metrics:
                continue
            records.append(
                raw_record(
                    record_type=_STUDY_METRIC_RECORD_TYPE,
                    payload={
                        "envelope": {
                            "schema_id": _STUDY_METRIC_SCHEMA_ID,
                            "observation_digest": observation.observation_digest,
                        },
                        "dimensions": {
                            "study_id": study_id,
                            "variant_id": variant_id,
                            "metric_name": metric_name,
                            "assignment_digest": assignment_digest,
                        },
                        "data": {"value": float(metrics[metric_name])},
                    },
                )
            )
    return tuple(records)


def _study_metric_definitions(
    metric_names: tuple[str, ...],
) -> tuple[tuple[NoetriumUnit, ...], dict[str, tuple[str, UniversalMetricAggregation]]]:
    definitions: list[NoetriumUnit] = []
    identities: dict[str, tuple[str, UniversalMetricAggregation]] = {}
    for metric_name in metric_names:
        predicate = metric_predicate_unit(
            ("dimensions", "metric_name"),
            metric_name,
        )
        for aggregation in _STUDY_METRIC_STATS:
            definition_id = (
                "study.metric."
                + metric_name
                + "."
                + aggregation.value
            )
            definition = metric_definition_unit(
                definition_id,
                aggregation=aggregation.value,
                record_types=(_STUDY_METRIC_RECORD_TYPE,),
                schema_ids=(_STUDY_METRIC_SCHEMA_ID,),
                value_path=(
                    ()
                    if aggregation is UniversalMetricAggregation.COUNT
                    else ("value",)
                ),
                group_by=(("dimensions", "variant_id"),),
                predicates=(predicate,),
                missing="fail",
                description=(
                    "Canonical Study aggregate projection from immutable "
                    "metric observation records."
                ),
            )
            definitions.append(definition)
            identities[definition_id] = (metric_name, aggregation)
    return tuple(definitions), identities


def evaluate_study_metric_aggregates(
    protocol: NoetriumUnit,
    observations: tuple[StudyMetricObservation, ...],
    *,
    expected_assignment_count: int,
) -> tuple[StudyMetricAggregate, ...]:
    """Project Study aggregates through the single universal MetricEngine."""

    metric_names = tuple(study_protocol_metric_names(protocol))
    if not metric_names:
        raise ValueError("study metric projection requires declared metric names")
    records = _study_metric_records(
        protocol,
        observations,
        expected_assignment_count=expected_assignment_count,
    )
    observed_names = tuple(
        name for name in metric_names
        if any(name == metric for observation in observations for metric, _ in observation.metrics)
    )
    if not observed_names:
        raise ValueError("Study has no authoritative numeric measurements to aggregate")
    definitions, identities = _study_metric_definitions(observed_names)
    report = MetricEngine.evaluate(records, definitions)

    grouped: dict[tuple[str, str], dict[UniversalMetricAggregation, object]] = {}
    for row in report.values:
        identity = identities.get(row.metric_id)
        if identity is None:
            raise RuntimeError("MetricEngine returned undeclared Study metric")
        metric_name, aggregation = identity
        if len(row.group_key) != 1 or type(row.group_key[0]) is not str:
            raise RuntimeError("Study metric projection returned invalid variant group")
        key = (row.group_key[0], metric_name)
        bucket = grouped.setdefault(key, {})
        if aggregation in bucket:
            raise RuntimeError("Study metric projection duplicated aggregate statistic")
        bucket[aggregation] = row.value

    aggregates: list[StudyMetricAggregate] = []
    required = set(_STUDY_METRIC_STATS)
    for (variant_id, metric_name), values in sorted(grouped.items()):
        if set(values) != required:
            missing = sorted(row.value for row in required - set(values))
            raise RuntimeError(
                "Study metric projection incomplete for "
                f"{variant_id!r}/{metric_name!r}: missing={missing!r}"
            )
        aggregates.append(
            StudyMetricAggregate(
                study_id=study_protocol_text(protocol, "study_id"),
                variant_id=variant_id,
                metric_name=metric_name,
                count=int(values[UniversalMetricAggregation.COUNT]),
                mean=float(values[UniversalMetricAggregation.MEAN]),
                sample_variance=float(
                    values[UniversalMetricAggregation.SAMPLE_VARIANCE]
                ),
                standard_error=float(
                    values[UniversalMetricAggregation.STANDARD_ERROR]
                ),
            )
        )
    return tuple(aggregates)


__all__ = ["MetricEngine", "evaluate_study_metric_aggregates"]
