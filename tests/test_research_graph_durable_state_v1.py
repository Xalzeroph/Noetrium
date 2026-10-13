from __future__ import annotations

from tests._execution_graph_fixtures import materialize_execution as _materialize_execution

from tests._execution_graph_fixtures import scheduling_vertex as ResearchSchedulingNode, scheduling_graph as ResearchSchedulingPlan

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphAttemptState,
    ResearchGraphControlPhase,
    ResearchGraphExecutionConflict,
    ResearchGraphFailureProvenance,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphReconciliationDisposition,
    execution_graph_id,
    execution_graph_research_revision_digest,
    execution_graph_vertices,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _failure_provenance(message: str) -> ResearchGraphFailureProvenance:
    return ResearchGraphFailureProvenance(
        "tests.SyntheticFailure",
        canonical_digest({"failure": message}),
        message,
    )


def _plan() -> ResearchSchedulingPlan:
    first = ResearchSchedulingNode("a", canonical_digest({"node": "a"}))
    second = ResearchSchedulingNode(
        "b",
        canonical_digest({"node": "b"}),
        ("a",),
    )
    return ResearchSchedulingPlan(
        "durable-graph",
        canonical_digest({"revision": 1}),
        (first, second),
    )


def test_claim_expiry_before_start_is_safe_to_requeue(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    _materialize_execution(store, "execution-1", _plan())
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
    _materialize_execution(store, "execution-2", _plan())
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


def test_locally_converged_running_attempt_relinquishes_before_ttl(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    _materialize_execution(store, "execution-local-convergence", _plan())
    store.mark_ready("execution-local-convergence", "a", now_ns=10)
    claim = store.claim(
        "execution-local-convergence",
        "a",
        owner_id="scheduler-local",
        now_ns=10,
        lease_expires_at_ns=10_000,
    )
    attempt_id = claim.attempt_id or ""
    store.mark_running(
        "execution-local-convergence",
        "a",
        attempt_id=attempt_id,
        owner_id="scheduler-local",
        now_ns=11,
    )

    relinquished = store.relinquish_running_attempt(
        "execution-local-convergence",
        "a",
        attempt_id=attempt_id,
        owner_id="scheduler-local",
        now_ns=12,
    )

    assert relinquished.state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
    assert relinquished.attempt_id == attempt_id
    assert relinquished.lease_owner_id is None
    assert relinquished.lease_expires_at_ns is None
    assert store.attempts("execution-local-convergence", "a")[0].state is (
        ResearchGraphAttemptState.RECONCILE_REQUIRED
    )
    assert store.node_control_state(
        "execution-local-convergence", "a"
    ).phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED

    with pytest.raises(ResearchGraphExecutionConflict):
        store.mark_succeeded(
            "execution-local-convergence",
            "a",
            attempt_id=attempt_id,
            owner_id="scheduler-local",
            now_ns=13,
        )


def test_failed_node_can_enter_durable_retry_wait_and_reclaim(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    _materialize_execution(store, "execution-3", _plan())
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
        failure_provenance=_failure_provenance("first attempt"),
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
    _materialize_execution(store, "execution-fence", _plan())
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
            failure_provenance=_failure_provenance("stale completion"),
        )



def test_per_node_pause_resume_is_independent_of_graph_control(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    _materialize_execution(store, "execution-node-control", _plan())

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
    _materialize_execution(store, "execution-node-claimed", _plan())
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
    _materialize_execution(store, "execution-node-running", _plan())
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
    x = ResearchSchedulingNode("x", canonical_digest({"node": "x"}))
    plan = ResearchSchedulingPlan(
        execution_graph_id(plan),
        execution_graph_research_revision_digest(plan),
        execution_graph_vertices(plan) + (x,),
    )
    _materialize_execution(store, "execution-node-cancel", plan)
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
    _materialize_execution(store, "execution-node-cancel-active", _plan())
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


def test_new_runtime_generation_fences_expired_abandoned_attempts(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph-generation.sqlite3")
    _materialize_execution(store, "generation-recovery", _plan())
    store.mark_ready_many("generation-recovery", ("a", "b"), now_ns=1)

    claimed = store.claim(
        "generation-recovery",
        "a",
        owner_id="research-graph-scheduler:old-generation:claim",
        now_ns=2,
        lease_expires_at_ns=10_000,
    )
    running = store.claim(
        "generation-recovery",
        "b",
        owner_id="research-graph-scheduler:old-generation:run",
        now_ns=2,
        lease_expires_at_ns=10_000,
    )
    store.mark_running(
        "generation-recovery",
        "b",
        attempt_id=running.attempt_id or "",
        owner_id="research-graph-scheduler:old-generation:run",
        now_ns=3,
    )

    recovered = store.recover_abandoned_owner_generation(
        "generation-recovery",
        current_owner_generation_id="new-generation",
        now_ns=10_001,
    )

    assert recovered.node("a").state is ResearchGraphLiveNodeState.READY
    assert recovered.node("b").state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED
    assert store.attempts("generation-recovery", "a")[0].state is (
        ResearchGraphAttemptState.ABANDONED_BEFORE_START
    )
    assert store.attempts("generation-recovery", "b")[0].state is (
        ResearchGraphAttemptState.RECONCILE_REQUIRED
    )
    assert store.node_control_state(
        "generation-recovery", "b"
    ).phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
    assert claimed.attempt_id != running.attempt_id


def test_foreign_runtime_generation_cannot_steal_unexpired_live_leases(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "concurrent-live-run.sqlite3")
    _materialize_execution(store, "simultaneous-run", _plan())
    store.mark_ready_many("simultaneous-run", ("a", "b"), now_ns=1)
    first = store.claim(
        "simultaneous-run", "a",
        owner_id="research-graph-scheduler:live-original:claimed",
        now_ns=2, lease_expires_at_ns=10_000,
    )
    second = store.claim(
        "simultaneous-run", "b",
        owner_id="research-graph-scheduler:live-original:running",
        now_ns=2, lease_expires_at_ns=10_000,
    )
    store.mark_running(
        "simultaneous-run", "b",
        attempt_id=second.attempt_id or "",
        owner_id="research-graph-scheduler:live-original:running",
        now_ns=3,
    )
    before = store.snapshot("simultaneous-run")
    resumed = store.recover_abandoned_owner_generation(
        "simultaneous-run",
        current_owner_generation_id="new-attaching-probe",
        now_ns=4,
    )
    assert resumed.node("a").state is ResearchGraphLiveNodeState.CLAIMED
    assert resumed.node("b").state is ResearchGraphLiveNodeState.RUNNING
    assert resumed.node("a").attempt_id == first.attempt_id
    assert resumed.node("b").attempt_id == second.attempt_id
    assert resumed.reconciliation_required_node_ids == ()
    assert store.control_state("simultaneous-run").phase is ResearchGraphControlPhase.ACTIVE
    assert store.snapshot("simultaneous-run").generation == before.generation


def test_current_runtime_generation_is_not_stolen_by_recovery(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph-generation-live.sqlite3")
    _materialize_execution(store, "generation-live", _plan())
    store.mark_ready("generation-live", "a", now_ns=1)
    claim = store.claim(
        "generation-live",
        "a",
        owner_id="research-graph-scheduler:current-generation:worker",
        now_ns=2,
        lease_expires_at_ns=10_000,
    )

    recovered = store.recover_abandoned_owner_generation(
        "generation-live",
        current_owner_generation_id="current-generation",
        now_ns=3,
    )

    assert recovered.node("a").state is ResearchGraphLiveNodeState.CLAIMED
    assert recovered.node("a").attempt_id == claim.attempt_id


def test_retry_descendant_validation_uses_batch_read_not_point_reads(
    tmp_path,
    monkeypatch,
) -> None:
    root = ResearchSchedulingNode(
        "root",
        canonical_digest({"node": "root"}),
    )
    descendant_ids = tuple(f"child-{index:03d}" for index in range(256))
    descendants = tuple(
        ResearchSchedulingNode(
            node_id,
            canonical_digest({"node": node_id}),
            ("root",),
        )
        for node_id in descendant_ids
    )
    plan = ResearchSchedulingPlan(
        "retry-batch-complexity",
        canonical_digest({"revision": "retry-batch-complexity"}),
        (root, *descendants),
    )
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    _materialize_execution(store, "execution-retry-batch", plan)
    store.mark_ready("execution-retry-batch", "root", now_ns=1)
    claim = store.claim(
        "execution-retry-batch",
        "root",
        owner_id="scheduler",
        now_ns=1,
        lease_expires_at_ns=100,
    )
    store.mark_running(
        "execution-retry-batch",
        "root",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler",
        now_ns=2,
    )
    store.mark_failed(
        "execution-retry-batch",
        "root",
        attempt_id=claim.attempt_id or "",
        owner_id="scheduler",
        now_ns=3,
        failure_type="SyntheticFailure",
        failure_message="retry batch",
        failure_provenance=_failure_provenance("retry batch"),
    )

    point_reads: list[str] = []
    original = store._node_tx

    def counted_node_tx(conn, execution_id, node_id):
        point_reads.append(node_id)
        return original(conn, execution_id, node_id)

    monkeypatch.setattr(store, "_node_tx", counted_node_tx)
    snapshot = store.retry_failed_subgraph(
        "execution-retry-batch",
        "root",
        descendant_node_ids=descendant_ids,
        retry_not_before_ns=10,
    )

    assert snapshot.node("root").state is ResearchGraphLiveNodeState.RETRY_WAIT
    assert all(
        snapshot.node(node_id).state is ResearchGraphLiveNodeState.PENDING
        for node_id in descendant_ids
    )
    assert not (set(point_reads) & set(descendant_ids))
