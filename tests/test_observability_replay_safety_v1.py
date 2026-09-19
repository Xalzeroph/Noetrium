from __future__ import annotations

from noetrium_platform.evidence.observability.api import (
    EventEnvelope,
    FanoutEventSink,
    ObservationEmissionMode,
    observation_emission_scope,
    operational_observation_enabled,
)
from noetrium_platform.evidence.observability.logging.context.api import DiagnosticAddress
from noetrium_platform.evidence.observability.logging.record.api import LogLevel
from noetrium_platform.evidence.observability.logging.record.runtime.logger import StructuredLogger
from noetrium_platform.evidence.observability.logging.storage.runtime.in_memory import InMemoryLogStore
from noetrium_platform.evidence.observability.telemetry.metric.composition.catalog import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime.recorder import InMemoryMetricRecorder
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


class _EventSink:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    def append_event(self, event: EventEnvelope) -> str:
        self.events.append(event)
        return event.event_id


def _context() -> ExecutionContext:
    return ExecutionContext(run_id="run", trace_id="trace", span_id="span")


def _address() -> DiagnosticAddress:
    return DiagnosticAddress(scope_path=(PLATFORM_SCOPE,))


def test_replay_scope_suppresses_fresh_event_log_and_metric_records() -> None:
    event_sink = _EventSink()
    fanout = FanoutEventSink(event_sink)
    log_store = InMemoryLogStore()
    logger = StructuredLogger(log_store, logger="test", address=_address())
    metrics = InMemoryMetricRecorder(build_default_registry())

    assert operational_observation_enabled()
    with observation_emission_scope(ObservationEmissionMode.REPLAY):
        assert not operational_observation_enabled()
        assert fanout.append_event(
            EventEnvelope("e-replay", "replay.event", _context(), "component")
        ) == ()
        log_id = logger.log(
            LogLevel.INFO,
            event="replay.log",
            message="must not become a fresh record",
        )
        assert log_id.startswith("log_")
        metrics.observe("model.ttft", 0.1, model="m", engine="e", replica="0")

    assert event_sink.events == []
    assert log_store.query(limit=10) == ()
    assert metrics.rows() == ()


def test_live_observation_resumes_after_nested_replay_scope() -> None:
    event_sink = _EventSink()
    fanout = FanoutEventSink(event_sink)
    with observation_emission_scope(ObservationEmissionMode.REPLAY):
        fanout.append_event(EventEnvelope("e-hidden", "hidden", _context(), "component"))
    fanout.append_event(EventEnvelope("e-live", "live", _context(), "component"))
    assert [row.event_id for row in event_sink.events] == ["e-live"]


def test_projection_rebuild_is_not_fresh_operational_execution() -> None:
    event_sink = _EventSink()
    fanout = FanoutEventSink(event_sink)
    with observation_emission_scope(ObservationEmissionMode.PROJECTION_REBUILD):
        fanout.append_event(
            EventEnvelope("e-rebuild", "projection.rebuild", _context(), "component")
        )
    assert event_sink.events == []
