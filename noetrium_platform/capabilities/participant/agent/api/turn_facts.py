from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)


AGENT_TURN_FACT_SCHEMA = "agent-turn-fact.v1"


class AgentTurnFactKind(StrEnum):
    """Domain facts proposed by Agent Turn VM for outer Machine commit."""

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
    """Immutable agent-domain fact; it is not itself a journal record.

    The Agent Turn VM may produce these facts, but only the enclosing
    Method/Run Machine is allowed to commit them to the Kernel Journal. Large
    model-visible payloads stay in their owning content-addressed stores and
    are referenced here by identity/digest rather than duplicated.
    """

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
        frozen = freeze_json(self.payload)
        object.__setattr__(self, "payload", frozen)
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


__all__ = [
    "AGENT_TURN_FACT_SCHEMA",
    "AgentTurnFact",
    "AgentTurnFactKind",
]
