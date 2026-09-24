from __future__ import annotations

import pytest

from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_migration import (
    ResearchOSExecutionCut,
    ResearchOSNodeMigrationDisposition,
    ResearchOSReuseProof,
    activate_research_os_execution_cut,
    materialize_research_os_execution_migration,
    plan_research_os_execution_migration,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.product import research_os as api
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphExecutionSnapshot,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionNotFound,
    ResearchGraphNodeExecutionRecord,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _method_v1(payload=None):
    return payload


def _method_v2(payload=None):
    return {"v": 2, "payload": payload}


def _stable(payload=None):
    return payload


def _portfolio(method) -> api.ResearchPortfolio:
    first = api.ResearchProgramBuilder("paper-a")
    first.method("method", implementation=method)
    first.experiment("main", definitions=("method",))
    first.analysis("analysis", depends_on=("main",))

    second = api.ResearchProgramBuilder("paper-b")
    second.method("stable", implementation=_stable)
    second.experiment("main", definitions=("stable",))

    return api.ResearchPortfolio(
        "suite",
        (first.freeze(), second.freeze()),
    )


def _revision(
    portfolio: api.ResearchPortfolio,
    *,
    parent: api.ResearchGraphRevision | None = None,
    message: str,
) -> api.ResearchGraphRevision:
    return api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        () if parent is None else (parent.revision_digest,),
        message,
    )


def _snapshot(
    compilation,
    *,
    execution_id: str = "logical-execution",
    live_node_id: str | None = None,
):
    cut = ResearchOSExecutionCut.from_compilation(execution_id, compilation)
    rows = []
    for node in compilation.plan.nodes:
        state = (
            ResearchGraphLiveNodeState.RUNNING
            if node.node_id == live_node_id
            else ResearchGraphLiveNodeState.SUCCEEDED
        )
        rows.append(
            ResearchGraphNodeExecutionRecord(
                cut.cut_id,
                node.node_id,
                node.semantic_digest,
                state,
                attempt_number=1,
                attempt_id=f"attempt:{node.node_id}",
                lease_owner_id=(
                    "worker-1"
                    if state is ResearchGraphLiveNodeState.RUNNING
                    else None
                ),
                lease_expires_at_ns=(
                    999_999
                    if state is ResearchGraphLiveNodeState.RUNNING
                    else None
                ),
            )
        )
    return ResearchGraphExecutionSnapshot(
        cut.cut_id,
        compilation.plan.graph_id,
        compilation.plan.graph_digest,
        compilation.plan.research_revision_digest,
        1,
        tuple(rows),
    )


def test_revision_migration_uses_immutable_cuts_and_minimal_semantic_restart() -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)

    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    migration = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        _snapshot(old),
    )
    by_id = {row.graph_node_id: row for row in migration.nodes}

    assert migration.source_cut != migration.target_cut
    assert migration.source_cut.cut_id != migration.target_cut.cut_id
    assert migration.can_switch
    assert by_id["paper-a::main"].disposition is (
        ResearchOSNodeMigrationDisposition.RESTART
    )
    assert by_id["paper-a::analysis"].disposition is (
        ResearchOSNodeMigrationDisposition.RESTART
    )
    assert by_id["paper-b::main"].disposition is (
        ResearchOSNodeMigrationDisposition.REUSE_CANDIDATE
    )
    assert migration.reuse_candidate_node_ids == ("paper-b::main",)


def test_active_source_node_blocks_revision_cut_switch_until_quiesced() -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)

    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    migration = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        _snapshot(old, live_node_id="paper-b::main"),
    )
    row = {
        item.graph_node_id: item
        for item in migration.nodes
    }["paper-b::main"]

    assert row.disposition is ResearchOSNodeMigrationDisposition.QUIESCE_REQUIRED
    assert not migration.can_switch


def test_execution_cut_identity_is_revision_and_graph_bound() -> None:
    portfolio = _portfolio(_method_v1)
    revision = _revision(portfolio, message="r1")
    compilation = compile_research_portfolio_graph(revision, portfolio)

    first = ResearchOSExecutionCut.from_compilation("execution-a", compilation)
    second = ResearchOSExecutionCut.from_compilation("execution-b", compilation)

    assert first.cut_id != second.cut_id
    assert len(first.cut_id) == 64



def _pause_cut(store, cut_id: str, *, now_ns: int = 14) -> None:
    control = store.control_state(cut_id)
    control = store.request_drain(
        cut_id,
        expected_generation=control.generation,
        now_ns=now_ns,
    )
    control = store.pause_if_quiescent(
        cut_id,
        expected_generation=control.generation,
        now_ns=now_ns + 1,
    )
    assert control.phase is ResearchGraphControlPhase.PAUSED


