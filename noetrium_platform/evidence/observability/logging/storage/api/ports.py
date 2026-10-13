from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar

T = TypeVar("T")


class LogStorageWriteActorPort(Protocol):
    """Storage-local serial mutation/freeze authority for one JSONL store."""

    def call(
        self,
        operation: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> T: ...


__all__ = ["LogStorageWriteActorPort"]
