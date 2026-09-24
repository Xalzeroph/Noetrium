from __future__ import annotations

import hashlib
import json

from noetrium_platform.substrate.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
    durable_unlink,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)

from .applied import AppliedModelDeployment
from .codec import decode_applied, encode_applied


class AppliedModelDeploymentStore:
    """Process-exact applied-state authority with durable clear tombstones.

    An applied snapshot identifies one physical process lifetime, not merely one
    launch configuration. Clearing publishes an immutable generation tombstone
    before deleting the active pointer. A power loss may therefore leave extra
    stale active bytes, but can never make a cleared process generation live
    again or let it be overwritten as a replacement generation.
    """

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        state = directories.root(ManagedDirectoryKind.STATE)
        self._root = state / "model" / "deployments" / "applied"
        self._cleared_root = (
            state / "model" / "deployments" / "applied_cleared"
        )
        self._lock_root = (
            directories.root(ManagedDirectoryKind.LOCKS)
            / "model-applied"
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._cleared_root.mkdir(parents=True, exist_ok=True)
        self._lock_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(deployment_id: str) -> str:
        return hashlib.sha256(deployment_id.encode("utf-8")).hexdigest()

    def _path(self, deployment_id: str):
        return self._root / f"{deployment_id}.json"

    def _lock_path(self, deployment_id: str):
        return self._lock_root / f"{self._key(deployment_id)}.lock"

    def _cleared_path(
        self,
        deployment_id: str,
        runtime_digest: str,
    ):
        return (
            self._cleared_root
            / f"{self._key(deployment_id)}.{runtime_digest}.json"
        )

    @staticmethod
    def _validate_runtime_digest(value: str) -> None:
        if (
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
        ):
            raise ValueError(
                "applied model runtime digest must be lowercase SHA-256"
            )

    @staticmethod
    def _decode(path) -> AppliedModelDeployment:
        return decode_applied(json.loads(path.read_text("utf-8")))

    def _cleared_snapshot_unlocked(
        self,
        deployment_id: str,
        runtime_digest: str,
    ) -> AppliedModelDeployment | None:
        marker = self._cleared_path(deployment_id, runtime_digest)
        if not marker.exists():
            return None
        try:
            value = self._decode(marker)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                "applied model clear tombstone is unreadable: "
                f"{deployment_id}:{runtime_digest}"
            ) from exc
        if (
            value.spec.deployment_id != deployment_id
            or value.runtime_digest != runtime_digest
        ):
            raise RuntimeError(
                "applied model clear tombstone identity drifted: "
                f"{deployment_id}:{runtime_digest}"
            )
        return value

    def _active_unlocked(
        self,
        deployment_id: str,
    ) -> AppliedModelDeployment | None:
        path = self._path(deployment_id)
        if not path.exists():
            return None
        value = self._decode(path)
        if value.spec.deployment_id != deployment_id:
            raise RuntimeError(
                "applied model snapshot identity drifted: "
                f"{deployment_id}"
            )
        return value

    def put(self, value: AppliedModelDeployment) -> AppliedModelDeployment:
        deployment_id = value.spec.deployment_id
        self._validate_id(deployment_id)
        runtime_digest = value.runtime_digest
        self._validate_runtime_digest(runtime_digest)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            if (
                self._cleared_snapshot_unlocked(
                    deployment_id,
                    runtime_digest,
                )
                is not None
            ):
                raise RuntimeError(
                    "cleared applied model process generation cannot be "
                    f"resurrected: {deployment_id}"
                )

            current = self._active_unlocked(deployment_id)
            if current is not None:
                if (
                    self._cleared_snapshot_unlocked(
                        deployment_id,
                        current.runtime_digest,
                    )
                    is not None
                ):
                    # A crash may have left the pre-clear active pathname after
                    # the exact clear tombstone committed. Finish only that
                    # logically dead generation before publishing replacement.
                    durable_unlink(self._path(deployment_id))
                    current = None
                elif current.runtime_digest == runtime_digest:
                    if current != value:
                        raise RuntimeError(
                            "same applied runtime digest has different payload: "
                            f"{deployment_id}"
                        )
                    return current
                else:
                    raise RuntimeError(
                        "refusing to overwrite a live applied model generation: "
                        f"{deployment_id}"
                    )

            atomic_replace_bytes(self._path(deployment_id), encode_applied(value))
            return value

    def read(self, deployment_id: str) -> AppliedModelDeployment | None:
        self._validate_id(deployment_id)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            current = self._active_unlocked(deployment_id)
            if current is None:
                return None
            if (
                self._cleared_snapshot_unlocked(
                    deployment_id,
                    current.runtime_digest,
                )
                is not None
            ):
                # Tombstone is the higher-order durable truth. The pathname may
                # be stale residue from a delete whose directory fsync was
                # interrupted; it must never be re-adopted as live.
                return None
            return current

    def clear(
        self,
        deployment_id: str,
        *,
        expected_runtime_digest: str,
    ) -> bool:
        self._validate_id(deployment_id)
        self._validate_runtime_digest(expected_runtime_digest)
        path = self._path(deployment_id)
        with InterprocessFileLock(self._lock_path(deployment_id)):
            marker_value = self._cleared_snapshot_unlocked(
                deployment_id,
                expected_runtime_digest,
            )
            current = self._active_unlocked(deployment_id)

            if current is None:
                return marker_value is not None

            if current.runtime_digest != expected_runtime_digest:
                raise RuntimeError(
                    "stale applied model clear generation: "
                    f"{deployment_id}"
                )

            if marker_value is None:
                # Physical stop has already been proven by the caller. Publish
                # that exact lifetime's terminal durable identity first.
                atomic_replace_bytes(
                    self._cleared_path(
                        deployment_id,
                        expected_runtime_digest,
                    ),
                    encode_applied(current),
                )
            elif marker_value != current:
                raise RuntimeError(
                    "applied model clear tombstone payload drifted: "
                    f"{deployment_id}"
                )

            durable_unlink(path)
            return True

    def reconcile_cleared(self) -> tuple[str, ...]:
        """Physically remove stale active pointers already terminally cleared."""

        removed: list[str] = []
        for path in sorted(self._root.glob("*.json")):
            deployment_id = path.stem
            self._validate_id(deployment_id)
            with InterprocessFileLock(self._lock_path(deployment_id)):
                current = self._active_unlocked(deployment_id)
                if current is None:
                    continue
                if (
                    self._cleared_snapshot_unlocked(
                        deployment_id,
                        current.runtime_digest,
                    )
                    is None
                ):
                    continue
                durable_unlink(path)
                removed.append(deployment_id)
        return tuple(removed)

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid applied deployment id")


__all__ = ["AppliedModelDeploymentStore"]
