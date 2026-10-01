from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Mapping
from uuid import uuid4

from noetrium_platform.substrate.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    fsync_directory,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.capabilities.model.asset.api import (
    ManagedModelAsset,
    ModelAssetMode,
    ModelStoragePoolStatus,
)


class LocalModelAssetStorage:
    """Content-addressed local model storage with stable logical model aliases."""

    _CHUNK=1024 * 1024

    def __init__(
        self,
        directories: DirectoryLayoutPort,
        *,
        additional_pools: Mapping[str, Path] | None = None,
    ) -> None:
        pools = {"default": directories.root(ManagedDirectoryKind.MODEL_ARTIFACTS)}
        for pool_id, path in (additional_pools or {}).items():
            self._validate_pool_id(pool_id)
            if pool_id == "default":
                raise ValueError(
                    "default model storage pool is owned by directory layout"
                )
            pools[pool_id] = path.expanduser().resolve()
        self._pools = pools
        for path in self._pools.values():
            path.mkdir(parents=True, exist_ok=True)
            (path / ".cas" / "sha256").mkdir(parents=True, exist_ok=True)
            (path / ".staging").mkdir(parents=True, exist_ok=True)
            with self._pool_lock(path):
                self._collect_unreferenced_cas_locked(path)

    def pools(self) -> tuple[ModelStoragePoolStatus, ...]:
        values = []
        for pool_id, path in sorted(self._pools.items()):
            total, used, free = shutil.disk_usage(path)
            values.append(
                ModelStoragePoolStatus(pool_id, path, total, used, free)
            )
        return tuple(values)

    def target(self, model_id: str, *, pool_id: str = "default") -> Path:
        self._validate_model_id(model_id)
        return self._pool(pool_id) / model_id

    def materialize(
        self,
        model_id: str,
        source: Path,
        mode: ModelAssetMode,
        *,
        pool_id: str = "default",
    ) -> Path:
        source = source.expanduser().resolve()
        if mode is ModelAssetMode.REFERENCE:
            return source

        destination = self.target(model_id, pool_id=pool_id)
        pool = self._pool(pool_id)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(
                f"managed model already exists in pool {pool_id}: {model_id}"
            )

        if mode is ModelAssetMode.SYMLINK:
            destination.symlink_to(
                source,
                target_is_directory=source.is_dir(),
            )
            fsync_directory(destination.parent)
            return destination

        if mode not in {
            ModelAssetMode.COPY,
            ModelAssetMode.MOVE,
            ModelAssetMode.FETCHED,
        }:
            raise ValueError(f"unsupported managed model mode: {mode}")

        digest = self._tree_digest(source)
        cas_path = self._cas_path(pool, digest)
        with self._pool_lock(pool):
            self._collect_unreferenced_cas_locked(pool)
            if cas_path.exists() or cas_path.is_symlink():
                if cas_path.is_symlink() or self._tree_digest(cas_path) != digest:
                    raise RuntimeError(
                        "model CAS object failed integrity verification"
                    )
                if mode is ModelAssetMode.MOVE:
                    self._remove_source(source)
            else:
                self._publish_cas_object(
                    source,
                    cas_path,
                    mode=mode,
                )
                if self._tree_digest(cas_path) != digest:
                    raise RuntimeError(
                        "published model CAS object failed integrity verification"
                    )
            relative = os.path.relpath(cas_path, destination.parent)
            destination.symlink_to(
                relative,
                target_is_directory=cas_path.is_dir(),
            )
            fsync_directory(destination.parent)
        return destination

    def remove(self, asset: ManagedModelAsset) -> bool:
        if type(asset) is not ManagedModelAsset:
            raise TypeError(
                "model storage removal requires ManagedModelAsset"
            )
        if asset.mode is ModelAssetMode.REFERENCE:
            return False
        if asset.storage_pool is None:
            raise RuntimeError(
                f"managed model asset lost storage pool identity: {asset.model_id}"
            )

        pool = self._pool(asset.storage_pool)
        expected = self.target(
            asset.model_id,
            pool_id=asset.storage_pool,
        ).absolute()
        path = asset.path.absolute()
        if path != expected:
            raise RuntimeError(
                "managed model asset path escaped canonical storage target: "
                f"{asset.model_id}"
            )

        if asset.mode is ModelAssetMode.SYMLINK:
            if path.is_symlink():
                path.unlink()
                fsync_directory(path.parent)
                return True
            if path.exists():
                raise RuntimeError(
                    "managed model symlink changed physical type: "
                    f"{asset.model_id}"
                )
            return False

        with self._pool_lock(pool):
            if not path.is_symlink():
                if path.exists():
                    raise RuntimeError(
                        "managed CAS model alias changed physical type: "
                        f"{asset.model_id}"
                    )
                return False

            target = self._alias_target(path)
            cas_root = (pool / ".cas" / "sha256").resolve()
            try:
                target.relative_to(cas_root)
            except ValueError as exc:
                raise RuntimeError(
                    "managed model alias escaped CAS root: "
                    f"{asset.model_id}"
                ) from exc

            aliases = self._aliases_for_target_locked(pool, target)
            if path not in aliases:
                raise RuntimeError(
                    "managed model alias lost CAS reference identity: "
                    f"{asset.model_id}"
                )
            if len(aliases) == 1:
                self._remove_cas_object(target)
            path.unlink()
            fsync_directory(path.parent)
            self._collect_unreferenced_cas_locked(pool)
            return True

    def staging_target(
        self,
        model_id: str,
        *,
        pool_id: str = "default",
    ) -> Path:
        self._validate_model_id(model_id)
        root = self._pool(pool_id) / ".staging"
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{model_id}.{uuid4().hex}"

    def _publish_cas_object(
        self,
        source: Path,
        destination: Path,
        *,
        mode: ModelAssetMode,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / (
            f".{destination.name}.publish.{uuid4().hex}"
        )
        try:
            # CAS objects are self-contained byte materializations. Never
            # preserve external symlinks (notably Hugging Face snapshot links)
            # inside Noetrium-owned content-addressed storage.
            self._copy_source(source, staging)
            self._fsync_tree(staging)
            staging.rename(destination)
            fsync_directory(destination.parent)
            if mode is ModelAssetMode.MOVE:
                self._remove_source(source)
        except BaseException:
            self._remove_source(staging)
            raise

    def _copy_source(self, source: Path, destination: Path) -> None:
        if source.is_symlink():
            resolved = source.resolve(strict=True)
            if not resolved.is_file():
                raise RuntimeError(
                    "model CAS refuses directory symlink source"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, destination)
            return
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return
        if not source.is_dir():
            raise RuntimeError(
                f"unsupported model source type: {source}"
            )

        destination.mkdir(parents=True, exist_ok=False)
        for entry in sorted(
            source.rglob("*"),
            key=lambda value: value.relative_to(source).as_posix(),
        ):
            relative = entry.relative_to(source)
            target = destination / relative
            if entry.is_symlink():
                resolved = entry.resolve(strict=True)
                if not resolved.is_file():
                    raise RuntimeError(
                        "model CAS refuses directory symlink entry: "
                        f"{entry}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resolved, target)
            elif entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif entry.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry, target)
            else:
                raise RuntimeError(
                    f"unsupported model CAS filesystem entry: {entry}"
                )

    @staticmethod
    def _remove_source(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    def _tree_digest(self, root: Path) -> str:
        if not (root.exists() or root.is_symlink()):
            raise FileNotFoundError(root)
        digest = sha256()
        is_root_directory = root.is_dir() and not root.is_symlink()
        base = root if is_root_directory else root.parent
        entries = (
            tuple(
                sorted(
                    root.rglob("*"),
                    key=lambda value: value.relative_to(root).as_posix(),
                )
            )
            if is_root_directory
            else (root,)
        )
        for entry in entries:
            relative = (
                entry.relative_to(base).as_posix()
                if is_root_directory
                else entry.name
            )
            encoded = relative.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)

            physical = entry
            if entry.is_symlink():
                physical = entry.resolve(strict=True)
                if not physical.is_file():
                    raise RuntimeError(
                        "model CAS refuses directory symlink entry: "
                        f"{entry}"
                    )

            if physical.is_dir():
                digest.update(b"D")
                continue
            if not physical.is_file():
                raise RuntimeError(
                    f"unsupported model CAS filesystem entry: {entry}"
                )
            digest.update(b"F")
            digest.update(physical.stat().st_size.to_bytes(16, "big"))
            with physical.open("rb") as handle:
                for chunk in iter(lambda: handle.read(self._CHUNK), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    def _fsync_tree(self, root: Path) -> None:
        if root.is_symlink():
            fsync_directory(root.parent)
            return
        if root.is_file():
            with root.open("rb") as handle:
                os.fsync(handle.fileno())
            fsync_directory(root.parent)
            return
        for path in sorted(
            (value for value in root.rglob("*") if value.is_file() and not value.is_symlink()),
            key=lambda value: value.as_posix(),
        ):
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        directories = [
            value
            for value in root.rglob("*")
            if value.is_dir() and not value.is_symlink()
        ]
        for directory in sorted(
            directories,
            key=lambda value: len(value.parts),
            reverse=True,
        ):
            fsync_directory(directory)
        fsync_directory(root)

    @staticmethod
    def _cas_path(pool: Path, digest: str) -> Path:
        return pool / ".cas" / "sha256" / digest[:2] / digest

    @staticmethod
    def _alias_target(alias: Path) -> Path:
        raw = os.readlink(alias)
        target = Path(raw)
        if not target.is_absolute():
            target = alias.parent / target
        return target.resolve(strict=False)

    def _aliases_for_target_locked(
        self,
        pool: Path,
        target: Path,
    ) -> tuple[Path, ...]:
        aliases: list[Path] = []
        for candidate in pool.iterdir():
            if candidate.name.startswith(".") or not candidate.is_symlink():
                continue
            if self._alias_target(candidate) == target:
                aliases.append(candidate.absolute())
        return tuple(sorted(aliases, key=lambda value: value.name))

    def _collect_unreferenced_cas_locked(self, pool: Path) -> None:
        cas_root = pool / ".cas" / "sha256"
        referenced = {
            self._alias_target(candidate)
            for candidate in pool.iterdir()
            if not candidate.name.startswith(".") and candidate.is_symlink()
        }
        if not cas_root.exists():
            return
        for prefix in tuple(cas_root.iterdir()):
            if not prefix.is_dir():
                continue
            for object_path in tuple(prefix.iterdir()):
                if object_path.resolve(strict=False) not in referenced:
                    self._remove_cas_object(object_path)
            if prefix.exists() and not any(prefix.iterdir()):
                prefix.rmdir()
                fsync_directory(prefix.parent)

    @staticmethod
    def _remove_cas_object(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
        if path.parent.exists():
            fsync_directory(path.parent)

    @staticmethod
    def _pool_lock(pool: Path) -> InterprocessFileLock:
        return InterprocessFileLock(pool / ".cas.lock")

    def _pool(self, pool_id: str) -> Path:
        self._validate_pool_id(pool_id)
        try:
            return self._pools[pool_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown model storage pool: {pool_id}"
            ) from exc

    @staticmethod
    def _validate_pool_id(value: str) -> None:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("invalid model storage pool id")

    @staticmethod
    def _validate_model_id(value: str) -> None:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("invalid model id")


__all__ = ["LocalModelAssetStorage"]
