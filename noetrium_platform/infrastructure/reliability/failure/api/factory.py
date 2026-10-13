from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .catalog import FailureSpec
from .contracts import RecoveryAction, RiskLevel
from .failure_units import failure_record
from noetrium_platform.foundation.kernel.kernel.errors import (
    describe_exception,
    redact_text,
    redact_value,
)


def _safe_exception_tree(
    exc: BaseException,
    *,
    seen: set[int] | None = None,
) -> dict[str, object]:
    """Canonical redacted exception tree used for stable failure identity."""

    visited = set() if seen is None else seen
    identity = id(exc)
    qualified_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    if identity in visited:
        return {"type": qualified_type, "cycle": True}
    visited.add(identity)
    node: dict[str, object] = {
        "type": qualified_type,
        "message": redact_text(str(exc)),
    }
    if isinstance(exc, BaseExceptionGroup):
        node["children"] = tuple(
            _safe_exception_tree(child, seen=visited)
            for child in exc.exceptions
        )
    cause = exc.__cause__
    if cause is None and not exc.__suppress_context__:
        cause = exc.__context__
    if cause is not None:
        node["cause"] = _safe_exception_tree(cause, seen=visited)
    return node


def _safe_cause_chain(exc: BaseException) -> tuple[str, str]:
    tree = _safe_exception_tree(exc)
    chain = json.dumps(
        tree,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return chain, hashlib.sha256(chain.encode("utf-8", "replace")).hexdigest()


def build_failure(
    *,
    component_id: str,
    failure_domain: str,
    failure_code: str,
    stage: str,
    context: ExecutionContext,
    exc: BaseException,
    operation_id: str | None = None,
    operation_invocation_id: str | None = None,
    operation_type: str | None = None,
    retryability: str = "unknown",
    recoverability: str = "unknown",
    recommended_recovery: RecoveryAction | None = None,
    data_integrity_risk: RiskLevel = RiskLevel.NONE,
    comparability_risk: RiskLevel = RiskLevel.NONE,
    scientific_validity_risk: RiskLevel = RiskLevel.NONE,
    operation_payload_digest: str | None = None,
    operation_idempotency_key: str | None = None,
    taxonomy_spec_sha256: str | None = None,
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
    failure_group_path: tuple[int, ...] = (),
    failure_group_size: int | None = None,
) -> NoetriumUnit:
    """Low-level deterministic failure-envelope factory.

    Production domain code should normally use ``build_failure_from_spec`` so taxonomy
    semantics remain catalog-owned. This lower-level factory exists for taxonomy tools
    and synthetic/test failures, not for backend-specific behavior.
    """

    _, cause_chain_digest = _safe_cause_chain(exc)
    raw_diagnostics = getattr(exc, "diagnostics", None)
    diagnostics = (
        redact_value(dict(raw_diagnostics))
        if isinstance(raw_diagnostics, Mapping)
        else {}
    )
    stable = hashlib.sha256(
        json.dumps(
            {
                "domain": failure_domain,
                "code": failure_code,
                "stage": stage,
                "component_id": component_id,
                "run": context.run_id,
                "trace": context.trace_id,
                "span": context.span_id,
                "operation_id": operation_id,
                "operation_invocation_id": operation_invocation_id,
                "operation_type": operation_type,
                "operation_payload_digest": operation_payload_digest,
                "cause": cause_chain_digest,
                "failure_group_path": tuple(failure_group_path),
                "taxonomy_spec_sha256": taxonomy_spec_sha256,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]
    return failure_record(
        failure_id=f"failure_{stable}",
        created_at=time.time(),
        component_id=component_id,
        operation_id=operation_id,
        operation_invocation_id=operation_invocation_id,
        operation_type=operation_type,
        failure_domain=failure_domain,
        failure_code=failure_code,
        stage=stage,
        context=context,
        cause_type=type(exc).__qualname__,
        cause_message=describe_exception(exc).safe_message,
        cause_chain_digest=cause_chain_digest,
        diagnostics=diagnostics,
        failure_group_path=tuple(failure_group_path),
        failure_group_size=failure_group_size,
        retryability=retryability,
        recoverability=recoverability,
        data_integrity_risk=data_integrity_risk,
        comparability_risk=comparability_risk,
        scientific_validity_risk=scientific_validity_risk,
        operation_payload_digest=operation_payload_digest,
        operation_idempotency_key=operation_idempotency_key,
        taxonomy_spec_sha256=taxonomy_spec_sha256,
        effect_certainty=effect_certainty,
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
        state_reads=state_reads,
        state_mutations=state_mutations,
        request_refs=request_refs,
        effect_refs=effect_refs,
        state_refs=state_refs,
        evidence_refs=evidence_refs,
        artifact_refs=artifact_refs,
        correlation_refs=correlation_refs,
        causal_event_refs=causal_event_refs,
        recommended_recovery=recommended_recovery,
    )


def build_failure_from_spec(
    *,
    spec: FailureSpec,
    component_id: str,
    context: ExecutionContext,
    exc: BaseException,
    operation_id: str | None = None,
    operation_invocation_id: str | None = None,
    operation_type: str | None = None,
    operation_payload_digest: str | None = None,
    operation_idempotency_key: str | None = None,
    retryability: str = "unknown",
    recoverability: str = "unknown",
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
    failure_group_path: tuple[int, ...] = (),
    failure_group_size: int | None = None,
) -> NoetriumUnit:
    """Build one envelope from catalog-owned failure semantics."""

    return build_failure(
        component_id=component_id,
        failure_domain=spec.domain,
        failure_code=spec.code,
        stage=spec.stage,
        context=context,
        exc=exc,
        operation_id=operation_id,
        operation_invocation_id=operation_invocation_id,
        operation_type=operation_type,
        operation_payload_digest=operation_payload_digest,
        operation_idempotency_key=operation_idempotency_key,
        retryability=retryability,
        recoverability=recoverability,
        recommended_recovery=spec.default_recovery,
        data_integrity_risk=spec.data_integrity_risk,
        comparability_risk=spec.comparability_risk,
        scientific_validity_risk=spec.scientific_validity_risk,
        taxonomy_spec_sha256=spec.digest(),
        effect_certainty=effect_certainty,
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
        state_reads=state_reads,
        state_mutations=state_mutations,
        request_refs=request_refs,
        effect_refs=effect_refs,
        state_refs=state_refs,
        evidence_refs=evidence_refs,
        artifact_refs=artifact_refs,
        correlation_refs=correlation_refs,
        causal_event_refs=causal_event_refs,
        failure_group_path=failure_group_path,
        failure_group_size=failure_group_size,
    )


__all__ = ["build_failure", "build_failure_from_spec"]
