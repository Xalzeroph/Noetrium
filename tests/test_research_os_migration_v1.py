from __future__ import annotations

from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_migration import (
    ResearchOSExecutionCut,
    ResearchOSNodeMigrationDisposition,
    plan_research_os_execution_migration,
)
from noetrium_platform.product import research_os as api
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphExecutionSnapshot,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeExecutionRecord,
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


def _snapshot(compilation, *, live_node_id: str | None = None):
    rows = []
    for node in compilation.plan.nodes:
        state = (
            ResearchGraphLiveNodeState.RUNNING
            if node.node_id == live_node_id
            else ResearchGraphLiveNodeState.SUCCEEDED
        )
        rows.append(
            ResearchGraphNodeExecutionRecord(
                "logical-execution",
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
        "logical-execution",
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
