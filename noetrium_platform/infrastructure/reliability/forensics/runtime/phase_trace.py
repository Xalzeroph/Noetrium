from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import time
from typing import Mapping

from noetrium_platform.foundation.kernel.event import causal_event, event_ref_from_digest
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    execution_context_payload,
)
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.forensics.api.ports import (
    ForensicStorePort,
)


@dataclass(frozen=True, slots=True)
class CausalPhase:
    name: str
    started: NoetriumUnit
    started_ns: int


class CausalPhaseTrace:
    """Domain-local causal phases linked to an existing run/event root.

    This is not a new log carrier. Every record is an ordinary system.event
    NoetriumUnit written to the owning authority's ForensicStore.
    """

    def __init__(
        self,
        store: ForensicStorePort,
        *,
        context: ExecutionContext,
        authority_domain: str,
        component_id: str,
        subject: str,
        causal_parent_digests: tuple[str, ...] = (),
    ) -> None:
        self._store = store
        self._context_payload = execution_context_payload(context)
        self._authority_domain = authority_domain
        self._component_id = component_id
        self._subject = subject
        self._head_digests = tuple(causal_parent_digests)

    @property
    def head_digests(self) -> tuple[str, ...]:
        return self._head_digests

    def _event(
        self,
        *,
        operation: str,
        phase: str,
        parent_digests: tuple[str, ...],
        attributes: Mapping[str, object] | None = None,
    ) -> NoetriumUnit:
        observed_ns = time.time_ns()
        return causal_event(
            authority_domain=self._authority_domain,
            generation=0,
            subject=self._subject,
            operation=operation,
            phase=phase,
            modality=TruthModality.OBSERVED,
            causal_parents=tuple(
                event_ref_from_digest(digest) for digest in parent_digests
            ),
            attributes={
                "context": self._context_payload,
                "component_id": self._component_id,
                "timestamp": observed_ns / 1_000_000_000,
                "payload": {
                    "phase_name": operation,
                    "observed_ns": observed_ns,
                    **dict(attributes or {}),
                },
            },
        )

    def start(
        self,
        name: str,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> CausalPhase:
        started_ns = time.time_ns()
        event = self._event(
            operation=name,
            phase="started",
            parent_digests=self._head_digests,
            attributes={
                "started_ns": started_ns,
                **dict(attributes or {}),
            },
        )
        self._store.append_event(event)
        self._head_digests = (event.unit_digest,)
        return CausalPhase(name=name, started=event, started_ns=started_ns)

    def complete(
        self,
        phase: CausalPhase,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> NoetriumUnit:
        finished_ns = time.time_ns()
        parent_digests = (
            (phase.started.unit_digest,)
            if self._head_digests == (phase.started.unit_digest,)
            else tuple(
                dict.fromkeys((phase.started.unit_digest, *self._head_digests))
            )
        )
        event = self._event(
            operation=phase.name,
            phase="completed",
            parent_digests=parent_digests,
            attributes={
                "started_ns": phase.started_ns,
                "finished_ns": finished_ns,
                "duration_ns": finished_ns - phase.started_ns,
                **dict(attributes or {}),
            },
        )
        self._store.append_event(event)
        self._head_digests = (event.unit_digest,)
        return event

    @contextmanager
    def phase(
        self,
        name: str,
        *,
        attributes: Mapping[str, object] | None = None,
    ):
        phase = self.start(name, attributes=attributes)
        try:
            yield phase
        except BaseException as exc:
            self.fail(phase, exc)
            raise
        else:
            self.complete(phase)

    def fail(
        self,
        phase: CausalPhase,
        exc: BaseException,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> NoetriumUnit:
        finished_ns = time.time_ns()
        diagnostics = getattr(exc, "diagnostics", None)
        parent_digests = (
            (phase.started.unit_digest,)
            if self._head_digests == (phase.started.unit_digest,)
            else tuple(
                dict.fromkeys((phase.started.unit_digest, *self._head_digests))
            )
        )
        event = self._event(
            operation=phase.name,
            phase="failed",
            parent_digests=parent_digests,
            attributes={
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
        self._store.append_event(event)
        self._head_digests = (event.unit_digest,)
        refs = tuple(getattr(exc, "causal_event_refs", ()))
        try:
            exc.causal_event_refs = tuple(dict.fromkeys((*refs, event.unit_digest)))
        except Exception:
            pass
        return event


__all__ = ["CausalPhase", "CausalPhaseTrace"]
