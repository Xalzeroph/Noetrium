from __future__ import annotations

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactNotFound,
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


class ResearchOSImmutableValueAuthority:
    """All immutable ResearchGraph values routed through canonical Blob CAS + catalog authority."""

    authority_id = "artifact.catalog+blob.scientific-values"
    supported_kinds = frozenset(ResearchValueKind)

    def __init__(
        self,
        blobs: ArtifactBlobStorePort,
        registry: ArtifactRegistryPort,
        retention: ArtifactRetentionPort,
    ) -> None:
        if not isinstance(blobs, ArtifactBlobStorePort):
            raise TypeError(
                "Research OS immutable value authority requires ArtifactBlobStorePort"
            )
        if not isinstance(registry, ArtifactRegistryPort):
            raise TypeError(
                "Research OS immutable value authority requires ArtifactRegistryPort"
            )
        if not isinstance(retention, ArtifactRetentionPort):
            raise TypeError(
                "Research OS immutable value authority requires ArtifactRetentionPort"
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
                "Research OS immutable value catalog metadata is not canonical"
            )
        raw = metadata["blob_size_bytes"]
        if not raw.isdigit():
            raise ValueError(
                "Research OS immutable value catalog blob_size_bytes is invalid"
            )
        value = int(raw)
        if value < 0:
            raise ValueError(
                "Research OS immutable value catalog blob size is negative"
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
        ):
            raise ValueError(
                "Research OS immutable value effective retention identity drifted"
            )
        if (
            subject.subject_digest in current.reason_refs
            and not current.pinned
        ):
            raise ValueError(
                "Research OS immutable value has an unpinned live execution reason"
            )
        return current

    @classmethod
    def _validate_record(
        cls,
        subject: ResearchOSValueSubject,
        record: ArtifactRecord,
    ) -> ArtifactBlobRef:
        if record.artifact_id != cls._artifact_id(subject):
            raise ValueError("Research OS immutable value identity drifted")
        if record.kind is not ArtifactKind.SCIENTIFIC:
            raise ValueError("Research OS immutable value artifact kind drifted")
        if record.scope != cls._scope(subject):
            raise ValueError("Research OS immutable value scope drifted")
        if record.producer_component_id != _RESEARCH_OS_ARTIFACT_PRODUCER:
            raise ValueError("Research OS immutable value producer drifted")
        if (
            record.producer_operation_id
            != f"{subject.graph_node_id}:{subject.output_name}"
        ):
            raise ValueError("Research OS immutable value producer operation drifted")
        if record.media_type != _RESEARCH_OS_ARTIFACT_MEDIA_TYPE:
            raise ValueError("Research OS immutable value media type drifted")
        if record.retention is not ArtifactRetention.RUN:
            raise ValueError("Research OS immutable value retention drifted")
        metadata = dict(record.metadata)
        if metadata.get("subject_digest") != subject.subject_digest:
            raise ValueError("Research OS immutable value subject digest drifted")
        if metadata.get("research_value_kind") != subject.kind.value:
            raise ValueError("Research OS immutable value kind drifted")
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
            raise TypeError("Research OS immutable value publish subject must be typed")
        payload = canonical_bytes(freeze_json(value))
        ref = self._blobs.put(
            payload,
            media_type=_RESEARCH_OS_ARTIFACT_MEDIA_TYPE,
        )
        if not self._blobs.verify(ref):
            raise RuntimeError(
                "Research OS immutable value blob failed immediate integrity verification"
            )
        record = self._record(subject, ref)
        stored = self._registry.put(record)
        if stored != record:
            raise RuntimeError(
                "Research OS immutable value registry changed immutable record"
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
            raise TypeError("Research OS immutable value lookup subject must be typed")
        record = self._registry.get(self._artifact_id(subject))
        ref = self._validate_record(subject, record)
        self._ensure_retention(subject, record.artifact_id)
        if not self._blobs.verify(ref):
            raise RuntimeError(
                "Research OS immutable value blob failed integrity verification"
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
            raise TypeError("Research OS immutable value resolve reference must be typed")
        if reference.authority_id != self.authority_id:
            raise ValueError("Research OS immutable value reference authority drifted")
        expected = self.lookup(reference.subject)
        if expected != reference:
            raise ValueError("Research OS immutable value reference identity drifted")
        record = self._registry.get(reference.authority_ref)
        blob_ref = self._validate_record(reference.subject, record)
        payload = self._blobs.get(blob_ref)
        value = strict_json_loads(payload)
        return freeze_json(value)

    def release_execution(
        self,
        subject: ResearchOSValueSubject,
    ) -> str:
        """Release only this execution subject's retention reason.

        Content, catalog identity and lineage remain immutable historical truth.
        Physical blob GC is a separate proof-backed operation.
        """

        if type(subject) is not ResearchOSValueSubject:
            raise TypeError("Research OS execution release subject must be typed")
        artifact_id = self._artifact_id(subject)
        try:
            record = self._registry.get(artifact_id)
        except ArtifactNotFound:
            return canonical_digest(
                {
                    "schema": "research-os.value-execution-release.v1",
                    "subject_digest": subject.subject_digest,
                    "artifact_id": artifact_id,
                    "disposition": "absent",
                }
            )
        self._validate_record(subject, record)
        try:
            current = self._retention.get(artifact_id)
        except ArtifactRetentionNotFound as exc:
            raise ValueError(
                "Research OS immutable value lost retention authority"
            ) from exc
        if current.retention is not ArtifactRetention.RUN:
            raise ValueError(
                "Research OS immutable value execution release requires RUN retention"
            )
        before_generation = current.generation
        if subject.subject_digest in current.reason_refs:
            remaining = tuple(
                ref
                for ref in current.reason_refs
                if ref != subject.subject_digest
            )
            current = self._retention.compare_and_set(
                artifact_id,
                expected_generation=current.generation,
                retention=current.retention,
                pinned=bool(remaining),
                reason_refs=remaining,
            )
        return canonical_digest(
            {
                "schema": "research-os.value-execution-release.v1",
                "subject_digest": subject.subject_digest,
                "artifact_id": artifact_id,
                "content_digest": record.digest,
                "retention": current.retention.value,
                "before_generation": before_generation,
                "after_generation": current.generation,
                "pinned": current.pinned,
                "reason_refs": current.reason_refs,
                "disposition": "released",
            }
        )

    def reuse(
        self,
        source: ResearchOSValueReference,
        target: ResearchOSValueSubject,
    ) -> ResearchOSValueReference:
        if type(source) is not ResearchOSValueReference:
            raise TypeError("Research OS immutable value reuse source must be typed")
        if type(target) is not ResearchOSValueSubject:
            raise TypeError("Research OS immutable value reuse target must be typed")
        if source.authority_id != self.authority_id:
            raise ValueError("Research OS immutable value reuse authority drifted")
        if target.kind is not source.subject.kind:
            raise ValueError("Research OS immutable value reuse kind drifted")
        if target.execution_cut_id == source.subject.execution_cut_id:
            raise ValueError("Research OS immutable value reuse requires a distinct target cut")
        if (
            target.graph_node_id != source.subject.graph_node_id
            or target.output_name != source.subject.output_name
            or target.semantic_digest != source.subject.semantic_digest
        ):
            raise ValueError("Research OS immutable value reuse semantic identity drifted")

        expected = self.lookup(source.subject)
        if expected != source:
            raise ValueError("Research OS immutable value reuse source reference drifted")
        source_record = self._registry.get(source.authority_ref)
        blob_ref = self._validate_record(source.subject, source_record)
        if not self._blobs.verify(blob_ref):
            raise RuntimeError("Research OS immutable value reuse source blob failed verification")

        target_record = self._record(target, blob_ref)
        stored = self._registry.put(target_record)
        if stored != target_record:
            raise RuntimeError(
                "Research OS immutable value registry changed reused record"
            )
        self._ensure_retention(target, stored.artifact_id)
        reused = ResearchOSValueReference(
            target,
            self.authority_id,
            stored.artifact_id,
            blob_ref.content_sha256,
        )
        if self.resolve(reused) != self.resolve(source):
            raise RuntimeError("Research OS immutable value reuse changed resolved value")
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


__all__ = ["ResearchOSImmutableValueAuthority"]
