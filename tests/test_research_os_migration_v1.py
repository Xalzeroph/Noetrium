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
    ResearchGraphExecutionConflict,
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

    with pytest.raises(ResearchGraphExecutionConflict, match="no longer the active"):
        materialize_research_os_execution_migration(
            plan,
            new,
            store,
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
