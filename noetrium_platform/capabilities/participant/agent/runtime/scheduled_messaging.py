from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.capabilities.participant.api import (
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256

from .conversation import ConversationKind, ConversationMessage
from .coordination import AgentCoordinationHub
from .participant_message_facts import ParticipantMessageFactBinding


PARTICIPANT_MESSAGE_ROUTE_SCHEMA = "participant-message-route.v1"


def participant_message_content_digest(
    text: str,
    *,
    priority: int,
    kind: ConversationKind,
) -> str:
    stripped = text.strip()
    if not stripped:
        raise ValueError("participant message text is required")
    if type(priority) is not int or priority < 0:
        raise ValueError("participant message priority must be non-negative")
    if not isinstance(kind, ConversationKind):
        raise TypeError("participant message kind must be ConversationKind")
    return canonical_digest({
        "text": stripped,
        "priority": priority,
        "kind": kind.value,
    })


def _conversation_message_digest(message: ConversationMessage) -> str:
    return canonical_digest({
        "message_id": message.message_id,
        "peer_id": message.peer_id,
        "sender_id": message.sender_id,
        "text": message.text,
        "turn": message.turn,
        "metadata": dict(message.metadata),
        "priority": message.priority,
        "generation": message.generation,
        "kind": message.kind.value,
    })


@dataclass(frozen=True, slots=True)
class ParticipantMessageRouteRequest:
    binding: ParticipantMessageFactBinding
    text: str
    priority: int = 0
    kind: ConversationKind = ConversationKind.TASK
    schema_version: str = PARTICIPANT_MESSAGE_ROUTE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PARTICIPANT_MESSAGE_ROUTE_SCHEMA:
            raise ValueError("unsupported participant message route schema")
        if not isinstance(self.binding, ParticipantMessageFactBinding):
            raise TypeError("participant message route binding must be typed")
        stripped = self.text.strip()
        if not stripped:
            raise ValueError("participant message route text is required")
        object.__setattr__(self, "text", stripped)
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("participant message route priority must be non-negative")
        if not isinstance(self.kind, ConversationKind):
            raise TypeError("participant message route kind must be ConversationKind")
        expected = participant_message_content_digest(
            stripped,
            priority=self.priority,
            kind=self.kind,
        )
        if self.binding.content_digest != expected:
            raise ValueError("participant message route content digest does not match request")

    @classmethod
    def from_schedule(
        cls,
        schedule: ParticipantMessageSchedule,
        entry: ParticipantMessageScheduleEntry,
        text: str,
        *,
        priority: int = 0,
        kind: ConversationKind = ConversationKind.TASK,
    ) -> "ParticipantMessageRouteRequest":
        stripped = text.strip()
        digest = participant_message_content_digest(
            stripped,
            priority=priority,
            kind=kind,
        )
        return cls(
            binding=ParticipantMessageFactBinding.from_schedule(
                schedule,
                entry,
                content_digest=digest,
            ),
            text=stripped,
            priority=priority,
            kind=kind,
        )


@dataclass(frozen=True, slots=True)
class ParticipantMessageRecipientReceipt:
    recipient_participant_id: str
    runtime_message_id: str
    runtime_message_digest: str

    def __post_init__(self) -> None:
        if not self.recipient_participant_id.strip() or not self.runtime_message_id.strip():
            raise ValueError("participant route recipient identity is required")
        require_sha256(self.runtime_message_digest, "participant route runtime_message_digest")


@dataclass(frozen=True, slots=True)
class ParticipantMessageRouteReceipt:
    schedule_digest: str
    entry_digest: str
    message_id: str
    recipient_receipts: tuple[ParticipantMessageRecipientReceipt, ...]
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.schedule_digest, "participant route schedule_digest")
        require_sha256(self.entry_digest, "participant route entry_digest")
        if not self.message_id.strip():
            raise ValueError("participant route message_id is required")
        if not isinstance(self.recipient_receipts, tuple) or not self.recipient_receipts:
            raise TypeError("participant route recipient receipts must be a non-empty tuple")
        if any(not isinstance(row, ParticipantMessageRecipientReceipt) for row in self.recipient_receipts):
            raise TypeError("participant route recipient receipts must be typed")
        recipients = tuple(row.recipient_participant_id for row in self.recipient_receipts)
        if len(recipients) != len(set(recipients)):
            raise ValueError("participant route recipient receipts must be unique")
        if tuple(sorted(recipients)) != recipients:
            raise ValueError("participant route recipient receipts must be canonical-sorted")
        object.__setattr__(self, "receipt_digest", canonical_digest(self.as_payload(include_digest=False)))

    def as_payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schedule_digest": self.schedule_digest,
            "entry_digest": self.entry_digest,
            "message_id": self.message_id,
            "recipient_receipts": [
                {
                    "recipient_participant_id": row.recipient_participant_id,
                    "runtime_message_id": row.runtime_message_id,
                    "runtime_message_digest": row.runtime_message_digest,
                }
                for row in self.recipient_receipts
            ],
        }
        if include_digest:
            payload["receipt_digest"] = self.receipt_digest
        return payload

    def as_fact_payload(self, binding: ParticipantMessageFactBinding) -> dict[str, object]:
        if not isinstance(binding, ParticipantMessageFactBinding):
            raise TypeError("participant route fact binding must be typed")
        if self.schedule_digest != binding.schedule_digest:
            raise ValueError("participant route receipt schedule identity mismatch")
        if self.entry_digest != binding.entry_digest or self.message_id != binding.message_id:
            raise ValueError("participant route receipt message identity mismatch")
        return {
            **binding.as_payload(stage="dispatch"),
            "stage": "routed",
            "route_receipt": self.as_payload(),
        }


