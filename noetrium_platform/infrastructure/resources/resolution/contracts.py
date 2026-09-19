from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar
from noetrium_platform.foundation.scope.api import ScopeIdentity

T=TypeVar("T")

class ResolutionPolicy(StrEnum):
    INHERIT="inherit"
    NO_INHERIT="no_inherit"
    OVERRIDE="override"
    MERGE="merge"

@dataclass(frozen=True, slots=True)
class ScopedValue(Generic[T]):
    namespace: str
    name: str
    scope: ScopeIdentity
    value: T
    policy: ResolutionPolicy=ResolutionPolicy.INHERIT

@dataclass(frozen=True, slots=True)
class ResolvedValue(Generic[T]):
    namespace: str
    name: str
    requested_scope: ScopeIdentity
    source_scopes: tuple[ScopeIdentity,...]
    value: T

__all__=["ResolutionPolicy","ResolvedValue","ScopedValue"]
