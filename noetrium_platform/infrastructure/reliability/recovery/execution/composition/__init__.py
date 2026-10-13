from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.reliability.recovery.api import (
    RecoveryExecutionFactoryPort,
    RecoveryLeaseStatePort,
)
from noetrium_platform.infrastructure.reliability.recovery.execution.runtime import (
    FileLockedRecoveryExecutionFactory,
)


def compose_file_locked_recovery_execution(
    lease_state: RecoveryLeaseStatePort,
    *,
    lock_path: Path,
) -> RecoveryExecutionFactoryPort:
    """Bind recovery ownership state to one interprocess execution fence.

    Lease state proves durable ownership.  The filesystem lock proves that only
    one local process may execute recovery mutations at a time.  Keeping this
    composition at the recovery-execution boundary prevents downstream code
    from constructing either authority itself.
    """

    if not isinstance(lock_path, Path):
        lock_path = Path(lock_path)
    return FileLockedRecoveryExecutionFactory(
        lease_state,
        lock_path=lock_path,
    )


__all__ = ["compose_file_locked_recovery_execution"]
