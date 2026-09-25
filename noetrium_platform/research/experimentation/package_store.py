"""Crash-durable storage for immutable ResearchPackage exports."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import RLock

from noetrium_platform.foundation.kernel.kernel import (
    MachineConflict,
    MachineIntegrityError,
)
from noetrium_platform.foundation.kernel.kernel.durability import (
    InterprocessFileLock,
    atomic_replace_bytes,
)
from .record import ResearchPackage


class DirectoryResearchPackageStore:
    """Content-checked package store; package bytes are never edited in place."""

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
        return self.packages / f"{self._key(package_id)}.json"

    def _lock_path(self, package_id: str) -> Path:
        return self.locks / f"{self._key(package_id)}.lock"


    def save(self, package: ResearchPackage) -> ResearchPackage:
        if not isinstance(package, ResearchPackage):
            raise TypeError("package store accepts ResearchPackage")
        with self._lock, InterprocessFileLock(self._lock_path(package.package_id)):
            path = self._path(package.package_id)
            if path.exists():
                try:
                    prior = ResearchPackage.import_bytes(path.read_bytes())
                except (OSError, TypeError, ValueError) as exc:
                    raise MachineIntegrityError("stored research package is invalid") from exc
                if prior.package_digest != package.package_digest:
                    raise MachineConflict("research package identity already has different content")
                return prior
            atomic_replace_bytes(path, package.export_bytes())
            return package

    def load(self, package_id: str) -> ResearchPackage | None:
        if type(package_id) is not str or not package_id.strip():
            raise ValueError("package_id must be non-empty text")
        path = self._path(package_id)
        if not path.exists():
            return None
        try:
            package = ResearchPackage.import_bytes(path.read_bytes())
        except (OSError, TypeError, ValueError) as exc:
            raise MachineIntegrityError("stored research package is invalid") from exc
        if package.package_id != package_id:
            raise MachineIntegrityError("stored research package identity mismatch")
        return package

    def package_ids(self) -> tuple[str, ...]:
        with self._lock:
            values: list[str] = []
            for path in sorted(self.packages.glob("*.json")):
                package = ResearchPackage.import_bytes(path.read_bytes())
                values.append(package.package_id)
            return tuple(values)


__all__ = ["DirectoryResearchPackageStore"]