from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


_HEX = frozenset("0123456789abcdef")


class DurableCarrierClosureAuthority(StrEnum):
    """Canonical authorities that must close before durable carrier GC."""

    EXECUTION = "execution"
    EVIDENCE = "evidence"
    RECOVERY = "recovery"


@dataclass(frozen=True, slots=True)
class DurableCarrierReferenceClosure:
    """Proof-backed retained-reference closure from one canonical authority."""

    authority: DurableCarrierClosureAuthority
    proof_digest: str
    retained_reference_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.authority) is not DurableCarrierClosureAuthority:
            raise TypeError("durable carrier closure authority must be typed")
        if (
            type(self.proof_digest) is not str
            or len(self.proof_digest) != 64
            or any(ch not in _HEX for ch in self.proof_digest)
        ):
            raise ValueError(
                "durable carrier closure proof_digest must be lowercase sha256"
            )
        if type(self.retained_reference_ids) is not tuple or any(
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            for value in self.retained_reference_ids
        ):
            raise TypeError(
                "durable carrier retained reference ids must be canonical text tuple"
            )
        if self.retained_reference_ids != tuple(
            sorted(set(self.retained_reference_ids))
        ):
            raise ValueError(
                "durable carrier retained reference ids must be unique sorted order"
            )


def validate_durable_carrier_closures(
    closures: tuple[DurableCarrierReferenceClosure, ...],
) -> tuple[DurableCarrierReferenceClosure, ...]:
    if type(closures) is not tuple or any(
        type(value) is not DurableCarrierReferenceClosure
        for value in closures
    ):
        raise TypeError(
            "durable carrier closures must be DurableCarrierReferenceClosure tuple"
        )
    authorities = tuple(value.authority for value in closures)
    if authorities != tuple(
        sorted(set(authorities), key=lambda value: value.value)
    ):
        raise ValueError(
            "durable carrier closures must have unique canonical authority order"
        )
    return closures


def durable_carrier_closure_complete(
    closures: tuple[DurableCarrierReferenceClosure, ...],
) -> bool:
    validate_durable_carrier_closures(closures)
    return tuple(value.authority for value in closures) == tuple(
        sorted(DurableCarrierClosureAuthority, key=lambda value: value.value)
    )


def durable_carrier_gc_eligible(
    closures: tuple[DurableCarrierReferenceClosure, ...],
) -> bool:
    return durable_carrier_closure_complete(closures) and all(
        not value.retained_reference_ids for value in closures
    )


__all__ = [
    "DurableCarrierClosureAuthority",
    "DurableCarrierReferenceClosure",
    "durable_carrier_closure_complete",
    "durable_carrier_gc_eligible",
    "validate_durable_carrier_closures",
]
