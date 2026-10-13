from __future__ import annotations
from typing import Protocol
from noetrium_platform.substrate.api import NoetriumUnit
from .contracts import ModelAssignment, ResolvedModelAssignment

class ModelAssignmentPort(Protocol):
    def assign(self, assignment: ModelAssignment) -> None: ...
    def resolve(self, role: str, scope: NoetriumUnit) -> ResolvedModelAssignment: ...

__all__ = ["ModelAssignmentPort"]
