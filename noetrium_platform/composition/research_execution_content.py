"""Shared immutable content substrate for ResearchPortfolio execution.

Materialization happens before Research OS execution. Both phases must observe the
same Artifact authorities; otherwise a benchmark can prove task identity but the
Trial runtime cannot recover the immutable task payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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
    ArtifactReferencePort,
)
from noetrium_platform.evidence.artifact.reference.providers import (
    SQLiteArtifactReferenceStore,
)
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    TaskArtifactSpec,
    TaskVerifierArtifact,
    TrialExecutionReceipt,
    TrialExecutionRequest,
)


@dataclass(frozen=True, slots=True)
class ResearchContentPublication:
    reference_id: str
    scope: ScopeIdentity
    payload: bytes
    media_type: str
    kind: ArtifactKind = ArtifactKind.DATASET
    retention: ArtifactRetention = ArtifactRetention.PROJECT
    producer_component_id: str = "research-execution-materializer"
    metadata: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ResearchExecutionContentAuthorities:
    root: Path
    blobs: ArtifactBlobStorePort
    artifacts: ArtifactRegistryPort
    references: ArtifactReferencePort
    _identity_digest: str = field(
        init=False,
        repr=False,
        compare=False,
        metadata={"transient": True},
    )

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
        object.__setattr__(
            self,
            "_identity_digest",
            canonical_digest(
                {
                    "schema": "noetrium.research-execution-content.v1",
                    "root": root.as_posix(),
                    "blob_durability": getattr(self.blobs, "durability", None),
                    "artifact_authority": type(self.artifacts).__qualname__,
                    "reference_authority": type(self.references).__qualname__,
                }
            ),
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def close(self) -> None:
        errors: list[BaseException] = []
        for label, authority in (
            ("artifact references", self.references),
            ("artifact catalog", self.artifacts),
            ("artifact blobs", self.blobs),
        ):
            close = getattr(authority, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except BaseException as exc:
                exc.add_note(f"while closing {label}")
                errors.append(exc)
        if errors:
            raise ExceptionGroup(
                "research execution content close failed",
                errors,
            )

    def publish_many(
        self,
        publications: tuple[ResearchContentPublication, ...],
    ) -> tuple[ArtifactReference, ...]:
        if type(publications) is not tuple or any(
            type(row) is not ResearchContentPublication for row in publications
        ):
            raise TypeError(
                "research content publish_many requires ResearchContentPublication tuple"
            )
        if not publications:
            return ()

        normalized_metadata: list[tuple[tuple[str, str], ...]] = []
        keys: list[tuple[str, str]] = []
        for row in publications:
            if type(row.reference_id) is not str or not row.reference_id.strip():
                raise ValueError("research content reference_id must be non-empty")
            if type(row.scope) is not ScopeIdentity:
                raise TypeError("research content scope must be ScopeIdentity")
            if type(row.payload) is not bytes:
                raise TypeError("research content payload must be bytes")
            if type(row.media_type) is not str or not row.media_type.strip():
                raise ValueError("research content media_type must be non-empty")
            if not isinstance(row.kind, ArtifactKind):
                raise TypeError("research content kind must be ArtifactKind")
            if not isinstance(row.retention, ArtifactRetention):
                raise TypeError("research content retention must be ArtifactRetention")
            if (
                type(row.producer_component_id) is not str
                or not row.producer_component_id.strip()
            ):
                raise ValueError(
                    "research content producer_component_id must be non-empty"
                )
            metadata = tuple(
                sorted(
                    (() if row.metadata is None else row.metadata.items()),
                    key=lambda item: item[0],
                )
            )
            if any(
                type(key) is not str
                or not key.strip()
                or type(value) is not str
                for key, value in metadata
            ):
                raise TypeError("research content metadata must be text pairs")
            normalized_metadata.append(metadata)
            keys.append((row.scope.key, row.reference_id))
        if len(keys) != len(set(keys)):
            raise ValueError("research content batch contains duplicate references")

        blobs = self.blobs.put_many(
            tuple((row.payload, row.media_type) for row in publications)
        )
        if len(blobs) != len(publications):
            raise RuntimeError("research content blob batch cardinality drifted")

        records = tuple(
            ArtifactRecord(
                artifact_id=(
                    "research-content-"
                    + canonical_digest(
                        {
                            "scope": row.scope.key,
                            "reference_id": row.reference_id,
                            "content_sha256": blob.content_sha256,
                            "media_type": row.media_type,
                        }
                    )
                ),
                kind=row.kind,
                scope=row.scope,
                digest=blob.content_sha256,
                producer_component_id=row.producer_component_id,
                media_type=row.media_type,
                retention=row.retention,
                metadata=metadata,
            )
            for row, blob, metadata in zip(
                publications, blobs, normalized_metadata, strict=True
            )
        )
        stored = self.artifacts.put_many(records)
        if stored != records:
            raise RuntimeError("research content artifact registration drifted")

        results: list[ArtifactReference | None] = [None] * len(publications)
        missing: list[tuple[str, ScopeIdentity, int, str]] = []
        missing_indices: list[int] = []
        current_references = self.references.resolve_many(
            tuple((row.reference_id, row.scope) for row in publications)
        )
        if len(current_references) != len(publications):
            raise RuntimeError(
                "research content reference resolution cardinality drifted"
            )
        for index, (row, record, current) in enumerate(
            zip(publications, records, current_references, strict=True)
        ):
            if current is None:
                missing.append((row.reference_id, row.scope, 0, record.artifact_id))
                missing_indices.append(index)
                continue
            if current.artifact_id != record.artifact_id:
                raise ValueError(
                    "immutable research content reference already points to "
                    "different content"
                )
            results[index] = current

        if missing:
            created = self.references.compare_and_set_many(tuple(missing))
            if len(created) != len(missing_indices):
                raise RuntimeError("research content reference batch cardinality drifted")
            for index, reference in zip(missing_indices, created, strict=True):
                results[index] = reference

        if any(reference is None for reference in results):
            raise RuntimeError("research content publication lost reference result")
        return tuple(reference for reference in results if reference is not None)

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
        return self.publish_many(
            (
                ResearchContentPublication(
                    reference_id=reference_id,
                    scope=scope,
                    payload=payload,
                    media_type=media_type,
                    kind=kind,
                    retention=retention,
                    producer_component_id=producer_component_id,
                    metadata=metadata,
                ),
            )
        )[0]

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
class ResearchExecutionTrialReceiptPublisher:
    """Publish the complete authoritative Trial receipt through Artifact authority."""

    content: ResearchExecutionContentAuthorities

    def __post_init__(self) -> None:
        if type(self.content) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "Trial receipt publisher requires ResearchExecutionContentAuthorities"
            )

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "publisher": "research-execution-trial-receipt.v1",
                "content_authority": self.content.identity_digest,
            }
        )

    def publish(
        self,
        request: TrialExecutionRequest,
        receipt: TrialExecutionReceipt,
    ) -> ArtifactReference:
        if type(request) is not TrialExecutionRequest:
            raise TypeError("Trial receipt publish requires TrialExecutionRequest")
        if type(receipt) is not TrialExecutionReceipt:
            raise TypeError("Trial receipt publish requires TrialExecutionReceipt")
        if receipt.request_digest != request.request_digest:
            raise ValueError("Trial receipt publish request identity drifted")
        if receipt.assignment_digest != request.assignment.assignment_digest:
            raise ValueError("Trial receipt publish assignment identity drifted")
        return self.content.publish(
            reference_id="trial-receipt:" + receipt.receipt_digest,
            scope=ScopeIdentity(ScopeKind.RUN, request.run_id),
            payload=canonical_bytes(receipt),
            media_type="application/vnd.noetrium.trial-receipt+json",
            kind=ArtifactKind.SCIENTIFIC,
            retention=ArtifactRetention.RUN,
            producer_component_id="experimentation.trial-receipt",
            metadata={
                "trial_receipt_digest": receipt.receipt_digest,
                "trial_request_digest": request.request_digest,
                "assignment_digest": receipt.assignment_digest,
                "study_id": request.assignment.study_id,
            },
        )


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
                "workload_task_ids": request.assignment.workload.task_ids,
                "workload_digest": request.assignment.workload.workload_digest,
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
    "ResearchContentPublication",
    "ResearchExecutionContentAuthorities",
    "ResearchExecutionTrialReceiptPublisher",
    "ResearchExecutionVerifierArtifactPublisher",
    "compose_research_execution_content",
]
