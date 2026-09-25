from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes, durable_unlink

from .start_intent_contracts import ServiceStartIntent

_SCHEMA = "service-start-intent-active.v1"


class ServiceStartIntentIndexIntegrityError(RuntimeError):
    pass


def _scope_digest(service_id: str, contract_digest: str) -> str:
    return hashlib.sha256(f"{service_id}\0{contract_digest}".encode("utf-8")).hexdigest()


class DirectoryActiveStartIntentIndex:
    """Recoverable O(1) pointer to the one unresolved intent for a frozen contract.

    The pointer is an acceleration structure, never the sole source of truth.  A missing
    pointer can be rebuilt by scanning authoritative per-intent documents after a crash.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, service_id: str, contract_digest: str) -> Path:
        return self.root / f"{_scope_digest(service_id, contract_digest)}.json"

    def read(self, service_id: str, contract_digest: str) -> str | None:
        path = self._path(service_id, contract_digest)
        if not path.exists():
            return None
        try:
            payload = decode_checksummed_document(
                path.read_bytes(), expected_schema=_SCHEMA
            ).payload
            if payload.get("service_id") != service_id or payload.get("contract_digest") != contract_digest:
                raise ServiceStartIntentIndexIntegrityError("active start-intent pointer scope mismatch")
            intent_id = payload.get("intent_id")
            if not isinstance(intent_id, str) or not intent_id:
                raise ServiceStartIntentIndexIntegrityError("active start-intent pointer id invalid")
            return intent_id
        except ChecksummedDocumentError as exc:
            raise ServiceStartIntentIndexIntegrityError(
                "active start-intent pointer integrity failure"
            ) from exc

    def bind(self, intent: ServiceStartIntent) -> None:
        atomic_replace_bytes(
            self._path(intent.service_id, intent.contract_digest),
            encode_checksummed_document(
                _SCHEMA,
                {
                    "service_id": intent.service_id,
                    "contract_digest": intent.contract_digest,
                    "intent_id": intent.intent_id,
                },
            ),
        )

    def clear(self, service_id: str, contract_digest: str, *, expected_intent_id: str) -> None:
        current = self.read(service_id, contract_digest)
        if current is None:
            return
        if current != expected_intent_id:
            raise ServiceStartIntentIndexIntegrityError(
                "active start-intent pointer changed before clear"
            )
        durable_unlink(self._path(service_id, contract_digest))


__all__ = [
    "DirectoryActiveStartIntentIndex",
    "ServiceStartIntentIndexIntegrityError",
]
