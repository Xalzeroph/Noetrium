from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from dataclasses import asdict

from noetrium_platform.foundation.kernel.kernel.durability.document_integrity import DocumentIntegrityError
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)

from .contracts import ServiceExitClass, ServicePhase
from .service_state_contracts import ServiceSupervisorState


SERVICE_STATE_DOCUMENT_SCHEMA = "service-supervisor-state.v3"


class ServiceStateIntegrityError(DocumentIntegrityError):
    """Persisted service-supervisor state is corrupt or semantically unsupported."""


def _payload(state: ServiceSupervisorState) -> dict[str, object]:
    return {
        "service_id": state.service_id,
        "contract_digest": state.contract_digest,
        "phase": state.phase.value,
        "attempt": state.attempt,
        "process": None if state.process is None else asdict(state.process),
        "ready_evidence_ref": state.ready_evidence_ref,
        "stdout_capture_ref": state.stdout_capture_ref,
        "stderr_capture_ref": state.stderr_capture_ref,
        "last_heartbeat_at": state.last_heartbeat_at,
        "ready_at": state.ready_at,
        "last_failure_id": state.last_failure_id,
        "last_exit_class": None if state.last_exit_class is None else int(state.last_exit_class),
        "updated_at": state.updated_at,
    }


class ServiceSupervisorStateCodec:
    """Versioned/checksummed document codec; owns no filesystem I/O."""

    schema = SERVICE_STATE_DOCUMENT_SCHEMA

    def encode(self, state: ServiceSupervisorState) -> bytes:
        if (state.ready_evidence_ref is None) != (state.ready_at is None):
            raise ServiceStateIntegrityError("service ready evidence and ready_at must be complete together")
        return encode_checksummed_document(self.schema, _payload(state))

    def decode(self, raw: bytes) -> ServiceSupervisorState:
        try:
            decoded = decode_checksummed_document(
                raw,
                expected_schema=self.schema,
            )
        except ChecksummedDocumentError as exc:
            raise ServiceStateIntegrityError.from_checksummed_document(
                exc, message="service state document integrity failure"
            ) from exc
        return self._decode_payload(decoded.payload)

    @staticmethod
    def _decode_payload(payload: dict[str, object]) -> ServiceSupervisorState:
        data = dict(payload)
        try:
            data["phase"] = ServicePhase(data["phase"])
            if data.get("last_exit_class") is not None:
                data["last_exit_class"] = ServiceExitClass(int(data["last_exit_class"]))
            if (data.get("ready_evidence_ref") is None) != (data.get("ready_at") is None):
                raise ValueError("service ready evidence and ready_at must be complete together")
            if data.get("process") is not None:
                process = data["process"]
                if not isinstance(process, dict):
                    raise TypeError("process identity must be an object")
                data["process"] = ServiceProcessIdentity(**process)
            return ServiceSupervisorState(**data)
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceStateIntegrityError("service state payload violates the supervisor-state contract") from exc


__all__ = [
    "SERVICE_STATE_DOCUMENT_SCHEMA",
    "ServiceStateIntegrityError",
    "ServiceSupervisorStateCodec",
]
