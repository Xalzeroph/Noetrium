from __future__ import annotations

import json

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.capabilities.model.asset.api import ManagedModelAsset
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from .codec import decode_model_asset, encode_model_asset


class ModelAssetRegistry:
    """Authoritative mutable management registry for model assets only."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = directories.root(ManagedDirectoryKind.STATE) / "model" / "assets"
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, value: ManagedModelAsset) -> ManagedModelAsset:
        self._validate_id(value.model_id)
        atomic_replace_bytes(self._root / f"{value.model_id}.json", encode_model_asset(value))
        return value

    def get(self, model_id: str) -> ManagedModelAsset:
        self._validate_id(model_id)
        return decode_model_asset(json.loads((self._root / f"{model_id}.json").read_text("utf-8")))

    def all(self) -> tuple[ManagedModelAsset, ...]:
        return tuple(self.get(path.stem) for path in sorted(self._root.glob("*.json")))

    def remove(self, model_id: str) -> bool:
        self._validate_id(model_id)
        path = self._root / f"{model_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid model id")


__all__ = ["ModelAssetRegistry"]
