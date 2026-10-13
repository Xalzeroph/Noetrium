from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.api import (
    ParticipantMessageFactBinding,
    participant_communication,
    participant_graph,
)
from noetrium_platform.capabilities.participant.agent.runtime import (
    AgentTurnFactBuffer,
    AgentTurnFactKind,
    record_participant_message_delivery,
    record_participant_message_dispatch,
)
from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    DeliveryStatus,
    ExecutionContext,
    canonical_digest,
)


def _topology():
    first = participant_communication(("agent-a",), ("agent-b",), channel="debate")
    second = participant_communication(("agent-b",), ("agent-a",), channel="debate")
    topology = participant_graph(("agent-a", "agent-b"), (first, second))
    return topology, first, second


def _binding(*, second: bool = False) -> ParticipantMessageFactBinding:
    topology, first, followup = _topology()
    relation = followup if second else first
    text = "counterargument" if second else "proposal"
    return ParticipantMessageFactBinding.from_relation(
        topology,
        relation,
        message_id="message-2" if second else "message-1",
        sender_participant_id="agent-b" if second else "agent-a",
        recipient_participant_ids=("agent-a",) if second else ("agent-b",),
        sequence=1 if second else 0,
        causal_parent_message_ids=("message-1",) if second else (),
        content_digest=canonical_digest({"text": text}),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        task_id="task-1",
        decision_cycle_id="cycle-1",
    )


def test_message_binding_preserves_topology_relation_and_causal_identity() -> None:
    topology, _, second = _topology()
    binding = _binding(second=True)
    assert binding.topology_digest == topology.unit_digest
    assert binding.relation_digest == second.unit_digest
    assert binding.message_id == "message-2"
    assert binding.causal_parent_message_ids == ("message-1",)
    assert binding.content_digest == canonical_digest({"text": "counterargument"})


def test_dispatch_and_delivery_share_agent_turn_fact_chain() -> None:
    binding = _binding()
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


def test_binding_rejects_relation_not_in_topology_or_illegal_sender() -> None:
    topology, first, _ = _topology()
    foreign = participant_communication(
        ("agent-a",), ("agent-b",), channel="private-other"
    )
    digest = canonical_digest({"text": "x"})
    with pytest.raises(ValueError, match="not in topology"):
        ParticipantMessageFactBinding.from_relation(
            topology,
            foreign,
            message_id="message-x",
            sender_participant_id="agent-a",
            recipient_participant_ids=("agent-b",),
            sequence=2,
            content_digest=digest,
        )
    with pytest.raises(ValueError, match="sender"):
        ParticipantMessageFactBinding.from_relation(
            topology,
            first,
            message_id="message-x",
            sender_participant_id="agent-b",
            recipient_participant_ids=("agent-b",),
            sequence=2,
            content_digest=digest,
        )


def test_delivery_fact_requires_transport_receipt() -> None:
    binding = _binding()
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
