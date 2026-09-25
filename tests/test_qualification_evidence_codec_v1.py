from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.qualification.api import (
    CudaFacts,
    DeploymentCapabilityFacts,
    DeploymentQualificationEvidenceRecord,
    DeploymentQualificationRequest,
    ModelArtifactFacts,
    OperatingSystemFacts,
    PythonRuntimeFacts,
)
from noetrium_platform.capabilities.model.qualification.providers.qualification_evidence_codec import (
    QualificationEvidenceCodecError,
    decode_qualification_record,
    encode_qualification_record,
)
from noetrium_platform.capabilities.model.qualification.runtime.qualification import DeploymentQualificationResolver


def _record() -> DeploymentQualificationEvidenceRecord:
    request = DeploymentQualificationRequest(
        "model", Path("/models/model"), Path("/opt/python/bin/python"), backends=("vllm",)
    )
    facts = DeploymentCapabilityFacts(
        captured_at_unix=1.0,
        operating_system=OperatingSystemFacts("Linux", "Ubuntu", "24.04", "6.8", "x86_64"),
        cuda=CudaFacts(None, None, None),
        gpus=(),
        python=PythonRuntimeFacts("/opt/python/bin/python", "3.11.0", None, False, False, None, None, None),
        model=ModelArtifactFacts("model", "/models/model", None, (), None, None, False),
        package_indexes=(),
    )
    plan = DeploymentQualificationResolver().resolve(request, facts)
    return DeploymentQualificationEvidenceRecord(1.0, request, facts, plan)


def test_strict_codec_round_trips_current_record() -> None:
    record = _record()
    assert decode_qualification_record(encode_qualification_record(record)) == record


def test_strict_codec_rejects_string_boolean() -> None:
    payload = encode_qualification_record(_record())
    payload["facts"]["python"]["ensurepip_available"] = "false"
    with pytest.raises(QualificationEvidenceCodecError, match="must be a boolean"):
        decode_qualification_record(payload)


def test_strict_codec_rejects_string_integer() -> None:
    payload = encode_qualification_record(_record())
    payload["request"]["tensor_parallel"] = "1"
    with pytest.raises(QualificationEvidenceCodecError, match="must be an integer"):
        decode_qualification_record(payload)


def test_strict_codec_rejects_extra_nested_field() -> None:
    payload = encode_qualification_record(_record())
    payload["facts"]["python"]["unexpected"] = "value"
    with pytest.raises(QualificationEvidenceCodecError, match="field set mismatch"):
        decode_qualification_record(payload)


def test_strict_codec_rejects_forged_derived_digest() -> None:
    payload = encode_qualification_record(_record())
    payload["plan"]["plan_digest"] = "0" * 64
    with pytest.raises(QualificationEvidenceCodecError, match="derived value mismatch"):
        decode_qualification_record(payload)
