from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from noetrium_platform.foundation.kernel.kernel.errors import attempt_secondary_delivery

from .contracts import RuntimeAction


class RuntimeControlObserverPort(Protocol):
    """Side-plane observer for exact runtime-control actions."""

    def action_started(self, action: RuntimeAction, *, mutating: bool) -> None: ...

    def action_finished(self, action: RuntimeAction, *, result: str, mutating: bool) -> None: ...

    def reconcile_finished(self, *, scope: str) -> None: ...

    def exact_service_started(self) -> None: ...

    def qualification_verified(self) -> None: ...


class RuntimeRecoveryObserverPort(Protocol):
    """Side-plane observer for one-click recovery/lease orchestration."""

    def lease_wait_started(self) -> None: ...

    def lease_acquired(self) -> None: ...

    def lease_conflict(self) -> None: ...

    def recovery_round(self, action: RuntimeAction, *, round_number: int) -> None: ...


class RuntimeLifecycleObserverPort(RuntimeControlObserverPort, RuntimeRecoveryObserverPort, Protocol):
    """Combined observer used by one-click orchestration and nested runtime control."""



@dataclass(frozen=True, slots=True)
class RuntimeObserverFailure:
    stage: str
    error_type: str

    @classmethod
    def from_exception(cls, stage: str, exc: BaseException) -> "RuntimeObserverFailure":
        return cls(stage=stage, error_type=type(exc).__qualname__)


class RuntimeObserverFailureSink(Protocol):
    def record(self, failure: RuntimeObserverFailure) -> None: ...


def notify_runtime_observer(
    observer: object | None,
    failure_sink: RuntimeObserverFailureSink | None,
    *,
    stage: str,
    callback: Callable[[], None],
) -> RuntimeObserverFailure | None:
    """Deliver one observer callback without allowing diagnostics to alter runtime truth."""

    if observer is None:
        return None
    try:
        callback()
        return None
    except Exception as exc:
        failure = RuntimeObserverFailure.from_exception(stage, exc)
        if failure_sink is not None:
            attempt_secondary_delivery(lambda: failure_sink.record(failure))
        return failure


__all__ = [
    "RuntimeControlObserverPort",
    "RuntimeLifecycleObserverPort",
    "RuntimeObserverFailure",
    "RuntimeObserverFailureSink",
    "RuntimeRecoveryObserverPort",
    "notify_runtime_observer",
]
