from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.api import (
    EventDeliveryError,
    EventEnvelope,
    FanoutEventSink,
)


class RecordingSink:
    sink_id = "recording"

    def __init__(self) -> None:
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return event.event_id


class BrokenSink:
    sink_id = "broken"

    def append_event(self, event):
        del event
        raise OSError("backend unavailable")


def event() -> EventEnvelope:
    return EventEnvelope(
        "event-1",
        "TEST",
        ExecutionContext(run_id="run", trace_id="trace", span_id="span"),
        "component",
    )


def test_fanout_attempts_all_sinks_even_when_one_fails():
    first = RecordingSink()
    second = RecordingSink()
    fanout = FanoutEventSink(first, BrokenSink(), second)

    with pytest.raises(EventDeliveryError) as exc:
        fanout.append_event(event())

    assert [row.event_id for row in first.events] == ["event-1"]
    assert [row.event_id for row in second.events] == ["event-1"]
    assert exc.value.event_id == "event-1"
    assert [(row.sink_id, row.error_type) for row in exc.value.failures] == [
        ("broken", "OSError")
    ]


def test_fanout_returns_each_sink_receipt_when_all_succeed():
    first = RecordingSink()
    second = RecordingSink()
    assert FanoutEventSink(first, second).append_event(event()) == ("event-1", "event-1")


def test_fanout_requires_a_real_delivery_target():
    with pytest.raises(ValueError):
        FanoutEventSink()


def test_delivery_failure_message_and_digest_use_safe_exception_descriptor():
    class SecretSink:
        sink_id = "secret-sink"
        def append_event(self, event):
            del event
            raise RuntimeError("authorization: Bearer abcdefghijklmnop token=supersecretvalue")

    with pytest.raises(EventDeliveryError) as exc:
        FanoutEventSink(SecretSink()).append_event(event())
    failure = exc.value.failures[0]
    assert "supersecretvalue" not in failure.message
    assert "abcdefghijklmnop" not in failure.message
    assert "REDACTED" in failure.message
    assert len(failure.error_digest) == 64
