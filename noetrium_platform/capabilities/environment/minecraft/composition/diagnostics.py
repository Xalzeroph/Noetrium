from __future__ import annotations

from collections import deque
from typing import Mapping, Protocol

from noetrium_platform.evidence.observability.api.metrics import ContextMetricSink
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogWriterPort
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue
from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope, FailureLedgerPort

from ..api import MinecraftDiagnosticsPort


class MinecraftFailureMaterializer(Protocol):
    """Composition-owned taxonomy adapter for one MC failure observation.

    Minecraft emits a stable provider code, but it must not decide the platform
    failure taxonomy or scientific risk. The project/platform composition root
    supplies this materializer and may bind it to ``build_failure_from_spec``.
    """

    def __call__(
        self,
        *,
        phase: str,
        code: str,
        message: str,
        exception: BaseException,
        context: ExecutionContext,
        attributes: Mapping[str, JsonValue],
        correlation_refs: tuple[str, ...],
    ) -> FailureEnvelope: ...


class MinecraftDiagnosticContext(Protocol):
    """Late-bound context source used by metrics and failure materialization."""

    def __call__(self) -> ExecutionContext: ...


_LOG_LEVELS: dict[str, LogLevel] = {level.value: level for level in LogLevel}


class StructuredMinecraftDiagnostics(MinecraftDiagnosticsPort):
    """Bind the MC diagnostic seam to platform-owned diagnostic authorities.

    The adapter owns no persistence, taxonomy, retry policy or metric registry.
    It only translates MC diagnostic facts into injected platform interfaces.
    A sink failure is retained in ``diagnostic_errors`` so the environment
    operation is not masked by an observability failure, while the composition
    root can surface the loss through its own health/error policy.
    """

    def __init__(
        self,
        *,
        logger: LogWriterPort,
        context: MinecraftDiagnosticContext | None = None,
        metrics: ContextMetricSink | None = None,
        failure_ledger: FailureLedgerPort | None = None,
        failure_materializer: MinecraftFailureMaterializer | None = None,
        max_diagnostic_errors: int = 64,
    ) -> None:
        if max_diagnostic_errors <= 0:
            raise ValueError("max_diagnostic_errors must be positive")
        if metrics is not None and context is None:
            raise ValueError("metrics require an injected execution context provider")
        if failure_ledger is not None and (context is None or failure_materializer is None):
            raise ValueError(
                "failure_ledger requires both an execution context provider and a failure materializer"
            )
        self._logger = logger
        self._context = context
        self._metrics = metrics
        self._failure_ledger = failure_ledger
        self._failure_materializer = failure_materializer
        self._diagnostic_errors: deque[str] = deque(maxlen=max_diagnostic_errors)

    @property
    def diagnostic_errors(self) -> tuple[str, ...]:
        return tuple(self._diagnostic_errors)

    def _level(self, value: str) -> LogLevel:
        try:
            return _LOG_LEVELS[value.lower()]
        except KeyError as exc:
            raise ValueError(f"unknown Minecraft diagnostic log level: {value!r}") from exc

    def _record_adapter_error(self, operation: str, exc: BaseException) -> None:
        self._diagnostic_errors.append(f"{operation}:{type(exc).__name__}:{exc}")

    def event(
        self,
        *,
        phase: str,
        event: str,
        attributes: Mapping[str, JsonValue] | None = None,
        level: str = "DEBUG",
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        if not phase.strip() or not event.strip():
            raise ValueError("Minecraft diagnostic phase and event must be non-empty")
        normalized = {"diagnostic_phase": phase, **dict(attributes or {})}
        try:
            self._logger.log(
                self._level(level),
                event=event,
                message=f"minecraft.{phase}.{event}",
                attributes=normalized,
                correlation_refs=correlation_refs,
            )
        except BaseException as exc:
            self._record_adapter_error("event", exc)

    def failure(
        self,
        *,
        phase: str,
        code: str,
        message: str,
        exception: BaseException | None = None,
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        if not phase.strip() or not code.strip() or not message.strip():
            raise ValueError("Minecraft diagnostic failure phase, code and message are required")
        normalized = {
            "diagnostic_phase": phase,
            "failure_code": code,
            **dict(attributes or {}),
        }
        failure_exception = exception or RuntimeError(message)
        try:
            if exception is None:
                self._logger.log(
                    LogLevel.ERROR,
                    event="MC_FAILURE",
                    message=message,
                    attributes=normalized,
                    correlation_refs=correlation_refs,
                )
            else:
                self._logger.exception(
                    event="MC_FAILURE",
                    message=message,
                    exc=exception,
                    attributes=normalized,
                    correlation_refs=correlation_refs,
                )
        except BaseException as exc:
            self._record_adapter_error("failure.log", exc)

        if self._failure_ledger is None:
            return
        assert self._context is not None
        assert self._failure_materializer is not None
        try:
            envelope = self._failure_materializer(
                phase=phase,
                code=code,
                message=message,
                exception=failure_exception,
                context=self._context(),
                attributes=normalized,
                correlation_refs=correlation_refs,
            )
            self._failure_ledger.append_failure_once(envelope)
        except BaseException as exc:
            self._record_adapter_error("failure.ledger", exc)

    def metric(
        self,
        *,
        name: str,
        value: float,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        if not name.strip():
            raise ValueError("Minecraft diagnostic metric name must be non-empty")
        if self._metrics is None:
            return
        assert self._context is not None
        try:
            self._metrics.observe(self._context(), name, value, **dict(labels or {}))
        except BaseException as exc:
            self._record_adapter_error("metric", exc)


__all__ = [
    "MinecraftDiagnosticContext",
    "MinecraftFailureMaterializer",
    "StructuredMinecraftDiagnostics",
]
