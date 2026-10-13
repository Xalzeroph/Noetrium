from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)

from .artifact_closure import ModelArtifactClosureAuthority


_GIB = 1024**3


class ModelRuntimeAssetCache:
    """Disposable content-addressed hot projection for model serving bytes.

    The authoritative model path and artifact identity never change. A cached
    directory is only a Provider-side source for a bind mount whose in-container
    target remains the authoritative path.
    """

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise TypeError("model runtime asset cache root must be pathlib.Path")
        self.root = root.expanduser().absolute()
        self._objects = self.root / "objects" / "sha256"
        self._staging = self.root / ".staging"
        self._locks = self.root / ".locks"
        for path in (self._objects, self._staging, self._locks):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    @staticmethod
    def _tree_bytes(root: Path) -> int:
        total = 0
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
        return total

    def _target(self, digest: str) -> Path:
        return self._objects / digest[:2] / digest

    @staticmethod
    def _same_filesystem(source: Path, cache_root: Path) -> bool:
        return source.stat().st_dev == cache_root.stat().st_dev

    def resolve(
        self,
        source: Path,
        closure: ModelArtifactClosure,
    ) -> Path:
        """Return a verified hot path, or the authoritative source if cache is unavailable."""

        if not isinstance(source, Path):
            raise TypeError("model runtime cache source must be pathlib.Path")
        if not isinstance(closure, ModelArtifactClosure):
            raise TypeError("model runtime cache requires ModelArtifactClosure")
        source = source.expanduser().resolve(strict=True)
        if not source.is_dir():
            raise RuntimeError("model runtime cache source must be a directory")

        # Caching onto the same physical filesystem cannot improve cold weight I/O.
        if self._same_filesystem(source, self.root):
            return source

        digest = closure.digest()
        target = self._target(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = InterprocessFileLock(self._locks / f"{digest}.lock")
        with lock:
            if target.is_dir():
                try:
                    if ModelArtifactClosureAuthority().freeze(target) == closure:
                        return target
                except Exception:
                    pass
                self._remove(target)
            elif target.exists() or target.is_symlink():
                self._remove(target)

            for stale in self._staging.glob(f"{digest}.*"):
                self._remove(stale)

            required_bytes = self._tree_bytes(source)
            free_bytes = shutil.disk_usage(self.root).free
            reserve_bytes = max(_GIB, required_bytes // 20)
            if free_bytes < required_bytes + reserve_bytes:
                return source

            staging = self._staging / f"{digest}.{uuid4().hex}"
            try:
                shutil.copytree(source, staging, symlinks=False)
                observed = ModelArtifactClosureAuthority().freeze(staging)
                if observed != closure:
                    raise RuntimeError(
                        "model runtime cache projection failed artifact verification"
                    )
                staging.rename(target)
            except BaseException:
                self._remove(staging)
                raise
            return target


__all__ = ["ModelRuntimeAssetCache"]
