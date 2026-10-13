"""Crash-durable storage for immutable research.package NoetriumUnits."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import RLock

from noetrium_platform.foundation.kernel.kernel import (
    InterprocessFileLock,
    MachineConflict,
    MachineIntegrityError,
    atomic_replace_bytes,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from .record import (
    require_research_package,
    research_package_digest,
    research_package_id,
)


class DirectoryResearchPackageStore:
    """Content-addressed package store; Unit bytes are never edited in place."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.packages = self.root / "packages"
        self.locks = self.root / "locks"
        self.packages.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def _key(package_id: str) -> str:
        return sha256(package_id.encode("utf-8")).hexdigest()

    def _path(self, package_id: str) -> Path:
        return self.packages / f"{self._key(package_id)}.unit"

    def _lock_path(self, package_id: str) -> Path:
        return self.locks / f"{self._key(package_id)}.lock"

    @staticmethod
    def _decode(raw: bytes) -> NoetriumUnit:
        try:
            return require_research_package(decode_unit(raw))
        except (TypeError, ValueError) as exc:
            raise MachineIntegrityError("stored research package is invalid") from exc

    def save(self, package: NoetriumUnit) -> NoetriumUnit:
        package = require_research_package(package)
        package_id = research_package_id(package)
        with self._lock, InterprocessFileLock(self._lock_path(package_id)):
            path = self._path(package_id)
            if path.exists():
                try:
                    prior = self._decode(path.read_bytes())
                except OSError as exc:
                    raise MachineIntegrityError("stored research package is invalid") from exc
                if research_package_digest(prior) != research_package_digest(package):
                    raise MachineConflict("research package identity already has different content")
                return prior
            atomic_replace_bytes(path, encode_unit(package))
            return package

    def load(self, package_id: str) -> NoetriumUnit | None:
        if type(package_id) is not str or not package_id.strip():
            raise ValueError("package_id must be non-empty text")
        path = self._path(package_id)
        if not path.exists():
            return None
        try:
            package = self._decode(path.read_bytes())
        except OSError as exc:
            raise MachineIntegrityError("stored research package is invalid") from exc
        if research_package_id(package) != package_id:
            raise MachineIntegrityError("stored research package identity mismatch")
        return package

    def package_ids(self) -> tuple[str, ...]:
        with self._lock:
            values: list[str] = []
            for path in sorted(self.packages.glob("*.unit")):
                try:
                    package = self._decode(path.read_bytes())
                except OSError as exc:
                    raise MachineIntegrityError("stored research package is invalid") from exc
                values.append(research_package_id(package))
            return tuple(values)


__all__ = ["DirectoryResearchPackageStore"]
