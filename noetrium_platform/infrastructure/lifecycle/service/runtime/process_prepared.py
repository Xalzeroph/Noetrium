from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from typing import Protocol, runtime_checkable

from .capture_paths import ServiceCapturePaths
from .environment import MaterializedServiceEnvironment
from .prepared_start import PreparedServiceStartReconcileResult, ServiceStartRecoveryHandle


@runtime_checkable
class CrashDurablePreparedProcessBackend(Protocol):
    """Optional process-backend capability for cross-controller start recovery.

    The Service layer owns the WAL/state machine.  A backend only supplies opaque
    provider recovery material and exact process reconciliation for its own launch
    transport.
    """

    start_recovery_durability: str

    def prepare_start_recovery(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        *,
        intent_id: str,
        attempt: int,
    ) -> ServiceStartRecoveryHandle: ...

    def start_prepared(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]: ...

    def reconcile_prepared_start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> PreparedServiceStartReconcileResult: ...


def crash_durable_prepared_process_backend(
    value: object,
) -> CrashDurablePreparedProcessBackend | None:
    if not isinstance(value, CrashDurablePreparedProcessBackend):
        return None
    if value.start_recovery_durability != "crash_durable":
        return None
    return value


__all__ = [
    "CrashDurablePreparedProcessBackend",
    "crash_durable_prepared_process_backend",
]
