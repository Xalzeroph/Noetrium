"""Durable file store for model deployment qualification evidence."""

from __future__ import annotations

from pathlib import Path
import re

from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    atomic_replace_bytes,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.capabilities.model.qualification.api import (
    DeploymentQualificationEvidenceRecord,
    DeploymentQualificationEvidenceStorePort,
)
from .qualification_evidence_codec import (
    QualificationEvidenceCodecError,
    decode_qualification_record,
    encode_qualification_record,
)


_SCHEMA = "model-deployment-qualification-evidence.v4"
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
        record: DeploymentQualificationEvidenceRecord,
    ) -> DeploymentQualificationEvidenceRecord:
        atomic_replace_bytes(
            self._path(record.plan.plan_digest),
            encode_checksummed_document(_SCHEMA, encode_qualification_record(record)),
        )
        return record

    def get(self, plan_digest: str) -> DeploymentQualificationEvidenceRecord:
        if _DIGEST_RE.fullmatch(plan_digest) is None:
            raise ValueError("qualification plan digest must be a lowercase SHA-256 digest")
        path = self._path(plan_digest)
        if not path.is_file():
            raise KeyError(plan_digest)
        try:
            document = decode_checksummed_document(path.read_bytes(), expected_schema=_SCHEMA)
            record = decode_qualification_record(document.payload)
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
