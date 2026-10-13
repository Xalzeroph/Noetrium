from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.record import record_digest, record_id
from noetrium_platform.foundation.kernel.record_plane import EventSink
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .emission import operational_observation_enabled


@dataclass(frozen=True, slots=True)
class EventDeliveryFailure:
    sink_id: str
    error_type: str
    error_digest: str
    message: str = field(
        default="",
        repr=False,
        compare=False,
        metadata={"transient": True},
    )

    @classmethod
    def from_exception(
        cls,
        sink_id: str,
        exc: BaseException,
    ) -> "EventDeliveryFailure":
        descriptor = describe_exception(exc)
        return cls(
            sink_id=sink_id,
            error_type=descriptor.error_type,
            error_digest=descriptor.error_digest,
            message=descriptor.safe_message,
        )


class EventDeliveryError(RuntimeError):
    def __init__(
        self,
        record_identity: str,
        failures: tuple[EventDeliveryFailure, ...],
    ) -> None:
        self.record_id = record_identity
        self.failures = failures
        summary = ", ".join(
            f"{row.sink_id}:{row.error_type}" for row in failures
        )
        super().__init__(
            f"event delivery failed for {record_identity}: {summary}"
        )


class FanoutEventSink:
    """Storage-neutral fanout over immutable event Units."""

    def __init__(self, *sinks: EventSink) -> None:
        if not sinks:
            raise ValueError("FanoutEventSink requires at least one sink")
        self._sinks = tuple(sinks)

    @staticmethod
    def _sink_id(sink: EventSink) -> str:
        explicit = getattr(sink, "sink_id", None)
        if isinstance(explicit, str) and explicit.strip():
            return explicit
        kind = type(sink)
        return f"{kind.__module__}.{kind.__qualname__}"

    def append_event(self, event: NoetriumUnit) -> tuple[object, ...]:
        if not operational_observation_enabled():
            return ()
        results: list[object] = []
        failures: list[EventDeliveryFailure] = []
        for sink in self._sinks:
            try:
                results.append(sink.append_event(event))
            except Exception as exc:
                failures.append(
                    EventDeliveryFailure.from_exception(
                        self._sink_id(sink),
                        exc,
                    )
                )
        if failures:
            raise EventDeliveryError(
                record_id(event) or record_digest(event),
                tuple(failures),
            )
        return tuple(results)


__all__ = [
    "EventDeliveryError",
    "EventDeliveryFailure",
    "FanoutEventSink",
]
