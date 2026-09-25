from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .recovery_state import DurableRecoveryAttempt


class DurableRecoveryStorePort(Protocol):
    """Minimal durable state boundary used by the exact recovery runner."""

    def recovery_session(self) -> AbstractContextManager[None]: ...

    def exists(self) -> bool: ...

    def create(self, attempt: DurableRecoveryAttempt) -> None: ...

    def write(self, attempt: DurableRecoveryAttempt) -> None: ...

    def load(self) -> DurableRecoveryAttempt: ...


__all__ = ["DurableRecoveryStorePort"]
