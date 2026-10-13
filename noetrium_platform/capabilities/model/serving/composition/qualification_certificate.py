from __future__ import annotations

import math

from noetrium_platform.capabilities.model.serving.api import (
    QualificationCertificate,
    QualificationEvidence,
    QualificationPolicy,
    ResourceEnvelope,
    ResourceQualificationMeasurements,
    evaluate_qualification,
    measured_latency_isolation_concurrency,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _sha256(value: str, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _preferred_operating_concurrency(
    evidence: QualificationEvidence,
    *,
    max_qualified_concurrency: int,
) -> int:
    """Choose the measured successful-token goodput optimum.

    Qualification already establishes the safe concurrency envelope and records
    the complete measured operating curve.  The preferred point is only a
    runtime *starting prior*, never a capacity limit, so it should not inject an
    arbitrary latency multiplier into lifetime admission.  Start at the measured
    concurrency with maximum successful output-token goodput and let the live
    adaptive window move downward on queue/preemption/rate pressure or probe
    upward when later evidence supports it.  Equal-goodput ties choose the lower
    concurrency because it provides identical work with less occupied capacity.
    """
    samples = tuple(
        sorted(
            (
                row
                for row in evidence.performance
                if row.concurrency <= max_qualified_concurrency
            ),
            key=lambda row: row.concurrency,
        )
    )
    if not samples:
        raise ValueError(
            "qualification evidence has no performance samples within "
            "the qualified concurrency ceiling"
        )
    if len({row.concurrency for row in samples}) != len(samples):
        raise ValueError(
            "qualification performance concurrency samples must be unique"
        )
    if samples[-1].concurrency != max_qualified_concurrency:
        raise ValueError(
            "qualification evidence does not measure the qualified ceiling"
        )
    for sample in samples:
        if (
            sample.ttft_p99 <= 0
            or sample.tpot_p99 <= 0
            or sample.output_tokens_per_second <= 0
        ):
            raise ValueError(
                "qualification operating-point samples require positive "
                "TTFT-p99, TPOT-p99 and output throughput"
            )
    if len(samples) == 1:
        return samples[0].concurrency

    def token_goodput(sample) -> float:
        return float(sample.output_tokens_per_second) * (1.0 - float(sample.error_rate))

    best_goodput = max(token_goodput(row) for row in samples)
    return min(
        row.concurrency
        for row in samples
        if token_goodput(row) == best_goodput
    )


def issue_measured_qualification_certificate(
    evidence: QualificationEvidence,
    policy: QualificationPolicy,
    resources: ResourceQualificationMeasurements,
    *,
    qualified_roles: tuple[str, ...],
    target_host_identity_digest: str,
) -> QualificationCertificate:
    """Issue a certificate from measured performance and Authority bounds.

    The selected request concurrency must have an explicit performance sample.
    Memory peaks remain observed measurements; aggregate token residency is a
    deterministic bound derived upstream from the canonical planner KV budget
    and immutable model geometry. A caller cannot independently author either
    performance or resource-capacity claims.
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

    latency_isolation_concurrency = measured_latency_isolation_concurrency(
        evidence.performance,
        max_qualified_concurrency=resources.max_qualified_concurrency,
    )
    preferred_concurrency = _preferred_operating_concurrency(
        evidence,
        max_qualified_concurrency=resources.max_qualified_concurrency,
    )
    solo_sample = next(
        row for row in evidence.performance if row.concurrency == 1
    )
    preemptive_sample = evidence.preemptive_return
    preemptive_latency_isolation = bool(
        preemptive_sample is not None
        and preemptive_sample.borrower_active_during_return
        and preemptive_sample.borrower_concurrency
        >= resources.max_qualified_concurrency
        and preemptive_sample.return_concurrency
        >= latency_isolation_concurrency
        and float(preemptive_sample.return_ttft_p99)
        <= float(solo_sample.ttft_p99)
        and float(preemptive_sample.return_tpot_p99)
        <= float(solo_sample.tpot_p99)
    )
    preferred_samples = tuple(
        item
        for item in evidence.performance
        if item.concurrency == preferred_concurrency
    )
    if len(preferred_samples) != 1:
        raise ValueError(
            "qualification evidence must contain exactly one preferred "
            "operating-point sample"
        )
    preferred_sample = preferred_samples[0]
    prefill_rate = evidence.prefill_input_tokens_per_second
    if (
        isinstance(prefill_rate, bool)
        or not isinstance(prefill_rate, (int, float))
        or not math.isfinite(float(prefill_rate))
        or float(prefill_rate) <= 0.0
    ):
        raise ValueError(
            "qualification prefill_input_tokens_per_second must be finite "
            "and positive"
        )
    # The prefill window is an Authority-proven aggregate token-residency
    # bound, not a latency-derived estimate. TTFT times single-request prefill
    # throughput proves only service time and can over-admit long prompts.
    max_prefill_queued_tokens = resources.max_prefill_queued_tokens
    envelope = ResourceEnvelope(
        peak_gpu_memory_bytes_per_device=resources.peak_gpu_memory_bytes_per_device,
        peak_host_memory_bytes=resources.peak_host_memory_bytes,
        max_qualified_concurrency=resources.max_qualified_concurrency,
        latency_isolation_concurrency=latency_isolation_concurrency,
        preemptive_latency_isolation=preemptive_latency_isolation,
        preemptive_return_ttft_p99_seconds=(
            None
            if preemptive_sample is None
            else float(preemptive_sample.return_ttft_p99)
        ),
        preemptive_return_tpot_p99_seconds=(
            None
            if preemptive_sample is None
            else float(preemptive_sample.return_tpot_p99)
        ),
        ttft_p99_seconds=float(sample.ttft_p99),
        tpot_p99_seconds=float(sample.tpot_p99),
        minimum_output_tokens_per_second=float(sample.output_tokens_per_second),
        max_prefill_queued_tokens=max_prefill_queued_tokens,
        prefill_input_tokens_per_second=float(prefill_rate),
        preferred_operating_concurrency=preferred_concurrency,
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
