from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.capabilities.model.serving.api import (
    PerformanceSample, QualificationEvidence, QualificationPolicy,
    ResourceQualificationMeasurements, RoleCanaryResult,
)
from noetrium_platform.capabilities.model.serving.composition import issue_measured_qualification_certificate
from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _evidence(*, passed: int = 100, error_rate: float = 0.0) -> QualificationEvidence:
    return QualificationEvidence(
        model_stack_digest="a" * 64,
        canaries=(RoleCanaryResult("planner", 100, passed, 10, min(passed, 10), 0),),
        performance=(
            PerformanceSample(1, 0.09, 0.18, 0.009, 0.018, 30.0, error_rate),
            PerformanceSample(2, 0.1, 0.2, 0.01, 0.02, 50.0, error_rate),
        ),
        prefill_input_tokens_per_second=1000.0,
        preemptive_return=None,
        exact_output_reproducibility_checked=True,
        long_context_checked=True,
        tool_call_checked=True,
    )


def _resources() -> ResourceQualificationMeasurements:
    return ResourceQualificationMeasurements(24 << 30, 48 << 30, 2, 200)


def test_certificate_is_derived_from_measured_evidence_and_resources() -> None:
    evidence = _evidence()
    cert = issue_measured_qualification_certificate(
        evidence, QualificationPolicy(), _resources(),
        qualified_roles=("planner",), target_host_identity_digest="b" * 64,
    )
    assert cert.model_stack_digest == evidence.model_stack_digest
    assert cert.qualified_roles == ("planner",)
    assert cert.resource_envelope.max_qualified_concurrency == 2
    assert cert.resource_envelope.latency_isolation_concurrency == 1
    assert cert.resource_envelope.ttft_p99_seconds == 0.2
    assert cert.resource_envelope.tpot_p99_seconds == 0.02
    assert cert.resource_envelope.minimum_output_tokens_per_second == 50.0
    assert cert.resource_envelope.max_prefill_queued_tokens == 200
    expected = canonical_digest({
        "qualification_evidence": evidence,
        "qualification_policy": QualificationPolicy(),
        "resource_measurements": _resources(),
        "qualified_roles": ("planner",),
        "target_host_identity_digest": "b" * 64,
    })
    assert cert.evidence_digest == expected


def test_certificate_rejects_unqualified_or_unmeasured_claims() -> None:
    with pytest.raises(ValueError, match="does not satisfy policy"):
        issue_measured_qualification_certificate(
            _evidence(passed=50), QualificationPolicy(), _resources(),
            qualified_roles=("planner",), target_host_identity_digest="b" * 64,
        )
    evidence = _evidence()
    with pytest.raises(ValueError, match="exactly one sample"):
        issue_measured_qualification_certificate(
            evidence, QualificationPolicy(), ResourceQualificationMeasurements(1, 1, 3, 200),
            qualified_roles=("planner",), target_host_identity_digest="b" * 64,
        )


