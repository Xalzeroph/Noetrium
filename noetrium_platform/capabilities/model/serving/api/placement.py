from __future__ import annotations

from dataclasses import dataclass



@dataclass(frozen=True, slots=True)
class DeploymentPlacement:
    """Frozen physical GPU assignment for one qualified deployment."""

    gpu_uuids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.gpu_uuids:
            raise ValueError("deployment placement requires at least one GPU")
        if any(not gpu.strip() for gpu in self.gpu_uuids):
            raise ValueError("deployment placement GPU identities must be non-empty")
        if len(set(self.gpu_uuids)) != len(self.gpu_uuids):
            raise ValueError("deployment placement cannot contain duplicate GPUs")


__all__ = ["DeploymentPlacement"]
