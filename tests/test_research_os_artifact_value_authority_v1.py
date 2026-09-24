from __future__ import annotations

import pytest

from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSImmutableValueAuthority,
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
    first = ResearchOSImmutableValueAuthority(
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

    reopened = ResearchOSImmutableValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )
    looked_up = reopened.lookup(subject)
    assert looked_up == published
    assert reopened.resolve(looked_up) == value
    assert reopened.reuse_proof(looked_up) == proof


def test_same_subject_cannot_be_rebound_to_different_artifact_content(tmp_path) -> None:
    authority = ResearchOSImmutableValueAuthority(
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
    authority = ResearchOSImmutableValueAuthority(
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
    authority = ResearchOSImmutableValueAuthority(
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



def test_immutable_value_authority_covers_every_research_value_kind(tmp_path) -> None:
    authority = ResearchOSImmutableValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )

    assert authority.supported_kinds == frozenset(ResearchValueKind)
    for index, kind in enumerate(ResearchValueKind):
        source = ResearchOSValueSubject(
            canonical_digest({"cut": f"source-{kind.value}"}),
            "paper::node",
            f"value-{index}",
            kind,
            canonical_digest({"semantic": kind.value}),
        )
        value = {"kind": kind.value, "index": index}
        published = authority.publish(source, value)
        assert authority.lookup(source) == published
        assert authority.resolve(published) == value

        target = ResearchOSValueSubject(
            canonical_digest({"cut": f"target-{kind.value}"}),
            source.graph_node_id,
            source.output_name,
            kind,
            source.semantic_digest,
        )
        reused = authority.reuse(published, target)
        assert reused.subject == target
        assert reused.content_digest == published.content_digest
        assert authority.resolve(reused) == value
        assert len(authority.reuse_proof(reused)) == 64


def test_immutable_value_reuse_rejects_cross_kind_rebinding(tmp_path) -> None:
    authority = ResearchOSImmutableValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "retention.sqlite3"),
    )
    source = ResearchOSValueSubject(
        canonical_digest({"cut": "source"}),
        "paper::node",
        "value",
        ResearchValueKind.DATA,
        canonical_digest({"semantic": "same"}),
    )
    published = authority.publish(source, {"value": 1})
    target = ResearchOSValueSubject(
        canonical_digest({"cut": "target"}),
        source.graph_node_id,
        source.output_name,
        ResearchValueKind.METRIC,
        source.semantic_digest,
    )
    with pytest.raises(ValueError, match="reuse kind drifted"):
        authority.reuse(published, target)
