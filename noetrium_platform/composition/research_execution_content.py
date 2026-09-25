"""Shared immutable content substrate for ResearchPortfolio execution.

Materialization happens before Research OS execution. Both phases must observe the
same Artifact authorities; otherwise a benchmark can prove task identity but the
Trial runtime cannot recover the immutable task payload.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactRegistryPort,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.catalog.providers import (
    SQLiteArtifactRegistry,
)
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobResolverPort,
    ArtifactBlobStorePort,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.evidence.artifact.reference.api import (
    ArtifactReference,
    ArtifactReferenceNotFound,
    ArtifactReferencePort,
)
from noetrium_platform.evidence.artifact.reference.providers import (
    SQLiteArtifactReferenceStore,
)
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    freeze_json,
    thaw_json,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    TaskArtifactSpec,
    TaskVerifierArtifact,
    TrialExecutionRequest,
)


@dataclass(frozen=True, slots=True)
class ResearchExecutionContentAuthorities:
    root: Path
    blobs: ArtifactBlobStorePort
    artifacts: ArtifactRegistryPort
    references: ArtifactReferencePort

    def __post_init__(self) -> None:
        root = Path(self.root).expanduser().absolute()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise ValueError(
                "research execution content root must be a real directory"
            )
        if not isinstance(self.blobs, ArtifactBlobStorePort):
            raise TypeError(
                "research execution content blobs must satisfy ArtifactBlobStorePort"
            )
        if not isinstance(self.artifacts, ArtifactRegistryPort):
            raise TypeError(
                "research execution content artifacts must satisfy ArtifactRegistryPort"
            )
        if not isinstance(self.references, ArtifactReferencePort):
            raise TypeError(
                "research execution content references must satisfy ArtifactReferencePort"
            )
        object.__setattr__(self, "root", root)

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "schema": "noetrium.research-execution-content.v1",
                "root": self.root.as_posix(),
                "blob_durability": getattr(self.blobs, "durability", None),
                "artifact_authority": type(self.artifacts).__qualname__,
                "reference_authority": type(self.references).__qualname__,
            }
        )

    def publish(
        self,
        *,
        reference_id: str,
        scope: ScopeIdentity,
        payload: bytes,
        media_type: str,
        kind: ArtifactKind = ArtifactKind.DATASET,
        retention: ArtifactRetention = ArtifactRetention.PROJECT,
        producer_component_id: str = "research-execution-materializer",
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactReference:
        if type(reference_id) is not str or not reference_id.strip():
            raise ValueError("research content reference_id must be non-empty")
        if type(scope) is not ScopeIdentity:
            raise TypeError("research content scope must be ScopeIdentity")
        if type(payload) is not bytes:
            raise TypeError("research content payload must be bytes")
        if type(media_type) is not str or not media_type.strip():
            raise ValueError("research content media_type must be non-empty")
        if not isinstance(kind, ArtifactKind):
            raise TypeError("research content kind must be ArtifactKind")
        if not isinstance(retention, ArtifactRetention):
            raise TypeError("research content retention must be ArtifactRetention")
        if type(producer_component_id) is not str or not producer_component_id.strip():
            raise ValueError(
                "research content producer_component_id must be non-empty"
            )
        rows = tuple(
            sorted(
                (() if metadata is None else metadata.items()),
                key=lambda row: row[0],
            )
        )
        if any(
            type(key) is not str
            or not key.strip()
            or type(value) is not str
            for key, value in rows
        ):
            raise TypeError("research content metadata must be text pairs")

        blob = self.blobs.put(payload, media_type=media_type)
        artifact_id = "research-content-" + canonical_digest(
            {
                "scope": scope.key,
                "reference_id": reference_id,
                "content_sha256": blob.content_sha256,
                "media_type": media_type,
            }
        )
        record = ArtifactRecord(
            artifact_id=artifact_id,
            kind=kind,
            scope=scope,
            digest=blob.content_sha256,
            producer_component_id=producer_component_id,
            media_type=media_type,
            retention=retention,
            metadata=rows,
        )
        stored = self.artifacts.put(record)
        if stored != record:
            raise RuntimeError("research content artifact registration drifted")

        try:
            current = self.references.resolve(reference_id, scope)
        except ArtifactReferenceNotFound:
            current = None
        if current is not None:
            if current.artifact_id != artifact_id:
                raise ValueError(
                    "immutable research content reference already points to "
                    "different content"
                )
            return current
        return self.references.compare_and_set(
            reference_id,
            scope,
            expected_generation=0,
            artifact_id=artifact_id,
        )

    def read(self, reference: ArtifactReference) -> bytes:
        if type(reference) is not ArtifactReference:
            raise TypeError("research content read requires ArtifactReference")
        current = self.references.resolve(
            reference.reference_id,
            reference.scope,
        )
        if current != reference:
            raise ValueError("research content reference generation drifted")
        record = self.artifacts.get(reference.artifact_id)
        resolver = self.blobs
        if not isinstance(resolver, ArtifactBlobResolverPort):
            raise TypeError(
                "research content blob store must support immutable resolution"
            )
        blob = resolver.resolve(
            record.digest,
            media_type=record.media_type,
        )
        payload = self.blobs.get(blob)
        if blob.content_sha256 != record.digest:
            raise ValueError("research content blob/catalog digest drifted")
        return payload


@dataclass(frozen=True, slots=True)
class ResearchExecutionVerifierArtifactPublisher:
    """Artifact-authority-backed verifier handoff publisher."""

    content: ResearchExecutionContentAuthorities

    def __post_init__(self) -> None:
        if type(self.content) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "verifier artifact publisher requires "
                "ResearchExecutionContentAuthorities"
            )

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "publisher": "research-execution-verifier-artifact.v1",
                "content_authority": self.content.identity_digest,
            }
        )

    def publish(
        self,
        *,
        request: TrialExecutionRequest,
        declaration: TaskArtifactSpec,
        payload: object,
    ) -> TaskVerifierArtifact:
        if type(request) is not TrialExecutionRequest:
            raise TypeError(
                "verifier artifact publish requires TrialExecutionRequest"
            )
        if type(declaration) is not TaskArtifactSpec:
            raise TypeError(
                "verifier artifact publish requires TaskArtifactSpec"
            )
        frozen = freeze_json(payload)
        encoded = json.dumps(
            thaw_json(frozen),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        scope = ScopeIdentity(ScopeKind.RUN, request.run_id)
        reference = self.content.publish(
            reference_id=(
                "verifier:"
                f"{request.assignment.assignment_digest}:"
                f"{declaration.artifact_id}"
            ),
            scope=scope,
            payload=encoded,
            media_type="application/json",
            kind=ArtifactKind.SCIENTIFIC,
            retention=ArtifactRetention.RUN,
            producer_component_id=(
                "noetrium.verifier-stage-workload-provider"
            ),
            metadata={
                "task_id": (
                    ""
                    if request.assignment.task_id is None
                    else request.assignment.task_id
                ),
                "artifact_id": declaration.artifact_id,
                "assignment_digest": (
                    request.assignment.assignment_digest
                ),
            },
        )
        return TaskVerifierArtifact(declaration, reference)


def compose_research_execution_content(
    root: str | Path,
) -> ResearchExecutionContentAuthorities:
    resolved = Path(root).expanduser().absolute()
    resolved.mkdir(parents=True, exist_ok=True)
    return ResearchExecutionContentAuthorities(
        resolved,
        DirectoryArtifactBlobStore(resolved / "blobs"),
        SQLiteArtifactRegistry(resolved / "artifact-catalog.sqlite3"),
        SQLiteArtifactReferenceStore(resolved / "artifact-references.sqlite3"),
    )


__all__ = [
    "ResearchExecutionContentAuthorities",
    "ResearchExecutionVerifierArtifactPublisher",
    "compose_research_execution_content",
]
