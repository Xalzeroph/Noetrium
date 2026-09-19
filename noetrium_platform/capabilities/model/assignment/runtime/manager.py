from __future__ import annotations

from noetrium_platform.capabilities.model.assignment.api import ModelAssignment, ResolvedModelAssignment
from noetrium_platform.infrastructure.resources.resolution import HierarchicalResourceResolver, ScopedValue
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeRegistryPort


class ModelAssignmentManager:
    """Scoped model-role assignment authority, separate from physical model assets."""

    def __init__(self, scopes: ScopeRegistryPort) -> None:
        self._resolver = HierarchicalResourceResolver[str](ancestry=scopes.ancestry)

    def assign(self, assignment: ModelAssignment) -> None:
        self._resolver.bind(ScopedValue("model-role", assignment.role, assignment.scope, assignment.model_id, assignment.policy))

    def resolve(self, role: str, scope: ScopeIdentity) -> ResolvedModelAssignment:
        result = self._resolver.resolve(namespace="model-role", name=role, scope=scope)
        return ResolvedModelAssignment(role, result.value, scope, result.source_scopes)


__all__ = ["ModelAssignmentManager"]
