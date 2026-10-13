"""Durable file store for model deployment qualification evidence."""
from __future__ import annotations


from pathlib import Path
import re

from noetrium_platform.foundation.kernel.record import RecordRole, evidence_record, record_document
from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    atomic_replace_bytes,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.capabilities.model.qualification.api import (
    DeploymentQualificationEvidence,
    DeploymentQualificationEvidenceStorePort,
)
from .qualification_evidence_codec import (
    QualificationEvidenceCodecError,
    decode_qualification_record,
    encode_qualification_record,
)


_SCHEMA = "noetrium.record.model-deployment-qualification.v1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class QualificationEvidenceIntegrityError(RuntimeError):
    """Raised when a persisted qualification record is malformed or altered."""


class FileDeploymentQualificationEvidenceStore(DeploymentQualificationEvidenceStorePort):
    """Publish one immutable qualification record per plan digest."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        record: DeploymentQualificationEvidence,
    ) -> DeploymentQualificationEvidence:
        typed_payload = encode_qualification_record(record)
        envelope = evidence_record(
            "model.deployment.qualification.v1",
            payload={"qualification": typed_payload},
            provenance={"plan_digest": record.plan.plan_digest},
        )
        atomic_replace_bytes(
            self._path(record.plan.plan_digest),
            encode_checksummed_document(_SCHEMA, record_document(envelope)),
        )
        return record

    def get(self, plan_digest: str) -> DeploymentQualificationEvidence:
        if _DIGEST_RE.fullmatch(plan_digest) is None:
            raise ValueError("qualification plan digest must be a lowercase SHA-256 digest")
        path = self._path(plan_digest)
        if not path.is_file():
            raise KeyError(plan_digest)
        try:
            document = decode_checksummed_document(path.read_bytes(), expected_schema=_SCHEMA)
            payload = document.payload
            if not isinstance(payload, dict):
                raise QualificationEvidenceCodecError("qualification record envelope must be an object")
            if payload.get("record_type") != "model.deployment.qualification.v1":
                raise QualificationEvidenceCodecError("qualification record type mismatch")
            roles = payload.get("roles")
            if roles != [RecordRole.EVIDENCE.value]:
                raise QualificationEvidenceCodecError("qualification record roles mismatch")
            record_payload = payload.get("payload")
            if not isinstance(record_payload, dict) or set(record_payload) != {"qualification"}:
                raise QualificationEvidenceCodecError("qualification record payload mismatch")
            record = decode_qualification_record(record_payload["qualification"])
        except (
            ChecksummedDocumentError,
            QualificationEvidenceCodecError,
            KeyError,
            TypeError,
            ValueError,
            OSError,
        ) as exc:
            raise QualificationEvidenceIntegrityError(
                f"invalid qualification evidence record: {plan_digest}"
            ) from exc
        if record.plan.plan_digest != plan_digest:
            raise QualificationEvidenceIntegrityError(
                f"qualification evidence plan digest mismatch: {plan_digest}"
            )
        return record

    def _path(self, plan_digest: str) -> Path:
        return self._root / f"{plan_digest}.json"


__all__ = [
    "FileDeploymentQualificationEvidenceStore",
    "QualificationEvidenceIntegrityError",
]
