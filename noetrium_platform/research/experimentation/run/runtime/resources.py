from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult

from ..lifecycle.api import RunCleanupReport, attach_cleanup_note
from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentComponentBindingPort,
    ExperimentSpec,
)
from ..identity.api import RunIdentity
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantSessionLifecyclePort


@dataclass(frozen=True, slots=True)
class OpenRunResources:
    bound: BoundParticipants
    context: ExecutionContext
    operation_results: tuple[OperationResult[JsonValue], ...]
    participant_sessions: tuple[ParticipantSessionBinding, ...] = ()

    def by_role(self, role: str) -> object | None:
        row = next(
            (item for item in self.participant_sessions if item.participant.role == role),
            None,
        )
        return row.session if row is not None else None



class RunResourceAcquirer:
    """Acquires participants in dependency order; rolls back in exact reverse order."""

    def __init__(self, binder: ExperimentComponentBindingPort, lifecycle: ParticipantSessionLifecyclePort) -> None:
        self._binder = binder
        self._lifecycle = lifecycle

    @staticmethod
    def open_context(spec: ExperimentSpec, identity: RunIdentity) -> ExecutionContext:
        return ExecutionContext(identity.run_id, identity.trace_id, "run-open", study_id=spec.study_id)

    def acquire(self, spec: ExperimentSpec, identity: RunIdentity) -> OpenRunResources:
        context = self.open_context(spec, identity)
        rows: list[OperationResult[JsonValue]] = []
        bound: BoundParticipants | None = None
        sessions: list[ParticipantSessionBinding] = []
        try:
            bound = self._binder.bind(spec, context)
            if bound is None:
                raise RuntimeError("participant binder returned no bound participants")
            rows.extend(bound.operation_results)
            for participant in bound.participants:
                binding, operation = self._lifecycle.open_participant(participant, context, identity.session_id)
                sessions.append(binding)
                rows.append(operation)
        except BaseException as exc:
            self._rollback_partial(bound, tuple(sessions), context, identity, exc)
            raise
        return self._project(bound, tuple(sessions), context, tuple(rows))

    @staticmethod
    def _project(bound, sessions, context, rows) -> OpenRunResources:
        return OpenRunResources(bound, context, rows, sessions)

    def rollback(self, resources: OpenRunResources, *, context: ExecutionContext, identity: RunIdentity, primary: BaseException) -> None:
        self._rollback_partial(resources.bound, resources.participant_sessions, context, identity, primary)

    def _rollback_partial(self, bound, sessions, context, identity, primary) -> None:
        del bound
        rows = [
            self._lifecycle.close_participant(binding, context, identity.session_id)
            for binding in reversed(sessions)
        ]
        attach_cleanup_note(primary, RunCleanupReport(tuple(rows)))


__all__ = ["OpenRunResources", "RunResourceAcquirer"]
