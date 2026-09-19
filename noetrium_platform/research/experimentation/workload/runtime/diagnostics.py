from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import NoReturn

from noetrium_platform.research.experimentation.experiment.api import FailureScope
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from ..api import (
    WorkloadDiagnosticsPort,
    WorkloadFailurePolicyPort,
    WorkloadTaskRunError,
)


class WorkloadDiagnosticEmitter:
    """Observation-plane adapter that can never become execution authority."""

    def __init__(
        self,
        diagnostics: WorkloadDiagnosticsPort | None,
        *,
        event_prefix: str,
        metric_prefix: str,
        max_errors: int,
    ) -> None:
        self._diagnostics = diagnostics
        self._event_prefix = event_prefix
        self._metric_prefix = metric_prefix
        self._errors: deque[str] = deque(maxlen=max_errors)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors)

    def clear(self) -> None:
        self._errors.clear()

    def _record_error(self, operation: str, exc: BaseException) -> None:
        descriptor = describe_exception(exc)
        self._errors.append(
            f"{operation}:{descriptor.qualified_type}:"
            f"{descriptor.safe_message}:{descriptor.error_digest}"
        )

    def event(
        self,
        suffix: str,
        *,
        level: str = "DEBUG",
        **attributes: object,
    ) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.event(
                f"{self._event_prefix}_{suffix}",
                level=level,
                attributes=attributes,
            )
        except Exception as exc:
            self._record_error("event", exc)

    def metric(
        self,
        suffix: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.metric(
                f"{self._metric_prefix}.{suffix}",
                value,
                labels=labels,
            )
        except Exception as exc:
            self._record_error("metric", exc)

    def failure(self, phase: str, code: str, exc: BaseException) -> None:
        if self._diagnostics is None:
            return
        try:
            self._diagnostics.failure(
                code,
                describe_exception(exc).safe_message,
                phase=phase,
                exception=exc,
            )
        except Exception as diagnostic_exc:
            self._record_error("failure", diagnostic_exc)


class WorkloadFailureRouter:
    """Classify execution failures without allowing diagnostics to swallow them."""

    def __init__(
        self,
        policy: WorkloadFailurePolicyPort,
        diagnostics: WorkloadDiagnosticEmitter,
    ) -> None:
        self._policy = policy
        self._diagnostics = diagnostics

    def raise_classified(
        self,
        phase: str,
        code: str,
        exc: BaseException,
    ) -> NoReturn:
        scope = self._policy.scope(phase, exc)
        if not isinstance(scope, FailureScope):
            raise TypeError("workload failure policy returned an invalid FailureScope")
        self._diagnostics.failure(phase, code, exc)
        raise WorkloadTaskRunError(
            phase,
            code,
            describe_exception(exc).safe_message,
            scope=scope,
        ) from exc


__all__ = ["WorkloadDiagnosticEmitter", "WorkloadFailureRouter"]
