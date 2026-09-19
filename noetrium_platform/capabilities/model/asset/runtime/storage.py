from __future__ import annotations

from pathlib import Path
import shutil
from typing import Mapping

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.capabilities.model.asset.api import ManagedModelAsset, ModelAssetMode, ModelStoragePoolStatus


class LocalModelAssetStorage:
    """Local model-weight storage with explicit named pools for large assets."""

    def __init__(
        self, directories: DirectoryLayoutPort, *, additional_pools: Mapping[str, Path] | None = None
    ) -> None:
        pools = {"default": directories.root(ManagedDirectoryKind.MODEL_ARTIFACTS)}
        for pool_id, path in (additional_pools or {}).items():
            self._validate_pool_id(pool_id)
            if pool_id == "default":
                raise ValueError("default model storage pool is owned by directory layout")
            pools[pool_id] = path.expanduser().resolve()
        self._pools = pools
        for path in self._pools.values():
            path.mkdir(parents=True, exist_ok=True)

    def pools(self) -> tuple[ModelStoragePoolStatus, ...]:
        values = []
        for pool_id, path in sorted(self._pools.items()):
            total, used, free = shutil.disk_usage(path)
            values.append(ModelStoragePoolStatus(pool_id, path, total, used, free))
        return tuple(values)

    def target(self, model_id: str, *, pool_id: str = "default") -> Path:
        return self._pool(pool_id) / model_id

    def materialize(
        self, model_id: str, source: Path, mode: ModelAssetMode, *, pool_id: str = "default"
    ) -> Path:
        source = source.expanduser().resolve()
        if mode is ModelAssetMode.REFERENCE:
            return source
        destination = self.target(model_id, pool_id=pool_id)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"managed model already exists in pool {pool_id}: {model_id}")
        if mode is ModelAssetMode.COPY:
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                destination.mkdir(parents=True, exist_ok=False)
                shutil.copy2(source, destination / source.name)
        elif mode is ModelAssetMode.MOVE:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        elif mode is ModelAssetMode.SYMLINK:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(source, target_is_directory=source.is_dir())
        return destination

    def remove(self, asset: ManagedModelAsset) -> bool:
        if asset.mode is ModelAssetMode.REFERENCE:
            return False
        path = asset.path
        if asset.mode is ModelAssetMode.SYMLINK:
            if not path.is_symlink():
                return False
            path.unlink()
            return True
        if not path.exists():
            return False
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True

    def _pool(self, pool_id: str) -> Path:
        self._validate_pool_id(pool_id)
        try:
            return self._pools[pool_id]
        except KeyError as exc:
            raise KeyError(f"unknown model storage pool: {pool_id}") from exc

    @staticmethod
    def _validate_pool_id(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid model storage pool id")


__all__ = ["LocalModelAssetStorage"]
