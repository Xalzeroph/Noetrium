"""Default decision-cycle RuntimeProgram.

This preset replaces the hard-coded DecisionCycleCoordinator transaction.
Participant binding, participant opening, trial execution, reverse cleanup and
finalization are explicit Runtime Machine transitions. Downstream research may
replace the Program without replacing the host or kernel.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.capabilities.participant.core.api import (
    BoundParticipants,
    ParticipantSessionBinding,
)
from noetrium_platform.capabilities.participant.core.api.runtime_ports import (
    ParticipantSessionLifecyclePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    OperationResult,
    OperationStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.decision.cycle_identity import (
    DecisionCycleIdentity,
)
from noetrium_platform.research.execution.decision.cycle_result import (
    DecisionCycleResult,
)
from noetrium_platform.research.execution.machines import (
    ProgramNodeRequest,
    ProgramNodeResult,
    RuntimeConcern,
    ResearchHostOperation,
    RuntimeProgramBuilder,
    ResearchProgramHost,
)
from noetrium_platform.research.execution.workflow.api import TrialCycleExecution
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentComponentBindingPort,
    ExperimentSpec,
    ExperimentTrialCycleExecutorPort,
)
from noetrium_platform.research.experimentation.run.lifecycle.api import (
    RunCleanupFailure,
    RunCleanupReport,
    attach_cleanup_note,
)


DECISION_CYCLE_RUNTIME_PROGRAM = (
    RuntimeProgramBuilder.create(
        program_id="runtime.decision-cycle.default",
        version="1",
        state_schema="runtime.decision-cycle.state.v1",
        entrypoint="bind",
    )
    .semantic(
        "bind",
        RuntimeConcern.CONTEXT,
        "runtime.decision-cycle.bind",
        next_node="open",
    )
    .semantic(
        "open",
        RuntimeConcern.LOGICAL_SCHEDULING,
        "runtime.decision-cycle.open-next",
        next_node="open",
    )
    .semantic(
        "execute",
        RuntimeConcern.TURN,
        "runtime.decision-cycle.execute",
        next_node="close",
    )
    .semantic(
        "close",
        RuntimeConcern.RECOVERY,
        "runtime.decision-cycle.close-next",
        next_node="close",
    )
    .semantic(
        "finalize",
        RuntimeConcern.EVENT,
        "runtime.decision-cycle.finalize",
    )
    .build()
)


@dataclass(slots=True)
class _CycleFrame:
    spec: ExperimentSpec
    identity: DecisionCycleIdentity
    binder: ExperimentComponentBindingPort
    lifecycle: ParticipantSessionLifecyclePort
    trial: ExperimentTrialCycleExecutorPort
    task: object
    input_kind: str
    input_payload: object
    context: ExecutionContext
    operations: list[OperationResult[JsonValue]] = field(default_factory=list)
    bound: BoundParticipants | None = None
    participant_sessions: list[ParticipantSessionBinding] = field(default_factory=list)
    execution: TrialCycleExecution | None = None
    primary_error: BaseException | None = None
    cleanup_rows: list[OperationResult[JsonValue]] = field(default_factory=list)

    @property
    def cleanup_report(self) -> RunCleanupReport:
        return RunCleanupReport(tuple(self.cleanup_rows))


def identity_context(
    identity: DecisionCycleIdentity,
    spec: ExperimentSpec,
) -> ExecutionContext:
    return ExecutionContext(
        run_id=identity.run_id,
        trace_id=identity.trace_id,
        span_id=identity.decision_cycle_id,
        study_id=spec.study_id,
        task_id=identity.task_id,
        decision_cycle_id=identity.decision_cycle_id,
    )


def _component_ref(component) -> dict[str, str]:
    return {
        "component_id": component.component_id,
        "implementation_id": component.implementation_id,
        "implementation_version": component.implementation_version,
        "schema_version": component.schema_version,
        "generation_id": component.generation_id,
    }


def _frame(binding: object) -> _CycleFrame:
    if not isinstance(binding, _CycleFrame):
        raise TypeError("decision-cycle RuntimeProgram binding is invalid")
    return binding


def _bind(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    frame = _frame(binding)
    try:
        bound = frame.binder.bind(frame.spec, frame.context)
        if bound is None:
            raise RuntimeError("decision cycle participant binder returned no participants")
        frame.bound = bound
        frame.operations.extend(bound.operation_results)
    except BaseException as exc:
        frame.primary_error = exc
        return ProgramNodeResult(
            value={"bound": False},
            state_update={
                "outcome": "failed",
                "failure_digest": canonical_digest({
                    "type": type(exc).__name__,
                    "message": str(exc),
                }),
            },
            next_node="finalize",
            events=({"type": "decision_cycle_bind_failed"},),
        )
    participant_ids = tuple(_component_ref(row.component) for row in bound.participants)
    return ProgramNodeResult(
        value={"participant_count": len(participant_ids)},
        state_update={
            "participant_ids": participant_ids,
            "open_cursor": 0,
            "opened_count": 0,
            "close_cursor": -1,
            "outcome": "running",
        },
        events=({
            "type": "decision_cycle_participants_bound",
            "participant_ids": participant_ids,
        },),
    )


def _open_next(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    frame = _frame(binding)
    if frame.bound is None:
        raise RuntimeError("decision cycle open requires bound participants")
    cursor = request.data.get("open_cursor", 0)
    if type(cursor) is not int or cursor < 0:
        raise ValueError("decision cycle open cursor is invalid")
    participants = frame.bound.participants
    if cursor >= len(participants):
        return ProgramNodeResult(
            value={"opened_count": len(frame.participant_sessions)},
            state_update={
                "opened_count": len(frame.participant_sessions),
                "close_cursor": len(frame.participant_sessions) - 1,
            },
            next_node="execute",
            events=({"type": "decision_cycle_participants_ready"},),
        )

    participant = participants[cursor]
    try:
        session, operation = frame.lifecycle.open_participant(
            participant,
            frame.context,
            frame.identity.session_id,
        )
        frame.participant_sessions.append(session)
        frame.operations.append(operation)
    except BaseException as exc:
        frame.primary_error = exc
        return ProgramNodeResult(
            value={
                "opened_count": len(frame.participant_sessions),
                "failed_participant": _component_ref(participant.component),
            },
            state_update={
                "outcome": "failed",
                "opened_count": len(frame.participant_sessions),
                "close_cursor": len(frame.participant_sessions) - 1,
                "failure_digest": canonical_digest({
                    "type": type(exc).__name__,
                    "message": str(exc),
                }),
            },
            next_node="close" if frame.participant_sessions else "finalize",
            events=({
                "type": "decision_cycle_participant_open_failed",
                "participant_id": _component_ref(participant.component),
            },),
        )

    return ProgramNodeResult(
        value={
            "participant_id": _component_ref(participant.component),
            "open_cursor": cursor + 1,
        },
        state_update={
            "open_cursor": cursor + 1,
            "opened_count": len(frame.participant_sessions),
        },
        next_node="open",
        events=({
            "type": "decision_cycle_participant_opened",
            "participant_id": _component_ref(participant.component),
        },),
    )


def _execute(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    frame = _frame(binding)
    if frame.bound is None:
        raise RuntimeError("decision cycle execution requires bound participants")
    try:
        result = frame.trial.execute(
            bound=frame.bound,
            participant_sessions=tuple(frame.participant_sessions),
            context=frame.context,
            task=frame.task,
            input_kind=frame.input_kind,
            input_payload=frame.input_payload,
        )
        if not isinstance(result, TrialCycleExecution):
            raise TypeError("trial executor returned invalid TrialCycleExecution")
        frame.execution = result
        frame.operations.extend(result.operation_results)
        frame.context = result.final_context
    except BaseException as exc:
        frame.primary_error = exc
        return ProgramNodeResult(
            value={"executed": False},
            state_update={
                "outcome": "failed",
                "close_cursor": len(frame.participant_sessions) - 1,
                "failure_digest": canonical_digest({
                    "type": type(exc).__name__,
                    "message": str(exc),
                }),
            },
            next_node="close" if frame.participant_sessions else "finalize",
            events=({"type": "decision_cycle_trial_failed"},),
        )

    return ProgramNodeResult(
        value={"executed": True},
        state_update={
            "outcome": "executed",
            "close_cursor": len(frame.participant_sessions) - 1,
            "trial_result_digest": canonical_digest({
                "context_text": result.context_text,
                "primary_result": result.primary_result,
                "final_context": result.final_context,
            }),
        },
        next_node="close" if frame.participant_sessions else "finalize",
        events=({"type": "decision_cycle_trial_completed"},),
    )


def _close_next(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    frame = _frame(binding)
    cursor = request.data.get("close_cursor", len(frame.participant_sessions) - 1)
    if type(cursor) is not int:
        raise TypeError("decision cycle close cursor must be int")
    if cursor < 0:
        return ProgramNodeResult(
            value={"cleanup_count": len(frame.cleanup_rows)},
            next_node="finalize",
            events=({"type": "decision_cycle_cleanup_completed"},),
        )
    if cursor >= len(frame.participant_sessions):
        raise ValueError("decision cycle close cursor exceeds opened participants")

    participant = frame.participant_sessions[cursor]
    try:
        operation = frame.lifecycle.close_participant(
            participant,
            frame.context,
            frame.identity.session_id,
        )
        frame.cleanup_rows.append(operation)
        frame.operations.append(operation)
        failed = False
    except BaseException as exc:
        # Participant lifecycle ports normally return typed failure Operations.
        # A provider exception is retained as a cleanup failure and cleanup continues.
        operation_id = (
            f"decision-cycle:{frame.identity.decision_cycle_id}:close:{cursor}"
        )
        descriptor = {
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        frame.cleanup_rows.append(
            OperationResult(
                operation_id=operation_id,
                invocation_id=f"{operation_id}:provider-exception",
                status=OperationStatus.FAILED,
                failure_id=canonical_digest(descriptor),
                diagnostics=descriptor,
                cause=exc,
            )
        )
        frame.operations.append(frame.cleanup_rows[-1])
        failed = True

    next_cursor = cursor - 1
    return ProgramNodeResult(
        value={
            "closed_participant": _component_ref(participant.participant.component),
            "cleanup_failed": failed,
        },
        state_update={"close_cursor": next_cursor},
        next_node="close" if next_cursor >= 0 else "finalize",
        events=({
            "type": "decision_cycle_participant_closed",
            "participant_id": _component_ref(participant.participant.component),
            "failed": failed,
        },),
    )


def _finalize(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    frame = _frame(binding)
    cleanup = frame.cleanup_report
    if frame.primary_error is not None:
        status = MachineStatus.FAILED
        outcome = "failed"
    elif cleanup.failures:
        status = MachineStatus.FAILED
        outcome = "cleanup_failed"
    elif frame.execution is None:
        status = MachineStatus.FAILED
        outcome = "missing_result"
    else:
        status = MachineStatus.COMPLETED
        outcome = "completed"

    return ProgramNodeResult(
        value={"outcome": outcome},
        state_update={
            "outcome": outcome,
            "cleanup_failures": tuple(
                {
                    "operation_id": row.operation_id,
                    "failure_id": row.failure_id,
                    "diagnostics": row.diagnostics,
                }
                for row in cleanup.failures
            ),
        },
        status=status,
        events=({
            "type": "decision_cycle_finalized",
            "outcome": outcome,
            "cleanup_failure_count": len(cleanup.failures),
        },),
    )


_DECISION_CYCLE_OPERATIONS = (
    ResearchHostOperation(
            "runtime.decision-cycle.bind",
            _bind,
            canonical_digest({
                "operation": "runtime.decision-cycle.bind",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.decision-cycle.open-next",
            _open_next,
            canonical_digest({
                "operation": "runtime.decision-cycle.open-next",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.decision-cycle.execute",
            _execute,
            canonical_digest({
                "operation": "runtime.decision-cycle.execute",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.decision-cycle.close-next",
            _close_next,
            canonical_digest({
                "operation": "runtime.decision-cycle.close-next",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.decision-cycle.finalize",
            _finalize,
            canonical_digest({
                "operation": "runtime.decision-cycle.finalize",
                "implementation_revision": 1,
            }),
        ),
)


class DecisionCycleRuntime:
    """Default decision-cycle preset over the universal ResearchProgramHost."""

    def __init__(
        self,
        binder: ExperimentComponentBindingPort,
        lifecycle: ParticipantSessionLifecyclePort,
        trial: ExperimentTrialCycleExecutorPort,
        *,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        self._binder = binder
        self._lifecycle = lifecycle
        self._trial = trial
        self._host = ResearchProgramHost(
            host_id="decision-cycle",
            program=DECISION_CYCLE_RUNTIME_PROGRAM,
            operations=_DECISION_CYCLE_OPERATIONS,
            journal=journal if journal is not None else InMemoryMachineJournal(),
            snapshot_store=snapshot_store,
            max_steps=4096,
            dependency_identity={
                "preset": "decision-cycle",
                "version": 1,
            },
        )

    def run(
        self,
        spec: ExperimentSpec,
        identity: DecisionCycleIdentity,
        *,
        task: object,
        input_kind: str,
        input_payload: object,
    ) -> DecisionCycleResult:
        frame = _CycleFrame(
            spec=spec,
            identity=identity,
            binder=self._binder,
            lifecycle=self._lifecycle,
            trial=self._trial,
            task=task,
            input_kind=input_kind,
            input_payload=input_payload,
            context=identity_context(identity, spec),
        )
        machine_id = (
            f"runtime-cycle:{identity.run_id}:{identity.decision_cycle_id}:"
            f"{DECISION_CYCLE_RUNTIME_PROGRAM.program_digest[:16]}"
        )
        execution = self._host.execute(
            machine_id=machine_id,
            instance_identity={
                "run_id": identity.run_id,
                "session_id": identity.session_id,
                "decision_cycle_id": identity.decision_cycle_id,
                "task_id": identity.task_id,
                "experiment_spec_digest": spec.identity_digest(),
            },
            binding=frame,
            initial_data={
                "run_id": identity.run_id,
                "session_id": identity.session_id,
                "decision_cycle_id": identity.decision_cycle_id,
                "task_id": identity.task_id,
                "experiment_spec_digest": spec.identity_digest(),
                "outcome": "new",
            },
            payload={"source": "decision-cycle-runtime"},
            command_id_prefix=machine_id,
        )

        cleanup = frame.cleanup_report
        if frame.primary_error is not None:
            attach_cleanup_note(frame.primary_error, cleanup)
            raise frame.primary_error
        if cleanup.failures:
            raise RunCleanupFailure(
                cleanup,
                trial_completed=frame.execution is not None,
            )
        if execution.status is not MachineStatus.COMPLETED or frame.execution is None:
            raise RuntimeError(
                "decision-cycle RuntimeProgram failed without a provider exception"
            )
        return DecisionCycleResult(
            identity.run_id,
            identity.decision_cycle_id,
            frame.execution.context_text,
            frame.execution.primary_result,
            tuple(frame.operations),
            identity,
        )


__all__ = [
    "DECISION_CYCLE_RUNTIME_PROGRAM",
    "DecisionCycleRuntime",
    "identity_context",
]
