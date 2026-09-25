from __future__ import annotations

from typing import ContextManager, Protocol, TypedDict

from .records import DiagnosticObjectRecord, OperationInvocationRecord, StateWriterRecord


class MetricQueryRow(TypedDict):
    """Validated read-side metric row returned by diagnostic queries."""

    sequence: int
    metric: str
    value: float
    timestamp: float
    run_id: str
    task_id: str | None
    decision_cycle_id: str | None
    trace_id: str
    span_id: str
    operation_id: str | None
    component_id: str | None
    dimensions: dict[str, str]


class DiagnosticIndexSessionPort(Protocol):
    """Consistent read snapshot for compound diagnostic joins."""

    def locate(self, object_id: str) -> DiagnosticObjectRecord | None: ...
    def last_writer(self, run_id: str, state_name: str) -> StateWriterRecord | None: ...
    def around(
        self,
        *,
        run_id: str,
        timestamp: float,
        seconds: float = 30.0,
    ) -> tuple[DiagnosticObjectRecord, ...]: ...
    def recent_state_writers(
        self,
        *,
        run_id: str,
        before: float,
        limit: int = 12,
    ) -> tuple[StateWriterRecord, ...]: ...
    def related_to(self, object_id: str, *, limit: int = 100) -> tuple[DiagnosticObjectRecord, ...]: ...
    def operation_invocation(self, invocation_id: str) -> OperationInvocationRecord | None: ...
    def unclosed_operations(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]: ...
    def operations_open_at(
        self,
        *,
        run_id: str,
        timestamp: float,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]: ...


class DiagnosticEvidencePort(Protocol):
    """Read-only diagnostic evidence surface independent of ledger/index backend."""

    @property
    def source_ref(self) -> str: ...

    def verify_authoritative(self) -> dict[str, tuple[int, str]]: ...
    def projection_freshness(
        self,
    ) -> tuple[bool, dict[str, tuple[int, str]], dict[str, tuple[int, str]]]: ...
    def read_session(self) -> ContextManager[DiagnosticIndexSessionPort]: ...
    def locate(self, object_id: str) -> DiagnosticObjectRecord | None: ...
    def last_writer(self, run_id: str, state_name: str) -> StateWriterRecord | None: ...
    def around(
        self,
        *,
        run_id: str,
        timestamp: float,
        seconds: float = 30.0,
    ) -> tuple[DiagnosticObjectRecord, ...]: ...
    def recent_state_writers(
        self,
        *,
        run_id: str,
        before: float,
        limit: int = 12,
    ) -> tuple[StateWriterRecord, ...]: ...
    def related_to(self, object_id: str, *, limit: int = 100) -> tuple[DiagnosticObjectRecord, ...]: ...
    def unclosed_operations(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]: ...


class MetricQueryPort(Protocol):
    def query(
        self,
        *,
        run_id: str,
        metric: str | None = None,
        decision_cycle_id: str | None = None,
        limit: int = 1000,
    ) -> tuple[MetricQueryRow, ...]: ...


__all__ = ["DiagnosticEvidencePort", "DiagnosticIndexSessionPort", "MetricQueryPort", "MetricQueryRow"]
