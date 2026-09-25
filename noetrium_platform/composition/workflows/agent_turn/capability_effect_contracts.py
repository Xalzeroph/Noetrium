from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.participant.capability.api import CapabilityResult
from noetrium_platform.foundation.kernel.kernel import JsonValue, OperationResult


class UnsafeEffectfulCapability(RuntimeError):
    pass


class UnresolvedCapabilityEffect(RuntimeError):
    pass


class CapabilityEffectIdentityConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityEffectExecution:
    result: CapabilityResult
    operation_results: tuple[OperationResult[JsonValue], ...]
    replayed_from_intent: bool = False


__all__ = [
    "CapabilityEffectExecution",
    "CapabilityEffectIdentityConflict",
    "UnresolvedCapabilityEffect",
    "UnsafeEffectfulCapability",
]
