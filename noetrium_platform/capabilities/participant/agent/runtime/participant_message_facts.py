from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    ExecutionContext,
)

from noetrium_platform.capabilities.participant.api.messaging import ParticipantMessageFactBinding
from .turn_facts import AgentTurnFact, AgentTurnFactKind, AgentTurnFactSink


def record_participant_message_dispatch(
    facts: AgentTurnFactSink,
    *,
    context: ExecutionContext,
    binding: ParticipantMessageFactBinding,
    artifact_refs: tuple[str, ...] = (),
) -> AgentTurnFact:
    if not isinstance(binding, ParticipantMessageFactBinding):
        raise TypeError("participant message dispatch binding must be typed")
    return facts.append(
        AgentTurnFactKind.ACTION,
        context=context,
        payload=binding.as_payload(stage="dispatch"),
        artifact_refs=artifact_refs,
    )


def record_participant_message_delivery(
    facts: AgentTurnFactSink,
    *,
    context: ExecutionContext,
    binding: ParticipantMessageFactBinding,
    receipt: DeliveryReceipt,
    artifact_refs: tuple[str, ...] = (),
) -> AgentTurnFact:
    if not isinstance(binding, ParticipantMessageFactBinding):
        raise TypeError("participant message delivery binding must be typed")
    return facts.append(
        AgentTurnFactKind.EFFECT,
        context=context,
        payload=binding.as_payload(stage="delivery", receipt=receipt),
        artifact_refs=artifact_refs,
    )


__all__ = [
    "ParticipantMessageFactBinding",
    "record_participant_message_delivery",
    "record_participant_message_dispatch",
]
