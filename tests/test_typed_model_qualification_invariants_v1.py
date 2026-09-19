from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.qualification.api import (
    BackendCandidatePlan,
    CandidateDecision,
    DeploymentQualificationApplicationReceipt,
    DeploymentQualificationPlan,
    DeploymentQualificationRuntimeReceipt,
    DeploymentRuntimeQualificationStatus,
    InstallPackage,
    QualificationCommandReceipt,
    QualificationMaterializationStatus,
    RuntimeCheckReceipt,
)


_SHA = "a" * 64


def _command() -> QualificationCommandReceipt:
    return QualificationCommandReceipt("pip-install", _SHA, 0, "b" * 64, "c" * 64)


def _check() -> RuntimeCheckReceipt:
    return RuntimeCheckReceipt("backend-import", _SHA, 0, "b" * 64, "c" * 64)

@pytest.mark.parametrize("value", ("", "z" * 64, "A" * 64, "a" * 63))
def test_command_receipt_rejects_non_sha256_identity(value: str) -> None:
    with pytest.raises(ValueError):
        QualificationCommandReceipt("pip-install", value, 0, "b" * 64, "c" * 64)


def test_command_and_runtime_receipts_reject_boolean_return_code() -> None:
    with pytest.raises(ValueError):
        QualificationCommandReceipt("pip-install", _SHA, True, "b" * 64, "c" * 64)
    with pytest.raises(ValueError):
        RuntimeCheckReceipt("backend-import", _SHA, False, "b" * 64, "c" * 64)


def test_runtime_check_rejects_invalid_output_digest_and_preview_type() -> None:
    with pytest.raises(ValueError):
        RuntimeCheckReceipt("backend-import", _SHA, 0, "not-a-digest", "c" * 64)
    with pytest.raises(ValueError):
        RuntimeCheckReceipt(
            "backend-import", _SHA, 0, "b" * 64, "c" * 64, stdout_preview=1  # type: ignore[arg-type]
        )

def test_install_package_and_candidate_require_typed_nonempty_values() -> None:
    with pytest.raises(ValueError):
        InstallPackage("", "1.0", "https://index.example/simple")
    with pytest.raises(ValueError):
        BackendCandidatePlan(
            "vllm",
            CandidateDecision.ACCEPTED,
            "1.0",
            ("not-a-package",),  # type: ignore[arg-type]
            (),
            (),
        )


def test_qualification_plan_requires_sha_bound_candidate_authority() -> None:
    candidate = BackendCandidatePlan(
        "vllm",
        CandidateDecision.ACCEPTED,
        "1.0",
        (InstallPackage("vllm", "1.0", "https://index.example/simple"),),
        (),
        (),
    )
    with pytest.raises(ValueError):
        DeploymentQualificationPlan("not-a-digest", _SHA, (candidate,), "vllm")
    with pytest.raises(ValueError):
        DeploymentQualificationPlan(_SHA, "b" * 64, (), None)

def test_application_receipt_rejects_untyped_or_unbound_evidence() -> None:
    with pytest.raises(ValueError):
        DeploymentQualificationApplicationReceipt(
            "x" * 64,
            "serving-env",
            "vllm",
            (),
            (_command(),),
            _command(),
            QualificationMaterializationStatus.SUCCEEDED,
        )
    with pytest.raises(ValueError):
        DeploymentQualificationApplicationReceipt(
            _SHA,
            "",
            "vllm",
            (),
            (_command(),),
            _command(),
            QualificationMaterializationStatus.SUCCEEDED,
        )


def test_runtime_receipt_requires_bound_digests_and_typed_checks() -> None:
    with pytest.raises(ValueError):
        DeploymentQualificationRuntimeReceipt(
            "not-a-digest",
            _SHA,
            "serving-env",
            "vllm",
            (_check(),),
            DeploymentRuntimeQualificationStatus.PASSED,
        )