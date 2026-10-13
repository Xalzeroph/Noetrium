from __future__ import annotations

from dataclasses import replace
from typing import Protocol, TypeVar

from .operation import OperationAuxiliaryFailure, OperationRequest, OperationResult

T = TypeVar("T")
R = TypeVar("R")


class OperationAuxiliaryFailureSink(Protocol):
    """Non-authoritative sink for failures in diagnostics/observation/projection paths."""

    def record(
        self,
        request: OperationRequest[object],
        failures: tuple[OperationAuxiliaryFailure, ...],
    ) -> None: ...


class OperationAuxiliaryFailureReporter:
    """Reports final auxiliary failures after every observer has had its turn.

    The reporter is intentionally last in the operation boundary.  Its own failure is
    returned as another auxiliary failure but can never change primary operation truth.
    """

    def __init__(self, sink: OperationAuxiliaryFailureSink | None = None) -> None:
        self._sink = sink

    def report(
        self,
        request: OperationRequest[T],
        result: OperationResult[R],
    ) -> OperationResult[R]:
        failures = result.auxiliary_failures
        if self._sink is None or not failures:
            return result
        try:
            self._sink.record(request, failures)  # type: ignore[arg-type]
        except Exception as exc:
            reporting_failure = OperationAuxiliaryFailure.from_exception(
                "auxiliary_failure_sink",
                "auxiliary_failure_record",
                exc,
            )
            return replace(
                result,
                auxiliary_failures=failures + (reporting_failure,),
            )
        return result


__all__ = ["OperationAuxiliaryFailureReporter", "OperationAuxiliaryFailureSink"]
