from __future__ import annotations

import math
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock, InterprocessLockBusy

from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLease, RecoveryLeaseBusy
from noetrium_platform.infrastructure.reliability.recovery.api.ports import RecoveryLeaseStatePort


class FileLockedRecoveryExecution:
    """Filesystem execution fence composed with an independently supplied lease state port."""

    def __init__(
        self,
        store: RecoveryLeaseStatePort,
        lock_path: Path,
        owner_id: str,
        manifest_digest: str,
        ttl_seconds: float,
    ) -> None:
        self.store = store
        self.owner_id = owner_id
        self.manifest_digest = manifest_digest
        self.ttl_seconds = ttl_seconds
        self._lock = InterprocessFileLock(lock_path, blocking=False)
        self._entered = False

    def __enter__(self) -> "FileLockedRecoveryExecution":
        try:
            self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise RecoveryLeaseBusy("another runtime recovery command holds the execution lock") from exc
        try:
            self.store.acquire(
                self.owner_id,
                self.manifest_digest,
                ttl_seconds=self.ttl_seconds,
            )
        except BaseException:
            self._lock.__exit__(None, None, None)
            raise
        self._entered = True
        return self

    def renew(self) -> RecoveryLease:
        if not self._entered:
            raise RuntimeError("runtime recovery execution guard is not active")
        return self.store.renew(
            self.owner_id,
            self.manifest_digest,
            ttl_seconds=self.ttl_seconds,
        )

    def assert_owned(self) -> RecoveryLease:
        if not self._entered:
            raise RuntimeError("runtime recovery execution guard is not active")
        return self.store.assert_owned(self.owner_id, self.manifest_digest)

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._entered:
            return
        self._entered = False
        try:
            self.store.release(self.owner_id, self.manifest_digest)
        finally:
            self._lock.__exit__(exc_type, exc, tb)


class FileLockedRecoveryExecutionFactory:
    """Filesystem fence backend; lease storage and fence location are independent dependencies."""

    def __init__(self, store: RecoveryLeaseStatePort, *, lock_path: Path) -> None:
        self.store = store
        self.lock_path = Path(lock_path)

    def execution(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        ttl_seconds: float,
    ) -> FileLockedRecoveryExecution:
        if not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and positive")
        return FileLockedRecoveryExecution(
            self.store,
            self.lock_path,
            owner_id,
            manifest_digest,
            ttl_seconds,
        )


__all__ = ["FileLockedRecoveryExecution", "FileLockedRecoveryExecutionFactory"]
