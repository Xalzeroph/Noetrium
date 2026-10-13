from __future__ import annotations

from tests._execution_graph_fixtures import materialize_execution as _materialize_execution

from noetrium_platform.product.research_control import ResearchExecutionTarget

from tests.test_research_execution_v1 import (
    _Runtime,
    _ReconciliationRuntime,
    _ValueAuthority,
    _bound,
    _portfolio,
)
from noetrium_platform.composition.research_values import ResearchValueRouter


def test_repeat_run_of_terminal_revision_creates_fresh_physical_cut(tmp_path):
    runtime = _Runtime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=True,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="same-science")
        target = ResearchExecutionTarget("repeat-run", revision)

        first = research.run(target)
        first_active = graph.active_cut("repeat-run")
        assert first.state == "succeeded"
        assert first_active is not None
        assert first_active.generation == 1
        first_snapshot = graph.snapshot(first_active.cut_id)
        assert all(node.state.value == "succeeded" for node in first_snapshot.nodes)

        second = research.run(target)
        second_active = graph.active_cut("repeat-run")
        assert second.state == "succeeded"
        assert second_active is not None
        assert second_active.generation == 2
        assert second_active.cut_id != first_active.cut_id
        assert second.payload["cut_id"] == second_active.cut_id

        # Old immutable execution truth remains independently inspectable.
        preserved = graph.snapshot(first_active.cut_id)
        assert preserved == first_snapshot
        assert runtime.executed.count("paper::source") == 2
        assert runtime.executed.count("paper::consume") == 2
    finally:
        pool.close()


def test_run_auto_resumes_paused_nonterminal_cut_without_new_generation(tmp_path):
    runtime = _Runtime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=True,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="pause-resume")
        target = ResearchExecutionTarget("resume-run", revision)

        first = research.run(target.for_graph(("paper", "source")))
        assert first.state == "succeeded"
        active_before = graph.active_cut("resume-run")
        assert active_before is not None
        paused = research.pause(target)
        assert paused.state == "paused"

        resumed = research.run(target)
        active_after = graph.active_cut("resume-run")
        assert resumed.state == "succeeded"
        assert active_after is not None
        assert active_after.generation == active_before.generation
        assert active_after.cut_id == active_before.cut_id
        assert runtime.executed.count("paper::source") == 1
        assert runtime.executed.count("paper::consume") == 1
    finally:
        pool.close()


def test_revision_migration_advances_physical_cut_generation(tmp_path):
    from tests.test_research_execution_v1 import _portfolio_v2

    runtime = _ReconciliationRuntime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=True,
    )
    try:
        first_portfolio = _portfolio()
        first_revision = research.commit(first_portfolio, message="r1")
        target1 = ResearchExecutionTarget("migrate-generation", first_revision)
        assert research.run(target1.for_graph(("paper", "source"))).state == "succeeded"
        assert research.pause(target1).state == "paused"
        active1 = graph.active_cut("migrate-generation")
        assert active1 is not None and active1.generation == 1

        second_portfolio = _portfolio_v2()
        second_revision = research.commit(
            second_portfolio,
            parents=(first_revision,),
            message="r2",
        )
        target2 = ResearchExecutionTarget("migrate-generation", second_revision)
        migrated = research.migrate(target2)
        active2 = graph.active_cut("migrate-generation")
        assert migrated.state == "paused"
        assert active2 is not None
        assert active2.generation == 2
        assert active2.cut_id != active1.cut_id
        assert migrated.payload["target_cut_id"] == active2.cut_id

        # A plain RUN absorbs the paused migrated cut and continues it in place.
        ran = research.run(target2)
        active3 = graph.active_cut("migrate-generation")
        assert ran.state == "succeeded"
        assert active3 == active2
    finally:
        pool.close()


def test_run_preserves_explicit_global_recovery_intent(tmp_path):
    from noetrium_platform.composition.research_execution_graph import compile_research_portfolio_graph
    from noetrium_platform.composition.research_execution_migration import ResearchExecutionCut

    runtime = _ReconciliationRuntime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=False,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="auto-recovery")
        target = ResearchExecutionTarget("auto-recovery", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        claim = graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="manual-worker",
            now_ns=2,
            lease_expires_at_ns=(1 << 62),
        )
        graph.mark_running(
            cut.cut_id,
            "paper::source",
            attempt_id=claim.attempt_id or "",
            owner_id="manual-worker",
            now_ns=3,
        )
        interrupted = research.interrupt(target)
        assert interrupted.state == "recovery_required"

        ran = research.run(target)
        assert ran.state == "recovery_required"
        active = graph.active_cut(target.execution_id)
        assert active is not None and active.generation == 1
        assert graph.control_state(active.cut_id).phase.value == "recovery_required"
        assert graph.snapshot(active.cut_id).reconciliation_required_node_ids == ("paper::source",)
        assert runtime.executed == []
    finally:
        pool.close()


