from __future__ import annotations

from tests._execution_graph_fixtures import materialize_execution as _materialize_execution

from tests._execution_graph_fixtures import scheduling_vertex as ResearchSchedulingNode, scheduling_graph as ResearchSchedulingPlan

from pathlib import Path
from threading import Event, Thread
from time import sleep

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphExecutionConflict,
    ResearchGraphLeaseRenewal,
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


def _plan() -> ResearchSchedulingPlan:
    return ResearchSchedulingPlan(
        "batch-lease-renewal",
        canonical_digest({"revision": "r1"}),
        (
            ResearchSchedulingNode("a", canonical_digest({"node": "a"})),
            ResearchSchedulingNode("b", canonical_digest({"node": "b"})),
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
    _materialize_execution(store, "execution", _plan())
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


def test_lease_renewal_writer_priority_prevents_normal_barging(tmp_path: Path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "priority.sqlite3")
    _materialize_execution(store, "execution", _plan())
    claim = _running_attempt(store, "a", "scheduler")
    holder_entered = Event()
    release_holder = Event()
    order: list[str] = []
    errors: list[BaseException] = []

    def hold_writer() -> None:
        with store._writer_connection():
            holder_entered.set()
            assert release_holder.wait(2.0)

    def renew() -> None:
        try:
            store.renew_leases(
                "execution",
                (ResearchGraphLeaseRenewal("a", claim.attempt_id or "", "scheduler", 200),),
                now_ns=4,
            )
            order.append("renew")
        except BaseException as exc:
            errors.append(exc)

    def normal_write() -> None:
        try:
            store.mark_ready("execution", "b", now_ns=5)
            order.append("normal")
        except BaseException as exc:
            errors.append(exc)

    holder = Thread(target=hold_writer)
    priority = Thread(target=renew)
    normal = Thread(target=normal_write)
    holder.start()
    assert holder_entered.wait(1.0)
    priority.start()
    for _ in range(1000):
        if store._writer_gate._priority_waiters:
            break
        sleep(0.001)
    assert store._writer_gate._priority_waiters == 1
    normal.start()
    release_holder.set()
    holder.join(2.0)
    priority.join(2.0)
    normal.join(2.0)

    assert errors == []
    assert order == ["renew", "normal"]
