"""Dynamic Experiment result contracts.

All declarative Experiment/participant/model-role/metric semantics are
NoetriumUnits in unit_semantics.py. This module contains only runtime result
values and semantic enum labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)
from noetrium_platform.foundation.kernel.record import RecordRole, record_unit
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


def raw_record(
    *,
    record_type: str,
    payload: JsonValue,
    record_id: str | None = None,
    provenance: JsonValue = None,
    caused_by: tuple[str, ...] = (),
) -> NoetriumUnit:
    return record_unit(
        record_type,
        frozenset({RecordRole.OBSERVATION, RecordRole.EVIDENCE}),
        payload=payload,
        provenance=provenance,
        caused_by=caused_by,
        record_id_value=record_id,
    )


class MetricAggregation(StrEnum):
    COUNT = "count"
    SUM = "sum"
    MEAN = "mean"
    MIN = "min"
    MAX = "max"
    STDDEV = "stddev"
    SAMPLE_VARIANCE = "sample_variance"
    STANDARD_ERROR = "standard_error"
    P50 = "p50"
    P95 = "p95"
    FIRST = "first"
    LAST = "last"
    DISTINCT_COUNT = "distinct_count"


class MetricMissingPolicy(StrEnum):
    SKIP = "skip"
    ZERO = "zero"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class MetricValue:
    metric_id: str
    group_key: tuple[JsonValue, ...]
    value: JsonValue
    sample_size: int
    record_digests: tuple[str, ...]
    value_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.metric_id) is not str or not self.metric_id.strip():
            raise ValueError("metric value metric_id must be non-empty")
        if type(self.group_key) is not tuple:
            raise TypeError("metric value group_key must be a tuple")
        if type(self.sample_size) is not int or self.sample_size < 0:
            raise ValueError("metric value sample_size must be non-negative")
        if type(self.record_digests) is not tuple:
            raise TypeError("metric value record_digests must be tuple")
        for digest in self.record_digests:
            require_sha256(digest, "metric value record digest")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(
            self,
            "value_digest",
            canonical_digest({
                "metric_id": self.metric_id,
                "group_key": self.group_key,
                "value": self.value,
                "sample_size": self.sample_size,
                "record_digests": self.record_digests,
            }),
        )


@dataclass(frozen=True, slots=True)
class MetricReport:
    raw_cut_digest: str
    definitions_digest: str
    values: tuple[MetricValue, ...]
    report_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.raw_cut_digest, "metric report raw_cut_digest")
        require_sha256(self.definitions_digest, "metric report definitions_digest")
        if type(self.values) is not tuple or any(
            type(item) is not MetricValue for item in self.values
        ):
            raise TypeError("metric report values must contain MetricValue")
        object.__setattr__(
            self,
            "report_digest",
            canonical_digest({
                "raw_cut_digest": self.raw_cut_digest,
                "definitions_digest": self.definitions_digest,
                "values": tuple(item.value_digest for item in self.values),
            }),
        )


__all__ = [
    "raw_record",
    "MetricAggregation",
    "MetricMissingPolicy",
    "MetricValue",
    "MetricReport",
]
