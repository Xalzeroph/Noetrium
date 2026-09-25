from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .operation import OperationAuxiliaryFailure, OperationRequest


@dataclass(frozen=True, slots=True)
class FailureRecordReceipt:
    """Result of authoritative failure recording plus any non-primary recording degradations."""

    failure_id: str | None
    auxiliary_failures: tuple[OperationAuxiliaryFailure, ...] = ()


class OperationFailureSink(Protocol):
    """Authoritative failure-materialization port; implementation may be durable."""

    def record(
        self,
        request: OperationRequest[object],
        exc: BaseException,
    ) -> FailureRecordReceipt: ...


@dataclass(frozen=True, slots=True)
class FailureMaterialization:
    failure_id: str | None = None
    auxiliary_failures: tuple[OperationAuxiliaryFailure, ...] = ()


class FailureMaterializer:
    """Isolates failure persistence from the primary component exception."""

    def __init__(self, sink: OperationFailureSink | None = None) -> None:
        self._sink = sink

    def materialize(
        self,
        request: OperationRequest[object],
        exc: BaseException,
    ) -> FailureMaterialization:
        if self._sink is None:
            return FailureMaterialization()
        try:
            receipt = self._sink.record(request, exc)
            if not isinstance(receipt, FailureRecordReceipt):
                raise TypeError("OperationFailureSink.record must return FailureRecordReceipt")
            return FailureMaterialization(
                failure_id=receipt.failure_id,
                auxiliary_failures=receipt.auxiliary_failures,
            )
        except Exception as sink_exc:
            return FailureMaterialization(
                auxiliary_failures=(
                    OperationAuxiliaryFailure.from_exception(
                        "failure_sink",
                        "failure_record",
                        sink_exc,
                    ),
                ),
            )


__all__ = [
    "FailureMaterialization",
    "FailureMaterializer",
    "FailureRecordReceipt",
    "OperationFailureSink",
]
