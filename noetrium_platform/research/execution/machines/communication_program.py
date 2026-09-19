"""Journal-backed multi-participant communication as RuntimeProgram semantics.

Peer presence, generation, inbox ordering and message delivery are research
execution state, not an Agent-specific in-memory manager.  The default program
is intentionally replaceable: downstream papers may replace any rule/handler
with their own communication and logical-scheduling semantics.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from .domains import RuntimeConcern
from .program import ProgramHandlerRegistry, ProgramNodeRequest, ProgramNodeResult, ResearchProgram
from .program_host import ResearchProgramHost
from .rule_program import (
    ProgramRule,
    ProgramRuleSet,
    RuleDispatchMode,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
)


class ParticipantMessageKind(StrEnum):
    CHAT = "chat"
    TASK = "task"
    INTERRUPT = "interrupt"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class CommunicationRuntimeSpec:
    max_participants: int = 64
    max_messages_per_inbox: int = 128

    def __post_init__(self) -> None:
        if type(self.max_participants) is not int or self.max_participants < 1:
            raise ValueError("communication max_participants must be positive")
        if type(self.max_messages_per_inbox) is not int or self.max_messages_per_inbox < 1:
            raise ValueError("communication max_messages_per_inbox must be positive")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "max_participants": self.max_participants,
            "max_messages_per_inbox": self.max_messages_per_inbox,
        })


def communication_initial_data(
    participant_ids: Sequence[str],
    *,
    spec: CommunicationRuntimeSpec = CommunicationRuntimeSpec(),
) -> JsonObject:
    if isinstance(participant_ids, (str, bytes, bytearray)) or not isinstance(participant_ids, Sequence):
        raise TypeError("participant_ids must be a sequence")
    ids = tuple(sorted(participant_ids))
    if not ids or any(type(value) is not str or not value.strip() for value in ids):
        raise ValueError("participant ids must be non-empty text")
    if len(ids) != len(set(ids)):
        raise ValueError("participant ids must be unique")
    if len(ids) > spec.max_participants:
        raise ValueError("participant topology exceeds communication capacity")
    return {
        "communication_spec_digest": spec.digest,
        "max_participants": spec.max_participants,
        "max_messages_per_inbox": spec.max_messages_per_inbox,
        "peers": {
            participant_id: {
                "connected": True,
                "busy": False,
                "generation": 1,
            }
            for participant_id in ids
        },
        "inboxes": {participant_id: () for participant_id in ids},
        "message_sequences": {participant_id: 0 for participant_id in ids},
    }


def communication_rule_set() -> ProgramRuleSet:
    return ProgramRuleSet(
        (
            ProgramRule(
                "participant-register",
                "participant.register",
                "runtime.communication.register",
                semantic=RuntimeConcern.COMMUNICATION.value,
                priority=100,
            ),
            ProgramRule(
                "participant-disconnect",
                "participant.disconnect",
                "runtime.communication.disconnect",
                semantic=RuntimeConcern.COMMUNICATION.value,
                priority=100,
            ),
            ProgramRule(
                "participant-busy",
                "participant.busy",
                "runtime.communication.busy",
                semantic=RuntimeConcern.LOGICAL_SCHEDULING.value,
                priority=100,
            ),
            ProgramRule(
                "message-route",
                "message.route",
                "runtime.communication.route",
                semantic=RuntimeConcern.COMMUNICATION.value,
                priority=100,
            ),
            ProgramRule(
                "message-consume",
                "message.consume",
                "runtime.communication.consume",
                semantic=RuntimeConcern.LOGICAL_SCHEDULING.value,
                priority=100,
            ),
        ),
        mode=RuleDispatchMode.FIRST,
        unhandled=UnhandledEventPolicy.ERROR,
    )


def compile_communication_runtime_program(
    *,
    program_id: str = "runtime.communication.default",
    version: str = "1",
) -> ResearchProgram:
    return compile_rule_program(
        program_id=program_id,
        kind=MachineKind.RUNTIME,
        version=version,
        state_schema="runtime.communication.state.v1",
        rules=communication_rule_set(),
    )


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("communication runtime data must be an object")
    return value


def _event_payload(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.payload)
    if not isinstance(value, dict):
        raise TypeError("communication event payload must be an object")
    return value


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _peers(data: dict[str, object]) -> dict[str, dict[str, object]]:
    value = data.get("peers")
    if not isinstance(value, dict):
        raise TypeError("communication peers must be an object")
    if any(not isinstance(peer, dict) for peer in value.values()):
        raise TypeError("communication peer state must be objects")
    return {str(key): dict(peer) for key, peer in value.items()}


def _inboxes(data: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    value = data.get("inboxes")
    if not isinstance(value, dict):
        raise TypeError("communication inboxes must be an object")
    result: dict[str, list[dict[str, object]]] = {}
    for key, rows in value.items():
        if not isinstance(rows, (tuple, list)) or any(not isinstance(row, dict) for row in rows):
            raise TypeError("communication inbox rows must be object sequences")
        result[str(key)] = [dict(row) for row in rows]
    return result


def _sequences(data: dict[str, object]) -> dict[str, int]:
    value = data.get("message_sequences")
    if not isinstance(value, dict):
        raise TypeError("communication message_sequences must be an object")
    result: dict[str, int] = {}
    for key, sequence in value.items():
        if type(sequence) is not int or sequence < 0:
            raise ValueError("communication message sequence must be non-negative")
        result[str(key)] = sequence
    return result


def _message_digest(message: Mapping[str, JsonValue]) -> str:
    return canonical_digest(dict(message))


def communication_operation_handlers() -> ProgramHandlerRegistry:
    operations = ProgramHandlerRegistry()

    def register(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        participant_id = _text(payload.get("participant_id"), "participant_id")
        peers = _peers(data)
        inboxes = _inboxes(data)
        sequences = _sequences(data)
        max_participants = data.get("max_participants")
        if type(max_participants) is not int or max_participants < 1:
            raise ValueError("communication max_participants is invalid")
        if participant_id not in peers and len(peers) >= max_participants:
            raise ValueError("communication participant capacity exceeded")
        previous = peers.get(participant_id, {"connected": False, "busy": False, "generation": 0})
        generation = previous.get("generation", 0)
        if type(generation) is not int or generation < 0:
            raise ValueError("communication peer generation is invalid")
        peers[participant_id] = {
            "connected": True,
            "busy": bool(previous.get("busy", False)),
            "generation": generation + 1,
        }
        inboxes.setdefault(participant_id, [])
        sequences.setdefault(participant_id, 0)
        return ProgramNodeResult(
            value=peers[participant_id],
            state_update={"peers": peers, "inboxes": inboxes, "message_sequences": sequences},
            events=({"type": "participant_registered", "participant_id": participant_id},),
        )

    def disconnect(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        participant_id = _text(payload.get("participant_id"), "participant_id")
        peers = _peers(data)
        if participant_id not in peers:
            raise ValueError(f"unknown participant: {participant_id}")
        peer = dict(peers[participant_id])
        peer["connected"] = False
        peers[participant_id] = peer
        return ProgramNodeResult(
            value=peer,
            state_update={"peers": peers},
            events=({"type": "participant_disconnected", "participant_id": participant_id},),
        )

    def busy(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        participant_id = _text(payload.get("participant_id"), "participant_id")
        busy_value = payload.get("busy")
        if not isinstance(busy_value, bool):
            raise TypeError("participant busy must be boolean")
        peers = _peers(data)
        if participant_id not in peers:
            raise ValueError(f"unknown participant: {participant_id}")
        peer = dict(peers[participant_id])
        peer["busy"] = busy_value
        peers[participant_id] = peer
        return ProgramNodeResult(
            value=peer,
            state_update={"peers": peers},
            events=({
                "type": "participant_busy_changed",
                "participant_id": participant_id,
                "busy": busy_value,
            },),
        )

    def route(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        sender_id = _text(payload.get("sender_id"), "sender_id")
        recipients_value = payload.get("recipient_ids")
        if not isinstance(recipients_value, (tuple, list)) or not recipients_value:
            raise TypeError("recipient_ids must be a non-empty sequence")
        recipient_ids = tuple(sorted(_text(value, "recipient_id") for value in recipients_value))
        if len(recipient_ids) != len(set(recipient_ids)):
            raise ValueError("recipient_ids must be unique")
        text = _text(payload.get("text"), "message text")
        priority = payload.get("priority", 0)
        if type(priority) is not int or priority < 0:
            raise ValueError("message priority must be non-negative")
        try:
            kind = ParticipantMessageKind(payload.get("kind", ParticipantMessageKind.TASK.value))
        except ValueError as exc:
            raise ValueError("unsupported participant message kind") from exc
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict) or any(
            type(key) is not str or type(value) is not str for key, value in metadata.items()
        ):
            raise TypeError("message metadata must be a string mapping")

        peers = _peers(data)
        all_ids = (sender_id, *recipient_ids)
        missing = tuple(sorted(set(all_ids) - set(peers)))
        if missing:
            raise ValueError(f"message route references unknown participants: {missing}")
        disconnected = tuple(sorted(
            participant_id for participant_id in set(all_ids)
            if peers[participant_id].get("connected") is not True
        ))
        if disconnected:
            raise RuntimeError(f"message route references disconnected participants: {disconnected}")

        inboxes = _inboxes(data)
        sequences = _sequences(data)
        limit = data.get("max_messages_per_inbox")
        if type(limit) is not int or limit < 1:
            raise ValueError("communication inbox limit is invalid")
        receipts: list[dict[str, object]] = []
        for recipient_id in recipient_ids:
            sequence = sequences.get(recipient_id, 0)
            generation = peers[recipient_id].get("generation")
            if type(generation) is not int or generation < 0:
                raise ValueError("recipient generation is invalid")
            message = {
                "message_id": f"participant-message:{recipient_id}:{sequence}",
                "recipient_id": recipient_id,
                "sender_id": sender_id,
                "text": text,
                "sequence": sequence,
                "priority": priority,
                "generation": generation,
                "kind": kind.value,
                "metadata": dict(sorted(metadata.items())),
            }
            message["message_digest"] = _message_digest(message)
            rows = inboxes.setdefault(recipient_id, [])
            rows.append(message)
            rows.sort(key=lambda row: (-int(row["priority"]), int(row["sequence"])))
            inboxes[recipient_id] = rows[:limit]
            sequences[recipient_id] = sequence + 1
            receipts.append({
                "recipient_id": recipient_id,
                "message_id": message["message_id"],
                "message_digest": message["message_digest"],
            })

        return ProgramNodeResult(
            value={"recipient_receipts": tuple(receipts)},
            state_update={"inboxes": inboxes, "message_sequences": sequences},
            events=({
                "type": "participant_message_routed",
                "sender_id": sender_id,
                "recipient_ids": recipient_ids,
                "kind": kind.value,
            },),
        )

    def consume(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        participant_id = _text(payload.get("participant_id"), "participant_id")
        limit = payload.get("limit", 1)
        if type(limit) is not int or limit < 1:
            raise ValueError("message consume limit must be positive")
        sender_filter = payload.get("sender_id")
        if sender_filter is not None:
            sender_filter = _text(sender_filter, "sender_id")
        inboxes = _inboxes(data)
        if participant_id not in inboxes:
            raise ValueError(f"unknown participant inbox: {participant_id}")
        rows = inboxes[participant_id]
        selected: list[dict[str, object]] = []
        remaining: list[dict[str, object]] = []
        for row in rows:
            if len(selected) < limit and (sender_filter is None or row.get("sender_id") == sender_filter):
                selected.append(row)
            else:
                remaining.append(row)
        inboxes[participant_id] = remaining
        return ProgramNodeResult(
            value={"messages": tuple(selected)},
            state_update={"inboxes": inboxes},
            events=({
                "type": "participant_messages_consumed",
                "participant_id": participant_id,
                "count": len(selected),
            },),
        )

    operations.register(
        "runtime.communication.register",
        register,
        implementation_digest=canonical_digest({
            "operation": "runtime.communication.register",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "runtime.communication.disconnect",
        disconnect,
        implementation_digest=canonical_digest({
            "operation": "runtime.communication.disconnect",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "runtime.communication.busy",
        busy,
        implementation_digest=canonical_digest({
            "operation": "runtime.communication.busy",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "runtime.communication.route",
        route,
        implementation_digest=canonical_digest({
            "operation": "runtime.communication.route",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "runtime.communication.consume",
        consume,
        implementation_digest=canonical_digest({
            "operation": "runtime.communication.consume",
            "implementation_revision": 1,
        }),
    )
    return operations


def default_communication_runtime_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    program = compile_communication_runtime_program()
    return ResearchProgramHost(
        host_id="runtime.communication",
        program=program,
        journal=journal,
        snapshot_store=snapshot_store,
        base_handlers=communication_runtime_handlers(),
        dependency_identity={
            "rule_set_digest": communication_rule_set().rule_set_digest,
        },
    )


def communication_runtime_handlers() -> ProgramHandlerRegistry:
    return build_rule_handlers(communication_rule_set(), communication_operation_handlers())


__all__ = [
    "CommunicationRuntimeSpec",
    "ParticipantMessageKind",
    "communication_initial_data",
    "communication_operation_handlers",
    "communication_rule_set",
    "communication_runtime_handlers",
    "default_communication_runtime_host",
    "compile_communication_runtime_program",
]
