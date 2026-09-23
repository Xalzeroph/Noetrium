from __future__ import annotations

import pytest

from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSArtifactValueAuthority,
)
from noetrium_platform.composition.research_os_values import ResearchOSValueSubject
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.catalog.providers import SQLiteArtifactRegistry
from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
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
    first = ResearchOSArtifactValueAuthority(blobs, registry)
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

    reopened = ResearchOSArtifactValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
    )
    looked_up = reopened.lookup(subject)
    assert looked_up == published
    assert reopened.resolve(looked_up) == value
    assert reopened.reuse_proof(looked_up) == proof


def test_same_subject_cannot_be_rebound_to_different_artifact_content(tmp_path) -> None:
    authority = ResearchOSArtifactValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3"),
    )
    subject = _subject()
    authority.publish(subject, {"value": 1})

    with pytest.raises(Exception):
        authority.publish(subject, {"value": 2})


def test_catalog_tampering_or_scope_drift_fails_closed(tmp_path) -> None:
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    registry = SQLiteArtifactRegistry(tmp_path / "artifacts.sqlite3")
    authority = ResearchOSArtifactValueAuthority(blobs, registry)
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
