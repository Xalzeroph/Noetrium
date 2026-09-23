from __future__ import annotations

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactRegistryPort,
    ArtifactRetention,
)
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobRef,
    ArtifactBlobStorePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_bytes,
    canonical_digest,
    freeze_json,
    strict_json_loads,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.product.research_os import ResearchValueKind

from .research_os_values import (
    ResearchOSValueReference,
    ResearchOSValueSubject,
)


_RESEARCH_OS_ARTIFACT_MEDIA_TYPE = "application/vnd.noetrium.research-os-value.v1+json"
_RESEARCH_OS_ARTIFACT_PRODUCER = "research-os.value-authority"


class ResearchOSArtifactValueAuthority:
    """ARTIFACT value routing through existing Blob CAS + immutable catalog authority."""

    authority_id = "artifact.catalog+blob"
    supported_kinds = frozenset({ResearchValueKind.ARTIFACT})

    def __init__(
        self,
        blobs: ArtifactBlobStorePort,
        registry: ArtifactRegistryPort,
    ) -> None:
        if not isinstance(blobs, ArtifactBlobStorePort):
            raise TypeError(
                "Research OS artifact value authority requires ArtifactBlobStorePort"
            )
        if not isinstance(registry, ArtifactRegistryPort):
            raise TypeError(
                "Research OS artifact value authority requires ArtifactRegistryPort"
            )
        self._blobs = blobs
        self._registry = registry

    @staticmethod
    def _artifact_id(subject: ResearchOSValueSubject) -> str:
        return f"research-os-value:{subject.subject_digest}"

    @staticmethod
    def _scope(subject: ResearchOSValueSubject) -> ScopeIdentity:
        return ScopeIdentity(ScopeKind.RUN, subject.execution_cut_id)

    @staticmethod
    def _metadata(
        subject: ResearchOSValueSubject,
        *,
        size_bytes: int,
    ) -> tuple[tuple[str, str], ...]:
        return (
            ("blob_size_bytes", str(size_bytes)),
            ("research_value_kind", subject.kind.value),
            ("subject_digest", subject.subject_digest),
        )

    @classmethod
    def _record(
        cls,
        subject: ResearchOSValueSubject,
        ref: ArtifactBlobRef,
    ) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=cls._artifact_id(subject),
            kind=ArtifactKind.SCIENTIFIC,
            scope=cls._scope(subject),
            digest=ref.content_sha256,
            producer_component_id=_RESEARCH_OS_ARTIFACT_PRODUCER,
            producer_operation_id=(
                f"{subject.graph_node_id}:{subject.output_name}"
            ),
            media_type=ref.media_type,
            retention=ArtifactRetention.RUN,
            metadata=cls._metadata(
                subject,
                size_bytes=ref.size_bytes,
            ),
        )

    @staticmethod
    def _size_bytes(record: ArtifactRecord) -> int:
        metadata = dict(record.metadata)
        if set(metadata) != {
            "blob_size_bytes",
            "research_value_kind",
            "subject_digest",
        }:
            raise ValueError(
                "Research OS artifact catalog metadata is not canonical"
            )
        raw = metadata["blob_size_bytes"]
        if not raw.isdigit():
            raise ValueError(
                "Research OS artifact catalog blob_size_bytes is invalid"
            )
        value = int(raw)
        if value < 0:
            raise ValueError(
                "Research OS artifact catalog blob size is negative"
            )
        return value

    @classmethod
    def _validate_record(
        cls,
        subject: ResearchOSValueSubject,
        record: ArtifactRecord,
    ) -> ArtifactBlobRef:
        if subject.kind is not ResearchValueKind.ARTIFACT:
            raise ValueError(
                "Research OS artifact authority received non-ARTIFACT subject"
            )
        if record.artifact_id != cls._artifact_id(subject):
            raise ValueError("Research OS artifact identity drifted")
        if record.kind is not ArtifactKind.SCIENTIFIC:
            raise ValueError("Research OS artifact kind drifted")
        if record.scope != cls._scope(subject):
            raise ValueError("Research OS artifact scope drifted")
        if record.producer_component_id != _RESEARCH_OS_ARTIFACT_PRODUCER:
            raise ValueError("Research OS artifact producer drifted")
        if (
            record.producer_operation_id
            != f"{subject.graph_node_id}:{subject.output_name}"
        ):
            raise ValueError("Research OS artifact producer operation drifted")
        if record.media_type != _RESEARCH_OS_ARTIFACT_MEDIA_TYPE:
            raise ValueError("Research OS artifact media type drifted")
        if record.retention is not ArtifactRetention.RUN:
            raise ValueError("Research OS artifact retention drifted")
        metadata = dict(record.metadata)
        if metadata.get("subject_digest") != subject.subject_digest:
            raise ValueError("Research OS artifact subject digest drifted")
        if metadata.get("research_value_kind") != subject.kind.value:
            raise ValueError("Research OS artifact value kind drifted")
        return ArtifactBlobRef(
            record.digest,
            cls._size_bytes(record),
            record.media_type,
        )

    def publish(
        self,
        subject: ResearchOSValueSubject,
        value: JsonValue,
    ) -> ResearchOSValueReference:
        if type(subject) is not ResearchOSValueSubject:
            raise TypeError("Research OS artifact publish subject must be typed")
        if subject.kind is not ResearchValueKind.ARTIFACT:
            raise ValueError(
                "Research OS artifact authority publishes ARTIFACT values only"
            )
        payload = canonical_bytes(freeze_json(value))
        ref = self._blobs.put(
            payload,
            media_type=_RESEARCH_OS_ARTIFACT_MEDIA_TYPE,
        )
        if not self._blobs.verify(ref):
            raise RuntimeError(
                "Research OS artifact blob failed immediate integrity verification"
            )
        record = self._record(subject, ref)
        stored = self._registry.put(record)
        if stored != record:
            raise RuntimeError(
                "Research OS artifact registry changed immutable artifact record"
            )
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            record.artifact_id,
            ref.content_sha256,
        )

    def lookup(
        self,
        subject: ResearchOSValueSubject,
    ) -> ResearchOSValueReference:
        if type(subject) is not ResearchOSValueSubject:
            raise TypeError("Research OS artifact lookup subject must be typed")
        record = self._registry.get(self._artifact_id(subject))
        ref = self._validate_record(subject, record)
        if not self._blobs.verify(ref):
            raise RuntimeError(
                "Research OS artifact blob failed integrity verification"
            )
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            record.artifact_id,
            ref.content_sha256,
        )

    def resolve(
        self,
        reference: ResearchOSValueReference,
    ) -> JsonValue:
        if type(reference) is not ResearchOSValueReference:
            raise TypeError("Research OS artifact resolve reference must be typed")
        if reference.authority_id != self.authority_id:
            raise ValueError("Research OS artifact reference authority drifted")
        if reference.subject.kind is not ResearchValueKind.ARTIFACT:
            raise ValueError("Research OS artifact reference kind drifted")
        expected = self.lookup(reference.subject)
        if expected != reference:
            raise ValueError("Research OS artifact reference identity drifted")
        record = self._registry.get(reference.authority_ref)
        blob_ref = self._validate_record(reference.subject, record)
        payload = self._blobs.get(blob_ref)
        value = strict_json_loads(payload)
        return freeze_json(value)

    def reuse_proof(
        self,
        reference: ResearchOSValueReference,
    ) -> str:
        resolved = self.resolve(reference)
        record = self._registry.get(reference.authority_ref)
        return canonical_digest(
            {
                "authority_id": self.authority_id,
                "subject_digest": reference.subject.subject_digest,
                "artifact_id": record.artifact_id,
                "scope": record.scope.key,
                "content_digest": record.digest,
                "resolved_value_digest": canonical_digest(resolved),
            }
        )


__all__ = ["ResearchOSArtifactValueAuthority"]
