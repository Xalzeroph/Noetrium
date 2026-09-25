from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphExecutionConflict,
    ResearchGraphLeaseRenewal,
    ResearchGraphNode,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


class _BatchReadStore(SQLiteResearchGraphExecutionStore):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.single_node_read_count = 0

    def _node_tx(self, conn, execution_id, node_id):
        self.single_node_read_count += 1
        return super()._node_tx(conn, execution_id, node_id)


def _plan() -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "batch-lease-renewal",
        canonical_digest({"revision": "r1"}),
        (
            ResearchGraphNode("a", canonical_digest({"node": "a"})),
            ResearchGraphNode("b", canonical_digest({"node": "b"})),
        ),
    )


def _running_attempt(
    store: SQLiteResearchGraphExecutionStore,
    node_id: str,
    owner_id: str,
):
    store.mark_ready("execution", node_id, now_ns=1)
    claim = store.claim(
        "execution",
        node_id,
        owner_id=owner_id,
        now_ns=2,
        lease_expires_at_ns=100,
    )
    store.mark_running(
        "execution",
        node_id,
        attempt_id=claim.attempt_id or "",
        owner_id=owner_id,
        now_ns=3,
    )
    return claim


def test_batch_lease_renewal_is_atomic_and_bumps_generation_once(
    tmp_path: Path,
) -> None:
    store = _BatchReadStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution", _plan())
    a = _running_attempt(store, "a", "scheduler")
    b = _running_attempt(store, "b", "scheduler")

    before = store.snapshot("execution")
    before_a = store.node_state("execution", "a")
    before_b = store.node_state("execution", "b")

    store.single_node_read_count = 0
    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="ownership mismatch",
    ):
        store.renew_leases(
            "execution",
            (
                ResearchGraphLeaseRenewal(
                    "a",
                    a.attempt_id or "",
                    "scheduler",
                    200,
                ),
                ResearchGraphLeaseRenewal(
                    "b",
                    b.attempt_id or "",
                    "wrong-owner",
                    200,
                ),
            ),
            now_ns=4,
        )
    assert store.single_node_read_count == 0

    after_failed = store.snapshot("execution")
    assert after_failed.generation == before.generation
    assert store.node_state("execution", "a").lease_expires_at_ns == (
        before_a.lease_expires_at_ns
    )
    assert store.node_state("execution", "b").lease_expires_at_ns == (
        before_b.lease_expires_at_ns
    )

    store.single_node_read_count = 0
    renewed = store.renew_leases(
        "execution",
        (
            ResearchGraphLeaseRenewal(
                "b",
                b.attempt_id or "",
                "scheduler",
                200,
            ),
            ResearchGraphLeaseRenewal(
                "a",
                a.attempt_id or "",
                "scheduler",
                200,
            ),
        ),
        now_ns=4,
    )

    assert store.single_node_read_count == 0
    assert tuple(row.node_id for row in renewed) == ("a", "b")
    assert all(row.lease_expires_at_ns == 200 for row in renewed)
    after_success = store.snapshot("execution")
    assert after_success.generation == before.generation + 1
    assert store.attempt_state("execution", "a", 1).lease_expires_at_ns == 200
    assert store.attempt_state("execution", "b", 1).lease_expires_at_ns == 200
