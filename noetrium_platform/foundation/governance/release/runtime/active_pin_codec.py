from __future__ import annotations

from dataclasses import asdict

from noetrium_platform.foundation.kernel.kernel.durability.document_integrity import DocumentIntegrityError
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)

from noetrium_platform.foundation.governance.release.api import ActiveReleasePin

_SCHEMA = "active-release-pin.v1"


class ActiveReleasePinIntegrityError(DocumentIntegrityError):
    pass


class ActiveReleasePinCodec:
    def encode(self, pin: ActiveReleasePin) -> bytes:
        return encode_checksummed_document(_SCHEMA, asdict(pin))

    def decode(self, raw: bytes) -> ActiveReleasePin:
        try:
            document = decode_checksummed_document(raw, expected_schema=_SCHEMA)
            return ActiveReleasePin(**document.payload)
        except ChecksummedDocumentError as exc:
            raise ActiveReleasePinIntegrityError.from_checksummed_document(
                exc, message="active release pin document integrity failure"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ActiveReleasePinIntegrityError(
                "active release pin payload violates the pin contract"
            ) from exc


__all__ = ["ActiveReleasePinCodec", "ActiveReleasePinIntegrityError"]
