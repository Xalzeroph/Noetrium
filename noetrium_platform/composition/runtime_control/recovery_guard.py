from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.launch_control.contracts import RuntimeAction, RuntimeLaunchManifestPort
from noetrium_platform.infrastructure.lifecycle.launch_control.execution_guard import RuntimeActionExecutionGuard
from noetrium_platform.infrastructure.reliability.recovery.api.ports import RecoveryExecutionPort


class RecoveryLeaseRuntimeActionGuard(RuntimeActionExecutionGuard):
    """Composition adapter binding Reliability recovery lease to Runtime action boundaries."""

    def __init__(self, execution: RecoveryExecutionPort) -> None:
        self.execution = execution

    def before_action(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None:
        del action, manifest
        self.execution.renew()

    def after_success(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> None:
        del action, manifest
        self.execution.renew()


__all__ = ["RecoveryLeaseRuntimeActionGuard"]
