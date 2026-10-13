from __future__ import annotations

from dataclasses import dataclass
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.governance.api import (
    CapabilityOffer,
)

from .ports import LoggingSystemPort, ObservationFactoryPort


@dataclass(frozen=True, slots=True)
class LoggingSystemBinding:
    """Public logging port paired with immutable composition provenance."""

    logging: LoggingSystemPort
    plan: NoetriumUnit
    offer: CapabilityOffer
    observations: ObservationFactoryPort | None = None


__all__ = ["LoggingSystemBinding"]
