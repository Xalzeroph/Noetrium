from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from .topology import (
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
)
from noetrium_platform.foundation.kernel.kernel import DeliveryReceipt, JsonObject, canonical_digest, require_sha256


PARTICIPANT_MESSAGE_ROUTE_SCHEMA = "participant-message-route.v3"


class ParticipantMessageKind(StrEnum):
    CHAT = "chat"
    TASK = "task"
    INTERRUPT = "interrupt"
    SYSTEM = "system"


def participant_message_content_digest(
    text: str,
    *,
    priority: int,
    kind: ParticipantMessageKind,
) -> str:
    stripped = text.strip()
    if not stripped:
        raise ValueError("participant message text is required")
    if type(priority) is not int or priority < 0:
        raise ValueError("participant message priority must be non-negative")
    if not isinstance(kind, ParticipantMessageKind):
        raise TypeError("participant message kind must be ParticipantMessageKind")
    return canonical_digest({
        "text": stripped,
        "priority": priority,
        "kind": kind.value,
    })


@dataclass(frozen=True, slots=True)
class ParticipantMessageFactBinding:
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
        recipients = self.recipient_participant_ids
        if not isinstance(recipients, tuple) or not recipients:
            raise TypeError("participant message recipients must be a non-empty tuple")
        if any(type(value) is not str or not value.strip() for value in recipients):
            raise ValueError("participant message recipients must be non-empty text")
        if len(recipients) != len(set(recipients)) or tuple(sorted(recipients)) != recipients:
            raise ValueError("participant message recipients must be unique canonical-sorted")
        parents = self.causal_parent_message_ids
        if not isinstance(parents, tuple):
            raise TypeError("participant message causal parents must be a tuple")
        if any(type(value) is not str or not value.strip() for value in parents):
            raise ValueError("participant message causal parents must be non-empty text")
        if len(parents) != len(set(parents)) or tuple(sorted(parents)) != parents:
            raise ValueError("participant message causal parents must be unique canonical-sorted")
        if self.message_id in parents:
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

    def identity_payload(self) -> dict[str, object]:
        return {
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
        payload: JsonObject = {"fact_type": "participant_message", "stage": stage, **self.identity_payload()}
        if receipt is not None:
            payload.update({
                "delivery_envelope_id": receipt.envelope_id,
                "delivery_envelope_digest": receipt.envelope_digest,
                "delivery_status": receipt.status,
                "delivery_attempt": receipt.attempt,
                "delivery_receipt_digest": receipt.receipt_digest,
            })
        return payload


@dataclass(frozen=True, slots=True)
class ParticipantMessageRouteRequest:
    binding: ParticipantMessageFactBinding
    text: str
    priority: int = 0
    kind: ParticipantMessageKind = ParticipantMessageKind.TASK
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
        if not isinstance(self.kind, ParticipantMessageKind):
            raise TypeError("participant message route kind must be ParticipantMessageKind")
        if self.binding.content_digest != participant_message_content_digest(
            stripped, priority=self.priority, kind=self.kind
        ):
            raise ValueError("participant message route content digest does not match request")

    @classmethod
    def from_schedule(
        cls,
        schedule: ParticipantMessageSchedule,
        entry: ParticipantMessageScheduleEntry,
        text: str,
        *,
        priority: int = 0,
        kind: ParticipantMessageKind = ParticipantMessageKind.TASK,
    ) -> "ParticipantMessageRouteRequest":
        digest = participant_message_content_digest(text, priority=priority, kind=kind)
        return cls(
            binding=ParticipantMessageFactBinding.from_schedule(
                schedule, entry, content_digest=digest
            ),
            text=text,
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
        recipients = tuple(row.recipient_participant_id for row in self.recipient_receipts)
        if len(recipients) != len(set(recipients)) or tuple(sorted(recipients)) != recipients:
            raise ValueError("participant route recipient receipts must be unique canonical-sorted")
        object.__setattr__(self, "receipt_digest", canonical_digest(self.as_payload(False)))

    def as_payload(self, include_digest: bool = True) -> dict[str, object]:
        payload = {
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


__all__ = [
    "PARTICIPANT_MESSAGE_ROUTE_SCHEMA",
    "ParticipantMessageFactBinding",
    "ParticipantMessageKind",
    "ParticipantMessageRecipientReceipt",
    "ParticipantMessageRouteReceipt",
    "ParticipantMessageRouteRequest",
    "ParticipantMessageRouterPort",
    "participant_message_content_digest",
]