def test_certificate_rejects_unobserved_role_and_invalid_host_identity() -> None:
    with pytest.raises(ValueError, match="missing role canaries"):
        issue_measured_qualification_certificate(
            _evidence(), QualificationPolicy(), _resources(),
            qualified_roles=("semantic",), target_host_identity_digest="b" * 64,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        issue_measured_qualification_certificate(
            _evidence(), QualificationPolicy(), _resources(),
            qualified_roles=("planner",), target_host_identity_digest="bad",
        )



def test_exact_output_reproducibility_is_observational_by_default() -> None:
    evidence = replace(
        _evidence(),
        exact_output_reproducibility_checked=False,
    )
    cert = issue_measured_qualification_certificate(
        evidence,
        QualificationPolicy(),
        _resources(),
        qualified_roles=("planner",),
        target_host_identity_digest="b" * 64,
    )
    assert cert.qualified_roles == ("planner",)


def test_exact_output_reproducibility_can_be_explicitly_required() -> None:
    evidence = replace(
        _evidence(),
        exact_output_reproducibility_checked=False,
    )
    with pytest.raises(ValueError, match="exact-output reproducibility"):
        issue_measured_qualification_certificate(
            evidence,
            QualificationPolicy(
                require_exact_output_reproducibility=True,
            ),
            _resources(),
            qualified_roles=("planner",),
            target_host_identity_digest="b" * 64,
        )

def test_policy_can_mark_non_applicable_capabilities_without_fabricating_evidence() -> None:
    evidence = replace(_evidence(), tool_call_checked=False, long_context_checked=False)
    policy = QualificationPolicy(
        require_tool_call_checked=False,
        require_long_context_checked=False,
    )
    cert = issue_measured_qualification_certificate(
        evidence, policy, _resources(),
        qualified_roles=("planner",), target_host_identity_digest="b" * 64,
    )
    assert cert.qualified_roles == ("planner",)


def test_policy_rejects_missing_capability_when_explicitly_required() -> None:
    evidence = replace(_evidence(), long_context_checked=False)
    with pytest.raises(ValueError, match="long-context contract not checked"):
        issue_measured_qualification_certificate(
            evidence, QualificationPolicy(require_long_context_checked=True), _resources(),
            qualified_roles=("planner",), target_host_identity_digest="b" * 64,
        )

def _multi_sample_evidence(samples: tuple[PerformanceSample, ...]) -> QualificationEvidence:
    return QualificationEvidence(
        model_stack_digest="c" * 64,
        canaries=(RoleCanaryResult("planner", 100, 100, 10, 10, 0),),
        performance=samples,
        prefill_input_tokens_per_second=1000.0,
        preemptive_return=None,
        exact_output_reproducibility_checked=True,
        long_context_checked=True,
        tool_call_checked=True,
    )


def test_preferred_concurrency_uses_peak_measured_goodput_even_when_latency_rises() -> None:
    evidence = _multi_sample_evidence(
        (
            PerformanceSample(1, 0.05, 0.10, 0.005, 0.010, 10.0, 0.0),
            PerformanceSample(2, 0.06, 0.12, 0.006, 0.011, 18.0, 0.0),
            PerformanceSample(4, 0.08, 0.18, 0.008, 0.015, 30.0, 0.0),
            # Higher tail latency no longer imposes an arbitrary static knee:
            # this sample is still inside the qualified safe envelope and has
            # the highest measured successful-token goodput.
            PerformanceSample(8, 0.15, 0.31, 0.010, 0.018, 40.0, 0.0),
        )
    )
    cert = issue_measured_qualification_certificate(
        evidence,
        QualificationPolicy(),
        ResourceQualificationMeasurements(24 << 30, 48 << 30, 8, 4096),
        qualified_roles=("planner",),
        target_host_identity_digest="d" * 64,
    )
    assert cert.resource_envelope.preferred_operating_concurrency == 8


def test_preferred_concurrency_maximizes_successful_token_goodput_across_qualified_curve() -> None:
    evidence = _multi_sample_evidence(
        (
            PerformanceSample(1, 0.04, 0.09, 0.004, 0.009, 10.0, 0.0),
            PerformanceSample(2, 0.05, 0.10, 0.005, 0.010, 20.0, 0.0),
            PerformanceSample(4, 0.06, 0.12, 0.006, 0.012, 30.0, 0.0),
            # Slightly higher raw throughput but lower successful-token goodput.
            PerformanceSample(8, 0.07, 0.14, 0.007, 0.014, 30.01, 0.0009),
        )
    )
    cert = issue_measured_qualification_certificate(
        evidence,
        QualificationPolicy(),
        ResourceQualificationMeasurements(24 << 30, 48 << 30, 8, 4096),
        qualified_roles=("planner",),
        target_host_identity_digest="e" * 64,
    )
    assert cert.resource_envelope.preferred_operating_concurrency == 4


def test_preferred_concurrency_uses_lower_load_on_equal_goodput() -> None:
    evidence = _multi_sample_evidence(
        (
            PerformanceSample(1, 0.04, 0.09, 0.004, 0.009, 10.0, 0.0),
            PerformanceSample(2, 0.05, 0.10, 0.005, 0.010, 20.0, 0.0),
            PerformanceSample(4, 0.06, 0.12, 0.006, 0.012, 30.0, 0.0),
            PerformanceSample(8, 0.07, 0.14, 0.007, 0.014, 30.0, 0.0),
        )
    )
    cert = issue_measured_qualification_certificate(
        evidence,
        QualificationPolicy(),
        ResourceQualificationMeasurements(24 << 30, 48 << 30, 8, 4096),
        qualified_roles=("planner",),
        target_host_identity_digest="f" * 64,
    )
    assert cert.resource_envelope.preferred_operating_concurrency == 4


def test_latency_isolation_concurrency_is_measured_against_solo() -> None:
    evidence = _multi_sample_evidence(
        (
            PerformanceSample(1, 0.05, 0.10, 0.005, 0.010, 10.0, 0.0),
            # Equal p99 latency: batching preserves isolated responsiveness.
            PerformanceSample(2, 0.05, 0.10, 0.005, 0.010, 19.0, 0.0),
            # TPOT regression makes concurrency 4 ineligible for isolation.
            PerformanceSample(4, 0.05, 0.10, 0.006, 0.011, 32.0, 0.0),
        )
    )
    cert = issue_measured_qualification_certificate(
        evidence,
        QualificationPolicy(),
        ResourceQualificationMeasurements(24 << 30, 48 << 30, 4, 4096),
        qualified_roles=("planner",),
        target_host_identity_digest="1" * 64,
    )
    assert cert.resource_envelope.latency_isolation_concurrency == 2
