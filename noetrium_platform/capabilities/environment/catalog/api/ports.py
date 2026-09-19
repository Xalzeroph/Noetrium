from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.scope.api import ScopeIdentity

from .contracts import (
    EnvironmentAssignment,
    EnvironmentBinding,
    EnvironmentInstance,
    EnvironmentOverlay,
    EnvironmentSpec,
    EnvironmentTemplate,
    ResolvedEnvironmentSpec,
)


class ExecutionEnvironmentCatalogPort(Protocol):
    def register_template(self, template: EnvironmentTemplate) -> None: ...
    def register_spec(self, spec: EnvironmentSpec) -> None: ...
    def register_overlay(self, overlay: EnvironmentOverlay) -> None: ...
    def assign(self, assignment: EnvironmentAssignment) -> None: ...
    def resolve(self, name: str, scope: ScopeIdentity) -> ResolvedEnvironmentSpec: ...
    def register_instance(self, instance: EnvironmentInstance) -> None: ...
    def bind(self, binding: EnvironmentBinding) -> None: ...
    def binding(self, role: str, scope: ScopeIdentity) -> EnvironmentBinding: ...


__all__ = ["ExecutionEnvironmentCatalogPort"]
