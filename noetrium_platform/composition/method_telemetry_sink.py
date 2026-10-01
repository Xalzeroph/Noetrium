from __future__ import annotations

import time

from noetrium_platform.evidence.observability.capture.api import RawObservationEnvelope
from noetrium_platform.evidence.observability.capture.runtime import (
    RegistryBoundRawObservationGateway,
)
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_bytes,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvent,
    MethodObservationPort,
)


_METHOD_OBSERVATION_SYSTEM = SystemIdentity("execution")
_METHOD_OBSERVATION_PRODUCER = "execution.method-observation.v1"


class RawLakeMethodObservationSink(MethodObservationPort):
    """Replay-safe side-plane projection of accepted Method events."""

    def __init__(self, gateway: RegistryBoundRawObservationGateway) -> None:
        self._gateway = gateway
        self._gateway.register_producer(
            _METHOD_OBSERVATION_PRODUCER,
            _METHOD_OBSERVATION_SYSTEM,
        )

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "sink": _METHOD_OBSERVATION_PRODUCER,
                "system": _METHOD_OBSERVATION_SYSTEM.key,
            }
        )

    def publish(self, event: MethodEvent, context: ExecutionContext) -> None:
        if not isinstance(event, MethodEvent):
            raise TypeError("method observation sink requires MethodEvent")
        if not isinstance(context, ExecutionContext):
            raise TypeError("method observation sink requires ExecutionContext")
        payload = {
            "kind": event.kind,
            "payload": event.payload,
            "run_id": context.run_id,
            "study_id": context.study_id,
            "task_id": context.task_id,
            "decision_cycle_id": context.decision_cycle_id,
            "operation_id": context.operation_id,
            "component_id": context.component_id,
        }
        event_id = "method-event:" + canonical_digest(
            {
                "context": {
                    "run_id": context.run_id,
                    "trace_id": context.trace_id,
                    "span_id": context.span_id,
                    "study_id": context.study_id,
                    "task_id": context.task_id,
                    "decision_cycle_id": context.decision_cycle_id,
                    "operation_id": context.operation_id,
                    "component_id": context.component_id,
                },
                "event": event,
            }
        )
        now = time.time()
        self._gateway.capture(
            RawObservationEnvelope(
                event_id=event_id,
                family="method.raw",
                context=context,
                system=_METHOD_OBSERVATION_SYSTEM,
                producer_id=_METHOD_OBSERVATION_PRODUCER,
                producer_version="1",
                payload=payload,
                raw_payload=canonical_bytes(payload),
                occurred_at=now,
                recorded_at=now,
                status="observed",
                outcome="observed",
                stream_id=context.run_id,
                correlation_id=context.trace_id,
                dimensions={"method_event_kind": event.kind},
            )
        )


__all__ = ["RawLakeMethodObservationSink"]
