from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.capabilities.participant.api import (
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    MachineKind,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.execution.machines.communication_program import (
    ParticipantMessageKind,
)
from noetrium_platform.research.execution.machines.program_host import ResearchProgramHost
from noetrium_platform.research.execution.machines.rule_program import MachineEvent

from .participant_message_facts import ParticipantMessageFactBinding


PARTICIPANT_MESSAGE_ROUTE_SCHEMA = "participant-message-route.v2"


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
        kind: ParticipantMessageKind = ParticipantMessageKind.TASK,
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
    @property
    def session(self):
        return self._session

    def route(self, request: ParticipantMessageRouteRequest) -> ParticipantMessageRouteReceipt: ...


class RuntimeParticipantMessageRouter(ParticipantMessageRouterPort):
    """Thin adapter from participant message intent to a RuntimeProgram event.

    The router owns no peer, inbox, checkpoint or delivery state. Those facts
    are committed by the bound Runtime Machine.
    """

    def __init__(
        self,
        host: ResearchProgramHost,
        *,
        machine_id: str,
        initial_data: JsonObject,
    ) -> None:
        if not isinstance(host, ResearchProgramHost):
            raise TypeError("participant message router requires ResearchProgramHost")
        if host.program.kind is not MachineKind.RUNTIME:
            raise ValueError("participant message router requires a RUNTIME Program host")
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("participant message router machine_id is required")
        if not isinstance(initial_data, Mapping):
            raise TypeError("participant message initial_data must be an object")
        self._session = host.open_session(
            machine_id=machine_id.strip(),
            instance_identity={
                "machine_id": machine_id.strip(),
                "initial_data_digest": canonical_digest(initial_data),
            },
            binding=None,
        )
        if not self._session.started:
            self._session.start(
                dict(initial_data),
                command_id="participant-communication:start",
            )
        elif not isinstance(self._session.data, dict):
            raise ValueError("participant communication machine data is invalid")

    def route(self, request: ParticipantMessageRouteRequest) -> ParticipantMessageRouteReceipt:
        if not isinstance(request, ParticipantMessageRouteRequest):
            raise TypeError("participant message route request must be typed")
        binding = request.binding
        event = MachineEvent(
            "message.route",
            {
                "sender_id": binding.sender_participant_id,
                "recipient_ids": binding.recipient_participant_ids,
                "text": request.text,
                "priority": request.priority,
                "kind": request.kind.value,
                "metadata": {
                    "schedule_digest": binding.schedule_digest,
                    "entry_digest": binding.entry_digest,
                    "message_id": binding.message_id,
                },
            },
            source=binding.sender_participant_id,
        )
        self._session.step(
            {"event": event.as_payload()},
            command_id=f"participant-message:{binding.entry_digest}:{binding.content_digest}",
        )
        value = self._session.previous_value
        if not isinstance(value, Mapping):
            raise ValueError("participant communication route result is missing")
        rows = value.get("recipient_receipts")
        if not isinstance(rows, (tuple, list)) or not rows:
            raise ValueError("participant communication route emitted no receipts")
        receipts: list[ParticipantMessageRecipientReceipt] = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("participant communication receipt row must be an object")
            receipts.append(ParticipantMessageRecipientReceipt(
                recipient_participant_id=str(row["recipient_id"]),
                runtime_message_id=str(row["message_id"]),
                runtime_message_digest=str(row["message_digest"]),
            ))
        return ParticipantMessageRouteReceipt(
            schedule_digest=binding.schedule_digest,
            entry_digest=binding.entry_digest,
            message_id=binding.message_id,
            recipient_receipts=tuple(receipts),
        )


__all__ = [
    "PARTICIPANT_MESSAGE_ROUTE_SCHEMA",
    "ParticipantMessageKind",
    "ParticipantMessageRecipientReceipt",
    "ParticipantMessageRouteReceipt",
    "ParticipantMessageRouteRequest",
    "ParticipantMessageRouterPort",
    "RuntimeParticipantMessageRouter",
    "participant_message_content_digest",
]
