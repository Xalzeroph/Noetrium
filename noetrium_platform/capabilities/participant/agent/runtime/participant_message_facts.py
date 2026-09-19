from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.participant.api import (
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
)
from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    ExecutionContext,
    JsonObject,
    require_sha256,
)

from .turn_facts import AgentTurnFact, AgentTurnFactKind, AgentTurnFactSink


@dataclass(frozen=True, slots=True)
class ParticipantMessageFactBinding:
    """Identity binding for one scheduled participant message.

    The schedule owns intended causal order. Agent Turn facts record what was
    actually attempted/observed. The enclosing Machine Journal remains the
    durable authority; this type deliberately owns no storage.
    """

    schedule_id: str
    schedule_digest: str
    topology_digest: str
    entry_digest: str
    message_id: str
    sender_participant_id: str
    recipient_participant_ids: tuple[str, ...]
    sequence: int
    causal_parent_message_ids: tuple[str, ...]
    content_digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("schedule_id", self.schedule_id),
            ("message_id", self.message_id),
            ("sender_participant_id", self.sender_participant_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"participant message {name} is required")
        for name, value in (
            ("schedule_digest", self.schedule_digest),
            ("topology_digest", self.topology_digest),
            ("entry_digest", self.entry_digest),
            ("content_digest", self.content_digest),
        ):
            require_sha256(value, f"participant message {name}")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("participant message sequence must be non-negative")
        if not isinstance(self.recipient_participant_ids, tuple) or not self.recipient_participant_ids:
            raise TypeError("participant message recipients must be a non-empty tuple")
        if any(not isinstance(value, str) or not value.strip() for value in self.recipient_participant_ids):
            raise ValueError("participant message recipients must be non-empty text")
        if len(self.recipient_participant_ids) != len(set(self.recipient_participant_ids)):
            raise ValueError("participant message recipients must be unique")
        if tuple(sorted(self.recipient_participant_ids)) != self.recipient_participant_ids:
            raise ValueError("participant message recipients must be canonical-sorted")
        if not isinstance(self.causal_parent_message_ids, tuple):
            raise TypeError("participant message causal parents must be a tuple")
        if any(not isinstance(value, str) or not value.strip() for value in self.causal_parent_message_ids):
            raise ValueError("participant message causal parents must be non-empty text")
        if len(self.causal_parent_message_ids) != len(set(self.causal_parent_message_ids)):
            raise ValueError("participant message causal parents must be unique")
        if tuple(sorted(self.causal_parent_message_ids)) != self.causal_parent_message_ids:
            raise ValueError("participant message causal parents must be canonical-sorted")
        if self.message_id in self.causal_parent_message_ids:
            raise ValueError("participant message cannot causally depend on itself")

    @classmethod
    def from_schedule(
        cls,
        schedule: ParticipantMessageSchedule,
        entry: ParticipantMessageScheduleEntry,
        *,
        content_digest: str,
    ) -> "ParticipantMessageFactBinding":
        if not isinstance(schedule, ParticipantMessageSchedule):
            raise TypeError("participant message schedule must be typed")
        if not isinstance(entry, ParticipantMessageScheduleEntry):
            raise TypeError("participant message entry must be typed")
        scheduled = next((row for row in schedule.entries if row.message_id == entry.message_id), None)
        if scheduled is None:
            raise ValueError("participant message entry is not present in schedule")
        if scheduled.digest() != entry.digest():
            raise ValueError("participant message entry does not match scheduled identity")
        return cls(
            schedule_id=schedule.schedule_id,
            schedule_digest=schedule.digest(),
            topology_digest=schedule.topology_digest,
            entry_digest=entry.digest(),
            message_id=entry.message_id,
            sender_participant_id=entry.sender_participant_id,
            recipient_participant_ids=entry.recipient_participant_ids,
            sequence=entry.sequence,
            causal_parent_message_ids=entry.causal_parent_message_ids,
            content_digest=content_digest,
        )

    def as_payload(
        self,
        *,
        stage: str,
        receipt: DeliveryReceipt | None = None,
    ) -> JsonObject:
        if stage not in {"dispatch", "delivery"}:
            raise ValueError("participant message fact stage must be dispatch or delivery")
        if stage == "delivery" and not isinstance(receipt, DeliveryReceipt):
            raise TypeError("participant message delivery fact requires DeliveryReceipt")
        if stage == "dispatch" and receipt is not None:
            raise ValueError("participant message dispatch fact cannot carry DeliveryReceipt")
        payload: JsonObject = {
            "fact_type": "participant_message",
            "stage": stage,
            "schedule_id": self.schedule_id,
            "schedule_digest": self.schedule_digest,
            "topology_digest": self.topology_digest,
            "entry_digest": self.entry_digest,
            "message_id": self.message_id,
            "sender_participant_id": self.sender_participant_id,
            "recipient_participant_ids": list(self.recipient_participant_ids),
            "sequence": self.sequence,
            "causal_parent_message_ids": list(self.causal_parent_message_ids),
            "content_digest": self.content_digest,
        }
        if receipt is not None:
            payload.update({
                "delivery_envelope_id": receipt.envelope_id,
                "delivery_envelope_digest": receipt.envelope_digest,
                "delivery_status": receipt.status,
                "delivery_attempt": receipt.attempt,
                "delivery_receipt_digest": receipt.receipt_digest,
            })
        return payload


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