def _complete_cut(store, activation) -> None:
    for node in activation.snapshot.nodes:
        store.mark_ready(activation.cut.cut_id, node.node_id, now_ns=10)
        claim = store.claim(
            activation.cut.cut_id,
            node.node_id,
            owner_id="worker",
            now_ns=11,
            lease_expires_at_ns=100,
        )
        store.mark_running(
            activation.cut.cut_id,
            node.node_id,
            attempt_id=claim.attempt_id or "",
            owner_id="worker",
            now_ns=12,
        )
        store.mark_succeeded(
            activation.cut.cut_id,
            node.node_id,
            attempt_id=claim.attempt_id or "",
            owner_id="worker",
            now_ns=13,
        )


def test_migration_materializes_proven_reuse_then_cas_switches_active_cut(tmp_path) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)

    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    _complete_cut(store, activation)
    _pause_cut(store, activation.cut.cut_id)
    source_snapshot = store.snapshot(activation.cut.cut_id)
    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        source_snapshot,
    )

    stable = {
        row.graph_node_id: row
        for row in plan.nodes
    }["paper-b::main"]
    assert stable.new_semantic_digest is not None
    proof = ResearchOSReuseProof(
        "paper-b::main",
        plan.source_cut.cut_id,
        stable.new_semantic_digest,
        canonical_digest({"artifact-proof": "paper-b::main"}),
    )
    materialized = materialize_research_os_execution_migration(
        plan,
        new,
        store,
        reuse_proofs=(proof,),
        now_ns=20,
    )

    assert materialized.active_cut.cut_id == plan.target_cut.cut_id
    assert materialized.reused_node_ids == ("paper-b::main",)
    assert materialized.snapshot.node("paper-b::main").state is (
        ResearchGraphLiveNodeState.REUSED
    )
    assert store.attempts(plan.target_cut.cut_id, "paper-b::main") == ()
    assert set(materialized.restart_node_ids) == {
        "paper-a::main",
        "paper-a::analysis",
    }
    assert store.snapshot(plan.source_cut.cut_id) == source_snapshot


def test_missing_reuse_proof_fails_closed_and_keeps_source_cut_active(tmp_path) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)
    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    _complete_cut(store, activation)
    _pause_cut(store, activation.cut.cut_id)
    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        store.snapshot(activation.cut.cut_id),
    )

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="missing mandatory reuse proofs",
    ):
        materialize_research_os_execution_migration(
            plan,
            new,
            store,
            now_ns=20,
        )

    active = store.active_cut("logical-execution")
    assert active is not None
    assert active.cut_id == plan.source_cut.cut_id
    with pytest.raises(ResearchGraphExecutionNotFound):
        store.snapshot(plan.target_cut.cut_id)


def test_migration_cas_rejects_stale_source_cut(tmp_path) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)
    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    _complete_cut(store, activation)
    _pause_cut(store, activation.cut.cut_id)
    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        store.snapshot(activation.cut.cut_id),
    )

    other_portfolio = _portfolio(_method_v1)
    other_revision = api.ResearchGraphRevision(
        other_portfolio.portfolio_id,
        other_portfolio.portfolio_digest,
        (old_revision.revision_digest,),
        "parallel revision",
    )
    other = compile_research_portfolio_graph(other_revision, other_portfolio)
    other_cut = ResearchOSExecutionCut.from_compilation(
        "logical-execution",
        other,
    )
    store.ensure_execution(other_cut.cut_id, other.plan)
    store.move_active_cut(
        "logical-execution",
        other_cut.cut_id,
        expected_cut_id=activation.cut.cut_id,
    )

    stable = {
        row.graph_node_id: row
        for row in plan.nodes
    }["paper-b::main"]
    assert stable.new_semantic_digest is not None
    proof = ResearchOSReuseProof(
        "paper-b::main",
        plan.source_cut.cut_id,
        stable.new_semantic_digest,
        canonical_digest({"stale-source-proof": "paper-b::main"}),
    )
    with pytest.raises(ResearchGraphExecutionConflict, match="no longer the active"):
        materialize_research_os_execution_migration(
            plan,
            new,
            store,
            reuse_proofs=(proof,),
            now_ns=20,
        )



