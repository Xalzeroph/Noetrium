from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .descriptor import describe_exception


@dataclass(frozen=True, slots=True)
class SecondaryDeliveryFailure:
    """Sanitized fact that a non-authoritative diagnostic delivery failed.

    Secondary delivery is explicitly best-effort: failure must never alter the primary
    business/runtime truth. Returning a structured fact (rather than silently swallowing
    the exception) makes the policy machine-visible and testable.
    """

    error_type: str
    error_digest: str


def attempt_secondary_delivery(callback: Callable[[], object]) -> SecondaryDeliveryFailure | None:
    """Attempt a diagnostic side-plane write without allowing it to affect primary truth."""

    try:
        callback()
        return None
    except Exception as exc:
        descriptor = describe_exception(exc)
        return SecondaryDeliveryFailure(
            error_type=descriptor.error_type,
            error_digest=descriptor.error_digest,
        )


__all__ = ["SecondaryDeliveryFailure", "attempt_secondary_delivery"]
