from __future__ import annotations

import json

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from .applied import AppliedModelDeployment
from .codec import decode_applied, encode_applied


class AppliedModelDeploymentStore:
    """Authoritative operational snapshot store for the last applied launch only."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = directories.root(ManagedDirectoryKind.STATE) / "model" / "deployments" / "applied"
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, value: AppliedModelDeployment) -> AppliedModelDeployment:
        self._validate_id(value.spec.deployment_id)
        atomic_replace_bytes(self._root / f"{value.spec.deployment_id}.json", encode_applied(value))
        return value

    def read(self, deployment_id: str) -> AppliedModelDeployment | None:
        self._validate_id(deployment_id)
        path = self._root / f"{deployment_id}.json"
        if not path.exists():
            return None
        return decode_applied(json.loads(path.read_text("utf-8")))

    def clear(self, deployment_id: str) -> bool:
        self._validate_id(deployment_id)
        path = self._root / f"{deployment_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid applied deployment id")


__all__ = ["AppliedModelDeploymentStore"]
