from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphAttemptState,
    ResearchGraphControlPhase,
    ResearchGraphExecutionConflict,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
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

    retry_snapshot = store.retry_failed_subgraph(
        "execution-3",
        "a",
        descendant_node_ids=(),
        retry_not_before_ns=50,
    )
    assert retry_snapshot.node("a").state is ResearchGraphLiveNodeState.RETRY_WAIT

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


def test_expired_running_lease_fences_stale_worker_terminal_commit(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution-fence", _plan())
    store.mark_ready("execution-fence", "a", now_ns=10)
    claim = store.claim(
        "execution-fence",
        "a",
        owner_id="scheduler-old",
        now_ns=10,
        lease_expires_at_ns=20,
    )
    running = store.mark_running(
        "execution-fence",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler-old",
        now_ns=11,
    )
    assert running.fencing_token == 1
    assert store.attempts("execution-fence", "a")[0].fencing_token == 1

    with pytest.raises(ResearchGraphExecutionConflict, match="stale worker is fenced"):
        store.mark_succeeded(
            "execution-fence",
            "a",
            attempt_id=claim.attempt_id or "",
            owner_id="scheduler-old",
            now_ns=21,
        )

    recovered = store.recover_expired("execution-fence", now_ns=21)
    assert recovered.node("a").state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED

    with pytest.raises(ResearchGraphExecutionConflict):
        store.mark_failed(
            "execution-fence",
            "a",
            attempt_id=claim.attempt_id or "",
            owner_id="scheduler-old",
            now_ns=22,
            failure_type="LateWorker",
            failure_message="stale completion",
        )



def test_per_node_pause_resume_is_independent_of_graph_control(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution-node-control", _plan())

    node_control = store.node_control_state("execution-node-control", "a")
    assert node_control.phase is ResearchGraphNodeControlPhase.ACTIVE
    assert store.control_state("execution-node-control").phase is (
        ResearchGraphControlPhase.ACTIVE
    )

    paused = store.pause_node_if_quiescent(
        "execution-node-control",
        "a",
        expected_generation=node_control.generation,
        now_ns=10,
    )
    assert paused.phase is ResearchGraphNodeControlPhase.PAUSED
    assert store.snapshot("execution-node-control").node("a").state is (
        ResearchGraphLiveNodeState.PENDING
    )
    assert store.control_state("execution-node-control").phase is (
        ResearchGraphControlPhase.ACTIVE
    )

    resumed = store.resume_node(
        "execution-node-control",
        "a",
        expected_generation=paused.generation,
        now_ns=11,
    )
    assert resumed.phase is ResearchGraphNodeControlPhase.ACTIVE
    assert store.control_state("execution-node-control").phase is (
        ResearchGraphControlPhase.ACTIVE
    )


def test_node_interrupt_claimed_before_start_is_safely_paused(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution-node-claimed", _plan())
    store.mark_ready("execution-node-claimed", "a", now_ns=1)
    claim = store.claim(
        "execution-node-claimed",
        "a",
        owner_id="scheduler",
        now_ns=2,
        lease_expires_at_ns=100,
    )
    control = store.node_control_state("execution-node-claimed", "a")

    interrupted = store.interrupt_node(
        "execution-node-claimed",
        "a",
        expected_generation=control.generation,
        now_ns=3,
    )

    assert interrupted.phase is ResearchGraphNodeControlPhase.PAUSED
    assert store.snapshot("execution-node-claimed").node("a").state is (
        ResearchGraphLiveNodeState.PENDING
    )
    attempts = store.attempts("execution-node-claimed", "a")
    assert len(attempts) == 1
    assert attempts[0].attempt_id == claim.attempt_id
    assert attempts[0].state is ResearchGraphAttemptState.EXPIRED_BEFORE_START
    assert store.control_state("execution-node-claimed").phase is (
        ResearchGraphControlPhase.ACTIVE
    )


def test_node_interrupt_running_localizes_reconciliation_debt(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution-node-running", _plan())
    store.mark_ready("execution-node-running", "a", now_ns=1)
    claim = store.claim(
        "execution-node-running",
        "a",
        owner_id="scheduler",
        now_ns=2,
        lease_expires_at_ns=100,
    )
    store.mark_running(
        "execution-node-running",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler",
        now_ns=3,
    )
    control = store.node_control_state("execution-node-running", "a")

    interrupted = store.interrupt_node(
        "execution-node-running",
        "a",
        expected_generation=control.generation,
        now_ns=4,
    )

    assert interrupted.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
    assert store.snapshot("execution-node-running").node("a").state is (
        ResearchGraphLiveNodeState.RECONCILE_REQUIRED
    )
    assert store.attempts("execution-node-running", "a")[0].state is (
        ResearchGraphAttemptState.RECONCILE_REQUIRED
    )
    assert store.control_state("execution-node-running").phase is (
        ResearchGraphControlPhase.ACTIVE
    )

    store.resolve_reconciliation(
        "execution-node-running",
        "a",
        disposition=ResearchGraphReconciliationDisposition.RETRY,
        now_ns=5,
        retry_not_before_ns=5,
    )
    settled = store.settle_node_recovery(
        "execution-node-running",
        "a",
        expected_generation=interrupted.generation,
        now_ns=6,
    )
    assert settled.phase is ResearchGraphNodeControlPhase.PAUSED
    assert store.snapshot("execution-node-running").node("a").state is (
        ResearchGraphLiveNodeState.RETRY_WAIT
    )


def test_cancel_node_subgraph_is_atomic_and_leaves_unrelated_work_active(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    # Add an independent sibling to prove cancellation stays inside descendants.
    x = ResearchGraphNode("x", canonical_digest({"node": "x"}))
    plan = ResearchGraphPlan(
        plan.graph_id,
        plan.research_revision_digest,
        plan.nodes + (x,),
    )
    store.ensure_execution("execution-node-cancel", plan)
    root_control = store.node_control_state("execution-node-cancel", "a")

    cancelled = store.cancel_node_subgraph(
        "execution-node-cancel",
        "a",
        descendant_node_ids=("b",),
        expected_generation=root_control.generation,
        now_ns=10,
    )

    assert cancelled.phase is ResearchGraphNodeControlPhase.CANCELLED
    snapshot = store.snapshot("execution-node-cancel")
    assert snapshot.node("a").state is ResearchGraphLiveNodeState.CANCELLED
    assert snapshot.node("b").state is ResearchGraphLiveNodeState.CANCELLED
    assert snapshot.node("x").state is ResearchGraphLiveNodeState.PENDING
    assert store.node_control_state(
        "execution-node-cancel", "b"
    ).phase is ResearchGraphNodeControlPhase.CANCELLED
    assert store.node_control_state(
        "execution-node-cancel", "x"
    ).phase is ResearchGraphNodeControlPhase.ACTIVE
    assert store.control_state("execution-node-cancel").phase is (
        ResearchGraphControlPhase.ACTIVE
    )


def test_cancel_node_subgraph_rejects_active_target_without_partial_mutation(
    tmp_path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution-node-cancel-active", _plan())
    store.mark_ready("execution-node-cancel-active", "b", now_ns=1)
    store.claim(
        "execution-node-cancel-active",
        "b",
        owner_id="scheduler",
        now_ns=2,
        lease_expires_at_ns=100,
    )
    control = store.node_control_state("execution-node-cancel-active", "a")

    with pytest.raises(ResearchGraphExecutionConflict, match="cannot be cancelled"):
        store.cancel_node_subgraph(
            "execution-node-cancel-active",
            "a",
            descendant_node_ids=("b",),
            expected_generation=control.generation,
            now_ns=3,
        )

    snapshot = store.snapshot("execution-node-cancel-active")
    assert snapshot.node("a").state is ResearchGraphLiveNodeState.PENDING
    assert snapshot.node("b").state is ResearchGraphLiveNodeState.CLAIMED
    assert store.node_control_state(
        "execution-node-cancel-active", "a"
    ).phase is ResearchGraphNodeControlPhase.ACTIVE
