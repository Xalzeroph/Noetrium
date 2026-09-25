from __future__ import annotations

from dataclasses import dataclass
import json
from enum import StrEnum
from typing import Any

from noetrium_platform.foundation.kernel.kernel.canonical import canonical_bytes, canonical_digest


class ChecksummedDocumentFailureCode(StrEnum):
    INVALID_JSON = "invalid_json"
    DOCUMENT_TYPE = "document_type"
    SCHEMA_MISSING = "schema_missing"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    PAYLOAD_TYPE = "payload_type"
    CHECKSUM_MISMATCH = "checksum_mismatch"


_SAFE_MESSAGES = {
    ChecksummedDocumentFailureCode.INVALID_JSON: "document is not valid UTF-8 JSON",
    ChecksummedDocumentFailureCode.DOCUMENT_TYPE: "document must be a JSON object",
    ChecksummedDocumentFailureCode.SCHEMA_MISSING: "document schema missing",
    ChecksummedDocumentFailureCode.UNSUPPORTED_SCHEMA: "unsupported document schema",
    ChecksummedDocumentFailureCode.PAYLOAD_TYPE: "document payload must be a JSON object",
    ChecksummedDocumentFailureCode.CHECKSUM_MISMATCH: "document payload checksum mismatch",
}


class ChecksummedDocumentError(RuntimeError):
    """Machine-classified malformed/unsupported/checksum-invalid document failure."""

    def __init__(self, code: ChecksummedDocumentFailureCode) -> None:
        self.code = code
        super().__init__(_SAFE_MESSAGES[code])

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        return (f"document-integrity:{self.code.value}",)


@dataclass(frozen=True)
class DecodedChecksummedDocument:
    payload: dict[str, Any]


def payload_sha256(payload: dict[str, Any]) -> str:
    return canonical_digest(payload)


def encode_checksummed_document(schema: str, payload: dict[str, Any]) -> bytes:
    if not schema:
        raise ValueError("document schema required")
    document = {
        "schema": schema,
        "payload": payload,
        "payload_sha256": payload_sha256(payload),
    }
    return json.dumps(
        document,
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def decode_checksummed_document(
    raw: bytes,
    *,
    expected_schema: str,
) -> DecodedChecksummedDocument:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ChecksummedDocumentError(ChecksummedDocumentFailureCode.INVALID_JSON) from exc
    if not isinstance(document, dict):
        raise ChecksummedDocumentError(ChecksummedDocumentFailureCode.DOCUMENT_TYPE)
    if "schema" not in document:
        raise ChecksummedDocumentError(ChecksummedDocumentFailureCode.SCHEMA_MISSING)
    if document.get("schema") != expected_schema:
        raise ChecksummedDocumentError(ChecksummedDocumentFailureCode.UNSUPPORTED_SCHEMA)
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise ChecksummedDocumentError(ChecksummedDocumentFailureCode.PAYLOAD_TYPE)
    if document.get("payload_sha256") != payload_sha256(payload):
        raise ChecksummedDocumentError(ChecksummedDocumentFailureCode.CHECKSUM_MISMATCH)
    return DecodedChecksummedDocument(dict(payload))


__all__ = [
    "ChecksummedDocumentError",
    "ChecksummedDocumentFailureCode",
    "DecodedChecksummedDocument",
    "decode_checksummed_document",
    "encode_checksummed_document",
    "payload_sha256",
]
