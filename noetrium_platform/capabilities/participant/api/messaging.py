from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import (
    DeliveryReceipt,
    JsonObject,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    endpoint_child_id,
    relation_id,
)
from .topology_semantics import (
    PARTICIPANT_COMMUNICATION_RELATION,
    validate_participant_graph,
)


PARTICIPANT_MESSAGE_ROUTE_SCHEMA = "participant-message-route.v4"


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
    return canonical_digest(
        {"text": stripped, "priority": priority, "kind": kind.value}
    )


@dataclass(frozen=True, slots=True)
class ParticipantMessageFactBinding:
    topology_digest: str
    relation_digest: str
    message_id: str
    sender_participant_id: str
    recipient_participant_ids: tuple[str, ...]
    sequence: int
    causal_parent_message_ids: tuple[str, ...]
    content_digest: str

    def __post_init__(self) -> None:
        require_sha256(self.topology_digest, "participant message topology_digest")
        require_sha256(self.relation_digest, "participant message relation_digest")
        require_sha256(self.content_digest, "participant message content_digest")
        for name, value in (
            ("message_id", self.message_id),
            ("sender_participant_id", self.sender_participant_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"participant message {name} is required")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("participant message sequence must be non-negative")
        recipients = self.recipient_participant_ids
        if type(recipients) is not tuple or not recipients:
            raise TypeError("participant message recipients must be non-empty tuple")
        if any(type(value) is not str or not value.strip() for value in recipients):
            raise ValueError("participant message recipients must be non-empty text")
        if len(recipients) != len(set(recipients)) or tuple(sorted(recipients)) != recipients:
            raise ValueError("participant message recipients must be unique sorted")
        parents = self.causal_parent_message_ids
        if type(parents) is not tuple:
            raise TypeError("participant message causal parents must be tuple")
        if any(type(value) is not str or not value.strip() for value in parents):
            raise ValueError("participant message causal parents must be non-empty text")
        if len(parents) != len(set(parents)) or tuple(sorted(parents)) != parents:
            raise ValueError("participant message causal parents must be unique sorted")
        if self.message_id in parents:
            raise ValueError("participant message cannot causally depend on itself")

    @classmethod
    def from_relation(
        cls,
        topology: NoetriumUnit,
        relation: NoetriumUnit,
        *,
        message_id: str,
        sender_participant_id: str,
        recipient_participant_ids: tuple[str, ...],
        sequence: int,
        causal_parent_message_ids: tuple[str, ...] = (),
        content_digest: str,
    ) -> "ParticipantMessageFactBinding":
        roles = frozenset(validate_participant_graph(topology))
        if type(relation) is not NoetriumUnit:
            raise TypeError("participant communication relation must be Unit")
        if relation not in topology.relations:
            raise ValueError("participant communication relation is not in topology")
        if relation_id(relation) != PARTICIPANT_COMMUNICATION_RELATION:
            raise ValueError("message binding requires communication relation Unit")
        sources = frozenset(
            endpoint_child_id(endpoint)
            for endpoint in relation.units("source")
        )
        targets = frozenset(
            endpoint_child_id(endpoint)
            for endpoint in relation.units("target")
        )
        if sender_participant_id not in sources:
            raise ValueError("message sender is not allowed by communication relation")
        recipients = tuple(sorted(recipient_participant_ids))
        if not recipients or any(recipient not in targets for recipient in recipients):
            raise ValueError("message recipients are not allowed by communication relation")
        if sender_participant_id not in roles or any(row not in roles for row in recipients):
            raise ValueError("message participants are not members of topology")
        return cls(
            topology_digest=topology.unit_digest,
            relation_digest=relation.unit_digest,
            message_id=message_id,
            sender_participant_id=sender_participant_id,
            recipient_participant_ids=recipients,
            sequence=sequence,
            causal_parent_message_ids=tuple(sorted(causal_parent_message_ids)),
            content_digest=content_digest,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "topology_digest": self.topology_digest,
            "relation_digest": self.relation_digest,
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
        payload: JsonObject = {
            "fact_type": "participant_message",
            "stage": stage,
            **self.identity_payload(),
        }
        if receipt is not None:
            payload.update(
                {
                    "delivery_envelope_id": receipt.envelope_id,
                    "delivery_envelope_digest": receipt.envelope_digest,
                    "delivery_status": receipt.status,
                    "delivery_attempt": receipt.attempt,
                    "delivery_receipt_digest": receipt.receipt_digest,
                }
            )
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
            stripped,
            priority=self.priority,
            kind=self.kind,
        ):
            raise ValueError("participant message route content digest does not match request")

    @classmethod
    def from_relation(
        cls,
        topology: NoetriumUnit,
        relation: NoetriumUnit,
        text: str,
        *,
        message_id: str,
        sender_participant_id: str,
        recipient_participant_ids: tuple[str, ...],
        sequence: int,
        causal_parent_message_ids: tuple[str, ...] = (),
        priority: int = 0,
        kind: ParticipantMessageKind = ParticipantMessageKind.TASK,
    ) -> "ParticipantMessageRouteRequest":
        digest = participant_message_content_digest(
            text,
            priority=priority,
            kind=kind,
        )
        return cls(
            binding=ParticipantMessageFactBinding.from_relation(
                topology,
                relation,
                message_id=message_id,
                sender_participant_id=sender_participant_id,
                recipient_participant_ids=recipient_participant_ids,
                sequence=sequence,
                causal_parent_message_ids=causal_parent_message_ids,
                content_digest=digest,
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
        require_sha256(
            self.runtime_message_digest,
            "participant route runtime_message_digest",
        )


@dataclass(frozen=True, slots=True)
class ParticipantMessageRouteReceipt:
    topology_digest: str
    relation_digest: str
    message_id: str
    recipient_receipts: tuple[ParticipantMessageRecipientReceipt, ...]
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.topology_digest, "participant route topology_digest")
        require_sha256(self.relation_digest, "participant route relation_digest")
        if not self.message_id.strip():
            raise ValueError("participant route message_id is required")
        if type(self.recipient_receipts) is not tuple or not self.recipient_receipts:
            raise TypeError("participant route recipient receipts must be non-empty tuple")
        recipients = tuple(row.recipient_participant_id for row in self.recipient_receipts)
        if len(recipients) != len(set(recipients)) or tuple(sorted(recipients)) != recipients:
            raise ValueError("participant route recipient receipts must be unique sorted")
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(self.as_payload(False)),
        )

    def as_payload(self, include_digest: bool = True) -> dict[str, object]:
        payload = {
            "topology_digest": self.topology_digest,
            "relation_digest": self.relation_digest,
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

    def as_fact_payload(
        self,
        binding: ParticipantMessageFactBinding,
    ) -> dict[str, object]:
        if not isinstance(binding, ParticipantMessageFactBinding):
            raise TypeError("participant route fact binding must be typed")
        if self.topology_digest != binding.topology_digest:
            raise ValueError("participant route receipt topology identity mismatch")
        if self.relation_digest != binding.relation_digest or self.message_id != binding.message_id:
            raise ValueError("participant route receipt relation/message identity mismatch")
        return {
            **binding.as_payload(stage="dispatch"),
            "stage": "routed",
            "route_receipt": self.as_payload(),
        }


class ParticipantMessageRouterPort(Protocol):
    def route(
        self,
        request: ParticipantMessageRouteRequest,
    ) -> ParticipantMessageRouteReceipt: ...


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
