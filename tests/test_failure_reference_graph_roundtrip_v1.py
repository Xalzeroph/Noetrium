from __future__ import annotations

from noetrium_platform.composition.research_execution import ExecutionNodeFailure
from noetrium_platform.composition.research_graph import _failure_provenance
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.reliability.failure.api import FailureReference
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)
from tests._execution_graph_fixtures import (
    materialize_execution,
    scheduling_graph,
    scheduling_vertex,
)


def test_failure_reference_survives_execution_graph_sqlite_roundtrip(tmp_path) -> None:
    reference = FailureReference(
        failure_id="failure-test",
        failure_unit_digest="a" * 64,
        request_refs=("request-1",),
        effect_refs=("effect-1",),
        state_refs=("state-1",),
        evidence_refs=("evidence-1",),
        artifact_refs=("artifact-1",),
        correlation_refs=("correlation-1",),
        causal_event_refs=("b" * 64,),
    )
    wrapped = ExecutionNodeFailure(reference)
    provenance = _failure_provenance(wrapped)

    assert provenance.failure_id == reference.failure_id
    assert provenance.evidence_refs == reference.graph_evidence_refs
    assert provenance.lower_refs == reference.lower_refs

    vertex = scheduling_vertex(
        "failure-node",
        canonical_digest({"node": "failure-node"}),
    )
    plan = scheduling_graph(
        "failure-roundtrip",
        canonical_digest({"revision": 1}),
        (vertex,),
    )
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    try:
        materialize_execution(store, "execution", plan)
        store.mark_ready("execution", "failure-node", now_ns=10)
        claim = store.claim(
            "execution",
            "failure-node",
            owner_id="scheduler",
            now_ns=10,
            lease_expires_at_ns=100,
        )
        store.mark_running(
            "execution",
            "failure-node",
            attempt_id=claim.attempt_id or "",
            owner_id="scheduler",
            now_ns=20,
        )
        failed = store.mark_failed(
            "execution",
            "failure-node",
            attempt_id=claim.attempt_id or "",
            owner_id="scheduler",
            now_ns=30,
            failure_type=type(wrapped).__name__,
            failure_message=str(wrapped),
            failure_provenance=provenance,
        )
        assert failed.state is ResearchGraphLiveNodeState.FAILED
        assert failed.failure_provenance == provenance

        reopened = SQLiteResearchGraphExecutionStore(
            tmp_path / "graph.sqlite3"
        )
        try:
            durable = reopened.node_state("execution", "failure-node")
            assert durable.failure_provenance == provenance
            assert durable.failure_provenance.failure_id == "failure-test"
            assert durable.failure_provenance.evidence_refs == (
                "failure-unit:" + "a" * 64,
                "evidence:evidence-1",
                "artifact:artifact-1",
            )
            assert durable.failure_provenance.lower_refs == (
                "request:request-1",
                "effect:effect-1",
                "state:state-1",
                "correlation:correlation-1",
                "causal-event:" + "b" * 64,
            )
        finally:
            reopened.close()
    finally:
        store.close()
