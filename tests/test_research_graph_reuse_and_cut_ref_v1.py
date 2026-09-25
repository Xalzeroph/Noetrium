from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphCutSwitchFence,
    ResearchGraphExecutionConflict,
    ResearchGraphLiveNodeState,
    ResearchGraphNode,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _plan(revision_seed: str) -> ResearchGraphPlan:
    semantic = canonical_digest({"semantic": "same"})
    return ResearchGraphPlan(
        "portfolio",
        canonical_digest({"revision": revision_seed}),
        (ResearchGraphNode("node", semantic),),
    )


def _succeed_source(store, execution_id: str, plan: ResearchGraphPlan) -> None:
    store.ensure_execution(execution_id, plan)
    store.mark_ready(execution_id, "node", now_ns=10)
    claim = store.claim(
        execution_id,
        "node",
        owner_id="worker",
        now_ns=11,
        lease_expires_at_ns=100,
    )
    store.mark_running(
        execution_id,
        "node",
        attempt_id=claim.attempt_id or "",
        owner_id="worker",
        now_ns=12,
    )
    store.mark_succeeded(
        execution_id,
        "node",
        attempt_id=claim.attempt_id or "",
        owner_id="worker",
        now_ns=13,
    )


def test_reused_node_has_proof_without_fabricating_target_attempt(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    source_plan = _plan("r1")
    target_plan = _plan("r2")
    source_id = canonical_digest({"cut": "r1"})
    target_id = canonical_digest({"cut": "r2"})
    _succeed_source(store, source_id, source_plan)
    store.ensure_execution(target_id, target_plan)

    semantic = target_plan.nodes[0].semantic_digest
    reused = store.mark_reused(
        target_id,
        "node",
        source_execution_id=source_id,
        source_node_id="node",
        semantic_digest=semantic,
        proof_digest=canonical_digest({"artifact-proof": "node"}),
        now_ns=20,
    )

    assert reused.state is ResearchGraphLiveNodeState.REUSED
    assert reused.attempt_number == 0
    assert store.attempts(target_id, "node") == ()
    proof = store.reuse_record(target_id, "node")
    assert proof is not None
    assert proof.source_execution_id == source_id
    assert proof.semantic_digest == semantic


def test_reuse_rejects_semantic_drift_or_unsuccessful_source(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    source_plan = _plan("r1")
    target_plan = ResearchGraphPlan(
        "portfolio",
        canonical_digest({"revision": "r2"}),
        (
            ResearchGraphNode(
                "node",
                canonical_digest({"semantic": "changed"}),
            ),
        ),
    )
    source_id = canonical_digest({"cut": "r1"})
    target_id = canonical_digest({"cut": "r2"})
    _succeed_source(store, source_id, source_plan)
    store.ensure_execution(target_id, target_plan)

    with pytest.raises(ResearchGraphExecutionConflict, match="semantic identity mismatch"):
        store.mark_reused(
            target_id,
            "node",
            source_execution_id=source_id,
            source_node_id="node",
            semantic_digest=target_plan.nodes[0].semantic_digest,
            proof_digest=canonical_digest({"proof": 1}),
            now_ns=20,
        )


def test_active_cut_ref_moves_with_compare_and_swap(tmp_path) -> None:
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    first_id = canonical_digest({"cut": "r1"})
    second_id = canonical_digest({"cut": "r2"})
    store.ensure_execution(first_id, _plan("r1"))
    store.ensure_execution(second_id, _plan("r2"))

    first = store.move_active_cut("logical", first_id)
    assert first.cut_id == first_id
    assert first.generation == 1

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="requires an exact source execution fence",
    ):
        store.move_active_cut(
            "logical",
            second_id,
            expected_cut_id=first_id,
        )

    snapshot = store.snapshot(first_id)
    fence = ResearchGraphCutSwitchFence(
        first_id,
        first.generation,
        snapshot.generation,
        store.control_state(first_id),
        tuple(
            store.node_control_state(first_id, node.node_id)
            for node in snapshot.nodes
        ),
    )
    second = store.move_active_cut(
        "logical",
        second_id,
        expected_cut_id=first_id,
        source_fence=fence,
    )
    assert second.cut_id == second_id
    assert second.generation == 2
    assert store.active_cut("logical") == second

    with pytest.raises(ResearchGraphExecutionConflict, match="compare-and-swap"):
        store.move_active_cut(
            "logical",
            first_id,
            expected_cut_id=first_id,
        )
