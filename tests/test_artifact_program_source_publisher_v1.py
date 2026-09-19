from __future__ import annotations

from hashlib import sha256

import pytest

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRecord
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.research.execution.composition import (
    ArtifactExecutableProgramSourcePublisher,
)


class _Artifacts:
    def __init__(self) -> None:
        self.rows = {}

    def put(self, artifact):
        assert isinstance(artifact, ArtifactRecord)
        current = self.rows.get(artifact.artifact_id)
        if current is not None and current != artifact:
            raise AssertionError("immutable artifact identity drifted")
        self.rows[artifact.artifact_id] = artifact
        return artifact

    def get(self, artifact_id):
        return self.rows[artifact_id]

    def query(self, query=None):
        del query
        return tuple(self.rows.values())


class _Content:
    durability = "crash_durable"

    def __init__(self) -> None:
        self.rows = {}

    def put(self, payload, *, media_type):
        digest = sha256(payload).hexdigest()
        ref = ArtifactBlobRef(digest, len(payload), media_type)
        self.rows[digest] = bytes(payload)
        return ref

    def get(self, ref):
        return self.rows[ref.content_sha256]

    def verify(self, ref):
        payload = self.rows.get(ref.content_sha256)
        return (
            payload is not None
            and sha256(payload).hexdigest() == ref.content_sha256
            and len(payload) == ref.size_bytes
        )


class _VolatileContent(_Content):
    durability = "process_local"


def test_artifact_program_source_publisher_binds_logical_and_blob_identity() -> None:
    artifacts = _Artifacts()
    content = _Content()
    publisher = ArtifactExecutableProgramSourcePublisher(
        artifacts,
        content,
        ScopeIdentity(ScopeKind.RUN, "voyager-run"),
    )
    source_text = "async function mineStone(bot) { return true; }"

    published = publisher.publish_source(
        program_id="voyager.skill.mineStone",
        language="javascript",
        source_text=source_text,
    )

    expected = sha256(source_text.encode("utf-8")).hexdigest()
    assert published.identity.content_sha256 == expected
    assert published.content.content_sha256 == expected
    assert content.get(published.content) == source_text.encode("utf-8")
    record = artifacts.get(published.identity.artifact_id)
    assert record.digest == expected
    assert record.scope == ScopeIdentity(ScopeKind.RUN, "voyager-run")
    assert published.identity.artifact_id.endswith(expected)


def test_artifact_program_source_publisher_versions_identity_by_content() -> None:
    publisher = ArtifactExecutableProgramSourcePublisher(
        _Artifacts(),
        _Content(),
        ScopeIdentity(ScopeKind.RUN, "run"),
    )

    first = publisher.publish_source(
        program_id="paper.skill",
        language="javascript",
        source_text="return 1;",
    )
    second = publisher.publish_source(
        program_id="paper.skill",
        language="javascript",
        source_text="return 2;",
    )

    assert first.identity.artifact_id != second.identity.artifact_id
    assert first.identity.content_sha256 != second.identity.content_sha256


def test_artifact_program_source_publisher_rejects_volatile_bytes() -> None:
    with pytest.raises(ValueError, match="crash-durable"):
        ArtifactExecutableProgramSourcePublisher(
            _Artifacts(),
            _VolatileContent(),
            ScopeIdentity(ScopeKind.RUN, "run"),
        )
