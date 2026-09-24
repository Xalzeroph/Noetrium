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
        return self._retired_root / f"{model_id}.json"

    def _lock(self, model_id: str) -> InterprocessFileLock:
        return InterprocessFileLock(
            self._lock_root / f"{model_id}.lock"
        )

    @staticmethod
    def _digest(value: ManagedModelAsset) -> str:
        return sha256(encode_model_asset(value)).hexdigest()

    @staticmethod
    def _retirement_payload(
        asset_digest: str,
        delete_managed_files: bool,
        gc_proof_digest: str | None,
    ) -> bytes:
        return json.dumps(
            {
                "asset_digest": asset_digest,
                "delete_managed_files": delete_managed_files,
                "gc_proof_digest": gc_proof_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _decode_retirement(raw: bytes) -> tuple[str, bool, str | None]:
        value = json.loads(raw.decode("utf-8"))
        proof = value.get("gc_proof_digest") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or set(value)
            != {"asset_digest", "delete_managed_files", "gc_proof_digest"}
            or type(value.get("asset_digest")) is not str
            or len(value["asset_digest"]) != 64
            or any(ch not in "0123456789abcdef" for ch in value["asset_digest"])
            or type(value.get("delete_managed_files")) is not bool
            or (
                proof is not None
                and (
                    type(proof) is not str
                    or len(proof) != 64
                    or any(ch not in "0123456789abcdef" for ch in proof)
                )
            )
            or (value["delete_managed_files"] and proof is None)
            or (not value["delete_managed_files"] and proof is not None)
        ):
            raise RuntimeError("invalid model asset retirement document")
        return value["asset_digest"], value["delete_managed_files"], proof


    def ensure_not_retired(self, model_id: str) -> None:
        self._validate_id(model_id)
        with self._lock(model_id):
            if self._retired_path(model_id).exists():
                raise RuntimeError(
                    "model asset identity is retired and cannot be reused: "
                    f"{model_id}"
                )

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
        *,
        delete_managed_files: bool,
        gc_proof_digest: str | None = None,
    ) -> ManagedModelAsset:
        """Fence one exact registered asset and retain metadata for recovery."""

        if type(expected) is not ManagedModelAsset:
            raise TypeError(
                "model asset retirement requires ManagedModelAsset"
            )
        if type(delete_managed_files) is not bool:
            raise TypeError(
                "model asset retirement deletion policy must be bool"
            )
        if delete_managed_files:
            if (
                type(gc_proof_digest) is not str
                or len(gc_proof_digest) != 64
                or any(
                    ch not in "0123456789abcdef"
                    for ch in gc_proof_digest
                )
            ):
                raise ValueError(
                    "model asset retirement GC proof must be lowercase sha256"
                )
        elif gc_proof_digest is not None:
            raise ValueError(
                "non-destructive model retirement cannot bind a GC proof"
            )
        self._validate_id(expected.model_id)
        with self._lock(expected.model_id):
            path = self._path(expected.model_id)
            retired = self._retired_path(expected.model_id)
            expected_digest = self._digest(expected)

            if retired.exists():
                (
                    retired_digest,
                    durable_delete,
                    durable_gc_proof,
                ) = self._decode_retirement(retired.read_bytes())
                if (
                    retired_digest != expected_digest
                    or durable_delete != delete_managed_files
                    or durable_gc_proof != gc_proof_digest
                ):
                    raise RuntimeError(
                        "model asset retirement generation/policy drifted: "
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
                self._retirement_payload(
                    expected_digest,
                    delete_managed_files,
                    gc_proof_digest,
                ),
            )
            return current

    def authorize_gc(
        self,
        expected: ManagedModelAsset,
        *,
        gc_proof_digest: str,
    ) -> ManagedModelAsset:
        """Upgrade logical retirement into proof-bound physical GC intent."""

        if type(expected) is not ManagedModelAsset:
            raise TypeError("model asset GC authorization requires ManagedModelAsset")
        if (
            type(gc_proof_digest) is not str
            or len(gc_proof_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in gc_proof_digest)
        ):
            raise ValueError("model asset GC proof must be lowercase sha256")
        self._validate_id(expected.model_id)
        with self._lock(expected.model_id):
            retired = self._retired_path(expected.model_id)
            if not retired.exists():
                raise RuntimeError(
                    "model asset must be logically retired before physical GC: "
                    f"{expected.model_id}"
                )
            expected_digest = self._digest(expected)
            retired_digest, durable_delete, durable_proof = self._decode_retirement(
                retired.read_bytes()
            )
            if retired_digest != expected_digest:
                raise RuntimeError(
                    "model asset GC generation drifted: "
                    f"{expected.model_id}"
                )
            path = self._path(expected.model_id)
            if not path.exists():
                if durable_delete and durable_proof == gc_proof_digest:
                    return expected
                raise RuntimeError(
                    "retired model asset metadata disappeared before GC authorization: "
                    f"{expected.model_id}"
                )
            current = self._read(expected.model_id)
            if self._digest(current) != expected_digest:
                raise RuntimeError(
                    "retired model asset metadata drifted before GC authorization: "
                    f"{expected.model_id}"
                )
            if durable_delete:
                if durable_proof != gc_proof_digest:
                    raise RuntimeError(
                        "model asset GC proof changed across retirement retry"
                    )
                return current
            atomic_replace_bytes(
                retired,
                self._retirement_payload(
                    expected_digest,
                    True,
                    gc_proof_digest,
                ),
            )
            return current

    def retirement(
        self,
        model_id: str,
    ) -> tuple[ManagedModelAsset | None, bool, str | None] | None:
        """Read durable policy, GC proof and retained metadata for recovery."""

        self._validate_id(model_id)
        with self._lock(model_id):
            retired = self._retired_path(model_id)
            if not retired.exists():
                return None
            (
                retired_digest,
                delete_managed_files,
                gc_proof_digest,
            ) = self._decode_retirement(retired.read_bytes())
            path = self._path(model_id)
            if not path.exists():
                return None, delete_managed_files, gc_proof_digest
            current = self._read(model_id)
            if retired_digest != self._digest(current):
                raise RuntimeError(
                    f"model asset retirement metadata drifted: {model_id}"
                )
            return current, delete_managed_files, gc_proof_digest

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
            (
                retired_digest,
                delete_managed_files,
                _gc_proof_digest,
            ) = self._decode_retirement(retired.read_bytes())
            if retired_digest != expected_digest:
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
            if not delete_managed_files:
                # Logical retirement fences new use but deliberately retains
                # exact metadata so a later proof-backed GC can still locate
                # and delete the managed bytes without guessing a path.
                return True
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
