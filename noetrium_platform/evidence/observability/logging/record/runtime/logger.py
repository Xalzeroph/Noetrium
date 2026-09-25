from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.evidence.observability.api.emission import operational_observation_enabled
from noetrium_platform.evidence.observability.logging.context.api import DiagnosticAddress
from noetrium_platform.evidence.observability.logging.record.api import (
    ExceptionDescriptorPort,
    LogLevel,
    LogRecord,
    LogWriterPort,
)
from noetrium_platform.evidence.observability.logging.sink.api import LogSinkPort


class StructuredLogger(LogWriterPort):
    """Record-node adapter that emits structured facts to an injected sink."""

    def __init__(
        self,
        sink: LogSinkPort,
        *,
        logger: str,
        address: DiagnosticAddress,
        attributes: Mapping[str, JsonValue] | None = None,
        exception_descriptor: ExceptionDescriptorPort | None = None,
    ) -> None:
        if not logger.strip():
            raise ValueError("logger must be non-empty")
        self._sink = sink
        self._logger = logger
        self._address = address
        self._attributes = self._normalize_attributes(attributes)
        self._exception_descriptor = exception_descriptor

    @property
    def address(self) -> DiagnosticAddress:
        return self._address

    def child(
        self,
        *,
        address: DiagnosticAddress | None = None,
        component_id: str | None = None,
    ) -> "StructuredLogger":
        target = address or self._address
        if component_id is not None:
            target = replace(target, component_id=component_id)
        return StructuredLogger(
            self._sink,
            logger=self._logger,
            address=target,
            attributes=self._attributes,
            exception_descriptor=self._exception_descriptor,
        )

    def log(
        self,
        level: LogLevel,
        *,
        event: str,
        message: str,
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
        failure_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
    ) -> str:
        log_id = self._make_id(level, event, message, failure_refs)
        if not operational_observation_enabled():
            return log_id
        normalized = self._merge_attributes(attributes)
        self._sink.append(
            LogRecord(
                log_id=log_id,
                created_at=time.time(),
                level=level,
                logger=self._logger,
                event=event,
                message=message,
                address=self._address,
                attributes=normalized,
                correlation_refs=tuple(dict.fromkeys(correlation_refs)),
                failure_refs=tuple(dict.fromkeys(failure_refs)),
                artifact_refs=tuple(dict.fromkeys(artifact_refs)),
            )
        )
        return log_id

    def exception(
        self,
        *,
        event: str,
        message: str,
        exc: BaseException,
        level: LogLevel = LogLevel.ERROR,
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
        failure_refs: tuple[str, ...] = (),
    ) -> str:
        log_id = self._make_id(level, event, message, failure_refs)
        if not operational_observation_enabled():
            return log_id
        normalized = self._merge_attributes(attributes)
        self._sink.append(
            LogRecord(
                log_id=log_id,
                created_at=time.time(),
                level=level,
                logger=self._logger,
                event=event,
                message=message,
                address=self._address,
                attributes=normalized,
                exception=(
                    self._exception_descriptor.describe(exc)
                    if self._exception_descriptor is not None
                    else describe_exception(exc)
                ),
                correlation_refs=tuple(dict.fromkeys(correlation_refs)),
                failure_refs=tuple(dict.fromkeys(failure_refs)),
            )
        )
        return log_id

    def failure(
        self,
        *,
        event: str,
        message: str,
        failure_id: str,
        level: LogLevel = LogLevel.ERROR,
        attributes: Mapping[str, JsonValue] | None = None,
        correlation_refs: tuple[str, ...] = (),
    ) -> str:
        if not failure_id.strip():
            raise ValueError("failure_id must be non-empty")
        return self.log(
            level,
            event=event,
            message=message,
            attributes=attributes,
            correlation_refs=correlation_refs,
            failure_refs=(failure_id,),
        )

    @staticmethod
    def _safe_value(value: object) -> str:
        return str(value).replace("\n", "\\n")[:2048]

    def _make_id(
        self,
        level: LogLevel,
        event: str,
        message: str,
        failure_refs: tuple[str, ...] = (),
    ) -> str:
        raw = "|".join(
            (
                self._logger,
                level.value,
                event,
                message,
                self._address.scope.key,
                self._address.component_id or "",
                *failure_refs,
            )
        )
        digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:24]
        return f"log_{digest}"

    def _merge_attributes(
        self,
        attributes: Mapping[str, JsonValue] | None,
    ) -> tuple[tuple[str, str], ...]:
        merged = dict(self._attributes)
        merged.update({str(k): self._safe_value(v) for k, v in (attributes or {}).items()})
        return tuple(sorted(merged.items()))

    @classmethod
    def _normalize_attributes(
        cls,
        attributes: Mapping[str, JsonValue] | None,
    ) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(k), cls._safe_value(v)) for k, v in (attributes or {}).items()))


__all__ = ["StructuredLogger"]
