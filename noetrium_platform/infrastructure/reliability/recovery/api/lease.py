from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class RecoveryLease:
    owner_id: str
    manifest_digest: str
    acquired_at: float
    expires_at: float

    def __post_init__(self) -> None:
        if not self.owner_id.strip() or not self.manifest_digest.strip():
            raise ValueError("recovery lease owner and manifest identity are required")
        if not math.isfinite(float(self.acquired_at)) or not math.isfinite(float(self.expires_at)):
            raise ValueError("recovery lease timestamps must be finite")
        if self.expires_at <= self.acquired_at:
            raise ValueError("recovery lease expiry must be later than acquisition")


class RecoveryLeaseBusy(RuntimeError):
    pass


__all__ = ["RecoveryLease", "RecoveryLeaseBusy"]
