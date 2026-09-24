from __future__ import annotations

import json

from noetrium_platform.substrate.api import DirectoryLayoutPort, ManagedDirectoryKind
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
    durable_unlink,
)

from .codec import decode_deployment, encode_deployment


class ModelDeploymentRegistry:
    """Authoritative mutable desired-deployment registry only."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._root = directories.root(ManagedDirectoryKind.STATE) / "model" / "deployments" / "desired"
        self._root.mkdir(parents=True, exist_ok=True)
        self._retired_root = self._root / "_retired"
        self._retired_root.mkdir(parents=True, exist_ok=True)

    def put(self, value: ModelDeploymentSpec) -> ModelDeploymentSpec:
        self._validate_id(value.deployment_id)
        if self._retired_path(value.deployment_id).exists():
            raise RuntimeError(
                "model deployment identity is retired and cannot be reused: "
                f"{value.deployment_id}"
            )
        atomic_replace_bytes(
            self._root / f"{value.deployment_id}.json",
            encode_deployment(value),
        )
        return value

    def get(self, deployment_id: str) -> ModelDeploymentSpec:
        self._validate_id(deployment_id)
        return decode_deployment(json.loads((self._root / f"{deployment_id}.json").read_text("utf-8")))

    def all(self) -> tuple[ModelDeploymentSpec, ...]:
        return tuple(self.get(path.stem) for path in sorted(self._root.glob("*.json")))

    def remove(self, deployment_id: str) -> bool:
        self._validate_id(deployment_id)
        path = self._root / f"{deployment_id}.json"
        retired = self._retired_path(deployment_id)
        if not path.exists():
            return False

        current = decode_deployment(json.loads(path.read_text("utf-8")))
        current_digest = canonical_digest(current)
        if retired.exists():
            retired_digest = retired.read_text("utf-8").strip()
            if retired_digest != current_digest:
                raise RuntimeError(
                    "model deployment retirement generation drifted: "
                    f"{deployment_id}"
                )
        else:
            # Retirement is published before desired-state deletion. A crash in
            # the middle therefore blocks identity reuse and makes remove()
            # safely retryable until the old desired record is durably gone.
            atomic_replace_bytes(
                retired,
                (current_digest + "\n").encode("ascii"),
            )
        durable_unlink(path)
        return True

    def _retired_path(self, deployment_id: str):
        return self._retired_root / f"{deployment_id}.sha256"

    @staticmethod
    def _validate_id(value: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("invalid deployment id")


__all__ = ["ModelDeploymentRegistry"]
