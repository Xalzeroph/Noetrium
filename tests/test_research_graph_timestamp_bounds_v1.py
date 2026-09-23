from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


_INT64_MAX = (1 << 63) - 1


def _plan() -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "timestamp-bounds",
        canonical_digest({"revision": "r1"}),
        (
            ResearchGraphNode(
                "node",
                canonical_digest({"node": "node"}),
            ),
        ),
    )


def test_sqlite_graph_timestamp_overflow_fails_before_durable_mutation(
    tmp_path: Path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution", _plan())

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
        store.renew_lease(
            "execution",
            "node",
            attempt_id=claim.attempt_id or "",
            owner_id="worker",
            now_ns=4,
            lease_expires_at_ns=_INT64_MAX + 1,
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
    )
    with pytest.raises(ValueError, match="signed 64-bit storage"):
        store.schedule_retry(
            "execution",
            "node",
            retry_not_before_ns=_INT64_MAX + 1,
        )
    assert store.snapshot("execution").node("node").state is (
        ResearchGraphLiveNodeState.FAILED
    )
