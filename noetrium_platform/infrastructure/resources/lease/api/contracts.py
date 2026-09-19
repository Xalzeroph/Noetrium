from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from noetrium_platform.foundation.scope.api import ScopeIdentity


class ResourceKind(StrEnum):
    STORAGE = "storage"
    WORKSPACE = "workspace"
    EXECUTION_ENVIRONMENT = "execution-environment"
    MODEL_ASSET = "model-asset"
    COMPUTE = "compute"
    GPU = "gpu"
    DATASET = "dataset"
    CACHE = "cache"
    NETWORK_ENDPOINT = "network-endpoint"
    RECOVERY = "recovery"


class ResourceOwnership(StrEnum):
    PLATFORM_MANAGED = "platform-managed"
    EXTERNAL = "external"
    SHARED = "shared"


class LeaseState(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True, order=True)
class ResourceIdentity:
    kind: ResourceKind
    resource_id: str

    def __post_init__(self) -> None:
        if not self.resource_id.strip():
            raise ValueError("resource_id must be non-empty")

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.resource_id}"


@dataclass(frozen=True, slots=True)
class ResourceOwner:
    resource: ResourceIdentity
    scope: ScopeIdentity
    ownership: ResourceOwnership = ResourceOwnership.PLATFORM_MANAGED


@dataclass(frozen=True, slots=True)
class ResourceLease:
    lease_id: str
    resource: ResourceIdentity
    holder_scope: ScopeIdentity
    purpose: str
    state: LeaseState = LeaseState.ACTIVE
    holder_generation: int = 1
    fencing_token: int = 1
    expires_at_epoch_s: float | None = None
    acquired_at_epoch_s: float | None = None
    released_at_epoch_s: float | None = None

    def __post_init__(self) -> None:
        if not self.lease_id.strip() or not self.purpose.strip():
            raise ValueError("lease identity and purpose must be non-empty")
        if self.holder_generation < 1:
            raise ValueError("lease holder generation must be >= 1")
        if self.fencing_token < 1:
            raise ValueError("lease fencing token must be >= 1")
        if self.expires_at_epoch_s is not None and (
            not math.isfinite(float(self.expires_at_epoch_s)) or self.expires_at_epoch_s <= 0
        ):
            raise ValueError("lease expiry must be a finite positive epoch timestamp")
        if self.acquired_at_epoch_s is not None and (
            not math.isfinite(float(self.acquired_at_epoch_s)) or self.acquired_at_epoch_s <= 0
        ):
            raise ValueError("lease acquisition must be a finite positive epoch timestamp")
        if (
            self.acquired_at_epoch_s is not None
            and self.expires_at_epoch_s is not None
            and self.expires_at_epoch_s <= self.acquired_at_epoch_s
        ):
            raise ValueError("lease expiry must be later than acquisition")
        if self.released_at_epoch_s is not None and (
            not math.isfinite(float(self.released_at_epoch_s)) or self.released_at_epoch_s <= 0
        ):
            raise ValueError("lease release must be a finite positive epoch timestamp")
        if (
            self.acquired_at_epoch_s is not None
            and self.released_at_epoch_s is not None
            and self.released_at_epoch_s < self.acquired_at_epoch_s
        ):
            raise ValueError("lease release cannot precede acquisition")
        if self.released_at_epoch_s is not None and self.state is not LeaseState.RELEASED:
            raise ValueError("only released leases may carry released_at_epoch_s")

    def expired_at(self, now_epoch_s: float) -> bool:
        if not math.isfinite(float(now_epoch_s)):
            raise ValueError("lease expiry observation time must be finite")
        return (
            self.state is LeaseState.ACTIVE
            and self.expires_at_epoch_s is not None
            and self.expires_at_epoch_s <= now_epoch_s
        )


__all__ = [
    "LeaseState",
    "ResourceIdentity",
    "ResourceKind",
    "ResourceLease",
    "ResourceOwner",
    "ResourceOwnership",
]
