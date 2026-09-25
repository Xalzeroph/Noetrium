from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.infrastructure.reliability.failure.api import RecoveryAction, RiskLevel
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.infrastructure.reliability.forensics.api.mutation import MutationRecord
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import DebugSnapshotService, FailureDiagnosisService
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry, build_telemetry_sqlite_backend
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryStore
from noetrium_platform.evidence.observability.telemetry.metric.providers import SQLiteTelemetryReader


def _ctx():
    return ExecutionContext(run_id="r1", trace_id="tr1", span_id="sp1", task_id="t1", decision_cycle_id="dc1", operation_id="op1", component_id="agent.planner")


def test_debug_snapshot_joins_failure_graph_writers_and_metrics(tmp_path: Path):
    root=tmp_path/'f'; store=ForensicStore(root)
    ctx=_ctx()
    store.append_mutation(MutationRecord(mutation_id="m1", state_name="agent.plan", aggregate_id="agent:r1", expected_version=0, new_version=1, old_digest="a", new_digest="b", component_id="agent.planner", operation_id="op0", context=ctx))
    failure=build_failure(component_id="agent.planner", operation_id="op1", operation_type="plan", stage="inference", failure_domain="LLM", failure_code="MODEL_ERROR", context=ctx, exc=RuntimeError("boom"), recommended_recovery=RecoveryAction.RETRY_OPERATION, scientific_validity_risk=RiskLevel.LOW)
    store.append_failure(failure)
    db=tmp_path/'telemetry.sqlite'
    runtime=build_concurrency_runtime()
    try:
        group=runtime.open_task_group("test-debug-snapshot-telemetry")
        ts=TelemetryStore(build_default_registry(), build_telemetry_sqlite_backend(db, task_group=group))
        ts.observe(ctx,"llm.request.latency",1.5,role="planner",model="m",endpoint="local",status="error")
    finally:
        runtime.close()
    snap=DebugSnapshotService(ForensicDiagnosticEvidence(ForensicStore(root,read_only=True)), SQLiteTelemetryReader(db)).build(failure.failure_id)
    assert snap.diagnosis and snap.diagnosis.headline == "LLM:MODEL_ERROR"
    assert any(x.get("mutation_id") == "m1" for x in snap.recent_state_writers)
    assert any(x["metric"] == "llm.request.latency" for x in snap.nearby_metrics)
    assert any(node.kind == "operation" for node in snap.causal_graph.nodes)
    with pytest.raises(TypeError):
        snap.object["failure_code"] = "changed"
    with pytest.raises(TypeError):
        snap.diagnosis.taxonomy["domain"] = "changed"
    rendered = asdict(snap)
    assert rendered["diagnosis"]["headline"] == "LLM:MODEL_ERROR"
    json.dumps(rendered, sort_keys=True)


def test_diagnostic_outputs_preserve_tail_record_for_output_cardinality_lower_bound(tmp_path: Path):
    root = tmp_path / "forensics"
    store = ForensicStore(root)
    ctx = _ctx()
    for index in range(32):
        store.append_mutation(MutationRecord(
            mutation_id=f"tail-proof-{index:02d}", state_name="agent.plan", aggregate_id="agent:r1",
            expected_version=index, new_version=index + 1, old_digest=f"old-{index}", new_digest=f"new-{index}",
            component_id="agent.planner", operation_id=f"mutation-{index:02d}", context=ctx, created_at=101.0 + index,
        ))
    failure = replace(build_failure(
        component_id="agent.planner", operation_id="op1", operation_type="plan", stage="inference",
        failure_domain="LLM", failure_code="MODEL_ERROR", context=ctx, exc=RuntimeError("boom"),
    ), created_at=100.0)
    store.append_failure(failure)
    evidence = ForensicDiagnosticEvidence(store)
    diagnosis = FailureDiagnosisService(evidence)

    timeline = diagnosis.timeline(failure.failure_id, seconds=60.0)
    why = diagnosis.why(failure.failure_id, window_seconds=60.0, writer_limit=32)
    snapshot = DebugSnapshotService(evidence).build(failure.failure_id, seconds=60.0)

    assert len(timeline) == 33
    assert len(why.related_objects) == 33
    assert len(snapshot.timeline) == 33
    assert timeline[-1]["mutation_id"] == "tail-proof-31"
    assert why.related_objects[-1]["mutation_id"] == "tail-proof-31"
    assert snapshot.timeline[-1]["mutation_id"] == "tail-proof-31"


def test_graph_projectors_remain_explicit_reference_only(tmp_path: Path):
    root=tmp_path/'f'; store=ForensicStore(root); ctx=_ctx()
    failure=build_failure(component_id="x", operation_id="op1", operation_type="x", stage="x", failure_domain="X", failure_code="Y", context=ctx, exc=RuntimeError("x"))
    store.append_failure(failure)
    snap=DebugSnapshotService(ForensicDiagnosticEvidence(ForensicStore(root,read_only=True))).build(failure.failure_id)
    assert all(edge.relation != "temporally_caused_by" for edge in snap.causal_graph.edges)
