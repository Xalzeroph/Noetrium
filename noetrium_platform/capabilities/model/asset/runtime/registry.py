from __future__ import annotations

from hashlib import sha256
import json

from noetrium_platform.substrate.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.capabilities.model.asset.api import ManagedModelAsset
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
    durable_unlink,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)

from .codec import decode_model_asset, encode_model_asset


class ModelAssetRegistry:
    """Durable mutable asset registry with terminal unregister semantics.

    Registered assets may be updated in place while active. Explicit retirement
    is different: it publishes a durable tombstone against one exact asset
    snapshot, immediately fences future updates, and keeps the metadata until
    physical managed-byte cleanup has converged.
    """

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = (
            directories.root(ManagedDirectoryKind.STATE)
            / "model"
            / "assets"
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._retired_root = self._root / "_retired"
        self._retired_root.mkdir(parents=True, exist_ok=True)
        self._lock_root = (
            directories.root(ManagedDirectoryKind.LOCKS)
            / "model-assets"
        )

    def _path(self, model_id: str):
        return self._root / f"{model_id}.json"

    def _retired_path(self, model_id: str):
        return self._retired_root / f"{model_id}.sha256"

    def _lock(self, model_id: str) -> InterprocessFileLock:
        return InterprocessFileLock(
            self._lock_root / f"{model_id}.lock"
        )

    @staticmethod
    def _digest(value: ManagedModelAsset) -> str:
        return sha256(encode_model_asset(value)).hexdigest()

    def put(self, value: ManagedModelAsset) -> ManagedModelAsset:
        self._validate_id(value.model_id)
        with self._lock(value.model_id):
            if self._retired_path(value.model_id).exists():
                raise RuntimeError(
                    "model asset identity is retired and cannot be reused: "
                    f"{value.model_id}"
                )
            atomic_replace_bytes(
                self._path(value.model_id),
                encode_model_asset(value),
            )
            return value

    def get(self, model_id: str) -> ManagedModelAsset:
        self._validate_id(model_id)
        if self._retired_path(model_id).exists():
            raise RuntimeError(
                f"model asset is retiring or retired: {model_id}"
            )
        return self._read(model_id)

    def _read(self, model_id: str) -> ManagedModelAsset:
        return decode_model_asset(
            json.loads(self._path(model_id).read_text("utf-8"))
        )

    def all(self) -> tuple[ManagedModelAsset, ...]:
        values: list[ManagedModelAsset] = []
        for path in sorted(self._root.glob("*.json")):
            if self._retired_path(path.stem).exists():
                continue
            values.append(self._read(path.stem))
        return tuple(values)

    def begin_retirement(
        self,
        expected: ManagedModelAsset,
    ) -> ManagedModelAsset:
        """Fence one exact registered asset and retain metadata for recovery."""

        if type(expected) is not ManagedModelAsset:
            raise TypeError(
                "model asset retirement requires ManagedModelAsset"
            )
        self._validate_id(expected.model_id)
        with self._lock(expected.model_id):
            path = self._path(expected.model_id)
            retired = self._retired_path(expected.model_id)
            expected_digest = self._digest(expected)

            if retired.exists():
                retired_digest = retired.read_text("ascii").strip()
                if retired_digest != expected_digest:
                    raise RuntimeError(
                        "model asset retirement generation drifted: "
                        f"{expected.model_id}"
                    )
                if not path.exists():
                    return expected
                current = self._read(expected.model_id)
                if self._digest(current) != expected_digest:
                    raise RuntimeError(
                        "retiring model asset metadata drifted: "
                        f"{expected.model_id}"
                    )
                return current

            current = self._read(expected.model_id)
            if self._digest(current) != expected_digest:
                raise RuntimeError(
                    "stale model asset generation: "
                    f"{expected.model_id}"
                )
            atomic_replace_bytes(
                retired,
                (expected_digest + "\n").encode("ascii"),
            )
            return current

    def retiring_asset(
        self,
        model_id: str,
    ) -> ManagedModelAsset | None:
        """Read exact retained metadata for an interrupted retirement."""

        self._validate_id(model_id)
        with self._lock(model_id):
            retired = self._retired_path(model_id)
            if not retired.exists():
                return None
            path = self._path(model_id)
            if not path.exists():
                return None
            current = self._read(model_id)
            if retired.read_text("ascii").strip() != self._digest(current):
                raise RuntimeError(
                    f"model asset retirement metadata drifted: {model_id}"
                )
            return current

    def finish_retirement(
        self,
        expected: ManagedModelAsset,
    ) -> bool:
        """Delete metadata only after managed physical bytes have converged."""

        if type(expected) is not ManagedModelAsset:
            raise TypeError(
                "model asset retirement requires ManagedModelAsset"
            )
        self._validate_id(expected.model_id)
        with self._lock(expected.model_id):
            retired = self._retired_path(expected.model_id)
            expected_digest = self._digest(expected)
            if not retired.exists():
                raise RuntimeError(
                    "model asset retirement was not prepared: "
                    f"{expected.model_id}"
                )
            if retired.read_text("ascii").strip() != expected_digest:
                raise RuntimeError(
                    "model asset retirement generation drifted: "
                    f"{expected.model_id}"
                )
            path = self._path(expected.model_id)
            if not path.exists():
                return True
            current = self._read(expected.model_id)
            if self._digest(current) != expected_digest:
                raise RuntimeError(
                    "retiring model asset metadata drifted: "
                    f"{expected.model_id}"
                )
            durable_unlink(path)
            return True

    @staticmethod
    def _validate_id(value: str) -> None:
        if (
            type(value) is not str
            or not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("invalid model id")


__all__ = ["ModelAssetRegistry"]
