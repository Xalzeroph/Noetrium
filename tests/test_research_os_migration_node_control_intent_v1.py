from __future__ import annotations

from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import (
    ResearchGraphNodeControlHalt,
    ResearchGraphScheduler,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_migration import (
    activate_research_os_execution_cut,
    materialize_research_os_execution_migration,
    plan_research_os_execution_migration,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeState,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


class _NeverExecute:
    def execute(self, context, node, *, deadline) -> None:
        del context, node, deadline
        raise AssertionError("preserved node control must prevent execution")


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def _portfolio(revision: int) -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.node(
        "a",
        kind=api.ResearchNodeKind.CUSTOM,
        config={"revision": revision},
    )
    builder.node(
        "b",
        kind=api.ResearchNodeKind.CUSTOM,
    )
    builder.depends("b", "a")
    return api.ResearchPortfolio("migration-control", (builder.freeze(),))


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


def _source_and_target():
    source_portfolio = _portfolio(1)
    source_revision = _revision(source_portfolio, message="r1")
    source = compile_research_portfolio_graph(source_revision, source_portfolio)

    target_portfolio = _portfolio(2)
    target_revision = _revision(
        target_portfolio,
        parent=source_revision,
        message="r2",
    )
    target = compile_research_portfolio_graph(target_revision, target_portfolio)
    return source, target


def _pause_graph(store, cut_id: str, *, now_ns: int) -> None:
    control = store.control_state(cut_id)
    paused = store.pause_if_quiescent(
        cut_id,
        expected_generation=control.generation,
        now_ns=now_ns,
    )
    assert paused.phase is ResearchGraphControlPhase.PAUSED


def test_revision_migration_preserves_local_pause_after_global_resume(
    tmp_path: Path,
) -> None:
    source, target = _source_and_target()
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        source,
        store,
    )
    node_control = store.node_control_state(activation.cut.cut_id, "paper::a")
    paused_node = store.pause_node_if_quiescent(
        activation.cut.cut_id,
        "paper::a",
        expected_generation=node_control.generation,
        now_ns=1,
    )
    assert paused_node.phase is ResearchGraphNodeControlPhase.PAUSED
    _pause_graph(store, activation.cut.cut_id, now_ns=2)

    plan = plan_research_os_execution_migration(
        "logical-execution",
        source,
        target,
        store.snapshot(activation.cut.cut_id),
    )
    materialized = materialize_research_os_execution_migration(
        plan,
        target,
        store,
        now_ns=3,
    )

    assert materialized.preserved_paused_node_ids == ("paper::a",)
    assert materialized.preserved_cancelled_node_ids == ()
    assert len(materialized.control_transfer_digest) == 64
    assert store.node_control_state(
        plan.target_cut.cut_id,
        "paper::a",
    ).phase is ResearchGraphNodeControlPhase.PAUSED
    assert store.snapshot(plan.target_cut.cut_id).node(
        "paper::a"
    ).state is ResearchGraphLiveNodeState.PENDING

    graph_control = store.control_state(plan.target_cut.cut_id)
    resumed = store.resume(
        plan.target_cut.cut_id,
        expected_generation=graph_control.generation,
        now_ns=4,
    )
    assert resumed.phase is ResearchGraphControlPhase.ACTIVE

    pool = _pool()
    scheduler = ResearchGraphScheduler(
        target.plan,
        _NeverExecute(),
        execution_pool=pool,
        execution_store=store,
        execution_id=plan.target_cut.cut_id,
    )
    try:
        with pytest.raises(ResearchGraphNodeControlHalt) as captured:
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert tuple(row.node_id for row in captured.value.controls) == ("paper::a",)
    assert captured.value.controls[0].phase is ResearchGraphNodeControlPhase.PAUSED
    assert store.attempts(plan.target_cut.cut_id, "paper::a") == ()
    assert store.attempts(plan.target_cut.cut_id, "paper::b") == ()


def test_revision_migration_never_revives_locally_cancelled_node(
    tmp_path: Path,
) -> None:
    source, target = _source_and_target()
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    activation = activate_research_os_execution_cut(
        "logical-execution",
        source,
        store,
    )
    node_control = store.node_control_state(activation.cut.cut_id, "paper::a")
    cancelled = store.cancel_node_subgraph(
        activation.cut.cut_id,
        "paper::a",
        descendant_node_ids=(),
        expected_generation=node_control.generation,
        now_ns=1,
    )
    assert cancelled.phase is ResearchGraphNodeControlPhase.CANCELLED
    _pause_graph(store, activation.cut.cut_id, now_ns=2)

    plan = plan_research_os_execution_migration(
        "logical-execution",
        source,
        target,
        store.snapshot(activation.cut.cut_id),
    )
    materialized = materialize_research_os_execution_migration(
        plan,
        target,
        store,
        now_ns=3,
    )

    assert materialized.preserved_cancelled_node_ids == ("paper::a",)
    assert materialized.preserved_paused_node_ids == ()
    assert store.node_control_state(
        plan.target_cut.cut_id,
        "paper::a",
    ).phase is ResearchGraphNodeControlPhase.CANCELLED
    assert store.snapshot(plan.target_cut.cut_id).node(
        "paper::a"
    ).state is ResearchGraphLiveNodeState.CANCELLED
    assert store.attempts(plan.target_cut.cut_id, "paper::a") == ()

    graph_control = store.control_state(plan.target_cut.cut_id)
    store.resume(
        plan.target_cut.cut_id,
        expected_generation=graph_control.generation,
        now_ns=4,
    )

    pool = _pool()
    scheduler = ResearchGraphScheduler(
        target.plan,
        _NeverExecute(),
        execution_pool=pool,
        execution_store=store,
        execution_id=plan.target_cut.cut_id,
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    results = {row.node_id: row for row in report.nodes}
    assert results["paper::a"].state is ResearchGraphNodeState.CANCELLED
    assert results["paper::b"].state is ResearchGraphNodeState.BLOCKED
    assert results["paper::b"].blocked_by_node_ids == ("paper::a",)
    assert store.attempts(plan.target_cut.cut_id, "paper::a") == ()
    assert store.attempts(plan.target_cut.cut_id, "paper::b") == ()
