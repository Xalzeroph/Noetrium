from __future__ import annotations

import base64

from noetrium_platform.foundation.kernel.kernel.durability.document_integrity import (
    DocumentIntegrityError,
)
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)

from .prepared_start import ServiceStartRecoveryHandle
from .start_intent_contracts import ServiceStartIntent, ServiceStartIntentPhase


SERVICE_START_INTENT_SCHEMA = "service-start-intent.v2"


class ServiceStartIntentIntegrityError(DocumentIntegrityError):
    pass


def _encode_contract(contract: ServiceLaunchContract) -> dict[str, object]:
    return {
        "service_id": contract.service_id,
        "generation": contract.generation,
        "executable": contract.executable,
        "argv": list(contract.argv),
        "cwd": contract.cwd,
        "environment_digest": contract.environment_digest,
        "artifact_digest": contract.artifact_digest,
        "runtime_identity_digest": contract.runtime_identity_digest,
        "readiness_timeout_s": contract.readiness_timeout_s,
        "stop_timeout_s": contract.stop_timeout_s,
        "heartbeat_interval_s": contract.heartbeat_interval_s,
    }


def _decode_contract(value: object) -> ServiceLaunchContract:
    if not isinstance(value, dict):
        raise TypeError("contract must be object")
    data = dict(value)
    argv = data.get("argv")
    if not isinstance(argv, list) or any(type(row) is not str for row in argv):
        raise TypeError("contract argv must be string list")
    data["argv"] = tuple(argv)
    return ServiceLaunchContract(**data)


class ServiceStartIntentCodec:
    schema = SERVICE_START_INTENT_SCHEMA

    def encode(self, intent: ServiceStartIntent) -> bytes:
        handle = intent.recovery_handle
        payload: dict[str, object] = {
            "intent_id": intent.intent_id,
            "contract": _encode_contract(intent.contract),
            "attempt": intent.attempt,
            "phase": intent.phase.value,
            "recovery_handle": None
            if handle is None
            else {
                "provider_schema": handle.provider_schema,
                "payload_sha256": handle.payload_sha256,
                "opaque_payload_b64": base64.b64encode(
                    handle.opaque_payload
                ).decode("ascii"),
            },
            "process": None
            if intent.process is None
            else {
                "pid": intent.process.pid,
                "start_identity": intent.process.start_identity,
                "process_group_id": intent.process.process_group_id,
                "control_pid": intent.process.control_pid,
                "anchor_pid": intent.process.anchor_pid,
                "anchor_start_identity": intent.process.anchor_start_identity,
                "anchor_control_pid": intent.process.anchor_control_pid,
            },
            "created_at": intent.created_at,
            "updated_at": intent.updated_at,
        }
        return encode_checksummed_document(self.schema, payload)

    def decode(self, raw: bytes) -> ServiceStartIntent:
        try:
            decoded = decode_checksummed_document(
                raw,
                expected_schema=self.schema,
            )
            data = dict(decoded.payload)
            data["contract"] = _decode_contract(data["contract"])
            data["phase"] = ServiceStartIntentPhase(data["phase"])
            handle = data.get("recovery_handle")
            if handle is not None:
                if not isinstance(handle, dict):
                    raise TypeError("recovery_handle must be object")
                opaque = base64.b64decode(
                    handle["opaque_payload_b64"],
                    validate=True,
                )
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
                exc,
                message="service-start intent document integrity failure",
            ) from exc
        except (
            KeyError,
            TypeError,
            ValueError,
            base64.binascii.Error,
        ) as exc:
            raise ServiceStartIntentIntegrityError(
                "service-start intent violates the intent contract"
            ) from exc


__all__ = [
    "SERVICE_START_INTENT_SCHEMA",
    "ServiceStartIntentCodec",
    "ServiceStartIntentIntegrityError",
]
