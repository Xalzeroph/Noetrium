from __future__ import annotations

from noetrium_platform.product.research_control import ResearchGraphRevision

from noetrium_platform.composition.research_execution_graph import compile_research_portfolio_graph
from noetrium_platform.composition.research_execution_migration import (
    ResearchExecutionCut,
    plan_research_execution_migration,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphExecutionSnapshot,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeExecutionRecord,
    execution_graph_vertices,
    execution_vertex_id,
    execution_vertex_semantic_digest,
)
from tests.test_research_execution_v1 import _portfolio, _portfolio_v2


def _revision(portfolio, *, parent=None, message):
    return ResearchGraphRevision(
        portfolio.unit_id,
        portfolio.unit_digest,
        () if parent is None else (parent.revision_digest,),
        message,
    )


def test_revision_migration_advances_physical_cut_generation_without_rewriting_source():
    old_portfolio = _portfolio()
    old_revision = _revision(old_portfolio, message="r1")
    old = compile_research_portfolio_graph(old_revision, old_portfolio)

    new_portfolio = _portfolio_v2()
    new_revision = _revision(new_portfolio, parent=old_revision, message="r2")
    new = compile_research_portfolio_graph(new_revision, new_portfolio)

    source_cut = ResearchExecutionCut.from_compilation(
        "logical-execution", old, generation=7
    )
    snapshot = ResearchGraphExecutionSnapshot(
        source_cut.cut_id,
        old.graph_id,
        old.graph_digest,
        old.research_revision_digest,
        1,
        tuple(
            ResearchGraphNodeExecutionRecord(
                source_cut.cut_id,
                execution_vertex_id(node),
                execution_vertex_semantic_digest(node),
                ResearchGraphLiveNodeState.SUCCEEDED,
                attempt_number=1,
                attempt_id=f"attempt:{execution_vertex_id(node)}",
            )
            for node in execution_graph_vertices(old.execution_unit)
        ),
    )

    plan = plan_research_execution_migration(
        "logical-execution",
        old,
        new,
        snapshot,
        source_generation=7,
        target_generation=8,
    )

    assert plan.source_cut == source_cut
    assert plan.source_cut.generation == 7
    assert plan.target_cut.generation == 8
    assert plan.source_cut.cut_id != plan.target_cut.cut_id
    assert plan.source_cut.research_revision_digest == old_revision.revision_digest
    assert plan.target_cut.research_revision_digest == new_revision.revision_digest
    assert snapshot.execution_id == plan.source_cut.cut_id
