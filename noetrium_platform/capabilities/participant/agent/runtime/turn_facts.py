from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)


AGENT_TURN_FACT_SCHEMA = "agent-turn-fact.v1"
_AGENT_TURN_FACT_FIELDS = frozenset({
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


class AgentTurnFactKind(StrEnum):
    """Agent Turn VM facts proposed for an enclosing Machine transition."""

    PLANNING_INPUT = "planning_input"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    DECISION = "decision"
    ACTION = "action"
    OBSERVATION = "observation"
    EFFECT = "effect"
    TERMINATION = "termination"


@dataclass(frozen=True, slots=True)
class AgentTurnFact:
    """Immutable candidate fact owned by Agent Turn VM, never a journal record."""

    schema_version: str
    session_id: str
    sequence: int
    kind: AgentTurnFactKind
    run_id: str
    trace_id: str
    span_id: str
    payload: JsonObject = field(default_factory=dict)
    task_id: str | None = None
    decision_cycle_id: str | None = None
    artifact_refs: tuple[str, ...] = ()
    previous_fact_digest: str | None = None
    fact_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != AGENT_TURN_FACT_SCHEMA:
            raise ValueError("unsupported agent turn fact schema")
        for name, value in (
            ("session_id", self.session_id),
            ("run_id", self.run_id),
            ("trace_id", self.trace_id),
            ("span_id", self.span_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"agent turn fact {name} is required")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("agent turn fact sequence must be positive")
        if not isinstance(self.kind, AgentTurnFactKind):
            raise TypeError("agent turn fact kind must be AgentTurnFactKind")
        if not isinstance(self.payload, Mapping):
            raise TypeError("agent turn fact payload must be a mapping")
        for name, value in (
            ("task_id", self.task_id),
            ("decision_cycle_id", self.decision_cycle_id),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"agent turn fact {name} must be non-empty when present")
        if not isinstance(self.artifact_refs, tuple) or any(
            not isinstance(ref, str) or not ref.strip() for ref in self.artifact_refs
        ):
            raise TypeError("agent turn fact artifact_refs must contain non-empty strings")
        if len(self.artifact_refs) != len(set(self.artifact_refs)):
            raise ValueError("agent turn fact artifact_refs must be unique")
        if self.sequence == 1:
            if self.previous_fact_digest is not None:
                raise ValueError("first agent turn fact cannot have a previous digest")
        else:
            if self.previous_fact_digest is None:
                raise ValueError("non-initial agent turn fact requires previous digest")
            require_sha256(self.previous_fact_digest, "agent turn previous_fact_digest")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "fact_digest", canonical_digest(self.as_payload(include_digest=False)))

    @classmethod
    def from_context(
        cls,
        *,
        session_id: str,
        sequence: int,
        kind: AgentTurnFactKind,
        context: ExecutionContext,
        payload: Mapping[str, JsonValue] | None = None,
        artifact_refs: tuple[str, ...] = (),
        previous_fact_digest: str | None = None,
    ) -> "AgentTurnFact":
        if not isinstance(context, ExecutionContext):
            raise TypeError("agent turn fact context must be ExecutionContext")
        return cls(
            AGENT_TURN_FACT_SCHEMA,
            session_id,
            sequence,
            kind,
            context.run_id,
            context.trace_id,
            context.span_id,
            {} if payload is None else dict(payload),
            context.task_id,
            context.decision_cycle_id,
            artifact_refs,
            previous_fact_digest,
        )

    @classmethod
    def from_payload(cls, document: Mapping[str, JsonValue]) -> "AgentTurnFact":
        """Strictly reconstruct one fact from a Kernel Journal event payload.

        This is a decoder, not a persistence seam. The supplied digest is
        checked against the canonical reconstructed fact so Journal remains the
        authority and malformed read-side projections fail closed.
        """

        if not isinstance(document, Mapping):
            raise TypeError("agent turn fact document must be a mapping")
        if frozenset(document) != _AGENT_TURN_FACT_FIELDS:
            raise ValueError("agent turn fact fields mismatch")
        if document["schema_version"] != AGENT_TURN_FACT_SCHEMA:
            raise ValueError("unsupported agent turn fact schema")

        kind_value = document["kind"]
        if not isinstance(kind_value, str):
            raise TypeError("agent turn fact kind must be text")
        try:
            kind = AgentTurnFactKind(kind_value)
        except ValueError as exc:
            raise ValueError("unsupported agent turn fact kind") from exc

        sequence = document["sequence"]
        if type(sequence) is not int or sequence <= 0:
            raise ValueError("agent turn fact sequence must be positive")
        payload = document["payload"]
        if not isinstance(payload, Mapping):
            raise TypeError("agent turn fact payload must be a mapping")
        refs = document["artifact_refs"]
        if isinstance(refs, (str, bytes, bytearray)) or not isinstance(refs, Sequence):
            raise TypeError("agent turn fact artifact_refs must be a sequence")
        artifact_refs = tuple(refs)
        if any(not isinstance(ref, str) for ref in artifact_refs):
            raise TypeError("agent turn fact artifact_refs must contain text")

        def required_text(field: str) -> str:
            value = document[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"agent turn fact {field} is required")
            return value

        def optional_text(field: str) -> str | None:
            value = document[field]
            if value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"agent turn fact {field} must be non-empty when present")
            return value

        previous = document["previous_fact_digest"]
        if previous is not None:
            if not isinstance(previous, str):
                raise TypeError("agent turn previous_fact_digest must be text")
            require_sha256(previous, "agent turn previous_fact_digest")
        supplied_digest = document["fact_digest"]
        if not isinstance(supplied_digest, str):
            raise TypeError("agent turn fact_digest must be text")
        require_sha256(supplied_digest, "agent turn fact_digest")

        fact = cls(
            AGENT_TURN_FACT_SCHEMA,
            required_text("session_id"),
            sequence,
            kind,
            required_text("run_id"),
            required_text("trace_id"),
            required_text("span_id"),
            dict(payload),
            optional_text("task_id"),
            optional_text("decision_cycle_id"),
            artifact_refs,
            previous,
        )
        if fact.fact_digest != supplied_digest:
            raise ValueError("agent turn fact digest mismatch")
        return fact

    def as_payload(self, *, include_digest: bool = True) -> JsonObject:
        payload: JsonObject = {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "kind": self.kind.value,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "task_id": self.task_id,
            "decision_cycle_id": self.decision_cycle_id,
            "payload": dict(self.payload),
            "artifact_refs": list(self.artifact_refs),
            "previous_fact_digest": self.previous_fact_digest,
        }
        if include_digest:
            payload["fact_digest"] = self.fact_digest
        return payload


class AgentTurnFactSink(Protocol):
    """Narrow candidate-fact seam; persistence authority is composition-owned."""

    def append(
        self,
        kind: AgentTurnFactKind,
        *,
        context: ExecutionContext,
        payload: Mapping[str, JsonValue] | None = None,
        artifact_refs: tuple[str, ...] = (),
    ) -> AgentTurnFact: ...


class AgentTurnFactBuffer:
    """Process-local fact chain with no persistence API."""

    def __init__(
        self,
        session_id: str,
        *,
        committed_count: int = 0,
        committed_head_digest: str | None = None,
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("agent turn fact buffer requires session_id")
        if type(committed_count) is not int or committed_count < 0:
            raise ValueError("agent turn committed_count must be non-negative")
        if committed_count == 0:
            if committed_head_digest is not None:
                raise ValueError("empty agent turn fact anchor cannot have a head digest")
        else:
            if committed_head_digest is None:
                raise ValueError("non-empty agent turn fact anchor requires a head digest")
            require_sha256(committed_head_digest, "agent turn committed_head_digest")
        self._session_id = session_id
        self._committed_count = committed_count
        self._committed_head_digest = committed_head_digest
        self._facts: list[AgentTurnFact] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def facts(self) -> tuple[AgentTurnFact, ...]:
        return tuple(self._facts)

    @property
    def committed_count(self) -> int:
        return self._committed_count

    @property
    def total_count(self) -> int:
        return self._committed_count + len(self._facts)

    @property
    def head_digest(self) -> str | None:
        return self._committed_head_digest if not self._facts else self._facts[-1].fact_digest

    @property
    def next_sequence(self) -> int:
        return self.total_count + 1

    def append(
        self,
        kind: AgentTurnFactKind,
        *,
        context: ExecutionContext,
        payload: Mapping[str, JsonValue] | None = None,
        artifact_refs: tuple[str, ...] = (),
    ) -> AgentTurnFact:
        fact = AgentTurnFact.from_context(
            session_id=self._session_id,
            sequence=self.next_sequence,
            kind=kind,
            context=context,
            payload=payload,
            artifact_refs=artifact_refs,
            previous_fact_digest=self.head_digest,
        )
        self._facts.append(fact)
        return fact

    @classmethod
    def resume_candidate(
        cls,
        session_id: str,
        *,
        committed_count: int,
        committed_head_digest: str | None,
    ) -> "AgentTurnFactBuffer":
        return cls(
            session_id,
            committed_count=committed_count,
            committed_head_digest=committed_head_digest,
        )

    @classmethod
    def replay_candidate(
        cls,
        session_id: str,
        facts: tuple[AgentTurnFact, ...],
    ) -> "AgentTurnFactBuffer":
        buffer = cls(session_id)
        for expected_sequence, fact in enumerate(facts, start=1):
            if not isinstance(fact, AgentTurnFact):
                raise TypeError("agent turn replay requires AgentTurnFact values")
            if fact.session_id != session_id:
                raise ValueError("agent turn replay session mismatch")
            if fact.sequence != expected_sequence:
                raise ValueError("agent turn replay sequence is not contiguous")
            if fact.previous_fact_digest != buffer.head_digest:
                raise ValueError("agent turn replay digest chain is broken")
            buffer._facts.append(fact)
        return buffer


__all__ = [
    "AGENT_TURN_FACT_SCHEMA",
    "AgentTurnFact",
    "AgentTurnFactBuffer",
    "AgentTurnFactKind",
    "AgentTurnFactSink",
]
