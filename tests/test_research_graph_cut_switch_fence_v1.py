from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphCutSwitchFence,
    ResearchGraphExecutionConflict,
    ResearchGraphNode,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


def _plan() -> ResearchGraphPlan:
    return ResearchGraphPlan(
        "cut-switch-fence",
        canonical_digest({"revision": "r1"}),
        (
            ResearchGraphNode(
                "node",
                canonical_digest({"node": "node"}),
            ),
        ),
    )


def _bound(tmp_path: Path):
    store = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    plan = _plan()
    source = canonical_digest({"cut": "source"})
    target = canonical_digest({"cut": "target"})
    store.ensure_execution(source, plan)
    store.ensure_execution(target, plan)
    active = store.move_active_cut("logical", source)
    snapshot = store.snapshot(source)
    control = store.control_state(source)
    node_controls = tuple(
        store.node_control_state(source, node.node_id)
        for node in snapshot.nodes
    )
    fence = ResearchGraphCutSwitchFence(
        source,
        active.generation,
        snapshot.generation,
        control,
        node_controls,
    )
    return store, source, target, fence


def test_guarded_cut_switch_succeeds_only_for_exact_source_transaction(
    tmp_path: Path,
) -> None:
    store, source, target, fence = _bound(tmp_path)

    moved = store.move_active_cut(
        "logical",
        target,
        expected_cut_id=source,
        source_fence=fence,
    )

    assert moved.cut_id == target
    assert moved.generation == fence.active_cut_generation + 1


def test_guarded_cut_switch_rejects_source_execution_generation_race(
    tmp_path: Path,
) -> None:
    store, source, target, fence = _bound(tmp_path)
    store.mark_ready(source, "node", now_ns=1)

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="source execution generation fence conflict",
    ):
        store.move_active_cut(
            "logical",
            target,
            expected_cut_id=source,
            source_fence=fence,
        )

    assert store.active_cut("logical").cut_id == source


def test_guarded_cut_switch_rejects_global_control_generation_race(
    tmp_path: Path,
) -> None:
    store, source, target, fence = _bound(tmp_path)
    control = store.control_state(source)
    store.request_drain(
        source,
        expected_generation=control.generation,
        now_ns=1,
    )

    with pytest.raises(
        ResearchGraphExecutionConflict,
        match="source control fence conflict",
    ):
        store.move_active_cut(
            "logical",
            target,
            expected_cut_id=source,
            source_fence=fence,
        )

    assert store.active_cut("logical").cut_id == source


def test_guarded_cut_switch_requires_expected_source_identity(
    tmp_path: Path,
) -> None:
    store, _source, target, fence = _bound(tmp_path)

    with pytest.raises(
        ValueError,
        match="requires expected_cut_id",
    ):
        store.move_active_cut(
            "logical",
            target,
            source_fence=fence,
        )
