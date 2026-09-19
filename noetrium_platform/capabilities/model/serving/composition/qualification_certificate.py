from __future__ import annotations

import math

from noetrium_platform.capabilities.model.serving.api import (
    QualificationCertificate,
    QualificationEvidence,
    QualificationPolicy,
    ResourceEnvelope,
    ResourceQualificationMeasurements,
    evaluate_qualification,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _sha256(value: str, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def issue_measured_qualification_certificate(
    evidence: QualificationEvidence,
    policy: QualificationPolicy,
    resources: ResourceQualificationMeasurements,
    *,
    qualified_roles: tuple[str, ...],
    target_host_identity_digest: str,
) -> QualificationCertificate:
    """Issue a certificate only from measured qualification authorities.

    The selected concurrency must have an explicit performance sample.  The
    certificate envelope is derived from that sample and measured memory, so a
    caller cannot independently author performance/resource claims.
    """

    _sha256(evidence.model_stack_digest, "qualification model_stack_digest")
    host_digest = _sha256(target_host_identity_digest, "qualification target_host_identity_digest")
    if type(qualified_roles) is not tuple or not qualified_roles:
        raise ValueError("qualification certificate requires at least one role")
    if any(type(role) is not str or not role.strip() for role in qualified_roles):
        raise ValueError("qualification certificate roles must be non-empty strings")
    if len(set(qualified_roles)) != len(qualified_roles):
        raise ValueError("qualification certificate roles must be unique")

    observed_roles = {item.role for item in evidence.canaries}
    missing_roles = sorted(set(qualified_roles) - observed_roles)
    if missing_roles:
        raise ValueError(f"qualification evidence missing role canaries: {missing_roles}")
    decision = evaluate_qualification(evidence, policy)
    if not decision.qualified:
        raise ValueError("qualification evidence does not satisfy policy: " + "; ".join(decision.reasons))

    samples = tuple(
        item for item in evidence.performance
        if item.concurrency == resources.max_qualified_concurrency
    )
    if len(samples) != 1:
        raise ValueError("qualification evidence must contain exactly one sample at max qualified concurrency")
    sample = samples[0]
    for field in ("ttft_p99", "tpot_p99", "output_tokens_per_second", "error_rate"):
        value = getattr(sample, field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError(f"qualification performance {field} must be finite")
    if sample.ttft_p99 <= 0 or sample.tpot_p99 <= 0 or sample.output_tokens_per_second <= 0:
        raise ValueError("qualification performance latency/throughput measurements must be positive")

    envelope = ResourceEnvelope(
        peak_gpu_memory_bytes_per_device=resources.peak_gpu_memory_bytes_per_device,
        peak_host_memory_bytes=resources.peak_host_memory_bytes,
        max_qualified_concurrency=resources.max_qualified_concurrency,
        ttft_p99_seconds=float(sample.ttft_p99),
        tpot_p99_seconds=float(sample.tpot_p99),
        minimum_output_tokens_per_second=float(sample.output_tokens_per_second),
    )
    evidence_digest = canonical_digest({
        "qualification_evidence": evidence,
        "qualification_policy": policy,
        "resource_measurements": resources,
        "qualified_roles": qualified_roles,
        "target_host_identity_digest": host_digest,
    })
    return QualificationCertificate(
        model_stack_digest=evidence.model_stack_digest,
        evidence_digest=evidence_digest,
        qualified_roles=qualified_roles,
        resource_envelope=envelope,
        target_host_identity_digest=host_digest,
    )


__all__ = ["issue_measured_qualification_certificate"]
