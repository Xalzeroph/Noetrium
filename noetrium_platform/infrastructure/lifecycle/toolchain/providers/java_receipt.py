from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.infrastructure.lifecycle.toolchain.api import JavaRuntimeReceipt, RuntimeToolchainError

_RECEIPT_SCHEMA = "runtime.java-receipt.v2"


def encode_java_runtime_receipt(receipt: JavaRuntimeReceipt) -> bytes:
    return encode_checksummed_document(_RECEIPT_SCHEMA, asdict(receipt))


def load_java_runtime_receipt(path: Path) -> JavaRuntimeReceipt:
    try:
        payload = decode_checksummed_document(
            path.read_bytes(), expected_schema=_RECEIPT_SCHEMA
        ).payload
        return JavaRuntimeReceipt(**payload)
    except (OSError, ChecksummedDocumentError, TypeError, ValueError) as exc:
        raise RuntimeToolchainError(
            "RECEIPT_INVALID", "Java runtime receipt cannot be trusted"
        ) from exc


__all__ = [
    "encode_java_runtime_receipt",
    "load_java_runtime_receipt",
]
