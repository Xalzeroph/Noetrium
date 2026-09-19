from __future__ import annotations

from dataclasses import asdict

from noetrium_platform.foundation.kernel.kernel.durability.document_integrity import DocumentIntegrityError
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat


SERVICE_HEARTBEAT_DOCUMENT_SCHEMA = "service-heartbeat.v2"


class ServiceHeartbeatIntegrityError(DocumentIntegrityError):
    pass


class ServiceHeartbeatCodec:
    schema = SERVICE_HEARTBEAT_DOCUMENT_SCHEMA

    def encode(self, heartbeat: ServiceHeartbeat) -> bytes:
        return encode_checksummed_document(self.schema, asdict(heartbeat))

    def decode(self, raw: bytes) -> ServiceHeartbeat:
        try:
            decoded = decode_checksummed_document(
                raw,
                expected_schema=self.schema,
            )
            return ServiceHeartbeat(**decoded.payload)
        except ChecksummedDocumentError as exc:
            raise ServiceHeartbeatIntegrityError.from_checksummed_document(
                exc, message="service heartbeat document integrity failure"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceHeartbeatIntegrityError("heartbeat payload violates the heartbeat contract") from exc


__all__ = [
    "SERVICE_HEARTBEAT_DOCUMENT_SCHEMA",
    "ServiceHeartbeatCodec",
    "ServiceHeartbeatIntegrityError",
]
