from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import JsonValue, OperationRequest, OperationResult, canonical_digest

from .emission import operational_observation_enabled
from .events import EventEnvelope, EventSink


EMITTED_EVENT_TYPES = (
    "OPERATION_STARTED",
    "OPERATION_SUCCEEDED",
    "OPERATION_FAILED",
    "OPERATION_CANCELLED",
    "OPERATION_INTERRUPTED",
)

class OperationLifecycleObserver:
    """Projects operation outcomes into storage-neutral structured events.

    The observer sees only stable identities/digests. Observation failure is handled by
    Kernel as an auxiliary failure and therefore cannot change scientific execution.
    """

    observer_id = "observability.operation_lifecycle"

    def __init__(self, sink: EventSink) -> None:
        self._sink = sink

    def _emit(
        self,
        *,
        request: OperationRequest[object],
        event_type: str,
        result: OperationResult[JsonValue] | None = None,
    ) -> None:
        if not operational_observation_enabled():
            return
        event_identity = canonical_digest({
            "invocation_id": request.invocation_id,
            "event_type": event_type,
        })[:24]
        auxiliary = tuple(
            {
                "subsystem": item.subsystem,
                "stage": item.stage,
                "error_type": item.error_type,
                "error_digest": item.error_digest,
            }
            for item in (() if result is None else result.auxiliary_failures)
        )
        payload: dict[str, object] = {
            "operation_id": request.operation_id,
            "operation_invocation_id": request.invocation_id,
            "operation_type": request.operation_type,
            "caller_component_id": request.caller.component_id,
            "target_component_id": request.target.component_id,
            "payload_schema": request.payload_schema,
            "payload_digest": request.payload_digest,
        }
        artifact_refs: tuple[str, ...] = ()
        state_refs: tuple[str, ...] = ()
        effect_refs: tuple[str, ...] = ()
        if result is not None:
            payload.update({
                "status": result.status.value,
                "output_digest": result.output_digest,
                "failure_id": result.failure_id,
                "auxiliary_failures": auxiliary,
            })
            artifact_refs = result.artifacts
            state_refs = result.mutations
            effect_refs = tuple(receipt.effect_id for receipt in result.effect_receipts)
        self._sink.append_event(EventEnvelope(
            event_id=f"event_operation_{event_identity}",
            event_type=event_type,
            context=request.context,
            component_id=request.target.component_id,
            payload=payload,
            artifact_refs=artifact_refs,
            state_refs=state_refs,
            effect_refs=effect_refs,
            request_refs=(request.invocation_id, request.operation_id),
        ))

    def on_started(self, request: OperationRequest[object]) -> None:
        self._emit(request=request, event_type="OPERATION_STARTED")

    def on_completed(
        self,
        request: OperationRequest[object],
        result: OperationResult[JsonValue],
    ) -> None:
        self._emit(
            request=request,
            event_type=f"OPERATION_{result.status.value.upper()}",
            result=result,
        )



__all__ = ["EMITTED_EVENT_TYPES", "OperationLifecycleObserver"]
