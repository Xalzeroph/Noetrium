from __future__ import annotations

from tests._execution_graph_fixtures import materialize_execution as _materialize_execution

from tests._execution_graph_fixtures import scheduling_vertex as ResearchSchedulingNode, scheduling_graph as ResearchSchedulingPlan

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLeaseRenewal,
    ResearchGraphFailureProvenance,
    ResearchGraphLiveNodeState,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


_INT64_MAX = (1 << 63) - 1


def _failure_provenance(message: str) -> ResearchGraphFailureProvenance:
    return ResearchGraphFailureProvenance(
        "tests.fixture",
        canonical_digest({"failure": message}),
        message,
    )


def _plan() -> ResearchSchedulingPlan:
    return ResearchSchedulingPlan(
        "timestamp-bounds",
        canonical_digest({"revision": "r1"}),
        (
            ResearchSchedulingNode(
                "node",
                canonical_digest({"node": "node"}),
            ),
        ),
    )


def test_sqlite_graph_timestamp_overflow_fails_before_durable_mutation(
    tmp_path: Path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    _materialize_execution(store, "execution", _plan())

    with pytest.raises(ValueError, match="signed 64-bit storage"):
        store.mark_ready(
            "execution",
            "node",
            now_ns=_INT64_MAX + 1,
        )
    assert store.snapshot("execution").node("node").state is (
        ResearchGraphLiveNodeState.PENDING
    )

    store.mark_ready("execution", "node", now_ns=1)
    with pytest.raises(ValueError, match="signed 64-bit storage"):
        store.claim(
            "execution",
            "node",
            owner_id="worker",
            now_ns=2,
            lease_expires_at_ns=_INT64_MAX + 1,
        )
    assert store.snapshot("execution").node("node").state is (
        ResearchGraphLiveNodeState.READY
    )
    assert store.attempts("execution", "node") == ()

    claim = store.claim(
        "execution",
        "node",
        owner_id="worker",
        now_ns=2,
        lease_expires_at_ns=_INT64_MAX,
    )
    store.mark_running(
        "execution",
        "node",
        attempt_id=claim.attempt_id or "",
        owner_id="worker",
        now_ns=3,
    )
    with pytest.raises(ValueError, match="signed 64-bit storage"):
        store.renew_leases(
            "execution",
            (
                ResearchGraphLeaseRenewal(
                    "node",
                    claim.attempt_id or "",
                    "worker",
                    _INT64_MAX + 1,
                ),
            ),
            now_ns=4,
        )
    attempts = store.attempts("execution", "node")
    assert len(attempts) == 1
    assert attempts[0].lease_expires_at_ns == _INT64_MAX

    store.mark_failed(
        "execution",
        "node",
        attempt_id=claim.attempt_id or "",
        owner_id="worker",
        now_ns=5,
        failure_type="fixture",
        failure_message="fixture",
        failure_provenance=_failure_provenance("fixture"),
    )
    with pytest.raises(ValueError, match="signed 64-bit storage"):
        store.retry_failed_subgraph(
            "execution",
            "node",
            descendant_node_ids=(),
            retry_not_before_ns=_INT64_MAX + 1,
        )
    assert store.snapshot("execution").node("node").state is (
        ResearchGraphLiveNodeState.FAILED
    )
