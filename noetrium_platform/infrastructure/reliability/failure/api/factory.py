from __future__ import annotations

import hashlib
import json
import time

from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext

from .catalog import FailureSpec
from .contracts import FailureEnvelope, RecoveryAction, RiskLevel
from noetrium_platform.foundation.kernel.kernel.errors import redact_text


def _safe_cause_chain(exc: BaseException) -> tuple[str, str]:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(
            f"{type(current).__module__}.{type(current).__qualname__}:{redact_text(str(current))}"
        )
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    chain = " <- ".join(parts)
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
    correlation_refs: tuple[str, ...] = (),
) -> FailureEnvelope:
    """Low-level deterministic failure-envelope factory.

    Production domain code should normally use ``build_failure_from_spec`` so taxonomy
    semantics remain catalog-owned. This lower-level factory exists for taxonomy tools
    and synthetic/test failures, not for backend-specific behavior.
    """

    _, cause_chain_digest = _safe_cause_chain(exc)
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
                "taxonomy_spec_sha256": taxonomy_spec_sha256,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]
    return FailureEnvelope(
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
        cause_message=redact_text(str(exc)),
        cause_chain_digest=cause_chain_digest,
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
        correlation_refs=correlation_refs,
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
    correlation_refs: tuple[str, ...] = (),
) -> FailureEnvelope:
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
        correlation_refs=correlation_refs,
    )


__all__ = ["build_failure", "build_failure_from_spec"]
