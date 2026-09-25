from __future__ import annotations

"""Diagnostic side-effect policy for one Minecraft environment session."""

from collections import deque
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from ..api.ports import MinecraftDiagnosticsPort


def safe_exception_message(exc: BaseException) -> str:
    descriptor = describe_exception(exc)
    return f"{descriptor.error_type}:{descriptor.safe_message} [{descriptor.error_digest[:12]}]"


class MinecraftSessionDiagnosticRecorder:
    """Best-effort diagnostic recorder; diagnostics never become session state."""

    def __init__(
        self,
        *,
        session_id: str,
        sink: MinecraftDiagnosticsPort | None,
        max_sink_failures: int = 64,
    ) -> None:
        if not session_id.strip() or max_sink_failures <= 0:
            raise ValueError("Minecraft diagnostic recorder configuration is invalid")
        self.session_id = session_id
        self.sink = sink
        self._sink_failures: deque[str] = deque(maxlen=max_sink_failures)

    @property
    def sink_failures(self) -> tuple[str, ...]:
        return tuple(self._sink_failures)

    def event(
        self,
        phase: str,
        event: str,
        *,
        level: str = "DEBUG",
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
    ) -> None:
        if self.sink is None:
            return
        try:
            self.sink.event(
                phase=phase,
                event=event,
                level=level,
                attributes={"session_id": self.session_id, **dict(attributes or {})},
                correlation_refs=correlation_refs,
            )
        except BaseException as exc:
            self._sink_failures.append(f"event:{phase}:{event}:{safe_exception_message(exc)}")

    def failure(
        self,
        phase: str,
        exc: BaseException,
        *,
        code: str | None = None,
    ) -> None:
        if self.sink is None:
            return
        try:
            self.sink.failure(
                phase=phase,
                code=code or str(getattr(exc, "cause_code", "MINECRAFT_ENVIRONMENT_FAILURE")),
                message=safe_exception_message(exc),
                exception=exc,
                attributes={"session_id": self.session_id},
            )
        except BaseException as sink_exc:
            self._sink_failures.append(f"failure:{phase}:{safe_exception_message(sink_exc)}")


__all__ = ["MinecraftSessionDiagnosticRecorder", "safe_exception_message"]
