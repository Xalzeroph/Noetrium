from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import pytest

from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat, build_runtime_qualification_receipt
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PersistedQualifiedModelEndpointBinding,
    QualifiedModelClosurePublicationError,
    load_qualified_model_deployment_closure,
    publish_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from tests.test_qualified_closure_publication_v3 import _publication


def _heartbeat_ref(heartbeat: ServiceHeartbeat) -> str:
    return (
        f"heartbeat:{heartbeat.deployment_id}:{heartbeat.pid}:"
        f"{heartbeat.process_start_marker}:{heartbeat.timestamp}"
    )
def test_process_restart_changes_runtime_qualification_identity() -> None:
    publication = _publication()
    deployment = publication.deployments[0]
    certificate = deployment.certificate
    now = time.time()
    common = dict(
        deployment_id=deployment.deployment_id,
        stack_digest=deployment.stack.digest(),
        argv_digest="a" * 64,
        ready=True,
        qualification_digest=certificate.digest(),
        timestamp=now - 0.1,
    )
    first_heartbeat = ServiceHeartbeat(pid=101, process_start_marker="start-a", **common)
    second_heartbeat = ServiceHeartbeat(pid=202, process_start_marker="start-b", **common)
    first = build_runtime_qualification_receipt(
        deployment, first_heartbeat, required_roles=("planner",),
        evidence_refs=(_heartbeat_ref(first_heartbeat),), max_heartbeat_age_seconds=30.0, now=now,
    )
    second = build_runtime_qualification_receipt(
        deployment, second_heartbeat, required_roles=("planner",),
        evidence_refs=(_heartbeat_ref(second_heartbeat),), max_heartbeat_age_seconds=30.0, now=now,
    )
    assert first.digest() != second.digest()
    assert first.evidence_refs != second.evidence_refs
def test_opaque_runtime_evidence_reference_is_rejected() -> None:
    publication = _publication()
    deployment = publication.deployments[0]
    certificate = deployment.certificate
    now = time.time()
    heartbeat = ServiceHeartbeat(
        deployment.deployment_id,
        deployment.stack.digest(),
        101,
        "start-a",
        "a" * 64,
        True,
        certificate.digest(),
        now - 0.1,
    )
    with pytest.raises(ValueError, match="exact live heartbeat evidence"):
        build_runtime_qualification_receipt(
            deployment,
            heartbeat,
            required_roles=("planner",),
            evidence_refs=("opaque-unverified-string",),
            max_heartbeat_age_seconds=30.0,
            now=now,
        )
def test_elapsed_receipt_can_be_published_when_generation_is_unchanged(tmp_path: Path) -> None:
    publication = _publication()
    receipt = publication.runtime_qualification_receipts[0]
    published = publish_qualified_model_deployment_closure(
        tmp_path / "closure.json",
        publication,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
        now=receipt.valid_until + 3600.0,
    )
    assert published.closure_digest

def test_elapsed_receipt_remains_bindable_after_publication(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "closure.json"
    publish_qualified_model_deployment_closure(
        path,
        publication,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )
    closure = load_qualified_model_deployment_closure(
        path,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )
    receipt = publication.runtime_qualification_receipts[0]
    binding = PersistedQualifiedModelEndpointBinding(
        closure,
        clock=lambda: receipt.valid_until + 1.0,
    )
    resolved = binding.binding_for(role="planner", capability_id="generation", input_schema_id="model.generation.request.v1", output_schema_id="model.generation.response.v1", prompt_generation="prompt-v1")
    assert resolved.role == "planner"
    assert resolved.deployment_id == publication.deployments[0].deployment_id
