from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    OperationAuxiliaryFailure,
    OperationRequest,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.auxiliary_failures import OperationAuxiliaryFailureSink

from .emission import operational_observation_enabled
from .events import EventEnvelope, EventSink


class OperationAuxiliaryFailureEventSink(OperationAuxiliaryFailureSink):
    """Durable-event projection for non-primary operation subsystem failures."""

    def __init__(self, sink: EventSink) -> None:
        self._sink = sink

    @staticmethod
    def _identity(
        request: OperationRequest[object],
        failure: OperationAuxiliaryFailure,
        ordinal: int,
    ) -> str:
        return canonical_digest({
            "operation_invocation_id": request.invocation_id,
            "subsystem": failure.subsystem,
            "stage": failure.stage,
            "error_type": failure.error_type,
            "error_digest": failure.error_digest,
            "ordinal": ordinal,
        })[:24]

    def record(
        self,
        request: OperationRequest[object],
        failures: tuple[OperationAuxiliaryFailure, ...],
    ) -> None:
        if not operational_observation_enabled():
            return
        for ordinal, failure in enumerate(failures):
            auxiliary_id = f"aux_failure_{self._identity(request, failure, ordinal)}"
            self._sink.append_event(EventEnvelope(
                event_id=f"event_{auxiliary_id}",
                event_type="OPERATION_AUXILIARY_FAILURE",
                context=request.context,
                component_id=request.target.component_id,
                payload={
                    "auxiliary_failure_id": auxiliary_id,
                    "operation_id": request.operation_id,
                    "operation_invocation_id": request.invocation_id,
                    "operation_type": request.operation_type,
                    "subsystem": failure.subsystem,
                    "stage": failure.stage,
                    "error_type": failure.error_type,
                    "error_digest": failure.error_digest,
                },
                request_refs=(request.invocation_id, request.operation_id),
            ))


__all__ = ["OperationAuxiliaryFailureEventSink"]
