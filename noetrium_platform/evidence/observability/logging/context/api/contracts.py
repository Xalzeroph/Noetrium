from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.scope.api import ScopeIdentity


@dataclass(frozen=True, slots=True)
class DiagnosticAddress:
    """Stable diagnostic location; it owns no log schema or persistence."""

    scope_path: tuple[ScopeIdentity, ...]
    system_path: tuple[SystemIdentity, ...] = ()
    component_id: str | None = None
    operation_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None

    def __post_init__(self) -> None:
        if not self.scope_path:
            raise ValueError("diagnostic address requires at least one scope")
        if any(not scope.scope_id.strip() for scope in self.scope_path):
            raise ValueError("diagnostic scope identities must be non-empty")
        if any(not system.key.strip() for system in self.system_path):
            raise ValueError("diagnostic system identities must be non-empty")
        if self.component_id is not None and not self.component_id.strip():
            raise ValueError("component_id must be non-empty when supplied")

    @property
    def scope(self) -> ScopeIdentity:
        return self.scope_path[-1]

    @property
    def system(self) -> SystemIdentity | None:
        return self.system_path[-1] if self.system_path else None


__all__ = ["DiagnosticAddress"]
