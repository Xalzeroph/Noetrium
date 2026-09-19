from __future__ import annotations

from typing import Protocol

from .contracts import RuntimeAction, RuntimeLaunchManifestPort
from noetrium_platform.infrastructure.reliability.recovery.api.ports import RecoveryExecutionPort


class RuntimeActionExecutionGuard(Protocol):
    """Operational guard around one Runtime action; owns no action semantics."""

    def before_action(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None: ...
    def after_success(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None: ...


class RecoveryLeaseRuntimeActionGuard:
    """Keeps the observable lease fresh at exact action boundaries.

    Mutual exclusion itself is provided by ``RecoveryExecutionPort``'s long-held
    flock; renewals here keep the durable owner/manifest document current for status.
    """

    def __init__(self, execution: RecoveryExecutionPort) -> None:
        self.execution = execution

    def before_action(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None:
        del action, manifest
        self.execution.renew()

    def after_success(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None:
        del action, manifest
        self.execution.renew()


__all__ = ["RecoveryLeaseRuntimeActionGuard", "RuntimeActionExecutionGuard"]
