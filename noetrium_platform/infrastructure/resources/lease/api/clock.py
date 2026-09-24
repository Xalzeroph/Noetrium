from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LeaseClockReading:
    """One local host/boot lease-clock observation.

    elapsed_seconds is suspend-aware elapsed time in one boot domain.
    wall_epoch_seconds is evidence only and never expiration authority.
    """

    host_identity_digest: str
    boot_identity_digest: str
    elapsed_seconds: float
    wall_epoch_seconds: float

    def __post_init__(self) -> None:
        for name, value in (
            ("host_identity_digest", self.host_identity_digest),
            ("boot_identity_digest", self.boot_identity_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"lease clock {name} must be lowercase sha256")
        if (
            not math.isfinite(float(self.elapsed_seconds))
            or self.elapsed_seconds < 0
        ):
            raise ValueError(
                "lease clock elapsed_seconds must be finite and non-negative"
            )
        if (
            not math.isfinite(float(self.wall_epoch_seconds))
            or self.wall_epoch_seconds <= 0
        ):
            raise ValueError(
                "lease clock wall_epoch_seconds must be finite and positive"
            )


@runtime_checkable
class LeaseClockPort(Protocol):
    def read(self) -> LeaseClockReading: ...


__all__ = ["LeaseClockPort", "LeaseClockReading"]
