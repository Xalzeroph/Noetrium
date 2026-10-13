from __future__ import annotations

from threading import RLock
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class DirectForensicWriteActor:
    """Bootstrap implementation of the forensic write-actor protocol.

    It uses the same single-writer lease and the same ledger/index writers as the
    structured runtime actor.  The only difference is execution mode: before the
    ResearchExecutionPool exists, calls execute synchronously under one reentrant
    process-local lock.  The store must be closed before a structured runtime
    takes over the same forensic root.
    """

    def __init__(self, actor_id: str) -> None:
        if type(actor_id) is not str or not actor_id.strip():
            raise ValueError("direct forensic actor_id must be non-empty")
        self._actor_id = actor_id.strip()
        self._lock = RLock()

    @property
    def actor_id(self) -> str:
        return self._actor_id

    def call(
        self,
        operation: str,
        fn: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        if type(operation) is not str or not operation.strip():
            raise ValueError("direct forensic operation must be non-empty")
        with self._lock:
            return fn(*args, **kwargs)


__all__ = ["DirectForensicWriteActor"]
