from __future__ import annotations

from dataclasses import replace
from typing import Protocol, TypeVar

from .json_value import JsonValue
from .operation import OperationAuxiliaryFailure, OperationRequest, OperationResult

T = TypeVar("T")
R = TypeVar("R")


class OperationObserver(Protocol):
    """Non-authoritative lifecycle observer.

    Observer delivery is deliberately outside operation truth. A broken telemetry,
    tracing or logging backend can only produce an auxiliary failure.
    """

    observer_id: str

    def on_started(self, request: OperationRequest[object]) -> None: ...

    def on_completed(
        self,
        request: OperationRequest[object],
        result: OperationResult[JsonValue],
    ) -> None: ...


class OperationObservationBus:
    """Isolated fan-out boundary between operation truth and lifecycle observers."""

    def __init__(self, observers: tuple[OperationObserver, ...] = ()) -> None:
        self._observers = tuple(observers)

    @staticmethod
    def _failure(observer: object, stage: str, exc: BaseException) -> OperationAuxiliaryFailure:
        observer_id = getattr(observer, "observer_id", type(observer).__qualname__)
        return OperationAuxiliaryFailure.from_exception(str(observer_id), stage, exc)

    def started(self, request: OperationRequest[T]) -> tuple[OperationAuxiliaryFailure, ...]:
        failures: list[OperationAuxiliaryFailure] = []
        for observer in self._observers:
            try:
                observer.on_started(request)  # type: ignore[arg-type]
            except Exception as exc:
                failures.append(self._failure(observer, "operation_started", exc))
        return tuple(failures)

    def completed(self, request: OperationRequest[T], result: OperationResult[R]) -> OperationResult[R]:
        failures = list(result.auxiliary_failures)
        initial_count = len(failures)
        for observer in self._observers:
            try:
                observer.on_completed(request, result)  # type: ignore[arg-type]
            except Exception as exc:
                failures.append(self._failure(observer, "operation_completed", exc))
        if len(failures) == initial_count:
            return result
        return replace(result, auxiliary_failures=tuple(failures))


__all__ = ["OperationObservationBus", "OperationObserver"]
