"""Checksummed storage for post-materialization runtime qualification."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from noetrium_platform.capabilities.model._persisted import (
    exact_fields,
    integer,
    optional_text,
    sequence,
    text,
    text_tuple,
)
from noetrium_platform.capabilities.model.qualification.api import (
    DeploymentQualificationRuntimeReceipt,
    DeploymentQualificationRuntimeStorePort,
    DeploymentRuntimeQualificationStatus,
    RuntimeCheckReceipt,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    atomic_replace_bytes,
    decode_checksummed_document,
    encode_checksummed_document,
)

_SCHEMA = "model-deployment-qualification-runtime.v2"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_FIELDS = frozenset({
    "application_digest", "plan_digest", "environment_id", "backend", "checks",
    "status", "reasons", "runtime_digest",
})
_CHECK_FIELDS = frozenset({
    "check", "command_digest", "return_code", "stdout_digest", "stderr_digest",
    "stdout_preview", "stderr_preview",
})


class QualificationRuntimeIntegrityError(RuntimeError):
    """Raised when a runtime qualification receipt is malformed or altered."""


class FileDeploymentQualificationRuntimeStore(DeploymentQualificationRuntimeStorePort):
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        receipt: DeploymentQualificationRuntimeReceipt,
    ) -> DeploymentQualificationRuntimeReceipt:
        atomic_replace_bytes(
            self._path(receipt.runtime_digest),
            encode_checksummed_document(_SCHEMA, self._payload(receipt)),
        )
        return receipt

    def get(self, runtime_digest: str) -> DeploymentQualificationRuntimeReceipt:
        if _DIGEST_RE.fullmatch(runtime_digest) is None:
            raise ValueError("runtime qualification digest must be a lowercase SHA-256 digest")
        path = self._path(runtime_digest)
        if not path.is_file():
            raise KeyError(runtime_digest)
        try:
            document = decode_checksummed_document(path.read_bytes(), expected_schema=_SCHEMA)
            receipt = self._receipt(document.payload)
        except (ChecksummedDocumentError, KeyError, TypeError, ValueError, OSError) as exc:
            raise QualificationRuntimeIntegrityError(
                f"invalid runtime qualification record: {runtime_digest}"
            ) from exc
        if receipt.runtime_digest != runtime_digest:
            raise QualificationRuntimeIntegrityError(
                f"runtime qualification digest mismatch: {runtime_digest}"
            )
        return receipt

    def _path(self, digest: str) -> Path:
        return self._root / f"{digest}.json"

    @staticmethod
    def _payload(receipt: DeploymentQualificationRuntimeReceipt) -> dict[str, Any]:
        return json.loads(canonical_bytes(receipt).decode("utf-8"))

    @staticmethod
    def _check(value: object) -> RuntimeCheckReceipt:
        data = exact_fields(value, field="runtime qualification check", fields=_CHECK_FIELDS)
        return RuntimeCheckReceipt(
            check=text(data["check"], field="check.check", allow_empty=False),
            command_digest=text(data["command_digest"], field="check.command_digest", allow_empty=False),
            return_code=integer(data["return_code"], field="check.return_code"),
            stdout_digest=text(data["stdout_digest"], field="check.stdout_digest", allow_empty=False),
            stderr_digest=text(data["stderr_digest"], field="check.stderr_digest", allow_empty=False),
            stdout_preview=text(data["stdout_preview"], field="check.stdout_preview"),
            stderr_preview=text(data["stderr_preview"], field="check.stderr_preview"),
        )

    @classmethod
    def _receipt(cls, value: object) -> DeploymentQualificationRuntimeReceipt:
        payload = exact_fields(value, field="runtime qualification receipt", fields=_RECEIPT_FIELDS)
        checks = sequence(payload["checks"], field="checks")
        receipt = DeploymentQualificationRuntimeReceipt(
            application_digest=text(
                payload["application_digest"], field="application_digest", allow_empty=False
            ),
            plan_digest=text(payload["plan_digest"], field="plan_digest", allow_empty=False),
            environment_id=text(payload["environment_id"], field="environment_id", allow_empty=False),
            backend=optional_text(payload["backend"], field="backend"),
            checks=tuple(cls._check(item) for item in checks),
            status=DeploymentRuntimeQualificationStatus(
                text(payload["status"], field="status", allow_empty=False)
            ),
            reasons=text_tuple(payload["reasons"], field="reasons"),
        )
        stored_digest = text(
            payload["runtime_digest"], field="runtime_digest", allow_empty=False
        )
        if receipt.runtime_digest != stored_digest:
            raise QualificationRuntimeIntegrityError("runtime qualification digest mismatch")
        return receipt


__all__ = [
    "FileDeploymentQualificationRuntimeStore",
    "QualificationRuntimeIntegrityError",
]
