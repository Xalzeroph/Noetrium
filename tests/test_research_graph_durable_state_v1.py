from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphAttemptState,
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphPlan,
    ResearchGraphReconciliationDisposition,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _plan() -> ResearchGraphPlan:
    first = ResearchGraphNode("a", canonical_digest({"node": "a"}))
    second = ResearchGraphNode(
        "b",
        canonical_digest({"node": "b"}),
        ("a",),
    )
    return ResearchGraphPlan(
        "durable-graph",
        canonical_digest({"revision": 1}),
        (first, second),
    )


def test_claim_expiry_before_start_is_safe_to_requeue(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution-1", _plan())
    store.mark_ready("execution-1", "a", now_ns=10)
    claim = store.claim(
        "execution-1",
        "a",
        owner_id="scheduler-1",
        now_ns=10,
        lease_expires_at_ns=20,
    )

    recovered = store.recover_expired("execution-1", now_ns=21)

    assert recovered.node("a").state is ResearchGraphLiveNodeState.READY
    assert recovered.node("a").attempt_number == 1
    attempts = store.attempts("execution-1", "a")
    assert len(attempts) == 1
    assert attempts[0].attempt_id == claim.attempt_id
    assert attempts[0].state is ResearchGraphAttemptState.EXPIRED_BEFORE_START


def test_running_expiry_requires_reconciliation_instead_of_blind_replay(tmp_path) -> None:
    path = tmp_path / "graph.sqlite3"
    store = SQLiteResearchGraphExecutionStore(path)
    store.ensure_execution("execution-2", _plan())
    store.mark_ready("execution-2", "a", now_ns=100)
    claim = store.claim(
        "execution-2",
        "a",
        owner_id="scheduler-1",
        now_ns=100,
        lease_expires_at_ns=200,
    )
    store.mark_running(
        "execution-2",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler-1",
        now_ns=120,
    )

    reopened = SQLiteResearchGraphExecutionStore(path)
    recovered = reopened.recover_expired("execution-2", now_ns=201)

    uncertain = recovered.node("a")
    assert uncertain.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
    assert uncertain.attempt_id == claim.attempt_id
    assert reopened.attempts("execution-2", "a")[0].state is (
        ResearchGraphAttemptState.RECONCILE_REQUIRED
    )

    resolved = reopened.resolve_reconciliation(
        "execution-2",
        "a",
        disposition=ResearchGraphReconciliationDisposition.SUCCEEDED,
        now_ns=220,
    )
    assert resolved.state is ResearchGraphLiveNodeState.SUCCEEDED
    assert reopened.attempts("execution-2", "a")[0].state is (
        ResearchGraphAttemptState.RECONCILED_SUCCEEDED
    )


def test_failed_node_can_enter_durable_retry_wait_and_reclaim(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution-3", _plan())
    store.mark_ready("execution-3", "a", now_ns=1)
    first = store.claim(
        "execution-3",
        "a",
        owner_id="scheduler-1",
        now_ns=1,
        lease_expires_at_ns=100,
    )
    store.mark_running(
        "execution-3",
        "a",
        attempt_id=first.attempt_id or "",
        owner_id="scheduler-1",
        now_ns=2,
    )
    store.mark_failed(
        "execution-3",
        "a",
        attempt_id=first.attempt_id or "",
        owner_id="scheduler-1",
        now_ns=3,
        failure_type="SyntheticFailure",
        failure_message="first attempt",
    )

    waiting = store.schedule_retry(
        "execution-3",
        "a",
        retry_not_before_ns=50,
    )
    assert waiting.state is ResearchGraphLiveNodeState.RETRY_WAIT

    ready = store.mark_ready("execution-3", "a", now_ns=50)
    assert ready.state is ResearchGraphLiveNodeState.READY
    second = store.claim(
        "execution-3",
        "a",
        owner_id="scheduler-2",
        now_ns=50,
        lease_expires_at_ns=150,
    )
    assert second.attempt_number == 2
    assert second.attempt_id != first.attempt_id
