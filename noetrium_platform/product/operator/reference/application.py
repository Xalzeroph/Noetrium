from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path

from noetrium_platform.product.operator.api import ResearchAction, ResearchRequest, ResearchResult
from noetrium_platform.foundation.kernel.kernel import JsonDocument, JsonInput
from noetrium_platform.foundation.kernel.kernel.durability import (
    InterprocessFileLock,
    atomic_replace_bytes,
    decode_checksummed_document,
    encode_checksummed_document,
)

_SCHEMA = "noetrium.operator-reference.v1"
_STATE_FIELDS = frozenset({"target", "phase", "generation", "events"})
_EVENT_FIELDS = frozenset({"sequence", "action", "phase", "generation"})
_EVENT_ACTIONS = frozenset(
    {ResearchAction.RUN, ResearchAction.STOP, ResearchAction.RESUME, ResearchAction.RECONCILE}
)


class ReferencePhase(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


def _positive_int(value: JsonInput, *, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _document(value: JsonInput, *, field: str) -> JsonDocument:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} keys must be strings")
    return value


@dataclass(frozen=True, slots=True)
class ReferenceEvent:
    sequence: int
    action: ResearchAction
    phase: ReferencePhase
    generation: int

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("reference event sequence must be a positive integer")
        if self.action not in _EVENT_ACTIONS:
            raise ValueError("reference event action is invalid")
        if not isinstance(self.phase, ReferencePhase):
            raise TypeError("reference event phase must be ReferencePhase")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("reference event generation must be a positive integer")

    def to_document(self) -> JsonDocument:
        return {
            "sequence": self.sequence,
            "action": self.action.value,
            "phase": self.phase.value,
            "generation": self.generation,
        }


@dataclass(frozen=True, slots=True)
class ReferenceState:
    target: str
    phase: ReferencePhase
    generation: int
    events: tuple[ReferenceEvent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("reference state target must be a non-empty string")
        if not isinstance(self.phase, ReferencePhase):
            raise TypeError("reference state phase must be ReferencePhase")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("reference state generation must be a positive integer")
        if not isinstance(self.events, tuple) or not self.events:
            raise ValueError("reference state events are invalid")
        _validate_reference_history(self)

    @classmethod
    def start(cls, target: str) -> "ReferenceState":
        phase = ReferencePhase.RUNNING
        event = ReferenceEvent(1, ResearchAction.RUN, phase, 1)
        return cls(target=target, phase=phase, generation=1, events=(event,))

    def transition(self, action: ResearchAction) -> "ReferenceState":
        phase = self.phase
        generation = self.generation
        if action is ResearchAction.STOP:
            if phase is not ReferencePhase.RUNNING:
                raise ValueError("reference target is not running")
            phase = ReferencePhase.STOPPED
        elif action is ResearchAction.RESUME:
            if phase is not ReferencePhase.STOPPED:
                raise ValueError("reference target is not stopped")
            phase = ReferencePhase.RUNNING
            generation += 1
        elif action is not ResearchAction.RECONCILE:
            raise ValueError(f"unsupported reference transition: {action}")
        event = ReferenceEvent(len(self.events) + 1, action, phase, generation)
        return ReferenceState(
            target=self.target,
            phase=phase,
            generation=generation,
            events=(*self.events, event),
        )

    def to_document(self) -> JsonDocument:
        return {
            "target": self.target,
            "phase": self.phase.value,
            "generation": self.generation,
            "events": tuple(event.to_document() for event in self.events),
        }


def _validate_reference_history(state: ReferenceState) -> None:
    expected_phase = ReferencePhase.RUNNING
    expected_generation = 1
    for expected_sequence, event in enumerate(state.events, start=1):
        if event.sequence != expected_sequence:
            raise ValueError("reference event sequence is not contiguous")
        if expected_sequence == 1:
            if event.action is not ResearchAction.RUN:
                raise ValueError("reference event history must begin with run")
        elif event.action is ResearchAction.RUN:
            raise ValueError("reference event history contains duplicate run")
        elif event.action is ResearchAction.STOP:
            if expected_phase is not ReferencePhase.RUNNING:
                raise ValueError("reference event stop transition is invalid")
            expected_phase = ReferencePhase.STOPPED
        elif event.action is ResearchAction.RESUME:
            if expected_phase is not ReferencePhase.STOPPED:
                raise ValueError("reference event resume transition is invalid")
            expected_phase = ReferencePhase.RUNNING
            expected_generation += 1
        if event.phase is not expected_phase or event.generation != expected_generation:
            raise ValueError("reference event state transition is inconsistent")
    if state.phase is not expected_phase or state.generation != expected_generation:
        raise ValueError("reference state does not match event history")


def _decode_event(value: JsonInput) -> ReferenceEvent:
    document = _document(value, field="reference event")
    if set(document) != _EVENT_FIELDS:
        raise ValueError("reference event fields are invalid")
    action_value = document["action"]
    phase_value = document["phase"]
    if not isinstance(action_value, str):
        raise ValueError("reference event action is invalid")
    if not isinstance(phase_value, str):
        raise ValueError("reference event phase is invalid")
    try:
        action = ResearchAction(action_value)
        phase = ReferencePhase(phase_value)
    except ValueError as exc:
        raise ValueError("reference event enum value is invalid") from exc
    return ReferenceEvent(
        sequence=_positive_int(document["sequence"], field="reference event sequence"),
        action=action,
        phase=phase,
        generation=_positive_int(document["generation"], field="reference event generation"),
    )


def _decode_reference_state(value: JsonInput, *, target: str) -> ReferenceState:
    document = _document(value, field="reference state")
    if set(document) != _STATE_FIELDS:
        raise ValueError("reference state fields are invalid")
    target_value = document["target"]
    phase_value = document["phase"]
    events_value = document["events"]
    if not isinstance(target_value, str) or target_value != target:
        raise ValueError("reference state target identity mismatch")
    if not isinstance(phase_value, str):
        raise ValueError("reference state phase is invalid")
    if not isinstance(events_value, (list, tuple)) or not events_value:
        raise ValueError("reference state events are invalid")
    try:
        phase = ReferencePhase(phase_value)
    except ValueError as exc:
        raise ValueError("reference state phase is invalid") from exc
    return ReferenceState(
        target=target_value,
        phase=phase,
        generation=_positive_int(document["generation"], field="reference state generation"),
        events=tuple(_decode_event(event) for event in events_value),
    )


class ReferenceResearchApplication:
    """Durable deterministic lifecycle used only for product/conformance qualification."""

    def __init__(self, state_root: Path) -> None:
        self._root = Path(state_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, target: str) -> Path:
        digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.json"

    def _lock_path(self, target: str) -> Path:
        return self._path(target).with_suffix(".lock")

    def _read(self, target: str) -> ReferenceState:
        path = self._path(target)
        if not path.is_file():
            raise FileNotFoundError(f"reference target does not exist: {target}")
        payload = decode_checksummed_document(
            path.read_bytes(), expected_schema=_SCHEMA
        ).payload
        return _decode_reference_state(payload, target=target)

    def _write(self, target: str, state: ReferenceState) -> None:
        if not isinstance(state, ReferenceState):
            raise TypeError("reference writer requires ReferenceState")
        if state.target != target:
            raise ValueError("reference state target identity mismatch")
        atomic_replace_bytes(
            self._path(target),
            encode_checksummed_document(_SCHEMA, state.to_document()),
        )

    def _result(self, request: ResearchRequest, state: ReferenceState) -> ResearchResult:
        if request.action is ResearchAction.EVIDENCE:
            result_payload = {
                "generation": state.generation,
                "events": tuple(event.to_document() for event in state.events),
            }
        else:
            result_payload = {
                "generation": state.generation,
                "event_count": len(state.events),
            }
        return ResearchResult(
            request.action,
            request.target,
            state.phase.value,
            result_payload,
        )

    def _run(self, request: ResearchRequest) -> ResearchResult:
        path = self._path(request.target)
        if path.exists():
            raise ValueError(f"reference target already exists: {request.target}")
        state = ReferenceState.start(request.target)
        self._write(request.target, state)
        return self._result(request, state)

    def _transition(self, request: ResearchRequest, state: ReferenceState) -> ResearchResult:
        updated = state.transition(request.action)
        self._write(request.target, updated)
        return self._result(request, updated)

    def execute(self, request: ResearchRequest) -> ResearchResult:
        if not isinstance(request, ResearchRequest):
            raise TypeError("reference application requires ResearchRequest")
        with InterprocessFileLock(self._lock_path(request.target)):
            if request.action is ResearchAction.RUN:
                return self._run(request)
            state = self._read(request.target)
            if request.action in {ResearchAction.INSPECT, ResearchAction.EVIDENCE}:
                return self._result(request, state)
            if request.action in {
                ResearchAction.STOP,
                ResearchAction.RESUME,
                ResearchAction.RECONCILE,
            }:
                return self._transition(request, state)
            raise ValueError(f"unsupported research action: {request.action}")


def build_reference_application(config_path: Path | None) -> ReferenceResearchApplication:
    if config_path is None:
        raise ValueError("reference application requires --application-config")
    data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"state_root"}:
        raise ValueError("reference application config must contain only state_root")
    state_root = data["state_root"]
    if not isinstance(state_root, str) or not state_root.strip():
        raise ValueError("reference application state_root must be a non-empty string")
    return ReferenceResearchApplication(Path(state_root))


__all__ = [
    "ReferenceEvent",
    "ReferencePhase",
    "ReferenceResearchApplication",
    "ReferenceState",
    "build_reference_application",
]
