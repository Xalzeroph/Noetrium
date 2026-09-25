import json
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.qualification.api import (
    CudaFacts,
    DeploymentCapabilityFacts,
    DeploymentQualificationEvidenceRecord,
    DeploymentQualificationRequest,
    GpuCapabilityFacts,
    GpuFabricFacts,
    HostExecutionFacts,
    ModelArtifactFacts,
    OperatingSystemFacts,
    PackageIndexFacts,
    PythonRuntimeFacts,
    StorageCapabilityFacts,
)
from noetrium_platform.capabilities.model.qualification.providers.qualification_evidence import (
    FileDeploymentQualificationEvidenceStore,
    QualificationEvidenceIntegrityError,
)
from noetrium_platform.capabilities.model.qualification.runtime.qualification import DeploymentQualificationResolver


def _facts() -> DeploymentCapabilityFacts:
    return DeploymentCapabilityFacts(
        captured_at_unix=1.0,
        operating_system=OperatingSystemFacts("Linux", "Ubuntu", "22.04", "6.8", "x86_64"),
        cuda=CudaFacts("580.173.02", "13.0", "12.4", ("12",)),
        gpus=(GpuCapabilityFacts("0", "GPU-0", "RTX 3090", 24576, 24000, "8.6"),),
        python=PythonRuntimeFacts(
            "/opt/env/bin/python",
            "3.11.0",
            "pip 26.0",
            True,
            True,
            "/opt/env/lib/python3.11/site-packages",
            "2.11.0",
            "13.0",
            ("sm86",),
        ),
        model=ModelArtifactFacts(
            "example-model",
            "/models/example-model",
            "example_decoder",
            ("ExampleForConditionalGeneration",),
            "bfloat16",
            262144,
            True,
        ),
        package_indexes=(
            PackageIndexFacts(
                "vllm", "https://pypi.org/simple", ("0.27.1",),
                selected_version="0.27.1", dependency_closure_complete=True,
            ),
        ),
        host=HostExecutionFacts("test-host", "x86_64", 16, 128 << 30, 96 << 30),
        fabric=GpuFabricFacts(("GPU0 GPU1 NV1",), "2.18", "/usr/lib/libnccl.so.2"),
        storage=StorageCapabilityFacts("/models/example-model", 1 << 40, 512 << 30, 1_000_000, "xfs", "dev0", True, True),
    )


def _record() -> DeploymentQualificationEvidenceRecord:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/env/bin/python"),
        python_environment_id="example-serving",
        backends=("vllm",),
    )
    facts = _facts()
    plan = DeploymentQualificationResolver().resolve(request, facts)
    return DeploymentQualificationEvidenceRecord(1.0, request, facts, plan)


def test_file_evidence_store_round_trips_request_facts_and_plan(tmp_path: Path) -> None:
    record = _record()
    store = FileDeploymentQualificationEvidenceStore(tmp_path)

    assert store.publish(record) == record
    assert store.get(record.plan.plan_digest) == record


def test_file_evidence_store_rejects_tampered_document(tmp_path: Path) -> None:
    record = _record()
    store = FileDeploymentQualificationEvidenceStore(tmp_path)
    store.publish(record)
    path = tmp_path / f"{record.plan.plan_digest}.json"
    document = json.loads(path.read_text("utf-8"))
    document["payload"]["record_digest"] = "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(QualificationEvidenceIntegrityError):
        store.get(record.plan.plan_digest)