def _stage_running_source(graph, target, portfolio):
    from noetrium_platform.composition.research_execution_graph import compile_research_portfolio_graph
    from noetrium_platform.composition.research_execution_migration import ResearchExecutionCut

    compilation = compile_research_portfolio_graph(target.revision, portfolio)
    cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
    _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
    graph.move_active_cut(target.execution_id, cut.cut_id)
    graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
    claim = graph.claim(
        cut.cut_id,
        "paper::source",
        owner_id="manual-owner",
        now_ns=2,
        lease_expires_at_ns=(1 << 63) - 1,
    )
    graph.mark_running(
        cut.cut_id,
        "paper::source",
        attempt_id=claim.attempt_id or "",
        owner_id="manual-owner",
        now_ns=3,
    )
    return cut


def test_run_preserves_explicit_node_local_recovery_intent(tmp_path):
    runtime = _ReconciliationRuntime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=True,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="auto-node-recovery")
        target = ResearchExecutionTarget("auto-node-recovery", revision)
        cut = _stage_running_source(graph, target, portfolio)
        interrupted = research.interrupt(target.for_graph(("paper", "source")))
        assert interrupted.state == "node_recovery_required"

        receipt = research.run(target)

        assert receipt.state == "node_recovery_required"
        assert graph.active_cut(target.execution_id).cut_id == cut.cut_id
        assert graph.node_control_state(cut.cut_id, "paper::source").phase.value == "recovery_required"
        assert runtime.executed == []
    finally:
        pool.close()


def test_run_preserves_explicit_graph_recovery_intent(tmp_path):
    runtime = _ReconciliationRuntime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=True,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="auto-graph-recovery")
        target = ResearchExecutionTarget("auto-graph-recovery", revision)
        cut = _stage_running_source(graph, target, portfolio)
        interrupted = research.interrupt(target)
        assert interrupted.state == "recovery_required"

        receipt = research.run(target)

        assert receipt.state == "recovery_required"
        assert graph.active_cut(target.execution_id).cut_id == cut.cut_id
        assert graph.control_state(cut.cut_id).phase.value == "recovery_required"
        assert runtime.executed == []
    finally:
        pool.close()


def test_run_preserves_explicit_cancelled_selected_subgraph(tmp_path):
    runtime = _Runtime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=True,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="partial-cancel-rerun")
        target = ResearchExecutionTarget("partial-cancel-rerun", revision)
        compilation = __import__(
            "noetrium_platform.composition.research_execution_graph",
            fromlist=["compile_research_portfolio_graph"],
        ).compile_research_portfolio_graph(revision, portfolio)
        from noetrium_platform.composition.research_execution_migration import ResearchExecutionCut

        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        # Cancel only the consume node; source remains pending, so the whole old
        # graph is not terminal and this specifically exercises selected cancellation.
        cancelled = research.cancel(target.for_graph(("paper", "consume")))
        assert cancelled.state == "node_cancelled"
        assert graph.active_cut(target.execution_id).generation == 1

        receipt = research.run(target.for_graph(("paper", "consume")))

        active = graph.active_cut(target.execution_id)
        assert receipt.state == "cancelled"
        assert active is not None
        assert active.generation == 1
        assert active.cut_id == cut.cut_id
        assert graph.snapshot(cut.cut_id).node("paper::consume").state.value == "cancelled"
    finally:
        pool.close()


def test_repeat_terminal_run_does_not_require_abandoned_owner_recovery_privilege(tmp_path):
    runtime = _Runtime()
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        ResearchValueRouter((_ValueAuthority(),)),
        exclusive_owner_generation=False,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="quiescent-repeat")
        target = ResearchExecutionTarget("quiescent-repeat", revision)
        first = research.run(target)
        first_cut = graph.active_cut(target.execution_id)
        assert first.state == "succeeded"
        assert first_cut is not None and first_cut.generation == 1

        second = research.run(target)
        second_cut = graph.active_cut(target.execution_id)
        assert second.state == "succeeded"
        assert second_cut is not None and second_cut.generation == 2
        assert second_cut.cut_id != first_cut.cut_id
    finally:
        pool.close()
