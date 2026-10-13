from __future__ import annotations

from dataclasses import dataclass
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from noetrium_platform.substrate.api import (
    CapabilityOffer,
)

from .ports import MethodCompositionPorts


@dataclass(frozen=True, slots=True)
class MethodSystemBinding:
    """Public method-system ports paired with immutable composition provenance."""

    ports: MethodCompositionPorts
    plan: NoetriumUnit
    offer: CapabilityOffer


__all__ = ["MethodSystemBinding"]