class _RacingActiveCutStore:
    def __init__(self, store, *, competing_cut_id: str) -> None:
        self._store = store
        self._competing_cut_id = competing_cut_id
        self._raced = False

    def active_cut(self, logical_execution_id: str):
        return self._store.active_cut(logical_execution_id)

    def move_active_cut(
        self,
        logical_execution_id: str,
        cut_id: str,
        *,
        expected_cut_id: str | None = None,
        source_fence=None,
    ):
        if not self._raced:
            self._raced = True
            self._store.move_active_cut(
                logical_execution_id,
                self._competing_cut_id,
                expected_cut_id=expected_cut_id,
            )
        return self._store.move_active_cut(
            logical_execution_id,
            cut_id,
            expected_cut_id=expected_cut_id,
            source_fence=source_fence,
        )


def test_migration_final_cas_conflict_keeps_staged_target_inactive_and_paused(
    tmp_path,
) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)
    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    _complete_cut(store, activation)
    _pause_cut(store, activation.cut.cut_id)
    source_snapshot = store.snapshot(activation.cut.cut_id)
    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        source_snapshot,
    )

    competing_portfolio = _portfolio(_method_v1)
    competing_revision = api.ResearchGraphRevision(
        competing_portfolio.portfolio_id,
        competing_portfolio.portfolio_digest,
        (old_revision.revision_digest,),
        "competing revision",
    )
    competing = compile_research_portfolio_graph(
        competing_revision,
        competing_portfolio,
    )
    competing_cut = ResearchOSExecutionCut.from_compilation(
        "logical-execution",
        competing,
    )
    store.ensure_execution(competing_cut.cut_id, competing.plan)

    stable = {
        row.graph_node_id: row
        for row in plan.nodes
    }["paper-b::main"]
    assert stable.new_semantic_digest is not None
    proof = ResearchOSReuseProof(
        "paper-b::main",
        plan.source_cut.cut_id,
        stable.new_semantic_digest,
        canonical_digest({"artifact-proof": "paper-b::main"}),
    )
    racing = _RacingActiveCutStore(
        store,
        competing_cut_id=competing_cut.cut_id,
    )

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="active cut",
    ):
        materialize_research_os_execution_migration(
            plan,
            new,
            store,
            reuse_proofs=(proof,),
            active_cut_store=racing,
            now_ns=20,
        )

    active = store.active_cut("logical-execution")
    assert active is not None
    assert active.cut_id == competing_cut.cut_id

    staged = store.snapshot(plan.target_cut.cut_id)
    assert store.control_state(plan.target_cut.cut_id).phase is (
        ResearchGraphControlPhase.PAUSED
    )
    assert staged.node("paper-b::main").state is ResearchGraphLiveNodeState.REUSED
    assert store.attempts(plan.target_cut.cut_id, "paper-b::main") == ()
    assert staged.node("paper-a::main").state is ResearchGraphLiveNodeState.PENDING
    assert staged.node("paper-a::analysis").state is ResearchGraphLiveNodeState.PENDING
    assert store.snapshot(plan.source_cut.cut_id) == source_snapshot



def test_migration_preserves_paused_and_cancelled_node_control_intent(
    tmp_path,
) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)
    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    source_cut_id = activation.cut.cut_id

    paused = store.node_control_state(source_cut_id, "paper-a::main")
    paused = store.request_node_drain(
        source_cut_id,
        "paper-a::main",
        expected_generation=paused.generation,
        now_ns=5,
    )
    paused = store.pause_node_if_quiescent(
        source_cut_id,
        "paper-a::main",
        expected_generation=paused.generation,
        now_ns=6,
    )
    assert paused.phase is ResearchGraphNodeControlPhase.PAUSED

    cancelled = store.node_control_state(source_cut_id, "paper-b::main")
    cancelled = store.cancel_node_subgraph(
        source_cut_id,
        "paper-b::main",
        descendant_node_ids=(),
        expected_generation=cancelled.generation,
        now_ns=7,
    )
    assert cancelled.phase is ResearchGraphNodeControlPhase.CANCELLED
    assert store.snapshot(source_cut_id).node("paper-b::main").state is (
        ResearchGraphLiveNodeState.CANCELLED
    )

    _pause_cut(store, source_cut_id, now_ns=8)
    source_snapshot = store.snapshot(source_cut_id)
    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        source_snapshot,
    )
    assert set(plan.restart_node_ids) == {
        "paper-a::main",
        "paper-a::analysis",
        "paper-b::main",
    }

    materialized = materialize_research_os_execution_migration(
        plan,
        new,
        store,
        now_ns=20,
    )

    target_cut_id = plan.target_cut.cut_id
    assert materialized.active_cut.cut_id == target_cut_id
    assert materialized.preserved_paused_node_ids == ("paper-a::main",)
    assert materialized.preserved_cancelled_node_ids == ("paper-b::main",)
    assert set(materialized.restart_node_ids) == {
        "paper-a::main",
        "paper-a::analysis",
    }
    assert len(materialized.control_transfer_digest) == 64

    assert store.control_state(target_cut_id).phase is ResearchGraphControlPhase.PAUSED
    assert store.node_control_state(
        target_cut_id,
        "paper-a::main",
    ).phase is ResearchGraphNodeControlPhase.PAUSED
    assert store.node_control_state(
        target_cut_id,
        "paper-b::main",
    ).phase is ResearchGraphNodeControlPhase.CANCELLED
    target_snapshot = store.snapshot(target_cut_id)
    assert target_snapshot.node("paper-a::main").state is (
        ResearchGraphLiveNodeState.PENDING
    )
    assert target_snapshot.node("paper-b::main").state is (
        ResearchGraphLiveNodeState.CANCELLED
    )
    assert store.attempts(target_cut_id, "paper-b::main") == ()



