"""Checksummed storage for qualification-plan materialization receipts."""

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
    DeploymentQualificationApplicationReceipt,
    DeploymentQualificationApplicationStorePort,
    InstallPackage,
    QualificationCommandReceipt,
    QualificationMaterializationStatus,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from noetrium_platform.foundation.kernel.kernel.durability import (
    ChecksummedDocumentError,
    atomic_replace_bytes,
    decode_checksummed_document,
    encode_checksummed_document,
)

_SCHEMA = "model-deployment-qualification-application.v1"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_FIELDS = frozenset({
    "plan_digest", "environment_id", "backend", "packages", "install_commands",
    "check_command", "status", "reasons", "application_digest",
})
_COMMAND_FIELDS = frozenset({
    "operation", "command_digest", "return_code", "stdout_digest", "stderr_digest",
})
_PACKAGE_FIELDS = frozenset({"name", "version", "index_url"})


class QualificationApplicationIntegrityError(RuntimeError):
    """Raised when a materialization receipt is malformed or altered."""


class FileDeploymentQualificationApplicationStore(DeploymentQualificationApplicationStorePort):
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def publish(
        self,
        receipt: DeploymentQualificationApplicationReceipt,
    ) -> DeploymentQualificationApplicationReceipt:
        atomic_replace_bytes(
            self._path(receipt.application_digest),
            encode_checksummed_document(_SCHEMA, self._payload(receipt)),
        )
        return receipt

    def get(self, application_digest: str) -> DeploymentQualificationApplicationReceipt:
        if _DIGEST_RE.fullmatch(application_digest) is None:
            raise ValueError("qualification application digest must be a lowercase SHA-256 digest")
        path = self._path(application_digest)
        if not path.is_file():
            raise KeyError(application_digest)
        try:
            document = decode_checksummed_document(path.read_bytes(), expected_schema=_SCHEMA)
            receipt = self._receipt(document.payload)
        except (ChecksummedDocumentError, KeyError, TypeError, ValueError, OSError) as exc:
            raise QualificationApplicationIntegrityError(
                f"invalid qualification application record: {application_digest}"
            ) from exc
        if receipt.application_digest != application_digest:
            raise QualificationApplicationIntegrityError(
                f"qualification application digest mismatch: {application_digest}"
            )
        return receipt

    def _path(self, digest: str) -> Path:
        return self._root / f"{digest}.json"

    @staticmethod
    def _payload(receipt: DeploymentQualificationApplicationReceipt) -> dict[str, Any]:
        return json.loads(canonical_bytes(receipt).decode("utf-8"))

    @staticmethod
    def _command(value: object) -> QualificationCommandReceipt:
        if value is None:
            raise ValueError("qualification command list cannot contain null")
        data = exact_fields(value, field="qualification command", fields=_COMMAND_FIELDS)
        return QualificationCommandReceipt(
            operation=text(data["operation"], field="command.operation", allow_empty=False),
            command_digest=text(data["command_digest"], field="command.command_digest", allow_empty=False),
            return_code=integer(data["return_code"], field="command.return_code"),
            stdout_digest=text(data["stdout_digest"], field="command.stdout_digest", allow_empty=False),
            stderr_digest=text(data["stderr_digest"], field="command.stderr_digest", allow_empty=False),
        )

    @staticmethod
    def _package(value: object) -> InstallPackage:
        data = exact_fields(value, field="package", fields=_PACKAGE_FIELDS)
        return InstallPackage(
            name=text(data["name"], field="package.name", allow_empty=False),
            version=text(data["version"], field="package.version", allow_empty=False),
            index_url=text(data["index_url"], field="package.index_url", allow_empty=False),
        )

    @classmethod
    def _optional_command(cls, value: object) -> QualificationCommandReceipt | None:
        return None if value is None else cls._command(value)

    @classmethod
    def _receipt(cls, value: object) -> DeploymentQualificationApplicationReceipt:
        payload = exact_fields(value, field="qualification application receipt", fields=_RECEIPT_FIELDS)
        packages = sequence(payload["packages"], field="packages")
        install_commands = sequence(payload["install_commands"], field="install_commands")
        receipt = DeploymentQualificationApplicationReceipt(
            plan_digest=text(payload["plan_digest"], field="plan_digest", allow_empty=False),
            environment_id=text(payload["environment_id"], field="environment_id", allow_empty=False),
            backend=optional_text(payload["backend"], field="backend"),
            packages=tuple(cls._package(item) for item in packages),
            install_commands=tuple(
                cls._command(item)
                for item in install_commands
            ),
            check_command=cls._optional_command(payload["check_command"]),
            status=QualificationMaterializationStatus(
                text(payload["status"], field="status", allow_empty=False)
            ),
            reasons=text_tuple(payload["reasons"], field="reasons"),
        )
        stored_digest = text(
            payload["application_digest"], field="application_digest", allow_empty=False
        )
        if receipt.application_digest != stored_digest:
            raise QualificationApplicationIntegrityError("qualification application digest mismatch")
        return receipt


__all__ = [
    "FileDeploymentQualificationApplicationStore",
    "QualificationApplicationIntegrityError",
]
