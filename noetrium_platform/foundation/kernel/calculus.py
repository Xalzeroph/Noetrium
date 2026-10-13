"""Irreducible computation laws of Noetrium.

Data always travels as NoetriumUnit. Computation is classified by law, not by
subsystem: pure transformation, coordinated authority transition, or physical
effect. New subsystems compose these laws instead of inventing a fourth one.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from .unit import NoetriumUnit


class TransitionLaw(StrEnum):
    PURE = "pure"
    AUTHORITY = "authority"
    PHYSICAL = "physical"


@runtime_checkable
class PureUnitTransform(Protocol):
    """Referentially transparent Unit -> Unit transformation."""

    @property
    def transform_id(self) -> str: ...

    def transform(self, source: NoetriumUnit) -> NoetriumUnit: ...


@runtime_checkable
class UnitAuthority(Protocol):
    """Linearizable transition over coordinated shared state."""

    @property
    def authority_id(self) -> str: ...

    def transact(self, intent: NoetriumUnit) -> NoetriumUnit: ...


@runtime_checkable
class UnitPhysicalEffect(Protocol):
    """External-world transition that may require observation/reconciliation."""

    @property
    def provider_id(self) -> str: ...

    def realize(self, authorized_intent: NoetriumUnit) -> NoetriumUnit: ...

    def observe(self, authorized_intent: NoetriumUnit) -> NoetriumUnit: ...

    def retire(self, authorized_intent: NoetriumUnit) -> NoetriumUnit: ...


__all__ = [
    "TransitionLaw",
    "PureUnitTransform",
    "UnitAuthority",
    "UnitPhysicalEffect",
]
