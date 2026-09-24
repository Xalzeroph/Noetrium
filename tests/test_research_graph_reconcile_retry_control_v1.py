from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import (
    ResearchGraphNodeControlHalt,
    ResearchGraphScheduler,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphAttemptState,
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphNodeControlPhase,
    ResearchGraphPlan,
    ResearchGraphReconciliationDisposition,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


class _NeverExecute:
    def execute(self, context, node, *, deadline) -> None:
        del context, node, deadline
        raise AssertionError(
            "reconciled retry must remain locally paused until explicit resume"
        )


def _plan() -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "reconcile-retry-control",
        canonical_digest({"revision": "r1"}),
        (
            ResearchGraphNode(
                "a",
                canonical_digest({"node": "a"}),
            ),
        ),
    )


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def test_reconciled_retry_remains_node_paused_until_explicit_resume(
    tmp_path: Path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution", _plan())
    store.mark_ready("execution", "a", now_ns=1)
    claim = store.claim(
        "execution",
        "a",
        owner_id="worker",
        now_ns=2,
        lease_expires_at_ns=100,
    )
    store.mark_running(
        "execution",
        "a",
        attempt_id=claim.attempt_id or "",
        owner_id="worker",
        now_ns=3,
    )
    control = store.node_control_state("execution", "a")
    interrupted = store.interrupt_node(
        "execution",
        "a",
        expected_generation=control.generation,
        now_ns=4,
    )
    assert interrupted.phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED

    resolved = store.resolve_reconciliation(
        "execution",
        "a",
        disposition=ResearchGraphReconciliationDisposition.RETRY,
        now_ns=5,
        retry_not_before_ns=5,
    )
    assert resolved.state is ResearchGraphLiveNodeState.RETRY_WAIT
    attempts = store.attempts("execution", "a")
    assert len(attempts) == 1
    assert attempts[0].state is ResearchGraphAttemptState.RECONCILED_RETRY

    settled = store.settle_node_recovery(
        "execution",
        "a",
        expected_generation=interrupted.generation,
        now_ns=6,
    )
    assert settled.phase is ResearchGraphNodeControlPhase.PAUSED

    pool = _pool()
    scheduler = ResearchGraphScheduler(
        _plan(),
        _NeverExecute(),
        execution_pool=pool,
        execution_store=store,
        execution_id="execution",
        selected_node_ids=("a",),
    )
    try:
        with pytest.raises(ResearchGraphNodeControlHalt) as captured:
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert tuple(row.node_id for row in captured.value.controls) == ("a",)
    assert captured.value.controls[0].phase is ResearchGraphNodeControlPhase.PAUSED
    assert store.snapshot("execution").node("a").state is (
        ResearchGraphLiveNodeState.RETRY_WAIT
    )
    assert len(store.attempts("execution", "a")) == 1


def test_unproven_pool_does_not_reclaim_foreign_generation_before_ttl(
    tmp_path: Path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph-no-exclusive.sqlite3")
    store.ensure_execution("execution-no-exclusive", _plan())
    store.mark_ready("execution-no-exclusive", "a", now_ns=1)
    claim = store.claim(
        "execution-no-exclusive",
        "a",
        owner_id="research-graph-scheduler:other-generation:worker",
        now_ns=2,
        lease_expires_at_ns=10**20,
    )
    pool = _pool()
    scheduler = ResearchGraphScheduler(
        _plan(),
        _NeverExecute(),
        execution_pool=pool,
        execution_store=store,
        execution_id="execution-no-exclusive",
        selected_node_ids=("a",),
    )
    try:
        with pytest.raises(Exception, match="active non-expired leases"):
            scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    current = store.snapshot("execution-no-exclusive").node("a")
    assert current.state is ResearchGraphLiveNodeState.CLAIMED
    assert current.attempt_id == claim.attempt_id
