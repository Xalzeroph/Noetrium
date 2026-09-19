"""Agent-turn semantics expressed as a Participant ResearchProgram.

This is not a separate VM. It is one reusable ParticipantProgram proving that
agent-specific turn semantics can live entirely above the universal
programmable Machine ABI.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
)
from .domains import ParticipantConcern, ParticipantProgramBuilder
from .program_host import ResearchProgramHost
from .program import (
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchProgram,
    core_program_handlers,
)

PARTICIPANT_TURN_FACT_WIRE_SCHEMA = "agent-turn-fact.v1"
PARTICIPANT_TURN_FACT_KINDS = frozenset({
    "planning_input", "model_request", "model_response", "decision",
    "action", "observation", "effect", "termination",
})
_FACT_FIELDS = frozenset({
    "schema_version", "session_id", "sequence", "kind", "run_id", "trace_id",
    "span_id", "task_id", "decision_cycle_id", "payload", "artifact_refs",
    "previous_fact_digest", "fact_digest",
})


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def _nonnegative(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _optional_digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _fact(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or frozenset(value) != _FACT_FIELDS:
        raise ValueError("participant turn fact fields mismatch")
    if value["schema_version"] != PARTICIPANT_TURN_FACT_WIRE_SCHEMA:
        raise ValueError("unsupported participant turn fact schema")
    _text(value["session_id"], "participant turn fact session_id")
    sequence = _nonnegative(value["sequence"], "participant turn fact sequence")
    if sequence == 0:
        raise ValueError("participant turn fact sequence must be positive")
    kind = _text(value["kind"], "participant turn fact kind")
    if kind not in PARTICIPANT_TURN_FACT_KINDS:
        raise ValueError("unsupported participant turn fact kind")
    for field in ("run_id", "trace_id", "span_id"):
        _text(value[field], f"participant turn fact {field}")
    for field in ("task_id", "decision_cycle_id"):
        item = value[field]
        if item is not None:
            _text(item, f"participant turn fact {field}")
    if not isinstance(value["payload"], dict):
        raise ValueError("participant turn fact payload must be an object")
    refs = value["artifact_refs"]
    if isinstance(refs, (str, bytes, bytearray)) or not isinstance(refs, Sequence):
        raise ValueError("participant turn fact artifact_refs must be a sequence")
    if any(type(ref) is not str or not ref.strip() for ref in refs):
        raise ValueError("participant turn fact artifact_refs must contain non-empty text")
    previous = _optional_digest(value["previous_fact_digest"], "previous_fact_digest")
    if sequence == 1 and previous is not None:
        raise ValueError("first participant turn fact cannot have a previous digest")
    if sequence > 1 and previous is None:
        raise ValueError("non-initial participant turn fact requires previous digest")
    supplied = _optional_digest(value["fact_digest"], "fact_digest")
    expected = canonical_digest({key: item for key, item in value.items() if key != "fact_digest"})
    if supplied != expected:
        raise ValueError("participant turn fact digest mismatch")
    return value


def participant_turn_program() -> ResearchProgram:
    return (
        ParticipantProgramBuilder.create(
            program_id="participant.turn",
            version="2",
            state_schema="participant.turn.state.v2",
            entrypoint="turn",
        )
        .semantic(
            "turn",
            ParticipantConcern.TURN,
            "participant.turn",
        )
        .build()
    )


def participant_turn_handlers() -> ProgramHandlerRegistry:
    registry = core_program_handlers()

    def turn(request: ProgramNodeRequest) -> ProgramNodeResult:
        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TypeError("participant turn payload must be an object")
        action = _text(payload.get("action"), "participant turn action")
        turn_id = _text(request.data.get("turn_id"), "turn_id")
        session_id = _text(request.data.get("session_id"), "session_id")
        if request.data.get("status") != "active":
            raise ValueError("participant turn requires active status")

        if action == "record_fact":
            fact_value = payload.get("fact")
            if not isinstance(fact_value, dict):
                raise TypeError("record_fact requires a fact object")
            fact = _fact(fact_value)
            if fact["session_id"] != session_id:
                raise ValueError("participant turn fact session mismatch")
            expected = _nonnegative(request.data.get("fact_count", 0), "fact_count") + 1
            if fact["sequence"] != expected:
                raise ValueError("participant turn fact sequence is not contiguous")
            if fact["previous_fact_digest"] != request.data.get("fact_head_digest"):
                raise ValueError("participant turn fact previous digest does not match head")
            return ProgramNodeResult(
                value={"fact_digest": fact["fact_digest"], "sequence": expected},
                state_update={
                    "fact_count": expected,
                    "fact_head_digest": fact["fact_digest"],
                    "last_fact_kind": fact["kind"],
                },
                status=MachineStatus.RUNNABLE,
                events=({"type": "agent_turn_fact", "turn_id": turn_id, "fact": fact},),
            )

        if action == "finish":
            if request.data.get("last_fact_kind") != "termination":
                raise ValueError("participant turn cannot finish before a termination fact")
            head = _optional_digest(payload.get("fact_head_digest"), "fact_head_digest")
            if head != request.data.get("fact_head_digest"):
                raise ValueError("participant turn finish fact head mismatch")
            termination = _text(payload.get("termination"), "termination")
            success = payload.get("success")
            if not isinstance(success, bool):
                raise ValueError("participant turn finish success must be boolean")
            return ProgramNodeResult(
                value={"success": success, "termination": termination},
                state_update={
                    "status": "completed" if success else "failed",
                    "termination": termination,
                },
                status=MachineStatus.COMPLETED if success else MachineStatus.FAILED,
                events=({
                    "type": "agent_turn_finished", "turn_id": turn_id,
                    "success": success, "termination": termination,
                    "fact_count": request.data.get("fact_count", 0),
                    "fact_head_digest": head,
                },),
            )

        raise ValueError(f"unsupported participant turn action: {action}")

    registry.register(
        "participant.turn",
        turn,
        implementation_digest=canonical_digest({
            "operation": "participant.turn",
            "implementation_revision": 1,
        }),
    )
    return registry


def participant_turn_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    program = participant_turn_program()
    return ResearchProgramHost(
        host_id="participant.turn",
        program=program,
        journal=journal,
        snapshot_store=snapshot_store,
        base_handlers=participant_turn_handlers(),
        dependency_identity={
            "fact_wire_schema": PARTICIPANT_TURN_FACT_WIRE_SCHEMA,
            "fact_kinds": tuple(sorted(PARTICIPANT_TURN_FACT_KINDS)),
        },
    )


def participant_turn_initial_data(*, turn_id: str, session_id: str,
                                  goal_digest: str | None = None) -> JsonObject:
    return {
        "turn_id": _text(turn_id, "turn_id"),
        "session_id": _text(session_id, "session_id"),
        "status": "active",
        "goal_digest": _optional_digest(goal_digest, "goal_digest"),
        "fact_count": 0,
        "fact_head_digest": None,
        "last_fact_kind": None,
        "termination": None,
    }


__all__ = [
    "PARTICIPANT_TURN_FACT_KINDS",
    "PARTICIPANT_TURN_FACT_WIRE_SCHEMA",
    "participant_turn_handlers",
    "participant_turn_host",
    "participant_turn_initial_data",
    "participant_turn_program",
]
