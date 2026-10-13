from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import time
from threading import RLock
from typing import Iterator, Mapping

from noetrium_platform.foundation.kernel.event import (
    causal_event,
    event_ref,
    event_ref_from_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
    execution_context_payload,
)
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.failure.api import (
    DEFAULT_FAILURE_CATALOG,
)
from noetrium_platform.infrastructure.reliability.forensics.api.ports import (
    ForensicStorePort,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime.recorder import (
    FailureRecorder,
)


@dataclass(frozen=True, slots=True)
class RunTracePhase:
    name: str
    component_id: str
    started: NoetriumUnit
    started_ns: int


class RunCausalTrace:
    """One durable causal root spanning bootstrap, control and runtime phases.

    The trace owns no persistence resource.  It can be rebound from a direct
    bootstrap ForensicStore to the managed runtime's ForensicStore while
    preserving one content-addressed causal head.
    """

    def __init__(
        self,
        store: ForensicStorePort,
        *,
        source_identity: object,
        execution_tenant_id: str | None = None,
        component_id: str = "noetrium.run",
        causal_parent_digests: tuple[str, ...] = (),
    ) -> None:
        started_ns = time.time_ns()
        seed = {
            "kind": "noetrium.run.invocation.v1",
            "source_identity": source_identity,
            "started_ns": started_ns,
            "pid": os.getpid(),
        }
        digest = canonical_digest(seed)
        run_id = "run_" + digest[:32]
        trace_id = "trace_" + digest
        span_id = "span_" + digest[:32]
        self._context = ExecutionContext(
            run_id=run_id,
            trace_id=trace_id,
            span_id=span_id,
            execution_tenant_id=execution_tenant_id,
        )
        self._store = store
        self._component_id = component_id
        self._lock = RLock()
        self._closed = False
        self._failed = False
        root = self._new_event(
            operation="run",
            phase="requested",
            component_id=component_id,
            causal_parents=(),
            causal_parent_digests=causal_parent_digests,
            payload={
                "source_identity": source_identity,
                "started_ns": started_ns,
            },
        )
        store.append_event(root)
        self._root = root
        self._head = root

    @property
    def context(self) -> ExecutionContext:
        return self._context

    @property
    def run_id(self) -> str:
        return self._context.run_id

    @property
    def root_event(self) -> NoetriumUnit:
        return self._root

    @property
    def head_event(self) -> NoetriumUnit:
        return self._head

    def _new_event(
        self,
        *,
        operation: str,
        phase: str,
        component_id: str,
        causal_parents: tuple[NoetriumUnit, ...],
        causal_parent_digests: tuple[str, ...] = (),
        payload: Mapping[str, object] | None = None,
    ) -> NoetriumUnit:
        observed_ns = time.time_ns()
        payload_dict = dict(payload or {})
        parent_digests = (
            tuple(event.unit_digest for event in causal_parents)
            + tuple(causal_parent_digests)
        )
        if len(parent_digests) != len(set(parent_digests)):
            raise ValueError("run trace causal parents must be unique")
        event_id = (
            "run-event-"
            + canonical_digest(
                {
                    "run_id": self._context.run_id,
                    "operation": operation,
                    "phase": phase,
                    "component_id": component_id,
                    "observed_ns": observed_ns,
                    "parent_digests": parent_digests,
                }
            )[:32]
        )
        attributes = {
            "event_id": event_id,
            "event_type": f"RUN_{operation}_{phase}".upper(),
            "context": execution_context_payload(self._context),
            "component_id": component_id,
            "timestamp": observed_ns / 1_000_000_000,
            "payload": {
                "run_id": self._context.run_id,
                "trace_id": self._context.trace_id,
                "phase": phase,
                "operation": operation,
                "observed_ns": observed_ns,
                **payload_dict,
            },
        }
        return causal_event(
            authority_domain="run." + self._context.run_id,
            generation=0,
            subject="run:" + self._context.run_id,
            operation=operation,
            phase=phase,
            modality=TruthModality.OBSERVED,
            causal_parents=(
                tuple(event_ref(event) for event in causal_parents)
                + tuple(
                    event_ref_from_digest(digest)
                    for digest in causal_parent_digests
                )
            ),
            event_kind="run.lifecycle",
            attributes=attributes,
        )

    def start_phase(
        self,
        name: str,
        *,
        component_id: str,
        attributes: Mapping[str, object] | None = None,
    ) -> RunTracePhase:
        if type(name) is not str or not name.strip():
            raise ValueError("run trace phase name must be non-empty")
        with self._lock:
            if self._closed:
                raise RuntimeError("run trace is closed")
            started_ns = time.time_ns()
            event = self._new_event(
                operation=name,
                phase="started",
                component_id=component_id,
                causal_parents=(self._head,),
                payload={
                    "phase_name": name,
                    "started_ns": started_ns,
                    **dict(attributes or {}),
                },
            )
            self._store.append_event(event)
            self._head = event
            return RunTracePhase(name, component_id, event, started_ns)

    def complete_phase(
        self,
        phase: RunTracePhase,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> NoetriumUnit:
        with self._lock:
            if self._closed:
                raise RuntimeError("run trace is closed")
            finished_ns = time.time_ns()
            parents = (
                (phase.started,)
                if self._head.unit_digest == phase.started.unit_digest
                else (phase.started, self._head)
            )
            event = self._new_event(
                operation=phase.name,
                phase="completed",
                component_id=phase.component_id,
                causal_parents=parents,
                payload={
                    "phase_name": phase.name,
                    "started_ns": phase.started_ns,
                    "finished_ns": finished_ns,
                    "duration_ns": finished_ns - phase.started_ns,
                    **dict(attributes or {}),
                },
            )
            self._store.append_event(event)
            self._head = event
            return event

    def fail_phase(
        self,
        phase: RunTracePhase,
        exc: BaseException,
        *,
        attributes: Mapping[str, object] | None = None,
        record_failure: bool = True,
    ) -> NoetriumUnit:
        with self._lock:
            if self._closed:
                raise RuntimeError("run trace is closed")
            finished_ns = time.time_ns()
            parent_already_failure = self._head.has_schema(
                "reliability.failure"
            )
            parents = (
                (phase.started,)
                if self._head.unit_digest == phase.started.unit_digest
                else (phase.started, self._head)
            )
            diagnostics = getattr(exc, "diagnostics", None)
            external_refs = tuple(
                getattr(exc, "causal_event_refs", ())
            )
            failed = self._new_event(
                operation=phase.name,
                phase="failed",
                component_id=phase.component_id,
                causal_parents=parents,
                causal_parent_digests=external_refs,
                payload={
                    "phase_name": phase.name,
                    "started_ns": phase.started_ns,
                    "finished_ns": finished_ns,
                    "duration_ns": finished_ns - phase.started_ns,
                    "cause_type": type(exc).__qualname__,
                    "cause_message": describe_exception(exc).safe_message,
                    **(
                        {"diagnostics": dict(diagnostics)}
                        if isinstance(diagnostics, Mapping)
                        else {}
                    ),
                    **dict(attributes or {}),
                },
            )
            self._store.append_event(failed)
            self._head = failed
            self._failed = True
            if not record_failure or parent_already_failure:
                return failed
            recorder = FailureRecorder(self._store)
            outcome = recorder.record(
                spec=DEFAULT_FAILURE_CATALOG.require(
                    "PLATFORM", "OPERATION_FAILURE", "component_boundary"
                ),
                component_id=phase.component_id,
                context=self._context,
                exc=exc,
                operation_type="control." + phase.name,
                request_refs=(self._context.run_id,),
                correlation_refs=(self._context.trace_id,),
                causal_event_refs=(failed.unit_digest,),
            )
            self._head = outcome.failure
            return outcome.failure

    @contextmanager
    def phase(
        self,
        name: str,
        *,
        component_id: str,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[RunTracePhase]:
        phase = self.start_phase(
            name,
            component_id=component_id,
            attributes=attributes,
        )
        try:
            yield phase
        except BaseException as exc:
            self.fail_phase(phase, exc)
            raise
        else:
            self.complete_phase(phase)

    def finish(
        self,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> NoetriumUnit:
        with self._lock:
            if self._closed:
                return self._head
            event = self._new_event(
                operation="run",
                phase="failed" if self._failed else "completed",
                component_id=self._component_id,
                causal_parents=(self._head,),
                payload=dict(attributes or {}),
            )
            self._store.append_event(event)
            self._head = event
            self._closed = True
            return event


__all__ = ["RunCausalTrace", "RunTracePhase"]
