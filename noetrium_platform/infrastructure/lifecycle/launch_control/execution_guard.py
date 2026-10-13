from __future__ import annotations

from typing import Protocol
from .contracts import RuntimeAction, RuntimeLaunchManifestPort


class RuntimeActionExecutionGuard(Protocol):
    """Operational guard extension point around one Runtime action."""

    def before_action(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None: ...
    def after_success(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None: ...


__all__ = ["RuntimeActionExecutionGuard"]
