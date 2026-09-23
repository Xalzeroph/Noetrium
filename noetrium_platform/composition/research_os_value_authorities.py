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
from noetrium_platform.evidence.artifact.retention.api import (
    ArtifactRetentionNotFound,
    ArtifactRetentionPort,
    ArtifactRetentionState,
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
        retention: ArtifactRetentionPort,
    ) -> None:
        if not isinstance(blobs, ArtifactBlobStorePort):
            raise TypeError(
                "Research OS artifact value authority requires ArtifactBlobStorePort"
            )
        if not isinstance(registry, ArtifactRegistryPort):
            raise TypeError(
                "Research OS artifact value authority requires ArtifactRegistryPort"
            )
        if not isinstance(retention, ArtifactRetentionPort):
            raise TypeError(
                "Research OS artifact value authority requires ArtifactRetentionPort"
            )
        self._blobs = blobs
        self._registry = registry
        self._retention = retention

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

    @staticmethod
    def _expected_retention(
        subject: ResearchOSValueSubject,
        artifact_id: str,
    ) -> ArtifactRetentionState:
        return ArtifactRetentionState(
            artifact_id=artifact_id,
            retention=ArtifactRetention.RUN,
            pinned=True,
            generation=1,
            reason_refs=(subject.subject_digest,),
        )

    def _ensure_retention(
        self,
        subject: ResearchOSValueSubject,
        artifact_id: str,
    ) -> ArtifactRetentionState:
        expected = self._expected_retention(subject, artifact_id)
        try:
            current = self._retention.get(artifact_id)
        except ArtifactRetentionNotFound:
            current = self._retention.compare_and_set(
                artifact_id,
                expected_generation=0,
                retention=expected.retention,
                pinned=expected.pinned,
                reason_refs=expected.reason_refs,
            )
        if (
            current.artifact_id != expected.artifact_id
            or current.retention is not expected.retention
            or current.pinned is not expected.pinned
            or current.reason_refs != expected.reason_refs
        ):
            raise ValueError(
                "Research OS artifact effective retention/pinning drifted"
            )
        return current

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
        self._ensure_retention(subject, stored.artifact_id)
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
        self._ensure_retention(subject, record.artifact_id)
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

    def reuse(
        self,
        source: ResearchOSValueReference,
        target: ResearchOSValueSubject,
    ) -> ResearchOSValueReference:
        if type(source) is not ResearchOSValueReference:
            raise TypeError("Research OS artifact reuse source must be typed")
        if type(target) is not ResearchOSValueSubject:
            raise TypeError("Research OS artifact reuse target must be typed")
        if source.authority_id != self.authority_id:
            raise ValueError("Research OS artifact reuse authority drifted")
        if source.subject.kind is not ResearchValueKind.ARTIFACT:
            raise ValueError("Research OS artifact reuse source kind drifted")
        if target.kind is not ResearchValueKind.ARTIFACT:
            raise ValueError("Research OS artifact reuse target kind drifted")
        if target.execution_cut_id == source.subject.execution_cut_id:
            raise ValueError("Research OS artifact reuse requires a distinct target cut")
        if (
            target.graph_node_id != source.subject.graph_node_id
            or target.output_name != source.subject.output_name
            or target.semantic_digest != source.subject.semantic_digest
        ):
            raise ValueError("Research OS artifact reuse semantic identity drifted")

        expected = self.lookup(source.subject)
        if expected != source:
            raise ValueError("Research OS artifact reuse source reference drifted")
        source_record = self._registry.get(source.authority_ref)
        blob_ref = self._validate_record(source.subject, source_record)
        if not self._blobs.verify(blob_ref):
            raise RuntimeError("Research OS artifact reuse source blob failed verification")

        target_record = self._record(target, blob_ref)
        stored = self._registry.put(target_record)
        if stored != target_record:
            raise RuntimeError(
                "Research OS artifact registry changed immutable reused artifact record"
            )
        self._ensure_retention(target, stored.artifact_id)
        reused = ResearchOSValueReference(
            target,
            self.authority_id,
            stored.artifact_id,
            blob_ref.content_sha256,
        )
        if self.resolve(reused) != self.resolve(source):
            raise RuntimeError("Research OS artifact reuse changed resolved value")
        return reused

    def reuse_proof(
        self,
        reference: ResearchOSValueReference,
    ) -> str:
        resolved = self.resolve(reference)
        record = self._registry.get(reference.authority_ref)
        retention = self._ensure_retention(
            reference.subject,
            record.artifact_id,
        )
        return canonical_digest(
            {
                "authority_id": self.authority_id,
                "subject_digest": reference.subject.subject_digest,
                "artifact_id": record.artifact_id,
                "scope": record.scope.key,
                "content_digest": record.digest,
                "resolved_value_digest": canonical_digest(resolved),
                "retention": retention.retention.value,
                "pinned": retention.pinned,
                "retention_generation": retention.generation,
                "retention_reason_refs": retention.reason_refs,
            }
        )


__all__ = ["ResearchOSArtifactValueAuthority"]
