from __future__ import annotations

import pytest
from tests.test_research_graph_durable_state_v1 import _materialize_execution, _plan
from noetrium_platform.composition.research_reconciliation import ResearchNodeReconciliationProof
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState, ResearchGraphReconciliationDisposition,
    ResearchGraphNodeResult, ResearchGraphNodeState,
)
from noetrium_platform.research.execution.graph.providers import SQLiteResearchGraphExecutionStore


def uncertain_store(tmp_path):
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    _materialize_execution(store, "execution", _plan())
    store.mark_ready("execution", "a", now_ns=1)
    claim = store.claim("execution", "a", owner_id="owner", now_ns=2, lease_expires_at_ns=20)
    store.mark_running("execution", "a", attempt_id=claim.attempt_id, owner_id="owner", now_ns=3)
    store.recover_expired("execution", now_ns=21)
    proof = ResearchNodeReconciliationProof(
        "a" * 64, "a", "b" * 64, "c" * 64, claim.attempt_id,
        ResearchGraphReconciliationDisposition.FAILED, "machine-journal", ("d" * 64,),
        failure_type="LowerMachineFailed", failure_message="lower Machine committed FAILED",
    )
    return store, proof


def test_reconciled_failure_preserves_lower_proof_in_node_and_attempt(tmp_path):
    store, proof = uncertain_store(tmp_path)
    provenance = proof.failure_provenance()
    resolved = store.resolve_reconciliation(
        "execution", "a", disposition=proof.disposition, now_ns=22,
        failure_type=proof.failure_type, failure_message=proof.failure_message,
        failure_provenance=provenance,
    )
    assert resolved.failure_provenance == provenance
    assert store.attempts("execution", "a")[0].failure_provenance == provenance
    reopened = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    node = reopened.snapshot("execution").node("a")
    result = ResearchGraphNodeResult(
        node.node_id, node.semantic_digest, ResearchGraphNodeState.FAILED,
        failure_type=node.failure_type, failure_message=node.failure_message,
        failure_provenance=node.failure_provenance,
    )
    assert result.failure_provenance.evidence_refs == proof.evidence_digests
    assert proof.proof_digest in result.failure_provenance.lower_refs


def test_failed_reconciliation_without_provenance_does_not_mutate_state(tmp_path):
    store, proof = uncertain_store(tmp_path)
    before = store.snapshot("execution")
    with pytest.raises(TypeError, match="provenance"):
        store.resolve_reconciliation(
            "execution", "a", disposition=proof.disposition, now_ns=22,
            failure_type=proof.failure_type, failure_message=proof.failure_message,
        )
    assert store.snapshot("execution") == before
    assert before.node("a").state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
