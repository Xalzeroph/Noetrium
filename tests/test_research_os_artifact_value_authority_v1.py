from __future__ import annotations

import pytest

from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSArtifactValueAuthority,
)
from noetrium_platform.composition.research_os_values import ResearchOSValueSubject
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRegistryConflict,
    ArtifactRecord,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.catalog.providers import SQLiteArtifactRegistry
from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
from noetrium_platform.evidence.artifact.retention.providers import (
    SQLiteArtifactRetentionStore,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.product.research_os import ResearchValueKind


def _subject(seed: str = "one") -> ResearchOSValueSubject:
    return ResearchOSValueSubject(
        canonical_digest({"cut": seed}),
        "paper::experiment",
        "report",
        ResearchValueKind.ARTIFACT,
        canonical_digest({"semantic": seed}),
    )


def test_artifact_value_authority_is_durable_and_content_addressed(tmp_path) -> None:
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    registry = SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    first = ResearchOSArtifactValueAuthority(
        blobs,
        registry,
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )
    subject = _subject()

    value = {
        "schema": "research-os.experiment-report-ref.v1",
        "manifest": {
            "generation": "a" * 64,
            "content_sha256": "b" * 64,
        },
    }
    published = first.publish(subject, value)
    assert published.content_digest is not None
    assert first.resolve(published) == value
    proof = first.reuse_proof(published)
    assert len(proof) == 64
    retention = SQLiteArtifactRetentionStore(
        tmp_path / "retention.sqlite3"
    ).get(published.authority_ref)
    assert retention.retention is ArtifactRetention.RUN
    assert retention.pinned
    assert retention.reason_refs == (subject.subject_digest,)

    reopened = ResearchOSArtifactValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )
    looked_up = reopened.lookup(subject)
    assert looked_up == published
    assert reopened.resolve(looked_up) == value
    assert reopened.reuse_proof(looked_up) == proof


def test_same_subject_cannot_be_rebound_to_different_artifact_content(tmp_path) -> None:
    authority = ResearchOSArtifactValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )
    subject = _subject()
    authority.publish(subject, {"value": 1})

    with pytest.raises(ArtifactRegistryConflict):
        authority.publish(subject, {"value": 2})


def test_catalog_tampering_or_scope_drift_fails_closed(tmp_path) -> None:
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    registry = SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    authority = ResearchOSArtifactValueAuthority(
        blobs,
        registry,
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )
    subject = _subject()
    published = authority.publish(subject, {"value": 1})

    other_subject = _subject("other")
    with pytest.raises(KeyError):
        authority.lookup(other_subject)

    stored = registry.get(published.authority_ref)
    assert stored.scope == ScopeIdentity(
        ScopeKind.RUN,
        subject.execution_cut_id,
    )
    assert stored.kind is ArtifactKind.SCIENTIFIC
    assert stored.retention is ArtifactRetention.RUN


def test_artifact_value_authority_rebinds_same_content_across_execution_cuts(tmp_path) -> None:
    authority = ResearchOSArtifactValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )
    source = _subject()
    published = authority.publish(source, {"value": 7})
    target = ResearchOSValueSubject(
        canonical_digest({"cut": "target"}),
        source.graph_node_id,
        source.output_name,
        source.kind,
        source.semantic_digest,
    )

    reused = authority.reuse(published, target)

    assert reused.subject == target
    assert reused.authority_id == published.authority_id
    assert reused.authority_ref != published.authority_ref
    assert reused.content_digest == published.content_digest
    assert authority.resolve(reused) == authority.resolve(published) == {"value": 7}
    assert len(authority.reuse_proof(reused)) == 64
    retention = SQLiteArtifactRetentionStore(
        tmp_path / "retention.sqlite3"
    ).get(reused.authority_ref)
    assert retention.retention is ArtifactRetention.RUN
    assert retention.pinned
    assert retention.reason_refs == (target.subject_digest,)
