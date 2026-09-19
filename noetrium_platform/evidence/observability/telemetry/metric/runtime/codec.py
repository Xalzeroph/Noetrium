from __future__ import annotations

import json

from ..api.json_contract import decode_string_map
from ..api.errors import TelemetryMetricCorruptionError
from ..api.ports import TelemetryStorageReadRow, TelemetryStorageWriteRow
from ..api.rows import PendingMetric

_QUERY_KEYS = (
    "sequence", "metric", "value", "timestamp", "run_id", "task_id",
    "decision_cycle_id", "trace_id", "span_id", "operation_id", "component_id",
    "participant_generations", "dimensions",
)


def encode_pending_metric(row: PendingMetric) -> TelemetryStorageWriteRow:
    context = row.context
    dimensions = json.dumps(
        dict(row.dimensions), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    generations = json.dumps(
        dict(context.participant_generations),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        row.metric, row.value, row.timestamp, context.run_id, context.study_id,
        context.condition_id, context.task_id, context.decision_cycle_id,
        context.trace_id, context.span_id, context.operation_id, context.component_id,
        generations, dimensions,
    )


def decode_metric_query_row(row: TelemetryStorageReadRow) -> dict[str, object]:
    if len(row) != len(_QUERY_KEYS):
        raise TelemetryMetricCorruptionError("telemetry query row has an invalid field count")
    values: list[object] = list(row)
    values[-2] = decode_string_map(row[-2], label="participant_generations_json")
    values[-1] = decode_string_map(row[-1], label="dimensions_json")
    return dict(zip(_QUERY_KEYS, values, strict=True))


__all__ = ["decode_metric_query_row", "encode_pending_metric"]
