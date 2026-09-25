from __future__ import annotations

from threading import RLock

from noetrium_platform.capabilities.participant.method.api.observability import (
    MethodObservation,
    MethodObservationDeliveryError,
    MethodObservationSink,
    MethodObservationOutboxPort,
)


class MethodObservationOutbox:
    """Generic exactly-once-at-sink handoff buffer for committed method observations.

    A method mutation is already committed before enqueue/delivery. Therefore
    delivery failure must retain the same observation and never authorize
    re-executing the scientific mutation.
    """

    def __init__(self,sink:MethodObservationSink)->None:
        self.sink=sink
        self._lock=RLock()
        self._pending:dict[str,MethodObservation]={}

    def restore(self,observations:tuple[MethodObservation,...])->None:
        rows={o.observation_id:o for o in observations}
        if len(rows)!=len(observations):
            raise ValueError("duplicate method observation ids in restored outbox")
        with self._lock:
            self._pending=rows

    def snapshot(self)->tuple[MethodObservation,...]:
        with self._lock:
            return tuple(self._pending.values())

    def pending_count(self)->int:
        with self._lock:
            return len(self._pending)

    def deliver(self,observation:MethodObservation)->None:
        with self._lock:
            existing=self._pending.get(observation.observation_id)
            if existing is not None and existing!=observation:
                raise ValueError("method observation id collision with different payload")
            self._pending[observation.observation_id]=observation
        try:
            self.sink.record(observation)
        except Exception as exc:
            raise MethodObservationDeliveryError(observation,exc) from exc
        with self._lock:
            self._pending.pop(observation.observation_id,None)

    def flush(self)->tuple[str,...]:
        delivered=[]
        while True:
            with self._lock:
                pending=tuple(self._pending.values())
            if not pending:
                return tuple(delivered)
            observation=pending[0]
            try:
                self.sink.record(observation)
            except Exception as exc:
                raise MethodObservationDeliveryError(observation,exc) from exc
            with self._lock:
                self._pending.pop(observation.observation_id,None)
            delivered.append(observation.observation_id)


class DefaultMethodObservationOutboxFactory:
    """Default participant-method runtime provider for observation handoff."""

    def create(self, sink: MethodObservationSink) -> MethodObservationOutboxPort:
        return MethodObservationOutbox(sink)


__all__ = ["DefaultMethodObservationOutboxFactory", "MethodObservationOutbox"]
