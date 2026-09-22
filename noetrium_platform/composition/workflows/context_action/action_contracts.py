from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, EffectIntentPhase
from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, ActionResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult, canonical_digest


@dataclass(frozen=True, slots=True)
class SafeActionExecution:
    result: ActionResult
    operation_results: tuple[OperationResult[JsonValue], ...]
    replayed_from_intent: bool = False


@dataclass(frozen=True, slots=True)
class ActionPreflightProof:
    """Immutable proof that one action/cycle passed explicit preflight."""
    decision_cycle_id: str
    action_type: str
    action_payload_digest: str
    existing_intent_id: str | None = None
    existing_phase: EffectIntentPhase | None = None
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.decision_cycle_id) is not str or not self.decision_cycle_id.strip():
            raise ValueError("action preflight decision_cycle_id is required")
        if type(self.action_type) is not str or not self.action_type.strip():
            raise ValueError("action preflight action_type is required")
        if type(self.action_payload_digest) is not str or len(self.action_payload_digest) != 64:
            raise ValueError("action preflight action_payload_digest must be SHA-256")
        if self.existing_intent_id is not None and (type(self.existing_intent_id) is not str or not self.existing_intent_id.strip()):
            raise ValueError("action preflight existing_intent_id must be non-empty")
        if self.existing_phase is not None and not isinstance(self.existing_phase, EffectIntentPhase):
            raise TypeError("action preflight existing_phase must be EffectIntentPhase")
        object.__setattr__(self, "proof_digest", canonical_digest(self.as_payload(include_digest=False)))

    @classmethod
    def build(cls, *, action_type: str, action_payload: object, context: ExecutionContext,
              existing_intent_id: str | None = None,
              existing_phase: EffectIntentPhase | None = None) -> "ActionPreflightProof":
        if not isinstance(context, ExecutionContext):
            raise TypeError("action preflight proof requires ExecutionContext")
        return cls(context.decision_cycle_id or context.span_id, action_type,
                   canonical_digest(action_payload), existing_intent_id, existing_phase)

    def require(self, *, action_type: str, action_payload: object, context: ExecutionContext) -> None:
        if not isinstance(context, ExecutionContext):
            raise TypeError("action preflight validation requires ExecutionContext")
        if self.decision_cycle_id != (context.decision_cycle_id or context.span_id):
            raise RuntimeError("action preflight proof belongs to another decision cycle")
        if self.action_type != action_type or self.action_payload_digest != canonical_digest(action_payload):
            raise RuntimeError("action preflight proof does not match requested action")

    def as_payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "decision_cycle_id": self.decision_cycle_id,
            "action_type": self.action_type,
            "action_payload_digest": self.action_payload_digest,
            "existing_intent_id": self.existing_intent_id,
            "existing_phase": None if self.existing_phase is None else self.existing_phase.value,
        }
        if include_digest:
            payload["proof_digest"] = self.proof_digest
        return payload

    @classmethod
    def from_payload(cls, value: object) -> "ActionPreflightProof":
        if not isinstance(value, Mapping):
            raise TypeError("action preflight proof payload must be an object")
        phase = value.get("existing_phase")
        proof = cls(value.get("decision_cycle_id"), value.get("action_type"),
                    value.get("action_payload_digest"), value.get("existing_intent_id"),
                    None if phase is None else EffectIntentPhase(phase))
        supplied = value.get("proof_digest")
        if supplied is not None and supplied != proof.proof_digest:
            raise ValueError("action preflight proof digest mismatch")
        return proof


@dataclass(frozen=True, slots=True)
class ActionSafetyPermit:
    decision_cycle_id: str
    environment_component_digest: str
    journal_durability: str | None
    request_digest: str
    intent_id: str | None


@dataclass(frozen=True, slots=True)
class PreparedSafeAction:
    """Exact action authorization frozen before crossing the side-effect boundary."""

    request: ActionRequest
    intent: EffectIntent | None
    permit: ActionSafetyPermit
    operation_results: tuple[OperationResult[JsonValue], ...] = ()


__all__ = ["ActionPreflightProof", "ActionSafetyPermit", "PreparedSafeAction", "SafeActionExecution"]
