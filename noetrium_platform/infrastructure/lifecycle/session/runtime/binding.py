from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.kernel.durability.checksummed_document import (
    ChecksummedDocumentError,
    decode_checksummed_document,
    encode_checksummed_document,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionBinding, PersistentSessionSpec

_SCHEMA = "persistent-session-binding.v2"


class PersistentSessionBindingIntegrityError(RuntimeError):
    pass


class PersistentSessionBindingCodec:
    def encode(self, binding: PersistentSessionBinding) -> bytes:
        return encode_checksummed_document(
            _SCHEMA,
            {
                "spec": asdict(binding.spec),
                "spec_digest": binding.spec_digest,
                "control_identity_digest": binding.control_identity_digest,
            },
        )

    def decode(self, raw: bytes) -> PersistentSessionBinding:
        try:
            document = decode_checksummed_document(raw, expected_schema=_SCHEMA)
            spec_data = dict(document.payload["spec"])
            spec_data["command_argv"] = tuple(spec_data["command_argv"])
            spec_data["process_environment"] = tuple(tuple(row) for row in spec_data.get("process_environment", ()))
            spec = PersistentSessionSpec(**spec_data)
            binding = PersistentSessionBinding(
                spec,
                str(document.payload["spec_digest"]),
                str(document.payload["control_identity_digest"]),
            )
        except (ChecksummedDocumentError, KeyError, TypeError, ValueError) as exc:
            descriptor = describe_exception(exc)
            raise PersistentSessionBindingIntegrityError(
                f"persistent session binding decode failed: {descriptor.error_type}; "
                f"error_digest={descriptor.error_digest}"
            ) from exc
        if binding.spec_digest != spec.digest():
            raise PersistentSessionBindingIntegrityError("persistent session binding digest mismatch")
        if len(binding.control_identity_digest) != 64:
            raise PersistentSessionBindingIntegrityError("persistent session control identity invalid")
        return binding


class DirectoryPersistentSessionBindingStore:
    """Filesystem implementation of the binding-store port."""

    def __init__(self, root: Path, codec: PersistentSessionBindingCodec | None = None) -> None:
        self.root = root.resolve()
        self.codec = codec or PersistentSessionBindingCodec()

    def _path(self, session_name: str) -> Path:
        return self.root / f"{session_name}.json"

    def read(self, session_name: str) -> PersistentSessionBinding | None:
        path = self._path(session_name)
        if not path.exists():
            return None
        return self.codec.decode(path.read_bytes())

    def bind_once(self, binding: PersistentSessionBinding) -> PersistentSessionBinding:
        path = self._path(binding.spec.session_name)
        guard = path.with_name(path.name + ".guard.lock")
        with InterprocessFileLock(guard):
            if path.exists():
                return self.codec.decode(path.read_bytes())
            atomic_replace_bytes(path, self.codec.encode(binding))
            return binding


__all__ = [
    "DirectoryPersistentSessionBindingStore",
    "PersistentSessionBindingCodec",
    "PersistentSessionBindingIntegrityError",
]