def test_migration_retry_reconciles_staged_pause_with_current_source_control(tmp_path) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)
    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    source_cut_id = activation.cut.cut_id

    node_control = store.node_control_state(source_cut_id, "paper-a::main")
    node_control = store.request_node_drain(
        source_cut_id,
        "paper-a::main",
        expected_generation=node_control.generation,
        now_ns=5,
    )
    node_control = store.pause_node_if_quiescent(
        source_cut_id,
        "paper-a::main",
        expected_generation=node_control.generation,
        now_ns=6,
    )
    assert node_control.phase is ResearchGraphNodeControlPhase.PAUSED
    _pause_cut(store, source_cut_id, now_ns=7)

    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        store.snapshot(source_cut_id),
    )

    competing_revision = api.ResearchGraphRevision(
        old_portfolio.portfolio_id,
        old_portfolio.portfolio_digest,
        (old_revision.revision_digest,),
        "competing revision",
    )
    competing = compile_research_portfolio_graph(
        competing_revision,
        old_portfolio,
    )
    competing_cut = ResearchOSExecutionCut.from_compilation(
        "logical-execution",
        competing,
    )
    store.ensure_execution(competing_cut.cut_id, competing.plan)
    racing = _RacingActiveCutStore(
        store,
        competing_cut_id=competing_cut.cut_id,
    )

    with pytest.raises(ResearchGraphExecutionConflict, match="active cut"):
        materialize_research_os_execution_migration(
            plan,
            new,
            store,
            active_cut_store=racing,
            now_ns=20,
        )

    assert store.active_cut("logical-execution").cut_id == competing_cut.cut_id
    assert store.node_control_state(
        plan.target_cut.cut_id,
        "paper-a::main",
    ).phase is ResearchGraphNodeControlPhase.PAUSED

    store.move_active_cut(
        "logical-execution",
        source_cut_id,
        expected_cut_id=competing_cut.cut_id,
    )
    source_node_control = store.node_control_state(
        source_cut_id,
        "paper-a::main",
    )
    source_node_control = store.resume_node(
        source_cut_id,
        "paper-a::main",
        expected_generation=source_node_control.generation,
        now_ns=30,
    )
    assert source_node_control.phase is ResearchGraphNodeControlPhase.ACTIVE

    materialized = materialize_research_os_execution_migration(
        plan,
        new,
        store,
        now_ns=40,
    )

    assert materialized.active_cut.cut_id == plan.target_cut.cut_id
    assert materialized.preserved_paused_node_ids == ()
    assert materialized.preserved_cancelled_node_ids == ()
    assert store.node_control_state(
        plan.target_cut.cut_id,
        "paper-a::main",
    ).phase is ResearchGraphNodeControlPhase.ACTIVE
    assert store.snapshot(plan.target_cut.cut_id).node(
        "paper-a::main"
    ).state is ResearchGraphLiveNodeState.PENDING



class _SourceControlRacingActiveCutStore:
    def __init__(self, store, *, node_id: str) -> None:
        self._store = store
        self._node_id = node_id
        self._raced = False

    def active_cut(self, logical_execution_id: str):
        return self._store.active_cut(logical_execution_id)

    def move_active_cut(
        self,
        logical_execution_id: str,
        cut_id: str,
        *,
        expected_cut_id: str | None = None,
        source_fence=None,
    ):
        if source_fence is not None and not self._raced:
            self._raced = True
            control = self._store.node_control_state(
                source_fence.source_execution_id,
                self._node_id,
            )
            assert control.phase is ResearchGraphNodeControlPhase.PAUSED
            resumed = self._store.resume_node(
                source_fence.source_execution_id,
                self._node_id,
                expected_generation=control.generation,
                now_ns=50,
            )
            assert resumed.phase is ResearchGraphNodeControlPhase.ACTIVE
        return self._store.move_active_cut(
            logical_execution_id,
            cut_id,
            expected_cut_id=expected_cut_id,
            source_fence=source_fence,
        )


