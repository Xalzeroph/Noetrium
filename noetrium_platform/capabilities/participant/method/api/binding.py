from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.governance.architecture.api.capability_composition import (
    BindingPlan,
    CapabilityOffer,
)

from .ports import MethodCompositionPorts


@dataclass(frozen=True, slots=True)
class MethodSystemBinding:
    """Public method-system ports paired with immutable composition provenance."""

    ports: MethodCompositionPorts
    plan: BindingPlan
    offer: CapabilityOffer


__all__ = ["MethodSystemBinding"]
