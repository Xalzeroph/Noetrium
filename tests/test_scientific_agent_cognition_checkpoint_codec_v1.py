from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.agent.api import (
    AgentActionSummary,
    AgentLoopCheckpoint,
    AgentMemoryCheckpoint,
    AgentReceiptCheckpoint,
)
from noetrium_platform.capabilities.participant.agent.runtime.cognition_checkpoint_codec import (
    agent_loop_checkpoint_from_payload,
    agent_loop_checkpoint_to_payload,
)


def _checkpoint() -> AgentLoopCheckpoint:
    summary = AgentActionSummary(
        "action:1",
        "move",
        "skill.move",
        True,
        True,
        observation_digest="b" * 64,
        rationale="advance",
        payload={"x": 1},
        timeout_s=9.0,
    )
    receipt = AgentReceiptCheckpoint(
        "action:1",
        "move",
        "skill.move",
        "sequence:1",
        True,
        True,
        effect_id="effect:1",
        effect_certainty="confirmed",
        diagnostics={"latency_ms": 4},
        payload={"provider": "test"},
    )
    return AgentLoopCheckpoint(
        schema_version="agent-cognition-checkpoint.v2",
        session_id="session:1",
        goal_digest="a" * 64,
        step=1,
        plan_calls=1,
        no_progress_steps=0,
        same_action_runs=1,
        last_observation_digest="b" * 64,
        action_summaries=(summary,),
        last_receipt=receipt,
        memory_checkpoint=AgentMemoryCheckpoint(0, ()),
    )


def test_agent_loop_checkpoint_codec_round_trips_exactly() -> None:
    checkpoint = _checkpoint()
    payload = agent_loop_checkpoint_to_payload(checkpoint)

    restored = agent_loop_checkpoint_from_payload(payload)

    assert restored == checkpoint
    assert restored.digest == checkpoint.digest
    assert payload["memory_checkpoint"]["schema_version"] == "agent-memory.v2"


def test_agent_loop_checkpoint_codec_rejects_unknown_fields() -> None:
    payload = agent_loop_checkpoint_to_payload(_checkpoint())
    payload["shadow_history"] = []

    with pytest.raises(ValueError, match="fields mismatch"):
        agent_loop_checkpoint_from_payload(payload)
