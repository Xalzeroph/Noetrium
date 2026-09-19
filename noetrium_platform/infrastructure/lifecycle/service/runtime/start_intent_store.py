from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock

from .start_intent_codec import ServiceStartIntentCodec
from .start_intent_contracts import ServiceStartIntent, ServiceStartIntentPhase
from .start_intent_index import DirectoryActiveStartIntentIndex


class ServiceStartIntentConflict(RuntimeError):
    pass


class DirectoryServiceStartIntentStore:
    """Durable intent documents plus a recoverable active-intent acceleration index."""

    def __init__(self, root: Path, codec: ServiceStartIntentCodec | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.codec = codec or ServiceStartIntentCodec()
        self._active = DirectoryActiveStartIntentIndex(root / "_active")
        self._guard_path = root / ".guard.lock"
        self._empty_scope_mtime: dict[tuple[str, str], int] = {}

    def _path(self, intent_id: str) -> Path:
        digest = hashlib.sha256(intent_id.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, intent_id: str) -> ServiceStartIntent:
        return self.codec.decode(self._path(intent_id).read_bytes())

    def create_once(self, intent: ServiceStartIntent) -> ServiceStartIntent:
        """Atomically create one intent identity without timestamp races between starters."""
        path = self._path(intent.intent_id)
        with InterprocessFileLock(self._guard_path):
            if path.exists():
                return self.codec.decode(path.read_bytes())
            self._assert_no_other_active_locked(intent)
            atomic_replace_bytes(path, self.codec.encode(intent))
            if intent.phase is not ServiceStartIntentPhase.COMPLETE:
                self._empty_scope_mtime.pop((intent.service_id, intent.contract_digest), None)
                self._active.bind(intent)
            else:
                self._remember_empty_scope(intent.service_id, intent.contract_digest)
            return intent

    def put(self, intent: ServiceStartIntent) -> None:
        with InterprocessFileLock(self._guard_path):
            path = self._path(intent.intent_id)
            if path.exists():
                current = self.codec.decode(path.read_bytes())
                if (
                    current.service_id != intent.service_id
                    or current.contract_digest != intent.contract_digest
                    or current.attempt != intent.attempt
                ):
                    raise ServiceStartIntentConflict("service-start intent immutable identity changed")
            if intent.phase is not ServiceStartIntentPhase.COMPLETE:
                self._assert_no_other_active_locked(intent)
            # Intent document is authoritative.  Publish it before touching the disposable
            # pointer so a crash can always recover by scanning these documents.
            atomic_replace_bytes(path, self.codec.encode(intent))
            if intent.phase is ServiceStartIntentPhase.COMPLETE:
                self._active.clear(
                    intent.service_id,
                    intent.contract_digest,
                    expected_intent_id=intent.intent_id,
                )
                self._remember_empty_scope(intent.service_id, intent.contract_digest)
            else:
                self._empty_scope_mtime.pop((intent.service_id, intent.contract_digest), None)
                self._active.bind(intent)

    def all(self) -> tuple[ServiceStartIntent, ...]:
        return tuple(self.codec.decode(path.read_bytes()) for path in sorted(self.root.glob("*.json")))

    def unresolved(self, service_id: str, contract_digest: str) -> tuple[ServiceStartIntent, ...]:
        with InterprocessFileLock(self._guard_path):
            active_id = self._active.read(service_id, contract_digest)
            if active_id is not None:
                path = self._path(active_id)
                if not path.exists():
                    raise ServiceStartIntentConflict(
                        "active service-start intent pointer references missing authoritative intent"
                    )
                intent = self.codec.decode(path.read_bytes())
                self._assert_scope(intent, service_id, contract_digest)
                if intent.phase is ServiceStartIntentPhase.COMPLETE:
                    # Crash window: COMPLETE document was durable but pointer clear was not.
                    self._active.clear(service_id, contract_digest, expected_intent_id=active_id)
                    self._remember_empty_scope(service_id, contract_digest)
                    return ()
                return (intent,)

            if self._empty_scope_is_current(service_id, contract_digest):
                return ()

            # Recovery-only slow path: a crash may occur after authoritative intent publish
            # and before active pointer publish.  Rebuild the acceleration index once.
            values = self._scan_unresolved_locked(service_id, contract_digest)
            if len(values) == 1:
                self._empty_scope_mtime.pop((service_id, contract_digest), None)
                self._active.bind(values[0])
            elif not values:
                self._remember_empty_scope(service_id, contract_digest)
            return values

    def _root_mtime_ns(self) -> int:
        return self.root.stat().st_mtime_ns

    def _remember_empty_scope(self, service_id: str, contract_digest: str) -> None:
        self._empty_scope_mtime[(service_id, contract_digest)] = self._root_mtime_ns()

    def _empty_scope_is_current(self, service_id: str, contract_digest: str) -> bool:
        cached = self._empty_scope_mtime.get((service_id, contract_digest))
        return cached is not None and cached == self._root_mtime_ns()

    def _scan_unresolved_locked(
        self, service_id: str, contract_digest: str
    ) -> tuple[ServiceStartIntent, ...]:
        values = [
            intent
            for intent in self.all()
            if intent.service_id == service_id
            and intent.contract_digest == contract_digest
            and intent.phase is not ServiceStartIntentPhase.COMPLETE
        ]
        return tuple(sorted(values, key=lambda item: (item.attempt, item.intent_id)))

    def _assert_no_other_active_locked(self, intent: ServiceStartIntent) -> None:
        active_id = self._active.read(intent.service_id, intent.contract_digest)
        if active_id is None or active_id == intent.intent_id:
            return
        active_path = self._path(active_id)
        if not active_path.exists():
            raise ServiceStartIntentConflict(
                "active service-start intent pointer references missing authoritative intent"
            )
        active = self.codec.decode(active_path.read_bytes())
        if active.phase is ServiceStartIntentPhase.COMPLETE:
            self._active.clear(
                intent.service_id,
                intent.contract_digest,
                expected_intent_id=active_id,
            )
            return
        raise ServiceStartIntentConflict("another unresolved service-start intent already exists")

    @staticmethod
    def _assert_scope(intent: ServiceStartIntent, service_id: str, contract_digest: str) -> None:
        if intent.service_id != service_id or intent.contract_digest != contract_digest:
            raise ServiceStartIntentConflict("active service-start intent scope mismatch")


__all__ = ["DirectoryServiceStartIntentStore", "ServiceStartIntentConflict"]