def test_atomic_cut_fence_rejects_source_node_control_race(tmp_path) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)
    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    source_cut_id = activation.cut.cut_id
    node_control = store.node_control_state(source_cut_id, "paper-a::main")
    node_control = store.request_node_drain(
        source_cut_id,
        "paper-a::main",
        expected_generation=node_control.generation,
        now_ns=5,
    )
    node_control = store.pause_node_if_quiescent(
        source_cut_id,
        "paper-a::main",
        expected_generation=node_control.generation,
        now_ns=6,
    )
    assert node_control.phase is ResearchGraphNodeControlPhase.PAUSED
    _pause_cut(store, source_cut_id, now_ns=7)

    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        store.snapshot(source_cut_id),
    )
    racing = _SourceControlRacingActiveCutStore(
        store,
        node_id="paper-a::main",
    )

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="source node control fence conflict",
    ):
        materialize_research_os_execution_migration(
            plan,
            new,
            store,
            active_cut_store=racing,
            now_ns=20,
        )

    active = store.active_cut("logical-execution")
    assert active is not None
    assert active.cut_id == source_cut_id
    assert store.node_control_state(
        source_cut_id,
        "paper-a::main",
    ).phase is ResearchGraphNodeControlPhase.ACTIVE
    assert store.control_state(plan.target_cut.cut_id).phase is (
        ResearchGraphControlPhase.PAUSED
    )
    assert store.node_control_state(
        plan.target_cut.cut_id,
        "paper-a::main",
    ).phase is ResearchGraphNodeControlPhase.PAUSED


class _ABAActiveCutStore:
    def __init__(self, store, *, competing_cut_id: str) -> None:
        self._store = store
        self._competing_cut_id = competing_cut_id
        self._raced = False

    def active_cut(self, logical_execution_id: str):
        return self._store.active_cut(logical_execution_id)

    def move_active_cut(
        self,
        logical_execution_id: str,
        cut_id: str,
        *,
        expected_cut_id: str | None = None,
        source_fence=None,
    ):
        if source_fence is not None and not self._raced:
            self._raced = True
            self._store.move_active_cut(
                logical_execution_id,
                self._competing_cut_id,
                expected_cut_id=expected_cut_id,
            )
            self._store.move_active_cut(
                logical_execution_id,
                source_fence.source_execution_id,
                expected_cut_id=self._competing_cut_id,
            )
        return self._store.move_active_cut(
            logical_execution_id,
            cut_id,
            expected_cut_id=expected_cut_id,
            source_fence=source_fence,
        )


def test_atomic_cut_fence_rejects_active_ref_aba(tmp_path) -> None:
    old_portfolio = _portfolio(_method_v1)
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)
    new_portfolio = _portfolio(_method_v2)
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        old,
        store,
    )
    source_cut_id = activation.cut.cut_id
    _pause_cut(store, source_cut_id, now_ns=5)
    plan = plan_research_os_execution_migration(
        "logical-execution",
        old,
        new,
        store.snapshot(source_cut_id),
    )

    competing_revision = api.ResearchGraphRevision(
        old_portfolio.portfolio_id,
        old_portfolio.portfolio_digest,
        (old_revision.revision_digest,),
        "aba competing revision",
    )
    competing = compile_research_portfolio_graph(
        competing_revision,
        old_portfolio,
    )
    competing_cut = ResearchOSExecutionCut.from_compilation(
        "logical-execution",
        competing,
    )
    store.ensure_execution(competing_cut.cut_id, competing.plan)
    racing = _ABAActiveCutStore(
        store,
        competing_cut_id=competing_cut.cut_id,
    )

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="active cut generation fence conflict",
    ):
        materialize_research_os_execution_migration(
            plan,
            new,
            store,
            active_cut_store=racing,
            now_ns=20,
        )

    active = store.active_cut("logical-execution")
    assert active is not None
    assert active.cut_id == source_cut_id
    assert active.generation > activation.active_cut.generation
    assert store.control_state(plan.target_cut.cut_id).phase is (
        ResearchGraphControlPhase.PAUSED
    )
