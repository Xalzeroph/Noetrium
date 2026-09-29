from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from threading import Lock
from typing import Generic, TypeVar


T = TypeVar("T")


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


__all__ = ["SingleFlightCache"]
