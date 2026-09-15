"""Research OS Agent Turn Machine domain semantics.

The interpreter owns only Agent Turn state transitions. It never writes a
journal and never calls a provider. MachineRuntime remains the sole commit
authority; full turn facts live in Journal event payloads while Machine state
retains only the bounded recovery cursor and terminal summary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import (
    MachineFamilyDescriptor,
    MachineKind,
    MachineSnapshot,
    TransitionProposal,
    canonical_digest,
    thaw_json,
)


AGENT_TURN_MACHINE_FAMILY_ID = "agent.turn.v2"
AGENT_TURN_MACHINE_STATE_SCHEMA = "agent.turn.state.v2"
AGENT_TURN_FACT_WIRE_SCHEMA = "agent-turn-fact.v1"
AGENT_TURN_FACT_KINDS = frozenset({
    "planning_input",
    "model_request",
    "model_response",
    "decision",
    "action",
    "observation",
    "effect",
    "termination",
})
_AGENT_FACT_FIELDS = frozenset({
    "schema_version",
    "session_id",
    "sequence",
    "kind",
    "run_id",
    "trace_id",
    "span_id",
    "task_id",
    "decision_cycle_id",
    "payload",
    "artifact_refs",
    "previous_fact_digest",
    "fact_digest",
})


def _payload(command: object) -> dict[str, object]:
    value = thaw_json(command.payload)
    if not isinstance(value, dict):
        raise ValueError(f"{command.kind} payload must be an object")
    return value


def _state(snapshot: MachineSnapshot) -> dict[str, object]:
    value = thaw_json(snapshot.state)
    if not isinstance(value, dict):
        raise ValueError("agent turn machine state must be an object")
    return value


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
    if not isinstance(value, dict) or frozenset(value) != _AGENT_FACT_FIELDS:
        raise ValueError("agent turn fact fields mismatch")
    if value["schema_version"] != AGENT_TURN_FACT_WIRE_SCHEMA:
        raise ValueError("unsupported agent turn fact schema")
    _text(value["session_id"], "agent turn fact session_id")
    sequence = _nonnegative(value["sequence"], "agent turn fact sequence")
    if sequence == 0:
        raise ValueError("agent turn fact sequence must be positive")
    kind = _text(value["kind"], "agent turn fact kind")
    if kind not in AGENT_TURN_FACT_KINDS:
        raise ValueError("unsupported agent turn fact kind")
    for field in ("run_id", "trace_id", "span_id"):
        _text(value[field], f"agent turn fact {field}")
    for field in ("task_id", "decision_cycle_id"):
        item = value[field]
        if item is not None:
            _text(item, f"agent turn fact {field}")
    if not isinstance(value["payload"], dict):
        raise ValueError("agent turn fact payload must be an object")
    refs = value["artifact_refs"]
    if isinstance(refs, (str, bytes, bytearray)) or not isinstance(refs, Sequence):
        raise ValueError("agent turn fact artifact_refs must be a sequence")
    if any(type(ref) is not str or not ref.strip() for ref in refs):
        raise ValueError("agent turn fact artifact_refs must contain non-empty text")
    if len(refs) != len(set(refs)):
        raise ValueError("agent turn fact artifact_refs must be unique")
    previous = _optional_digest(value["previous_fact_digest"], "previous_fact_digest")
    if sequence == 1 and previous is not None:
        raise ValueError("first agent turn fact cannot have a previous digest")
    if sequence > 1 and previous is None:
        raise ValueError("non-initial agent turn fact requires previous digest")
    supplied = _optional_digest(value["fact_digest"], "fact_digest")
    document = {key: item for key, item in value.items() if key != "fact_digest"}
    expected = canonical_digest(document)
    if supplied != expected:
        raise ValueError("agent turn fact digest mismatch")
    return value


class AgentTurnMachineInterpreter:
    """Bounded Agent Turn VM with Journal-owned ordered facts."""

    def propose(self, command: object, state: MachineSnapshot) -> TransitionProposal:
        payload = _payload(command)
        current = _state(state)
        if command.kind == "agent.turn.begin":
            if current.get("status") not in (None, "new"):
                raise ValueError("agent turn has already begun")
            turn_id = _text(payload.get("turn_id"), "turn_id")
            session_id = _text(payload.get("session_id"), "session_id")
            goal_digest = _optional_digest(payload.get("goal_digest"), "goal_digest")
            delta = {
                "turn_id": turn_id,
                "session_id": session_id,
                "status": "active",
                "goal_digest": goal_digest,
                "fact_count": 0,
                "fact_head_digest": None,
                "last_fact_kind": None,
                "termination": None,
            }
            event = {
                "type": "agent_turn_started",
                "turn_id": turn_id,
                "session_id": session_id,
                "goal_digest": goal_digest,
            }
            return self._proposal(command, state, delta, event)

        if current.get("status") != "active":
            raise ValueError("agent turn command requires active turn")
        turn_id = _text(payload.get("turn_id"), "turn_id")
        if turn_id != current.get("turn_id"):
            raise ValueError("agent turn command turn_id mismatch")

        if command.kind == "agent.fact.record":
            fact = _fact(payload.get("fact"))
            if fact["session_id"] != current.get("session_id"):
                raise ValueError("agent turn fact session mismatch")
            expected_sequence = _nonnegative(current.get("fact_count", 0), "fact_count") + 1
            if fact["sequence"] != expected_sequence:
                raise ValueError("agent turn fact sequence is not contiguous")
            if fact["previous_fact_digest"] != current.get("fact_head_digest"):
                raise ValueError("agent turn fact previous digest does not match machine head")
            delta = {
                "fact_count": expected_sequence,
                "fact_head_digest": fact["fact_digest"],
                "last_fact_kind": fact["kind"],
            }
            event = {
                "type": "agent_turn_fact",
                "turn_id": turn_id,
                "fact": fact,
            }
            return self._proposal(command, state, delta, event)

        if command.kind == "agent.turn.finish":
            if current.get("last_fact_kind") != "termination":
                raise ValueError("agent turn cannot finish before a termination fact")
            head = _optional_digest(payload.get("fact_head_digest"), "fact_head_digest")
            if head != current.get("fact_head_digest"):
                raise ValueError("agent turn finish fact head mismatch")
            termination = _text(payload.get("termination"), "termination")
            success = payload.get("success")
            if not isinstance(success, bool):
                raise ValueError("agent turn finish success must be boolean")
            delta = {
                "status": "completed" if success else "failed",
                "termination": termination,
            }
            event = {
                "type": "agent_turn_finished",
                "turn_id": turn_id,
                "success": success,
                "termination": termination,
                "fact_count": current.get("fact_count", 0),
                "fact_head_digest": head,
            }
            return self._proposal(command, state, delta, event)

        raise ValueError(f"unsupported agent turn command: {command.kind}")

    @staticmethod
    def _proposal(
        command: object,
        state: MachineSnapshot,
        delta: Mapping[str, object],
        event: Mapping[str, object],
    ) -> TransitionProposal:
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta=dict(delta),
            event_payloads=(dict(event),),
        )


def agent_turn_machine_family() -> MachineFamilyDescriptor:
    return MachineFamilyDescriptor(
        family_id=AGENT_TURN_MACHINE_FAMILY_ID,
        kind=MachineKind.AGENT,
        implementation_version="2",
        state_schema=AGENT_TURN_MACHINE_STATE_SCHEMA,
        command_kinds=("agent.turn.begin", "agent.fact.record", "agent.turn.finish"),
    )


__all__ = [
    "AGENT_TURN_FACT_KINDS",
    "AGENT_TURN_FACT_WIRE_SCHEMA",
    "AGENT_TURN_MACHINE_FAMILY_ID",
    "AGENT_TURN_MACHINE_STATE_SCHEMA",
    "AgentTurnMachineInterpreter",
    "agent_turn_machine_family",
]
