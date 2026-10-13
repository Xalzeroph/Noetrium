"""Latency profiler derives reproducible bounds from existing raw evidence."""
import base64
import json
from pathlib import Path
import sqlite3

from scripts.profile_research_execution_latency import inspect


def test_latency_report_reuses_existing_immutable_records(tmp_path: Path):
    root = tmp_path / "research"
    root.mkdir()
    with sqlite3.connect(root / "graph.v5.sqlite3") as db:
        db.execute("create table research_graph_nodes(state text)")
        db.execute("insert into research_graph_nodes values ('succeeded')")
        db.execute("insert into research_graph_nodes values ('running')")
        db.execute("create table research_graph_attempts(node_id text, "
                   "state text, started_at_ns integer, finished_at_ns integer, "
                   "failure_type text)")
        db.execute("insert into research_graph_attempts values "
                   "('node-1','succeeded',1000000000,3000000000,null)")
    raw = root / "platform-runtime/state/observability/raw/run-one"
    raw.mkdir(parents=True)
    response = {"usage": {"prompt_tokens": 100, "completion_tokens": 8,
                         "prompt_tokens_details": {"cached_tokens": 25}}}
    b64 = base64.b64encode(json.dumps(response).encode()).decode()
    rows = [
        {"family": "llm.request.raw", "idempotency_key": "abc:attempt:1:request",
         "timestamp": 9.0},
        {"family": "llm.attempt.raw", "idempotency_key": "abc:attempt:1:response",
         "timestamp": 10.5, "payload": {"__content_b64": b64}},
    ]
    (raw / "events.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8"
    )
    before = (raw / "events.jsonl").read_bytes()
    report = inspect(root)
    assert report["model"]["paired_request_count"] == 1
    assert report["model"]["request_latency_p50_seconds"] == 1.5
    assert report["model"]["cached_token_ratio"] == .25
    assert report["graph"]["node_states"] == {"succeeded": 1, "running": 1}
    assert report["graph"]["completed_attempt_count"] == 1
    assert report["graph"]["completed_attempt_p50_seconds"] == 2
    assert "not the end-to-end critical path" in report["limits"]
    assert (raw / "events.jsonl").read_bytes() == before


def test_missing_sources_are_not_reported_as_zero_latency(tmp_path):
    (tmp_path / "research").mkdir()
    summary = inspect(tmp_path / "research")
    assert summary["graph"]["available"] is False
    assert summary["model"]["request_latency_mean_seconds"] is None
    assert summary["model"]["request_latency_p95_seconds"] is None
    assert summary["model"]["cached_token_ratio"] is None


def test_completed_interval_union_is_max_for_independent_overlapping_work():
    from scripts.profile_research_execution_latency import _completed_overlap

    second = 1_000_000_000
    # Three independent attempts overlap perfectly: sum = 24, union = 10.
    rows = [
        ("a", "succeeded", 0, 10 * second, None),
        ("b", "succeeded", 0, 8 * second, None),
        ("c", "succeeded", 0, 6 * second, None),
    ]
    report = _completed_overlap(rows)
    assert report["completed_interval_work_sum_seconds"] == 24
    assert report["completed_interval_union_seconds"] == 10
    assert report["completed_interval_wall_span_seconds"] == 10
    assert report["completed_interval_overlap_saved_seconds"] == 14
    assert report["completed_interval_max_parallelism"] == 3
    assert report["completed_interval_effective_parallelism"] == 2.4


def test_completed_interval_union_excludes_idle_and_incomplete_work():
    from scripts.profile_research_execution_latency import _completed_overlap

    second = 1_000_000_000
    rows = [
        ("a", "succeeded", 1 * second, 3 * second, None),
        ("b", "succeeded", 5 * second, 8 * second, None),
        ("c", "running", 2 * second, None, None),
        ("d", "failed", None, None, "RuntimeError"),
        ("e", "succeeded", 3 * second, 3 * second, None),
    ]
    report = _completed_overlap(rows)
    assert report["completed_interval_union_seconds"] == 5
    assert report["completed_interval_wall_span_seconds"] == 7
    assert report["completed_interval_max_parallelism"] == 1
    assert report["completed_interval_overlap_saved_seconds"] == 0
    assert _completed_overlap([])["completed_interval_union_seconds"] is None


def test_timing_projection_separates_nested_physical_stage_evidence(tmp_path):
    root=tmp_path/'research';root.mkdir()
    journal_dir=root/'machine-state/unit-journal/machines';journal_dir.mkdir(parents=True)
    def invocation(queue, account, raw_ns, http_ns):
        return {'event_payloads': [{'type':'method.event','event':{
            'kind':'model.invocation','payload':{
                'dispatch_queue_seconds':queue,
                'dispatch_completion_accounting_wall_seconds':account,
                'provider_stage_timings_ns':{
                    'raw_exchange_capture':raw_ns,
                    'http_transport':http_ns,
                    'http_headers_wait':http_ns,
                },
            }
        }}]}
    lines=[invocation(2,4,3_000_000_000,1_000_000_000),
           invocation(4,6,5_000_000_000,2_000_000_000)]
    (journal_dir/'test.journal').write_text(''.join(json.dumps(x)+'\n' for x in lines))
    report=inspect(root)['model_stage_timings']
    assert report['complete_invocation_count']==2
    assert report['stage_seconds']['dispatch_queue_seconds']['mean']==3
    assert report['stage_seconds']['dispatch_completion_accounting_wall_seconds']['mean']==5
    assert report['stage_seconds']['provider.raw_exchange_capture']['mean']==4
    assert report['stage_seconds']['provider.http_transport']['p95']==1
    assert 'cannot be added' in report['caveat']
    assert inspect(root)['model']['request_latency_mean_seconds'] is None
