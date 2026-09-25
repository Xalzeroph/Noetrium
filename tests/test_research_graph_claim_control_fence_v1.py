from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphExecutionConflict,
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphNodeControlPhase,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _plan() -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "claim-control-fence",
        canonical_digest({"revision": 1}),
        (
            ResearchGraphNode(
                "node",
                canonical_digest({"node": "node"}),
            ),
        ),
    )


def test_graph_pause_between_ready_and_claim_is_atomically_fenced(
    tmp_path: Path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution", _plan())
    ready = store.mark_ready("execution", "node", now_ns=1)
    assert ready.state is ResearchGraphLiveNodeState.READY

    control = store.control_state("execution")
    paused = store.pause_if_quiescent(
        "execution",
        expected_generation=control.generation,
        now_ns=2,
    )
    assert paused.phase is ResearchGraphControlPhase.PAUSED

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="active graph control",
    ):
        store.claim(
            "execution",
            "node",
            owner_id="worker",
            now_ns=3,
            lease_expires_at_ns=10,
        )
    assert store.node_state("execution", "node").state is ResearchGraphLiveNodeState.READY
    assert store.attempts("execution", "node") == ()

    resumed = store.resume(
        "execution",
        expected_generation=paused.generation,
        now_ns=4,
    )
    assert resumed.phase is ResearchGraphControlPhase.ACTIVE
    claimed = store.claim(
        "execution",
        "node",
        owner_id="worker",
        now_ns=5,
        lease_expires_at_ns=10,
    )
    assert claimed.state is ResearchGraphLiveNodeState.CLAIMED
    assert len(store.attempts("execution", "node")) == 1


def test_node_pause_between_ready_and_claim_is_atomically_fenced(
    tmp_path: Path,
) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    store.ensure_execution("execution", _plan())
    ready = store.mark_ready("execution", "node", now_ns=1)
    assert ready.state is ResearchGraphLiveNodeState.READY

    control = store.node_control_state("execution", "node")
    paused = store.pause_node_if_quiescent(
        "execution",
        "node",
        expected_generation=control.generation,
        now_ns=2,
    )
    assert paused.phase is ResearchGraphNodeControlPhase.PAUSED

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="active node control",
    ):
        store.claim(
            "execution",
            "node",
            owner_id="worker",
            now_ns=3,
            lease_expires_at_ns=10,
        )
    assert store.node_state("execution", "node").state is ResearchGraphLiveNodeState.READY
    assert store.attempts("execution", "node") == ()

    resumed = store.resume_node(
        "execution",
        "node",
        expected_generation=paused.generation,
        now_ns=4,
    )
    assert resumed.phase is ResearchGraphNodeControlPhase.ACTIVE
    claimed = store.claim(
        "execution",
        "node",
        owner_id="worker",
        now_ns=5,
        lease_expires_at_ns=10,
    )
    assert claimed.state is ResearchGraphLiveNodeState.CLAIMED
    assert len(store.attempts("execution", "node")) == 1
