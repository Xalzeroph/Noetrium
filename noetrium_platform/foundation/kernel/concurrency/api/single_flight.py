from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from threading import Lock
from typing import Generic, TypeVar

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)


T = TypeVar("T")


class ContentAddressedSingleFlight:
    """Canonical host-visible producer fence for durable realizations.

    The fence is deliberately result-agnostic. After waiting for an earlier
    producer, the next caller must re-read the owning durable authority and
    adopt the published realization before deciding to produce again.
    """

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise TypeError("content-addressed single-flight root must be a Path")
        self.root = root.expanduser().absolute()

    @staticmethod
    def identity(namespace: str, realization_key: str) -> str:
        if type(namespace) is not str or not namespace.strip():
            raise ValueError("single-flight namespace must be non-empty text")
        if type(realization_key) is not str or not realization_key.strip():
            raise ValueError("single-flight realization key must be non-empty text")
        return canonical_digest(
            {
                "schema": "noetrium.content-addressed-single-flight.v1",
                "namespace": namespace.strip(),
                "realization_key": realization_key,
            }
        )

    def lock_path(self, namespace: str, realization_key: str) -> Path:
        digest = self.identity(namespace, realization_key)
        return self.root / digest[:2] / f"{digest}.lock"

    def producer(self, namespace: str, realization_key: str) -> InterprocessFileLock:
        return InterprocessFileLock(self.lock_path(namespace, realization_key))


class SingleFlightCache(Generic[T]):
    """Per-key concurrent construction cache.

    Construction for distinct keys remains concurrent. Concurrent callers for
    one exact key share one builder result (or the same builder exception).
    Failed construction is not cached, so a later call may retry cleanly.
    """

    def __init__(self, max_entries: int | None = None) -> None:
        if max_entries is not None and (
            type(max_entries) is not int or max_entries <= 0
        ):
            raise ValueError("single-flight cache max_entries must be positive or None")
        self._lock = Lock()
        self._max_entries = max_entries
        self._values: OrderedDict[str, T] = OrderedDict()
        self._flights: dict[str, Future[T]] = {}

    def get_or_create(self, key: str, builder: Callable[[], T]) -> T:
        if type(key) is not str or not key:
            raise ValueError("single-flight cache key must be non-empty text")
        if not callable(builder):
            raise TypeError("single-flight cache builder must be callable")

        with self._lock:
            if key in self._values:
                cached = self._values[key]
                self._values.move_to_end(key)
                return cached
            flight = self._flights.get(key)
            owner = flight is None
            if flight is None:
                flight = Future()
                self._flights[key] = flight

        if not owner:
            return flight.result()

        try:
            value = builder()
        except BaseException as exc:
            with self._lock:
                self._flights.pop(key, None)
            flight.set_exception(exc)
            raise

        with self._lock:
            self._values[key] = value
            self._values.move_to_end(key)
            if self._max_entries is not None:
                while len(self._values) > self._max_entries:
                    self._values.popitem(last=False)
            self._flights.pop(key, None)
        flight.set_result(value)
        return value

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)


__all__ = ["ContentAddressedSingleFlight", "SingleFlightCache"]
