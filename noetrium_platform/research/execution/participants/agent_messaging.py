from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.api import (
    ParticipantMessageRecipientReceipt,
    ParticipantMessageRouteReceipt,
    ParticipantMessageRouteRequest,
    ParticipantMessageRouterPort,
)
from noetrium_platform.foundation.kernel.kernel import JsonObject, MachineKind, canonical_digest
from noetrium_platform.research.execution.machines.api import ResearchProgramHostPort
from noetrium_platform.research.execution.machines.api import MachineEvent


class RuntimeParticipantMessageRouter(ParticipantMessageRouterPort):
    """Machine-backed execution adapter for Participant messaging contracts."""

    def __init__(
        self,
        host: ResearchProgramHostPort,
        *,
        machine_id: str,
        initial_data: JsonObject,
    ) -> None:
        if not isinstance(host, ResearchProgramHostPort):
            raise TypeError("participant message router requires ResearchProgramHostPort")
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
            self._session.start(dict(initial_data), command_id="participant-communication:start")

    @property
    def session(self):
        return self._session

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
        receipts = tuple(
            ParticipantMessageRecipientReceipt(
                recipient_participant_id=str(row["recipient_id"]),
                runtime_message_id=str(row["message_id"]),
                runtime_message_digest=str(row["message_digest"]),
            )
            for row in rows
            if isinstance(row, Mapping)
        )
        if len(receipts) != len(rows):
            raise TypeError("participant communication receipt row must be an object")
        return ParticipantMessageRouteReceipt(
            schedule_digest=binding.schedule_digest,
            entry_digest=binding.entry_digest,
            message_id=binding.message_id,
            recipient_receipts=receipts,
        )


__all__ = ["RuntimeParticipantMessageRouter"]
