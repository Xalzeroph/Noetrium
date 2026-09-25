from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .inventory import GPUInventory, HostInventory


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


class GpuPlacementPolicyPort(Protocol):
    """Choose an exact GPU group from already capacity-qualified candidates.

    The planner owns qualification/capacity checks; a placement policy owns only
    deterministic topology preference.  This keeps topology algorithms replaceable
    without coupling callers to a concrete inventory strategy.
    """

    def select(
        self,
        host: HostInventory,
        candidates: tuple[GPUInventory, ...],
        count: int,
    ) -> tuple[GPUInventory, ...]: ...


__all__ = ["DeploymentPlacement", "GpuPlacementPolicyPort"]
