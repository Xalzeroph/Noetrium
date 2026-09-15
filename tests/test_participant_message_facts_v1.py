from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.api import (
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
    ParticipantTopology,
    ParticipantTopologyMember,
)
from noetrium_platform.capabilities.participant.agent.runtime import (
    AgentTurnFactBuffer,
    AgentTurnFactKind,
    ParticipantMessageFactBinding,
    record_participant_message_delivery,
    record_participant_message_dispatch,
)
from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    DeliveryStatus,
    ExecutionContext,
    canonical_digest,
)


def _member(participant_id: str, role: str, token: str) -> ParticipantTopologyMember:
    digest = token * 64
    return ParticipantTopologyMember(
        participant_id=participant_id,
        role=role,
        requirement_digest=digest,
        binding_digest=digest,
        architecture_revision_digest=digest,
    )


def _schedule() -> tuple[ParticipantMessageSchedule, ParticipantMessageScheduleEntry, ParticipantMessageScheduleEntry]:
    topology = ParticipantTopology(
        topology_id="debate-topology",
        members=(
            _member("agent-a", "debater", "a"),
            _member("agent-b", "debater", "b"),
        ),
    )
    first = ParticipantMessageScheduleEntry(
        message_id="message-1",
        sender_participant_id="agent-a",
        recipient_participant_ids=("agent-b",),
        sequence=0,
    )
    second = ParticipantMessageScheduleEntry(
        message_id="message-2",
        sender_participant_id="agent-b",
        recipient_participant_ids=("agent-a",),
        sequence=1,
        causal_parent_message_ids=("message-1",),
    )
    schedule = ParticipantMessageSchedule.for_topology(
        "debate-round-1",
        topology,
        (first, second),
    )
    return schedule, first, second


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        task_id="task-1",
        decision_cycle_id="cycle-1",
    )


def test_message_binding_preserves_schedule_and_causal_identity() -> None:
    schedule, _, second = _schedule()
    content_digest = canonical_digest({"text": "counterargument"})

    binding = ParticipantMessageFactBinding.from_schedule(
        schedule,
        second,
        content_digest=content_digest,
    )

    assert binding.schedule_digest == schedule.digest()
    assert binding.topology_digest == schedule.topology_digest
    assert binding.entry_digest == second.digest()
    assert binding.message_id == "message-2"
    assert binding.causal_parent_message_ids == ("message-1",)
    assert binding.content_digest == content_digest


def test_dispatch_and_delivery_share_agent_turn_fact_chain() -> None:
    schedule, first, _ = _schedule()
    binding = ParticipantMessageFactBinding.from_schedule(
        schedule,
        first,
        content_digest=canonical_digest({"text": "proposal"}),
    )
    facts = AgentTurnFactBuffer("multi-agent-session")

    dispatched = record_participant_message_dispatch(
        facts,
        context=_context(),
        binding=binding,
        artifact_refs=("artifact://message/message-1",),
    )
    receipt = DeliveryReceipt(
        envelope_id="envelope-1",
        envelope_digest="e" * 64,
        status=DeliveryStatus.DELIVERED,
        attempt=1,
    )
    delivered = record_participant_message_delivery(
        facts,
        context=_context(),
        binding=binding,
        receipt=receipt,
        artifact_refs=("artifact://message/message-1",),
    )

    assert dispatched.kind is AgentTurnFactKind.ACTION
    assert dispatched.payload["fact_type"] == "participant_message"
    assert dispatched.payload["stage"] == "dispatch"
    assert delivered.kind is AgentTurnFactKind.EFFECT
    assert delivered.payload["stage"] == "delivery"
    assert delivered.payload["delivery_status"] == DeliveryStatus.DELIVERED
    assert delivered.payload["delivery_receipt_digest"] == receipt.receipt_digest
    assert delivered.previous_fact_digest == dispatched.fact_digest
    assert facts.head_digest == delivered.fact_digest


def test_binding_rejects_unscheduled_or_mutated_message_identity() -> None:
    schedule, _, second = _schedule()
    content_digest = canonical_digest({"text": "counterargument"})
    missing = ParticipantMessageScheduleEntry(
        message_id="message-3",
        sender_participant_id="agent-a",
        recipient_participant_ids=("agent-b",),
        sequence=2,
        causal_parent_message_ids=("message-2",),
    )
    mutated = ParticipantMessageScheduleEntry(
        message_id=second.message_id,
        sender_participant_id="agent-a",
        recipient_participant_ids=("agent-b",),
        sequence=second.sequence,
        causal_parent_message_ids=second.causal_parent_message_ids,
    )

    with pytest.raises(ValueError, match="not present"):
        ParticipantMessageFactBinding.from_schedule(
            schedule,
            missing,
            content_digest=content_digest,
        )
    with pytest.raises(ValueError, match="does not match"):
        ParticipantMessageFactBinding.from_schedule(
            schedule,
            mutated,
            content_digest=content_digest,
        )


def test_delivery_fact_requires_transport_receipt() -> None:
    schedule, first, _ = _schedule()
    binding = ParticipantMessageFactBinding.from_schedule(
        schedule,
        first,
        content_digest=canonical_digest({"text": "proposal"}),
    )

    with pytest.raises(TypeError, match="requires DeliveryReceipt"):
        binding.as_payload(stage="delivery")
    with pytest.raises(ValueError, match="cannot carry"):
        binding.as_payload(
            stage="dispatch",
            receipt=DeliveryReceipt(
                envelope_id="envelope-1",
                envelope_digest="e" * 64,
                status=DeliveryStatus.PENDING,
                attempt=0,
            ),
        )
