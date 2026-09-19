from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
import base64

from noetrium_platform.foundation.kernel.kernel.durability.document_integrity import DocumentIntegrityError
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)

from .prepared_start import ServiceStartRecoveryHandle
from .start_intent_contracts import ServiceStartIntent, ServiceStartIntentPhase


SERVICE_START_INTENT_SCHEMA = "service-start-intent.v1"


class ServiceStartIntentIntegrityError(DocumentIntegrityError):
    pass


class ServiceStartIntentCodec:
    schema = SERVICE_START_INTENT_SCHEMA

    def encode(self, intent: ServiceStartIntent) -> bytes:
        handle = intent.recovery_handle
        payload: dict[str, object] = {
            "intent_id": intent.intent_id,
            "service_id": intent.service_id,
            "contract_digest": intent.contract_digest,
            "attempt": intent.attempt,
            "phase": intent.phase.value,
            "recovery_handle": None
            if handle is None
            else {
                "provider_schema": handle.provider_schema,
                "payload_sha256": handle.payload_sha256,
                "opaque_payload_b64": base64.b64encode(handle.opaque_payload).decode("ascii"),
            },
            "process": None
            if intent.process is None
            else {
                "pid": intent.process.pid,
                "start_identity": intent.process.start_identity,
                "process_group_id": intent.process.process_group_id,
                "control_pid": intent.process.control_pid,
            },
            "created_at": intent.created_at,
            "updated_at": intent.updated_at,
        }
        return encode_checksummed_document(self.schema, payload)

    def decode(self, raw: bytes) -> ServiceStartIntent:
        try:
            decoded = decode_checksummed_document(raw, expected_schema=self.schema)
            data = dict(decoded.payload)
            data["phase"] = ServiceStartIntentPhase(data["phase"])
            handle = data.get("recovery_handle")
            if handle is not None:
                if not isinstance(handle, dict):
                    raise TypeError("recovery_handle must be object")
                opaque = base64.b64decode(handle["opaque_payload_b64"], validate=True)
                data["recovery_handle"] = ServiceStartRecoveryHandle(
                    str(handle["provider_schema"]),
                    str(handle["payload_sha256"]),
                    opaque,
                )
            process = data.get("process")
            if process is not None:
                if not isinstance(process, dict):
                    raise TypeError("process must be object")
                data["process"] = ServiceProcessIdentity(**process)
            return ServiceStartIntent(**data)
        except ChecksummedDocumentError as exc:
            raise ServiceStartIntentIntegrityError.from_checksummed_document(
                exc, message="service-start intent document integrity failure"
            ) from exc
        except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
            raise ServiceStartIntentIntegrityError("service-start intent violates the intent contract") from exc


__all__ = [
    "SERVICE_START_INTENT_SCHEMA",
    "ServiceStartIntentCodec",
    "ServiceStartIntentIntegrityError",
]