class ParticipantMessageRouterPort(Protocol):
    def route(self, request: ParticipantMessageRouteRequest) -> ParticipantMessageRouteReceipt: ...


class InProcessParticipantMessageRouter(ParticipantMessageRouterPort):
    """Deterministic provider over AgentCoordinationHub; owns no durable truth."""

    def __init__(self, hub: AgentCoordinationHub) -> None:
        if not isinstance(hub, AgentCoordinationHub):
            raise TypeError("participant message router requires AgentCoordinationHub")
        self._hub = hub

    def route(self, request: ParticipantMessageRouteRequest) -> ParticipantMessageRouteReceipt:
        if not isinstance(request, ParticipantMessageRouteRequest):
            raise TypeError("participant message route request must be typed")
        binding = request.binding
        statuses = {status.agent_id: status for status in self._hub.status()}
        participant_ids = (binding.sender_participant_id, *binding.recipient_participant_ids)
        missing = tuple(sorted(set(participant_ids) - set(statuses)))
        if missing:
            raise ValueError(f"participant route references unregistered peers: {missing}")
        disconnected = tuple(sorted(
            participant_id for participant_id in set(participant_ids)
            if not statuses[participant_id].connected
        ))
        if disconnected:
            raise RuntimeError(f"participant route references disconnected peers: {disconnected}")

        receipts: list[ParticipantMessageRecipientReceipt] = []
        for recipient_id in binding.recipient_participant_ids:
            message = self._hub.send(
                binding.sender_participant_id,
                recipient_id,
                request.text,
                priority=request.priority,
                kind=request.kind,
            )
            receipts.append(ParticipantMessageRecipientReceipt(
                recipient_participant_id=recipient_id,
                runtime_message_id=message.message_id,
                runtime_message_digest=_conversation_message_digest(message),
            ))
        return ParticipantMessageRouteReceipt(
            schedule_digest=binding.schedule_digest,
            entry_digest=binding.entry_digest,
            message_id=binding.message_id,
            recipient_receipts=tuple(receipts),
        )


__all__ = [
    "PARTICIPANT_MESSAGE_ROUTE_SCHEMA",
    "InProcessParticipantMessageRouter",
    "ParticipantMessageRecipientReceipt",
    "ParticipantMessageRouteReceipt",
    "ParticipantMessageRouteRequest",
    "ParticipantMessageRouterPort",
    "participant_message_content_digest",
]
