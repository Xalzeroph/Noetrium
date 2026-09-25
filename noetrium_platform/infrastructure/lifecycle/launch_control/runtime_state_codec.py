from __future__ import annotations

from dataclasses import asdict

from noetrium_platform.foundation.kernel.kernel.durability.document_integrity import DocumentIntegrityError
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)

from .runtime_state_contracts import RuntimeControlState, RuntimeTxnPhase


RUNTIME_CONTROL_DOCUMENT_SCHEMA = "runtime-control-state.v3"


class RuntimeControlStateIntegrityError(DocumentIntegrityError):
    pass


class RuntimeControlStateCodec:
    schema = RUNTIME_CONTROL_DOCUMENT_SCHEMA

    def encode(self, state: RuntimeControlState) -> bytes:
        payload = asdict(state)
        payload["phase"] = state.phase.value
        payload["completed_actions"] = list(state.completed_actions)
        payload["evidence_refs"] = list(state.evidence_refs)
        return encode_checksummed_document(self.schema, payload)

    def decode(self, raw: bytes) -> RuntimeControlState:
        try:
            decoded = decode_checksummed_document(
                raw,
                expected_schema=self.schema,
            )
            data = dict(decoded.payload)
            data["phase"] = RuntimeTxnPhase(data["phase"])
            data["completed_actions"] = tuple(data["completed_actions"])
            data["evidence_refs"] = tuple(data["evidence_refs"])
            return RuntimeControlState(**data)
        except ChecksummedDocumentError as exc:
            raise RuntimeControlStateIntegrityError.from_checksummed_document(
                exc, message="runtime control document integrity failure"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeControlStateIntegrityError(
                "runtime control payload violates the control-state contract"
            ) from exc


__all__ = [
    "RUNTIME_CONTROL_DOCUMENT_SCHEMA",
    "RuntimeControlStateCodec",
    "RuntimeControlStateIntegrityError",
]
