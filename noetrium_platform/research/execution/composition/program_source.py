from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactRegistryPort,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobStorePort
from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.research.execution.api import (
    PublishedExecutableProgramSource,
)


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactExecutableProgramSourcePublisher:
    """Publish generated executable source through existing Artifact authorities.

    The blob store owns exact bytes. The artifact registry owns the immutable
    logical research identity. The publisher creates no second source authority.
    """

    artifacts: ArtifactRegistryPort
    content: ArtifactBlobStorePort
    scope: ScopeIdentity
    producer_component_id: str = "research.execution.program-source"
    retention: ArtifactRetention = ArtifactRetention.RUN

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, ArtifactRegistryPort):
            raise TypeError(
                "program source publisher requires ArtifactRegistryPort"
            )
        if not isinstance(self.content, ArtifactBlobStorePort):
            raise TypeError(
                "program source publisher requires ArtifactBlobStorePort"
            )
        if getattr(self.content, "durability", None) != "crash_durable":
            raise ValueError(
                "program source publisher requires crash-durable blob storage"
            )
        if type(self.scope) is not ScopeIdentity:
            raise TypeError("program source publisher requires ScopeIdentity")
        _text(
            self.producer_component_id,
            "program source publisher producer_component_id",
        )
        if not isinstance(self.retention, ArtifactRetention):
            raise TypeError(
                "program source publisher retention must be ArtifactRetention"
            )

    def publish_source(
        self,
        *,
        program_id: str,
        language: str,
        source_text: str,
    ) -> PublishedExecutableProgramSource:
        program_id = _text(program_id, "executable source program_id")
        language = _text(language, "executable source language")
        if type(source_text) is not str or not source_text:
            raise ValueError("executable source text must be non-empty")
        raw = source_text.encode("utf-8")
        media_type = "text/plain; charset=utf-8"
        blob = self.content.put(raw, media_type=media_type)
        if not self.content.verify(blob):
            raise RuntimeError(
                "published executable source blob failed content verification"
            )
        artifact_id = (
            f"executable-source:{program_id}:{language}:"
            f"{blob.content_sha256}"
        )
        record = self.artifacts.put(
            ArtifactRecord(
                artifact_id=artifact_id,
                kind=ArtifactKind.SCIENTIFIC,
                scope=self.scope,
                digest=blob.content_sha256,
                producer_component_id=self.producer_component_id,
                producer_operation_id="publish_source",
                media_type=media_type,
                retention=self.retention,
                metadata=(("language", language), ("program_id", program_id)),
            )
        )
        if (
            record.artifact_id != artifact_id
            or record.digest != blob.content_sha256
        ):
            raise RuntimeError(
                "artifact registry returned foreign executable source identity"
            )
        return PublishedExecutableProgramSource(
            identity=ArtifactContentIdentity(
                record.artifact_id,
                record.digest,
            ),
            content=blob,
        )


__all__ = ["ArtifactExecutableProgramSourcePublisher"]
