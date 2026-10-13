from __future__ import annotations
from dataclasses import dataclass
from noetrium_platform.substrate.api import NoetriumUnit
from noetrium_platform.substrate.api import ResolutionPolicy

@dataclass(frozen=True, slots=True)
class ModelAssignment:
    role: str
    model_id: str
    scope: NoetriumUnit
    policy: ResolutionPolicy = ResolutionPolicy.INHERIT

@dataclass(frozen=True, slots=True)
class ResolvedModelAssignment:
    role: str
    model_id: str
    requested_scope: NoetriumUnit
    source_scopes: tuple[NoetriumUnit, ...]

__all__ = ["ModelAssignment", "ResolvedModelAssignment"]
