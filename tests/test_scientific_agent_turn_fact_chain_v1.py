from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.agent.api import (
    AGENT_TURN_FACT_SCHEMA,
    AgentTurnFact,
    AgentTurnFactKind,
)
from noetrium_platform.capabilities.participant.agent.runtime import AgentTurnFactBuffer
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


_CONTEXT = ExecutionContext(
    "run:1",
    "trace:1",
    "span:1",
    task_id="goal:1",
    decision_cycle_id="goal:1:plan:0",
)


def test_turn_fact_buffer_builds_contiguous_digest_chain() -> None:
    facts = AgentTurnFactBuffer("session:1")
    first = facts.append(
        AgentTurnFactKind.PLANNING_INPUT,
        context=_CONTEXT,
        payload={"goal_digest": "g", "observation_digest": "o"},
    )
    second = facts.append(
        AgentTurnFactKind.MODEL_REQUEST,
        context=_CONTEXT,
        payload={"request_id": "request:1", "request_body_ref": "sha256:body"},
    )

    assert first.schema_version == AGENT_TURN_FACT_SCHEMA
    assert first.sequence == 1
    assert first.previous_fact_digest is None
    assert second.sequence == 2
    assert second.previous_fact_digest == first.fact_digest
    assert facts.head_digest == second.fact_digest
    assert facts.next_sequence == 3
    assert second.as_payload()["fact_digest"] == second.fact_digest


def test_turn_fact_buffer_replays_only_an_intact_authoritative_chain() -> None:
    source = AgentTurnFactBuffer("session:1")
    source.append(AgentTurnFactKind.ACTION, context=_CONTEXT, payload={"action_id": "a1"})
    source.append(AgentTurnFactKind.OBSERVATION, context=_CONTEXT, payload={"observation_id": "o1"})

    replayed = AgentTurnFactBuffer.replay_candidate("session:1", source.facts)
    assert replayed.facts == source.facts
    assert replayed.head_digest == source.head_digest

    broken = AgentTurnFact(
        AGENT_TURN_FACT_SCHEMA,
        "session:1",
        2,
        AgentTurnFactKind.OBSERVATION,
        "run:1",
        "trace:1",
        "span:1",
        {"observation_id": "o1"},
        "goal:1",
        "goal:1:plan:0",
        (),
        "0" * 64,
    )
    with pytest.raises(ValueError, match="digest chain"):
        AgentTurnFactBuffer.replay_candidate("session:1", (source.facts[0], broken))


def test_non_initial_fact_requires_previous_digest() -> None:
    with pytest.raises(ValueError, match="requires previous digest"):
        AgentTurnFact(
            AGENT_TURN_FACT_SCHEMA,
            "session:1",
            2,
            AgentTurnFactKind.ACTION,
            "run:1",
            "trace:1",
            "span:1",
            {},
        )
