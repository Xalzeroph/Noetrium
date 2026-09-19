from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock
from noetrium_platform.infrastructure.lifecycle.host.bootstrap.api import (
    ServerBootstrapIdentityConflict,
    ServerBootstrapState,
    ServerBootstrapStateConflict,
)

from .state_codec import ServerBootstrapStateCodec


class DirectoryServerBootstrapStateStore:
    """Durable CAS state for outer server-controller bootstrap transactions."""

    def __init__(self, root: Path, codec: ServerBootstrapStateCodec | None = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.codec = codec or ServerBootstrapStateCodec()

    @staticmethod
    def _key(control_id: str, runtime_manifest_digest: str) -> str:
        return hashlib.sha256(f"{control_id}\0{runtime_manifest_digest}".encode()).hexdigest()

    def _path(self, control_id: str, runtime_manifest_digest: str) -> Path:
        return self.root / f"{self._key(control_id, runtime_manifest_digest)}.json"

    def _lock(self, control_id: str, runtime_manifest_digest: str) -> InterprocessFileLock:
        return InterprocessFileLock(self.root / f"{self._key(control_id, runtime_manifest_digest)}.lock")

    def load_or_create(self, initial: ServerBootstrapState) -> ServerBootstrapState:
        path = self._path(initial.control_id, initial.runtime_manifest_digest)
        with self._lock(initial.control_id, initial.runtime_manifest_digest):
            if path.exists():
                current = self.codec.decode(path.read_bytes())
                if not current.same_identity(initial):
                    raise ServerBootstrapIdentityConflict("existing server bootstrap state belongs to another frozen identity")
                return current
            atomic_replace_bytes(path, self.codec.encode(initial))
            return initial

    def write(self, state: ServerBootstrapState, *, expected_revision: int) -> ServerBootstrapState:
        path = self._path(state.control_id, state.runtime_manifest_digest)
        with self._lock(state.control_id, state.runtime_manifest_digest):
            if not path.exists():
                raise ServerBootstrapStateConflict("server bootstrap state missing during CAS write")
            current = self.codec.decode(path.read_bytes())
            if not current.same_identity(state):
                raise ServerBootstrapIdentityConflict("server bootstrap CAS identity drift")
            if current.revision != expected_revision:
                raise ServerBootstrapStateConflict(
                    f"server bootstrap revision conflict: expected={expected_revision} actual={current.revision}"
                )
            if state.revision != expected_revision + 1:
                raise ServerBootstrapStateConflict("server bootstrap CAS write must advance revision exactly once")
            atomic_replace_bytes(path, self.codec.encode(state))
            return state


__all__ = ["DirectoryServerBootstrapStateStore"]
