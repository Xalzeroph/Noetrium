from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.agent.api.cognition import AgentLoopCheckpoint
from noetrium_platform.composition.environment_fork import EnvironmentForkReceipt
from noetrium_platform.composition.execution_lineage import (
    ExecutionSourceCut,
    ExecutionStateAnchor,
    bind_execution_fork,
)


def _agent_checkpoint() -> AgentLoopCheckpoint:
    return AgentLoopCheckpoint(
        schema_version="agent-cognition-checkpoint.v2",
        session_id="agent:parent",
        goal_digest="a" * 64,
        step=0,
        plan_calls=0,
        no_progress_steps=0,
        same_action_runs=0,
        last_observation_digest="observation:initial",
    )


def _environment_receipt() -> EnvironmentForkReceipt:
    return EnvironmentForkReceipt(
        parent_session_id="environment:parent",
        child_session_id="environment:child",
        branch_id="branch:child",
        source_cut_id="cut:parent:7",
        source_checkpoint_sha256="b" * 64,
    )


def test_execution_source_cut_binds_agent_and_environment_state_identities() -> None:
    agent = _agent_checkpoint()
    environment = _environment_receipt()
    cut = ExecutionSourceCut(
        cut_id=environment.source_cut_id,
        branch_id="branch:parent",
        anchors=(
            ExecutionStateAnchor(
                authority="environment.session",
                state_id=environment.parent_session_id,
                sha256=environment.source_checkpoint_sha256,
            ),
            ExecutionStateAnchor(
                authority="participant.agent.cognition",
                state_id=agent.session_id,
                sha256=agent.digest,
            ),
        ),
    )

    receipt = bind_execution_fork(
        cut,
        fork_id="fork:7",
        child_branch_id=environment.branch_id,
    )

    assert receipt.parent_branch_id == "branch:parent"
    assert receipt.child_branch_id == "branch:child"
    assert receipt.source_cut_id == "cut:parent:7"
    assert receipt.source_cut_digest == cut.digest
    assert len(receipt.digest) == 64


def test_execution_source_cut_digest_is_independent_of_anchor_input_order() -> None:
    first = ExecutionStateAnchor("authority:z", "state:2", "2" * 64)
    second = ExecutionStateAnchor("authority:a", "state:1", "1" * 64)

    forward = ExecutionSourceCut("cut:1", "branch:parent", (first, second))
    reverse = ExecutionSourceCut("cut:1", "branch:parent", (second, first))

    assert forward.anchors == reverse.anchors
    assert forward.digest == reverse.digest


def test_execution_source_cut_rejects_duplicate_state_identity() -> None:
    with pytest.raises(ValueError, match="duplicate state identity"):
        ExecutionSourceCut(
            "cut:1",
            "branch:parent",
            (
                ExecutionStateAnchor("authority:a", "state:1", "1" * 64),
                ExecutionStateAnchor("authority:a", "state:1", "2" * 64),
            ),
        )


def test_execution_lineage_rejects_invalid_digest_and_parent_child_alias() -> None:
    with pytest.raises(ValueError, match="lowercase sha256"):
        ExecutionStateAnchor("authority:a", "state:1", "A" * 64)

    cut = ExecutionSourceCut(
        "cut:1",
        "branch:parent",
        (ExecutionStateAnchor("authority:a", "state:1", "1" * 64),),
    )
    with pytest.raises(ValueError, match="differ from parent"):
        bind_execution_fork(
            cut,
            fork_id="fork:1",
            child_branch_id="branch:parent",
        )
