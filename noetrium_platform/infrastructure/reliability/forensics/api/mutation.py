from __future__ import annotations

from dataclasses import dataclass, field, fields
import time
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.event import (
    causal_event,
    event_field,
    is_event_unit,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.context import (
    ExecutionContext,
    execution_context_from_payload,
    execution_context_payload,
)
from noetrium_platform.foundation.kernel.kernel.canonical import thaw_json
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.unit import NoetriumUnit


@dataclass(frozen=True, slots=True)
class MutationRecord:
    """Ephemeral construction value; persistent truth is state.mutation Event."""

    mutation_id: str
    state_name: str
    aggregate_id: str
    expected_version: int | None
    new_version: int
    old_digest: str | None
    new_digest: str
    component_id: str
    operation_id: str
    context: ExecutionContext
    phase: str = "committed"
    created_at: float = field(default_factory=time.time)
    effect_ref: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "context"
        }
        payload["context"] = thaw_json(execution_context_payload(self.context))
        return payload


def mutation_event(mutation: MutationRecord) -> NoetriumUnit:
    if type(mutation) is not MutationRecord:
        raise TypeError("mutation Event requires MutationRecord construction value")
    if not mutation.mutation_id.strip() or not mutation.state_name.strip():
        raise ValueError("mutation identity/state must be non-empty")
    if mutation.new_version < 1:
        raise ValueError("mutation new_version must be positive")
    document = mutation.to_dict()
    event_attributes = {
        "event_id": "event_mutation_" + mutation.mutation_id,
        "event_type": "STATE_MUTATION_COMMITTED",
        "context": document["context"],
        "component_id": mutation.component_id,
        "timestamp": mutation.created_at,
        "payload": document,
        "artifact_refs": (),
        "state_refs": (mutation.state_name,),
        "effect_refs": (
            () if mutation.effect_ref is None else (mutation.effect_ref,)
        ),
        "request_refs": (mutation.operation_id,),
    }
    key = mutation.aggregate_id + ":" + mutation.state_name
    return causal_event(
        authority_domain="state." + canonical_digest(key)[:32],
        generation=mutation.new_version,
        subject="state:" + key,
        operation="mutate",
        phase=mutation.phase,
        modality=TruthModality.AUTHORIZED,
        reads=(
            ()
            if mutation.old_digest is None
            else (f"state:{key}:{mutation.old_digest}",)
        ),
        writes=(f"state:{key}:{mutation.new_digest}",),
        event_kind="state.mutation",
        physical_effect=False,
        attributes=event_attributes,
    )


def is_mutation_event(value: object) -> bool:
    return (
        type(value) is NoetriumUnit
        and is_event_unit(value)
        and value.has_schema("state.mutation")
    )


def mutation_document(event: NoetriumUnit) -> dict[str, object]:
    if not is_mutation_event(event):
        raise TypeError("mutation projection requires state.mutation Event Unit")
    attributes = event_field(event, "event_attributes")
    if not isinstance(attributes, Mapping):
        raise TypeError("mutation event attributes must be object")
    payload = attributes.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError("mutation event payload must be object")
    return dict(thaw_json(payload))


def mutation_record_value(event: NoetriumUnit) -> MutationRecord:
    document = mutation_document(event)
    context = document.get("context")
    if not isinstance(context, Mapping):
        raise TypeError("mutation context must be object")
    return MutationRecord(
        mutation_id=str(document["mutation_id"]),
        state_name=str(document["state_name"]),
        aggregate_id=str(document["aggregate_id"]),
        expected_version=(
            None
            if document.get("expected_version") is None
            else int(document["expected_version"])
        ),
        new_version=int(document["new_version"]),
        old_digest=(
            None if document.get("old_digest") is None else str(document["old_digest"])
        ),
        new_digest=str(document["new_digest"]),
        component_id=str(document["component_id"]),
        operation_id=str(document["operation_id"]),
        context=execution_context_from_payload(context),
        phase=str(document.get("phase", "committed")),
        created_at=float(document["created_at"]),
        effect_ref=(
            None if document.get("effect_ref") is None else str(document["effect_ref"])
        ),
    )


__all__ = [
    "MutationRecord",
    "is_mutation_event",
    "mutation_document",
    "mutation_event",
    "mutation_record_value",
]
