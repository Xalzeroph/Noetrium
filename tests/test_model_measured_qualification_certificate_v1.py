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
        performance=(PerformanceSample(2, 0.1, 0.2, 0.01, 0.02, 50.0, error_rate),),
        exact_output_reproducibility_checked=True,
        long_context_checked=True,
        tool_call_checked=True,
    )


def _resources() -> ResourceQualificationMeasurements:
    return ResourceQualificationMeasurements(24 << 30, 48 << 30, 2)


def test_certificate_is_derived_from_measured_evidence_and_resources() -> None:
    evidence = _evidence()
    cert = issue_measured_qualification_certificate(
        evidence, QualificationPolicy(), _resources(),
        qualified_roles=("planner",), target_host_identity_digest="b" * 64,
    )
    assert cert.model_stack_digest == evidence.model_stack_digest
    assert cert.qualified_roles == ("planner",)
    assert cert.resource_envelope.max_qualified_concurrency == 2
    assert cert.resource_envelope.ttft_p99_seconds == 0.2
    assert cert.resource_envelope.tpot_p99_seconds == 0.02
    assert cert.resource_envelope.minimum_output_tokens_per_second == 50.0
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
            evidence, QualificationPolicy(), ResourceQualificationMeasurements(1, 1, 3),
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