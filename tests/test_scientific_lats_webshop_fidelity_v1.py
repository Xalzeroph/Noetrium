from __future__ import annotations

import math

import pytest

from hashlib import sha256

from noetrium_platform.capabilities.environment.api import EnvironmentBranchState, EnvironmentIdentity
from noetrium_platform.composition.execution_lineage import ExecutionStateAnchor
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from research.reproductions.lats_webshop import (
    FailedTrajectory,
    LATSNode,
    backpropagate,
    best_nonterminal_child,
    execute_candidate_from_parent,
    should_refresh_reflections,
    unique_failed_trajectories,
)


_IDENTITY = EnvironmentIdentity("lats-test", "1", "1", "1", "b" * 64)


def _context() -> ExecutionContext:
    return ExecutionContext("run", "trace", "span", task_id="webshop:fixed_0")


class _Session:
    def __init__(self, session_id: str, payload: bytes) -> None:
        self.session_id = session_id
        self.payload = payload
        self.closed = False

    def observe(self, context):
        raise AssertionError("LATS branch fixture does not observe")

    def act(self, request):
        raise AssertionError("LATS branch fixture delegates candidate execution")

    def reconcile(self, effect, context):
        raise AssertionError("LATS branch fixture does not reconcile")

    def capture_branch_state(self, context: ExecutionContext) -> EnvironmentBranchState:
        assert context.task_id is not None
        return EnvironmentBranchState.capture(
            environment=_IDENTITY,
            source_session_id=self.session_id,
            task_id=context.task_id,
            generation="generation:1",
            state_schema_id="lats-test.branch.v1",
            state_digest=sha256(self.payload).hexdigest(),
            opaque_payload=self.payload,
        )

    def restore_branch_state(self, state: EnvironmentBranchState, context: ExecutionContext) -> None:
        assert context.task_id is not None
        state.verify_for(
            environment=_IDENTITY,
            task_id=context.task_id,
            generation="generation:1",
        )
        self.payload = state.opaque_payload

    def close(self) -> None:
        self.closed = True


def test_lats_uct_matches_audited_unvisited_and_visited_rules() -> None:
    parent = LATSNode(visits=4)
    unseen = LATSNode(parent=parent, visits=0, value=0.0)
    rejected = LATSNode(parent=parent, visits=0, value=-0.25)
    visited = LATSNode(parent=parent, visits=2, value=1.0)

    assert math.isinf(unseen.uct())
    assert rejected.uct() == -0.25
    assert visited.uct() == pytest.approx(0.5 + math.sqrt(2.0 * math.log(4) / 2))


def test_lats_backpropagate_uses_running_mean_through_ancestors() -> None:
    root = LATSNode()
    child = LATSNode(parent=root)
    root.add_child(child)

    backpropagate(child, 0.4)
    backpropagate(child, 0.8)

    assert child.visits == 2
    assert root.visits == 2
    assert child.value == pytest.approx(0.6)
    assert root.value == pytest.approx(0.6)


def test_lats_selection_ignores_terminal_children() -> None:
    root = LATSNode(visits=5)
    terminal = LATSNode(parent=root, visits=1, value=10.0, is_terminal=True)
    candidate = LATSNode(parent=root, visits=1, value=0.5)
    root.add_child(terminal)
    root.add_child(candidate)

    assert best_nonterminal_child(root) is candidate


def test_lats_reflection_window_matches_first_three_unique_failures() -> None:
    failed = (
        FailedTrajectory("a", "trajectory-a"),
        FailedTrajectory("a", "trajectory-a-duplicate"),
        FailedTrajectory("b", "trajectory-b"),
        FailedTrajectory("c", "trajectory-c"),
        FailedTrajectory("d", "trajectory-d"),
    )

    selected = unique_failed_trajectories(failed)
    assert tuple(row.final_answer for row in selected) == ("a", "b", "c")
    assert should_refresh_reflections(failed_count=1, reflection_count=0)
    assert should_refresh_reflections(failed_count=3, reflection_count=2)
    assert not should_refresh_reflections(failed_count=4, reflection_count=3)


def test_lats_candidate_executes_only_after_parent_cut_is_restored() -> None:
    parent = _Session("parent:1", b"parent-state")
    opened: list[_Session] = []

    def open_child(session_id: str):
        assert session_id == "child:1"
        child = _Session("child:1", b"empty")
        opened.append(child)
        return child

    execution = execute_candidate_from_parent(
        parent,
        parent_session_id="parent:1",
        child_session_id="child:1",
        parent_branch_id="branch:parent",
        branch_id="branch:1",
        source_cut_id="cut:1",
        fork_id="fork:1",
        context=_context(),
        open_child=open_child,
        execute=lambda child: child.payload,
        source_anchors=(
            ExecutionStateAnchor(
                authority="participant.agent.cognition",
                state_id="agent:parent",
                sha256="a" * 64,
            ),
        ),
    )

    assert execution.child is opened[0]
    assert execution.result == b"parent-state"
    assert execution.fork_receipt.branch_id == "branch:1"
    assert execution.lineage_receipt.parent_branch_id == "branch:parent"
    assert execution.lineage_receipt.child_branch_id == "branch:1"
    assert execution.lineage_receipt.source_cut_id == "cut:1"
    assert tuple(anchor.authority for anchor in execution.lineage_receipt.source_cut.anchors) == (
        "environment.branch_state",
        "participant.agent.cognition",
    )
    assert parent.payload == b"parent-state"


def test_lats_candidate_failure_closes_branch_child() -> None:
    parent = _Session("parent:1", b"parent-state")
    child = _Session("child:1", b"empty")

    def fail(_child):
        raise RuntimeError("candidate failed")

    with pytest.raises(RuntimeError, match="candidate failed"):
        execute_candidate_from_parent(
            parent,
            parent_session_id="parent:1",
            child_session_id="child:1",
            parent_branch_id="branch:parent",
            branch_id="branch:1",
            source_cut_id="cut:1",
            fork_id="fork:1",
            context=_context(),
            open_child=lambda _session_id: child,
            execute=fail,
        )
    assert child.closed


def test_lats_invalid_lineage_closes_restored_child_before_propagating() -> None:
    parent = _Session("parent:1", b"parent-state")
    child = _Session("child:1", b"empty")

    with pytest.raises(ValueError, match="differ from parent"):
        execute_candidate_from_parent(
            parent,
            parent_session_id="parent:1",
            child_session_id="child:1",
            parent_branch_id="branch:1",
            branch_id="branch:1",
            source_cut_id="cut:1",
            fork_id="fork:1",
            context=_context(),
            open_child=lambda _session_id: child,
            execute=lambda _child: b"unreachable",
        )
    assert child.closed
