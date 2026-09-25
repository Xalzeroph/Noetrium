from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphAttemptState,
    ResearchGraphExecutionNotFound,
    ResearchGraphNode,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _plan() -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "attempt-point-read",
        canonical_digest({"revision": "r1"}),
        (
            ResearchGraphNode(
                "node",
                canonical_digest({"node": "node"}),
            ),
        ),
    )


def test_attempt_point_read_is_exact_and_fail_closed(tmp_path: Path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution", _plan())
    store.mark_ready("execution", "node", now_ns=1)
    claim = store.claim(
        "execution",
        "node",
        owner_id="worker",
        now_ns=2,
        lease_expires_at_ns=100,
    )
    store.mark_running(
        "execution",
        "node",
        attempt_id=claim.attempt_id or "",
        owner_id="worker",
        now_ns=3,
    )
    store.mark_succeeded(
        "execution",
        "node",
        attempt_id=claim.attempt_id or "",
        owner_id="worker",
        now_ns=4,
    )

    exact = store.attempt_state("execution", "node", 1)
    assert exact.attempt_number == 1
    assert exact.attempt_id == claim.attempt_id
    assert exact.state is ResearchGraphAttemptState.SUCCEEDED
    assert exact.finished_at_ns == 4
    assert store.attempts("execution", "node") == (exact,)

    with pytest.raises(ValueError, match="attempt_number must be positive"):
        store.attempt_state("execution", "node", 0)
    with pytest.raises(ResearchGraphExecutionNotFound, match="attempt not found"):
        store.attempt_state("execution", "node", 2)
