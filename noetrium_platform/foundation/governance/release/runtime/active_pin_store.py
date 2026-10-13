from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes, durable_unlink
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock

from .active_pin_codec import ActiveReleasePinCodec
from noetrium_platform.foundation.governance.release.api import ActiveReleasePin, ActiveReleasePinned


class ActiveReleasePinStore:
    """Operational artifact-lifetime pins; never a scientific state authority."""

    def __init__(self, root: Path, codec: ActiveReleasePinCodec | None = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.codec = codec or ActiveReleasePinCodec()
        self._guard = InterprocessFileLock(self.root / ".pins.guard.lock")

    @staticmethod
    def _key(control_id: str, runtime_manifest_digest: str) -> str:
        return hashlib.sha256(f"{control_id}\0{runtime_manifest_digest}".encode()).hexdigest()

    def _path(self, control_id: str, runtime_manifest_digest: str) -> Path:
        return self.root / f"{self._key(control_id, runtime_manifest_digest)}.json"


    def lifecycle(self, control_id: str, runtime_manifest_digest: str) -> InterprocessFileLock:
        key = self._key(control_id, runtime_manifest_digest)
        return InterprocessFileLock(self.root / f"{key}.lifecycle.lock")

    def get(self, control_id: str, runtime_manifest_digest: str) -> ActiveReleasePin | None:
        path = self._path(control_id, runtime_manifest_digest)
        if not path.exists():
            return None
        return self.codec.decode(path.read_bytes())

    def acquire(
        self,
        control_id: str,
        runtime_manifest_digest: str,
        release_digest: str,
    ) -> ActiveReleasePin:
        candidate = ActiveReleasePin.create(control_id, runtime_manifest_digest, release_digest)
        path = self._path(control_id, runtime_manifest_digest)
        with self._guard:
            if path.exists():
                current = self.codec.decode(path.read_bytes())
                if (
                    current.control_id != control_id
                    or current.runtime_manifest_digest != runtime_manifest_digest
                    or current.release_digest != release_digest
                ):
                    raise ActiveReleasePinned("existing active release pin is bound differently")
                return current
            atomic_replace_bytes(path, self.codec.encode(candidate))
            return candidate

    def release(self, control_id: str, runtime_manifest_digest: str) -> None:
        path = self._path(control_id, runtime_manifest_digest)
        with self._guard:
            if not path.exists():
                return
            current = self.codec.decode(path.read_bytes())
            if current.control_id != control_id or current.runtime_manifest_digest != runtime_manifest_digest:
                raise ActiveReleasePinned("refusing to release a mismatched active release pin")
            durable_unlink(path)

    def all(self) -> tuple[ActiveReleasePin, ...]:
        rows = []
        for path in sorted(self.root.glob("*.json")):
            rows.append(self.codec.decode(path.read_bytes()))
        return tuple(rows)

    def active_for_release(self, release_digest: str) -> tuple[ActiveReleasePin, ...]:
        return tuple(pin for pin in self.all() if pin.release_digest == release_digest)

    def assert_unpinned(self, release_digest: str) -> None:
        pins = self.active_for_release(release_digest)
        if pins:
            owners = ", ".join(sorted(f"{pin.control_id}:{pin.runtime_manifest_digest[:12]}" for pin in pins))
            raise ActiveReleasePinned(f"release {release_digest} is still pinned by {owners}")


__all__ = ["ActiveReleasePinStore", "ActiveReleasePinned"]
