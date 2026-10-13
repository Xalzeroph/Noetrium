"""Read-only latency projection from existing Noetrium execution evidence.

Accepts the path to an existing 'research' state directory. No mutation,
no sampling of other users' processes, and no new authoritative log format.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import statistics


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 3)


def _read_model_timings(root: Path) -> dict:
    observed: dict[str, dict[str, float]] = {}
    counts = Counter()
    usages = Counter()
    for file in (root / "platform-runtime/state/observability/raw").glob(
        "run-*/*.jsonl"
    ):
        for line in file.open(encoding="utf-8"):
            try:
                entry = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            family = entry.get("family")
            if family not in ("llm.request.raw", "llm.attempt.raw"):
                continue
            counts[family] += 1
            key = str(entry.get("idempotency_key", ""))
            if family == "llm.request.raw" and key.endswith(":request"):
                key = key[:-8]
            elif family == "llm.attempt.raw" and key.endswith(":response"):
                key = key[:-9]
            else:
                continue
            observed.setdefault(key, {})[family] = float(entry["timestamp"])
            if family == "llm.attempt.raw":
                try:
                    response = json.loads(base64.b64decode(
                        entry["payload"]["__content_b64"]
                    ))
                    usage = response.get("usage") or {}
                    usages["input_tokens"] += int(usage.get("prompt_tokens") or 0)
                    usages["output_tokens"] += int(usage.get("completion_tokens") or 0)
                    usages["cached_tokens"] += int(
                        (usage.get("prompt_tokens_details") or {}).get(
                            "cached_tokens") or 0
                    )
                except (ValueError, KeyError, TypeError):
                    counts["malformed_usage"] += 1
    durations = [
        max(0.0, stamps["llm.attempt.raw"] - stamps["llm.request.raw"])
        for stamps in observed.values()
        if set(stamps) == {"llm.request.raw", "llm.attempt.raw"}
    ]
    return {
        "request_count": counts["llm.request.raw"],
        "attempt_count": counts["llm.attempt.raw"],
        "paired_request_count": len(durations),
        "request_latency_p50_seconds": _quantile(durations, .5),
        "request_latency_p95_seconds": _quantile(durations, .95),
        "request_latency_mean_seconds": round(statistics.mean(durations), 3)
        if durations else None,
        "input_tokens": usages["input_tokens"],
        "output_tokens": usages["output_tokens"],
        "cached_token_ratio": round(
            usages["cached_tokens"] / usages["input_tokens"], 4
        ) if usages["input_tokens"] else None,
    }


def _read_model_stage_timings(root: Path) -> dict:
    """Stage latency from existing accepted Machine event evidence.

    Inference, transport, scheduling and Authority stage durations are
    inclusive in places; per-stage distributions intentionally cannot be
    interpreted as a decomposition of end-to-end elapsed time. Unknown facts
    are omitted, never replaced with zero observations.
    """
    stages: dict[str, list[float]] = {}
    complete = 0
    malformed = 0
    for file in (root / "machine-state/unit-journal/machines").glob("*.journal"):
        for line in file.open(encoding="utf-8"):
            if 'model.invocation' not in line:
                continue
            try:
                record = json.loads(line)
                for event in record.get("event_payloads", ()):
                    if event.get("type") != "method.event":
                        continue
                    item = event.get("event", {})
                    if item.get("kind") != "model.invocation":
                        continue
                    payload = item["payload"]
                    if not isinstance(payload, dict):
                        raise ValueError("model invocation payload must be an object")
                    complete += 1
                    for key in (
                        "dispatch_queue_seconds",
                        "dispatch_queue_admission_wall_seconds",
                        "dispatch_completion_accounting_wall_seconds",
                        "dispatch_service_seconds",
                    ):
                        value = payload.get(key)
                        if type(value) in (int, float) and 0 <= value < float('inf'):
                            stages.setdefault(key, []).append(float(value))
                    detailed = payload.get("provider_stage_timings_ns", {})
                    if not isinstance(detailed, dict):
                        raise ValueError("provider stages must be a mapping")
                    for key, nanoseconds in detailed.items():
                        if (type(key) is str and type(nanoseconds) in (int, float)
                                and 0 <= nanoseconds < float('inf')):
                            stages.setdefault('provider.' + key, []).append(
                                float(nanoseconds) / 1e9
                            )
            except (TypeError, ValueError, KeyError):
                malformed += 1
    return {
        "complete_invocation_count": complete,
        "malformed_journal_line_count": malformed,
        "stage_seconds": {
            key: {
                "count": len(values),
                "mean": round(statistics.mean(values), 3),
                "p50": _quantile(values, .5),
                "p95": _quantile(values, .95),
                "p99": _quantile(values, .99),
                "maximum": round(max(values), 3),
            }
            for key, values in sorted(stages.items())
        },
        "caveat": (
            "Stages may be nested or inclusive; means and quantiles cannot "
            "be added to infer the episode critical path. Missing is unknown."
        ),
    }


def _completed_overlap(rows: list[tuple]) -> dict:
    """Exact union/overlap of completed attempt intervals, O(N log N).

    This measures *observed parallelism*, not graph critical-path length:
    incomplete attempts and unsatisfied dependencies are not fabricated.
    Same-time terminal transitions close before new intervals open.
    """
    events: list[tuple[int, int]] = []
    total_work_ns = 0
    for _node, _state, started, finished, _failure in rows:
        if started is None or finished is None or finished < started:
            continue
        if finished == started:
            continue
        events.append((started, 1))
        events.append((finished, -1))
        total_work_ns += finished - started
    if not events:
        return {
            "completed_interval_work_sum_seconds": None,
            "completed_interval_union_seconds": None,
            "completed_interval_wall_span_seconds": None,
            "completed_interval_max_parallelism": None,
            "completed_interval_effective_parallelism": None,
            "completed_interval_overlap_saved_seconds": None,
        }
    events.sort(key=lambda row: (row[0], row[1]))
    occupied_ns = 0
    active = 0
    maximum_active = 0
    previous_ns = events[0][0]
    for timestamp, delta in events:
        if active > 0:
            occupied_ns += timestamp - previous_ns
        active += delta
        if active < 0:
            raise ValueError("completed attempt interval sweep underflow")
        maximum_active = max(maximum_active, active)
        previous_ns = timestamp
    if active:
        raise ValueError("completed attempt interval sweep did not close")
    return {
        "completed_interval_work_sum_seconds": round(total_work_ns / 1e9, 3),
        "completed_interval_union_seconds": round(occupied_ns / 1e9, 3),
        "completed_interval_wall_span_seconds": round(
            (events[-1][0] - events[0][0]) / 1e9, 3,
        ),
        "completed_interval_max_parallelism": maximum_active,
        "completed_interval_effective_parallelism": round(
            total_work_ns / occupied_ns, 3,
        ),
        "completed_interval_overlap_saved_seconds": round(
            (total_work_ns - occupied_ns) / 1e9, 3,
        ),
    }


def _read_graph_progress(root: Path) -> dict:
    path = root / "graph.v5.sqlite3"
    if not path.is_file():
        return {"available": False}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        states = dict(connection.execute(
            "select state, count(*) from research_graph_nodes group by state"
        ))
        rows = connection.execute(
            "select node_id, state, started_at_ns, finished_at_ns, "
            "failure_type from research_graph_attempts"
        ).fetchall()
    completed = sorted(
        (
            (finished - started) / 1e9, node, state
        )
        for node, state, started, finished, _failure in rows
        if started is not None and finished is not None and finished >= started
    )
    return {
        "available": True,
        "node_states": states,
        "attempts": len(rows),
        "completed_attempt_count": len(completed),
        **_completed_overlap(rows),
        "completed_attempt_p50_seconds": _quantile(
            [row[0] for row in completed], .5
        ),
        "longest_completed_attempts": [
            {"node_id": node, "state": state, "wall_seconds": round(time, 2)}
            for time, node, state in completed[-5:][::-1]
        ],
    }


def _read_execution_costs(root: Path) -> dict:
    files = sorted(
        (root / "platform-runtime/state/operations/forensics/events.chain")
        .glob("*.jsonl")
    )
    totals = Counter()
    samples = 0
    for file in files:
        for line in file.open(encoding="utf-8"):
            try:
                event = json.loads(line)["payload"]
                if event.get("event_type") != "EXECUTION_COST_OBSERVED":
                    continue
                value = event["payload"]["observation"]
                samples += 1
                totals["observed_wall_ns"] += int(value.get("wall_ns") or 0)
                totals["observed_cpu_ns"] += int(value.get("cpu_ns") or 0)
                for name, duration in value.get("wait_ns", []):
                    totals["wait:" + name] += int(duration)
            except (ValueError, KeyError, TypeError):
                continue
    return {
        "completed_cost_observations": samples,
        "cumulative_wall_seconds_not_critical_path": round(
            totals["observed_wall_ns"] / 1e9, 3
        ),
        "cumulative_cpu_seconds": round(totals["observed_cpu_ns"] / 1e9, 3),
        "observed_wait_seconds": {
            name.removeprefix("wait:"): round(duration / 1e9, 3)
            for name, duration in totals.items()
            if name.startswith("wait:")
        },
    }


def inspect(root: Path) -> dict:
    if not root.is_dir():
        raise FileNotFoundError(root)
    return {
        "schema": "noetrium.read-only-latency-projection.v1",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_root": str(root),
        "graph": _read_graph_progress(root),
        "model": _read_model_timings(root),
        "model_stage_timings": _read_model_stage_timings(root),
        "execution_costs": _read_execution_costs(root),
        "limits": (
            "Model request timing is journal emission to attempt emission, "
            "not exclusively GPU runtime. Sum of parallel attempt wall time "
            "is not the end-to-end critical path. Completed attempt interval "
            "union measures actual parallel execution, not the critical path "
            "of the full graph or incomplete work. Missing records are unknown."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("research_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.research_root), indent=2, sort_keys=True))
