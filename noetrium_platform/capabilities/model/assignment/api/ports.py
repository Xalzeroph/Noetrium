from __future__ import annotations
from typing import Protocol
from noetrium_platform.foundation.scope.api import ScopeIdentity
from .contracts import ModelAssignment, ResolvedModelAssignment

class ModelAssignmentPort(Protocol):
    def assign(self, assignment: ModelAssignment) -> None: ...
    def resolve(self, role: str, scope: ScopeIdentity) -> ResolvedModelAssignment: ...

__all__ = ["ModelAssignmentPort"]
