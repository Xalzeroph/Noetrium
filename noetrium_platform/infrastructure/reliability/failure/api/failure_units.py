"""Failure evidence as the universal causal Event Unit carrier."""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.event import (
    causal_event,
    event_field,
    event_ref_digest,
    is_event_unit,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    execution_context_from_payload,
    execution_context_payload,
    thaw_json,
)
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, UnitRef

from .contracts import RecoveryAction, RiskLevel


_FAILURE_KIND = "reliability.failure"
_TUPLE_FIELDS = frozenset({
    "input_artifacts",
    "output_artifacts",
    "state_reads",
    "state_mutations",
    "request_refs",
    "effect_refs",
    "state_refs",
    "evidence_refs",
    "artifact_refs",
    "correlation_refs",
    "causal_event_refs",
    "failure_group_path",
})
_RISK_FIELDS = frozenset({
    "data_integrity_risk",
    "comparability_risk",
    "scientific_validity_risk",
})


def _causal_refs(values: tuple[str, ...]) -> tuple[UnitRef, ...]:
    if type(values) is not tuple:
        raise TypeError("failure causal_event_refs must be a tuple")
    refs: list[UnitRef] = []
    for raw in values:
        if type(raw) is not str or not raw.strip():
            raise ValueError("failure causal event ref must be non-empty text")
        digest = raw.removeprefix("event:")
        if (
            len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise ValueError("failure causal event ref must be an event SHA-256")
        refs.append(UnitRef(("event:" + digest,)))
    if len(refs) != len(set(refs)):
        raise ValueError("failure causal event refs must be unique")
    return tuple(refs)


def failure_record(
    *,
    failure_id: str,
    created_at: float,
    component_id: str,
    operation_id: str | None,
    operation_invocation_id: str | None,
    operation_type: str | None,
    failure_domain: str,
    failure_code: str,
    stage: str,
    context: ExecutionContext,
    cause_type: str,
    cause_message: str,
    cause_chain_digest: str,
    retryability: str,
    recoverability: str,
    data_integrity_risk: RiskLevel,
    comparability_risk: RiskLevel,
    scientific_validity_risk: RiskLevel,
    diagnostics: Mapping[str, object] | None = None,
    failure_group_path: tuple[int, ...] = (),
    failure_group_size: int | None = None,
    operation_payload_digest: str | None = None,
    operation_idempotency_key: str | None = None,
    taxonomy_spec_sha256: str | None = None,
    mutation_phase: str | None = None,
    effect_certainty: str | None = None,
    input_artifacts: tuple[str, ...] = (),
    output_artifacts: tuple[str, ...] = (),
    state_reads: tuple[str, ...] = (),
    state_mutations: tuple[str, ...] = (),
    request_refs: tuple[str, ...] = (),
    effect_refs: tuple[str, ...] = (),
    state_refs: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
    artifact_refs: tuple[str, ...] = (),
    correlation_refs: tuple[str, ...] = (),
    causal_event_refs: tuple[str, ...] = (),
    recommended_recovery: RecoveryAction | None = None,
) -> NoetriumUnit:
    """Create one evidenced failure Event.

    A failure is not a second forensic carrier. It is a system.event Unit whose
    event_attributes are the stable failure document used by projections.
    """

    if type(failure_id) is not str or not failure_id.strip():
        raise ValueError("failure_id must be non-empty")
    failure_group_path = tuple(failure_group_path)
    if any(type(index) is not int or index < 0 for index in failure_group_path):
        raise ValueError("failure_group_path must contain non-negative integers")
    if failure_group_size is not None and (
        type(failure_group_size) is not int or failure_group_size < 1
    ):
        raise ValueError("failure_group_size must be a positive integer or None")
    payload = {
        "failure_id": failure_id.strip(),
        "created_at": float(created_at),
        "component_id": component_id,
        "operation_id": operation_id,
        "operation_invocation_id": operation_invocation_id,
        "operation_type": operation_type,
        "failure_domain": failure_domain,
        "failure_code": failure_code,
        "stage": stage,
        "context": execution_context_payload(context),
        "cause_type": cause_type,
        "cause_message": cause_message,
        "cause_chain_digest": cause_chain_digest,
        "diagnostics": dict(diagnostics or {}),
        "failure_group_path": failure_group_path,
        "failure_group_size": failure_group_size,
        "retryability": retryability,
        "recoverability": recoverability,
        "data_integrity_risk": RiskLevel(data_integrity_risk).value,
        "comparability_risk": RiskLevel(comparability_risk).value,
        "scientific_validity_risk": RiskLevel(scientific_validity_risk).value,
        "operation_payload_digest": operation_payload_digest,
        "operation_idempotency_key": operation_idempotency_key,
        "taxonomy_spec_sha256": taxonomy_spec_sha256,
        "mutation_phase": mutation_phase,
        "effect_certainty": effect_certainty,
        "input_artifacts": tuple(input_artifacts),
        "output_artifacts": tuple(output_artifacts),
        "state_reads": tuple(state_reads),
        "state_mutations": tuple(state_mutations),
        "request_refs": tuple(request_refs),
        "effect_refs": tuple(effect_refs),
        "state_refs": tuple(state_refs),
        "evidence_refs": tuple(evidence_refs),
        "artifact_refs": tuple(artifact_refs),
        "correlation_refs": tuple(correlation_refs),
        "recommended_recovery": (
            None
            if recommended_recovery is None
            else RecoveryAction(recommended_recovery).value
        ),
    }
    causal_parents = _causal_refs(causal_event_refs)
    read_keys = tuple(
        sorted(
            {
                *(f"request:{value}" for value in request_refs),
                *(f"effect:{value}" for value in effect_refs),
                *(f"state:{value}" for value in state_refs),
                *(f"evidence:{value}" for value in evidence_refs),
                *(f"artifact:{value}" for value in artifact_refs),
                *(f"correlation:{value}" for value in correlation_refs),
            }
        )
    )
    return causal_event(
        authority_domain=(
            "failure."
            + context.run_id.encode("utf-8").hex()[:24].lower()
            + "."
            + component_id.encode("utf-8").hex()[:16].lower()
        ),
        generation=0,
        subject="failure:" + failure_id.strip(),
        operation="record-failure",
        phase=stage,
        modality=TruthModality.EVIDENCED,
        causal_parents=causal_parents,
        reads=read_keys,
        event_kind=_FAILURE_KIND,
        attributes=payload,
    )


def is_failure_record(value: object) -> bool:
    return (
        type(value) is NoetriumUnit
        and is_event_unit(value)
        and value.has_schema(_FAILURE_KIND)
    )


def failure_field(failure: NoetriumUnit, name: str):
    if not is_failure_record(failure):
        raise TypeError("failure projection requires reliability.failure Event Unit")
    if name == "causal_event_refs":
        return tuple(
            digest
            for reference in event_field(failure, "causal_parents")
            if (digest := event_ref_digest(reference)) is not None
        )
    attributes = event_field(failure, "event_attributes")
    if not isinstance(attributes, Mapping):
        raise TypeError("failure event attributes must be an object")
    if name not in attributes:
        raise KeyError(name)
    value = attributes[name]
    if name == "context":
        if not isinstance(value, Mapping):
            raise TypeError("failure context projection must be an object")
        return execution_context_from_payload(value)
    if name in _RISK_FIELDS:
        return RiskLevel(value)
    if name == "recommended_recovery":
        return None if value is None else RecoveryAction(value)
    if name in _TUPLE_FIELDS:
        return tuple(value)
    return value


def failure_document(failure: NoetriumUnit) -> dict[str, object]:
    if not is_failure_record(failure):
        raise TypeError("failure document requires reliability.failure Event Unit")
    attributes = event_field(failure, "event_attributes")
    if not isinstance(attributes, Mapping):
        raise TypeError("failure event attributes must be an object")
    result = dict(thaw_json(attributes))
    result["causal_event_refs"] = tuple(failure_field(failure, "causal_event_refs"))
    return result


def replace_failure(
    failure: NoetriumUnit,
    **changes: object,
) -> NoetriumUnit:
    """Pure immutable rewrite of one failure Event Unit."""

    document = failure_document(failure)
    unknown = tuple(sorted(set(changes) - set(document)))
    if unknown:
        raise TypeError(f"unknown failure fields: {unknown}")
    document.update(changes)
    context = document["context"]
    if not isinstance(context, Mapping):
        raise TypeError("failure context must remain an object")
    document["context"] = execution_context_from_payload(context)
    for name in _RISK_FIELDS:
        document[name] = RiskLevel(document[name])
    recovery = document["recommended_recovery"]
    document["recommended_recovery"] = (
        None if recovery is None else RecoveryAction(recovery)
    )
    for name in _TUPLE_FIELDS:
        document[name] = tuple(document[name])
    return failure_record(**document)  # type: ignore[arg-type]


__all__ = [
    "failure_document",
    "failure_field",
    "failure_record",
    "is_failure_record",
    "replace_failure",
]
