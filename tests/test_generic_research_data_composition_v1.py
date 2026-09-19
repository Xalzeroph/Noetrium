from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.evidence.artifact.catalog.api import ArtifactKind, ArtifactRecord
from noetrium_platform.evidence.artifact.catalog.runtime import InMemoryArtifactRegistry
from noetrium_platform.evidence.artifact.content.api import ArtifactStorageVerificationError
from noetrium_platform.evidence.artifact.content.composition import (
    compose_filesystem_artifact_storage_bindings,
)
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity, DatasetVersion
from noetrium_platform.evidence.data.dataset.runtime import InMemoryDatasetRegistry
from noetrium_platform.evidence.data.query.api import ResearchResultKind, ResearchResultQuery
from noetrium_platform.evidence.data.query.cross.composition import (
    compose_builtin_research_result_query,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_common_artifact_storage_composition_verifies_filesystem_bytes(tmp_path) -> None:
    payload = b"portable-composition-content"
    content = tmp_path / "artifact.bin"
    content.write_bytes(payload)

    assembly = compose_filesystem_artifact_storage_bindings(tmp_path / "bindings.sqlite3")
    binding = assembly.bindings.bind(
        artifact_id="artifact:composition",
        content_sha256=_sha(payload),
        storage_provider_id="artifact.filesystem",
        location=str(content),
    )
    assert binding.content_sha256 == _sha(payload)
    assert assembly.bindings.resolve(binding.artifact_id) == binding

    content.write_bytes(b"tampered")
    with pytest.raises(ArtifactStorageVerificationError) as tampered:
        assembly.bindings.resolve(binding.artifact_id)
    assert tampered.value.code == "CONTENT_SHA256_MISMATCH"


def test_builtin_research_query_composition_wires_portable_sources() -> None:
    datasets = InMemoryDatasetRegistry()
    artifacts = InMemoryArtifactRegistry()
    scopes = InMemoryScopeRegistry()
    dataset_payload = b"dataset-content"
    report_payload = b"report-content"
    datasets.register(
        DatasetVersion(
            DatasetIdentity("evaluation", "v1"),
            PLATFORM_SCOPE,
            _sha(dataset_payload),
        )
    )

    artifacts.put(
        ArtifactRecord(
            artifact_id="report:summary",
            kind=ArtifactKind.REPORT,
            scope=PLATFORM_SCOPE,
            digest=_sha(report_payload),
            producer_component_id="project.analysis",
            media_type="application/json",
        )
    )
    query = compose_builtin_research_result_query(
        datasets=datasets,
        artifacts=artifacts,
        scopes=scopes,
    )
    page = query.query(
        ResearchResultQuery(
            kinds=(ResearchResultKind.DATASET, ResearchResultKind.REPORT),
        )
    )
    assert page.complete is True
    assert page.truncated is False
    assert page.matched_count == 2
    assert {record.reference.kind for record in page.records} == {
        ResearchResultKind.DATASET,
        ResearchResultKind.REPORT,
    }


def test_research_query_cut_is_independent_of_artifact_physical_location(tmp_path) -> None:
    payload = b"portable-report-content"
    digest = _sha(payload)
    location_a = tmp_path / "storage-a" / "report.bin"
    location_b = tmp_path / "storage-b" / "report.bin"
    location_a.parent.mkdir()
    location_b.parent.mkdir()
    location_a.write_bytes(payload)
    location_b.write_bytes(payload)

    storage_a = compose_filesystem_artifact_storage_bindings(tmp_path / "bindings-a.sqlite3")
    storage_b = compose_filesystem_artifact_storage_bindings(tmp_path / "bindings-b.sqlite3")
    binding_a = storage_a.bindings.bind(
        artifact_id="report:portable",
        content_sha256=digest,
        storage_provider_id="artifact.filesystem",
        location=str(location_a),
    )
    binding_b = storage_b.bindings.bind(
        artifact_id="report:portable",
        content_sha256=digest,
        storage_provider_id="artifact.filesystem",
        location=str(location_b),
    )
    assert binding_a.location != binding_b.location
    assert binding_a.content_sha256 == binding_b.content_sha256 == digest

    record = ArtifactRecord(
        artifact_id="report:portable",
        kind=ArtifactKind.REPORT,
        scope=PLATFORM_SCOPE,
        digest=digest,
        producer_component_id="project.analysis",
        media_type="application/octet-stream",
    )
    artifacts_a = InMemoryArtifactRegistry()
    artifacts_b = InMemoryArtifactRegistry()
    artifacts_a.put(record)
    artifacts_b.put(record)
    query = ResearchResultQuery(kinds=(ResearchResultKind.REPORT,))
    page_a = compose_builtin_research_result_query(
        datasets=InMemoryDatasetRegistry(),
        artifacts=artifacts_a,
        scopes=InMemoryScopeRegistry(),
    ).query(query)
    page_b = compose_builtin_research_result_query(
        datasets=InMemoryDatasetRegistry(),
        artifacts=artifacts_b,
        scopes=InMemoryScopeRegistry(),
    ).query(query)

    assert page_a.complete is page_b.complete is True
    assert page_a.records == page_b.records
    assert page_a.input_cut_digest == page_b.input_cut_digest
    assert page_a.query_digest == page_b.query_digest
    assert all(not hasattr(row, "location") for row in page_a.records)
