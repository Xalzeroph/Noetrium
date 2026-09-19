from __future__ import annotations

import json

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from .codec import decode_deployment, encode_deployment


class ModelDeploymentRegistry:
    """Authoritative mutable desired-deployment registry only."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = directories.root(ManagedDirectoryKind.STATE) / "model" / "deployments" / "desired"
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, value: ModelDeploymentSpec) -> ModelDeploymentSpec:
        self._validate_id(value.deployment_id)
        atomic_replace_bytes(self._root / f"{value.deployment_id}.json", encode_deployment(value))
        return value

    def get(self, deployment_id: str) -> ModelDeploymentSpec:
        self._validate_id(deployment_id)
        return decode_deployment(json.loads((self._root / f"{deployment_id}.json").read_text("utf-8")))

    def all(self) -> tuple[ModelDeploymentSpec, ...]:
        return tuple(self.get(path.stem) for path in sorted(self._root.glob("*.json")))

    def remove(self, deployment_id: str) -> bool:
        self._validate_id(deployment_id)
        path = self._root / f"{deployment_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid deployment id")


__all__ = ["ModelDeploymentRegistry"]
