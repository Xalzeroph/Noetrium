from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.evidence.observability.capture.composition import (
    build_file_raw_observation_lake,
)
from noetrium_platform.evidence.observability.capture.runtime import (
    RegistryBoundRawObservationGateway,
)
from noetrium_platform.evidence.observability.logging.composition import (
    LogQueryBinding,
    LogSinkBinding,
    compose_logging_system,
)
from noetrium_platform.evidence.observability.logging.record.api import (
    LoggingSystemBinding,
)
from noetrium_platform.evidence.observability.logging.storage.composition.jsonl import (
    build_jsonl_log_store,
)
from noetrium_platform.evidence.observability.logging.routing.runtime import (
    FanoutLogSink,
)
from noetrium_platform.evidence.observability.telemetry.metric.composition import (
    build_default_registry,
    build_telemetry_sqlite_backend,
)
from noetrium_platform.evidence.observability.telemetry.metric.runtime import (
    TelemetryStore,
)
from noetrium_platform.foundation.governance.architecture.runtime.capability_composition import (
    CapabilityCompositionPlanner,
)
from noetrium_platform.foundation.governance.system_registry.api import (
    SystemRegistryPort,
)
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest


@dataclass(slots=True)
class ManagedObservability:
    """Platform-owned durable observability authorities for one runtime.

    This bundle is intentionally composition-only.  Telemetry, raw capture and
    structured logging keep their existing ownership boundaries while the
    managed runtime guarantees that downstream projects do not have to wire
    persistence, registries or writer actors manually.
    """

    telemetry: TelemetryStore
    raw: RegistryBoundRawObservationGateway
    logging: LoggingSystemBinding
    _telemetry_backend: object
    _raw_closed: bool = False
    _telemetry_closed: bool = False
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        if not self._raw_closed:
            try:
                self.raw.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._raw_closed = True
        if not self._telemetry_closed:
            close = getattr(self._telemetry_backend, "close", None)
            if callable(close):
                try:
                    close()
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._telemetry_closed = True
            else:
                self._telemetry_closed = True
        if errors:
            raise ExceptionGroup("managed observability close failed", errors)
        self._closed = self._raw_closed and self._telemetry_closed

    def __enter__(self) -> "ManagedObservability":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


def build_managed_observability(
    root: Path,
    *,
    task_group: TaskGroupPort,
    systems: SystemRegistryPort,
    planner: CapabilityCompositionPlanner,
) -> ManagedObservability:
    """Build the default durable observability bus for a managed runtime."""

    resolved = Path(root).resolve()
    resolved.mkdir(parents=True, exist_ok=True)

    telemetry_backend = build_telemetry_sqlite_backend(
        resolved / "telemetry.sqlite",
        task_group=task_group,
    )
    telemetry = TelemetryStore(build_default_registry(), telemetry_backend)

    raw_lake = build_file_raw_observation_lake(
        resolved / "raw",
        task_group=task_group,
    )
    raw = RegistryBoundRawObservationGateway(raw_lake, systems)

    log_store = build_jsonl_log_store(
        resolved / "logs" / "structured.jsonl",
        task_group=task_group,
    )
    routed_log_sink = FanoutLogSink((log_store,))
    logging = compose_logging_system(
        sink=LogSinkBinding(
            routed_log_sink,
            "observability.logging.jsonl-sink.v1",
            canonical_digest(
                {
                    "kind": "jsonl-log-sink",
                    "path": str(log_store.path),
                }
            ),
        ),
        query=LogQueryBinding(
            log_store,
            "observability.logging.jsonl-query.v1",
            canonical_digest(
                {
                    "kind": "jsonl-log-query",
                    "path": str(log_store.path),
                }
            ),
        ),
        planner=planner,
        systems=systems,
        metrics=telemetry,
        raw_gateway=raw,
    )
    return ManagedObservability(
        telemetry=telemetry,
        raw=raw,
        logging=logging,
        _telemetry_backend=telemetry_backend,
    )


__all__ = ["ManagedObservability", "build_managed_observability"]
