"""Default long-lived run RuntimeProgram.

The run Runtime owns paper-variable execution semantics around participant
lifetime: binding, opening, optional checkpoint restoration, active-run
suspension, reverse cleanup and finalization. It does not own Run truth; the
separate RunMachine remains the authoritative scientific run lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from noetrium_platform.capabilities.participant.core.api import (
    BoundParticipants,
    ParticipantSessionBinding,
)
from noetrium_platform.capabilities.participant.core.api.runtime_ports import (
    ParticipantSessionLifecyclePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
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
from noetrium_platform.research.execution.machines import (
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchMachineSession,
    RuntimeConcern,
    ResearchHostOperation,
    RuntimeProgramBuilder,
    ResearchProgramHost,
)
from noetrium_platform.research.experimentation.checkpoint.api import (
    RunCheckpointCoordinatorPort,
)
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentComponentBindingPort,
    ExperimentSpec,
    ExperimentTrialCycleExecutorPort,
)
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.lifecycle.api import (
    RunCleanupFailure,
    RunCleanupReport,
    RunSessionPort,
)
from noetrium_platform.research.experimentation.run.lifecycle.runtime.session import (
    RunSession,
)
from .cycle import RunCycleExecutor
from .decision_runtime import identity_context
from .program import RunMachineBinding, RunMachineSession, RunPhase


RUN_RUNTIME_PROGRAM = (
    RuntimeProgramBuilder.create(
        program_id="runtime.run-lifetime.default",
        version="1",
        state_schema="runtime.run-lifetime.state.v1",
        entrypoint="bind",
    )
    .semantic(
        "bind",
        RuntimeConcern.CONTEXT,
        "runtime.run-lifetime.bind",
        next_node="open",
    )
    .semantic(
        "open",
        RuntimeConcern.LOGICAL_SCHEDULING,
        "runtime.run-lifetime.open-next",
        next_node="open",
    )
    .semantic(
        "restore",
        RuntimeConcern.RECOVERY,
        "runtime.run-lifetime.restore",
        next_node="activate",
    )
    .semantic(
        "activate",
        RuntimeConcern.EVENT,
        "runtime.run-lifetime.activate",
        next_node="active",
    )
    .semantic(
        "active",
        RuntimeConcern.LOGICAL_SCHEDULING,
        "runtime.run-lifetime.wait-active",
        next_node="close",
    )
    .semantic(
        "close",
        RuntimeConcern.RECOVERY,
        "runtime.run-lifetime.close-next",
        next_node="close",
    )
    .semantic(
        "finalize",
        RuntimeConcern.EVENT,
        "runtime.run-lifetime.finalize",
    )
    .build()
)


def _component_ref(component) -> dict[str, str]:
    return {
        "component_id": component.component_id,
        "implementation_id": component.implementation_id,
        "implementation_version": component.implementation_version,
        "schema_version": component.schema_version,
        "generation_id": component.generation_id,
    }


def _failure_receipt(
    *,
    operation_id: str,
    operation_type: str,
    exc: BaseException,
) -> OperationResult[JsonValue]:
    descriptor = {
        "operation_type": operation_type,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    return OperationResult(
        operation_id=operation_id,
        invocation_id=f"{operation_id}:provider-exception",
        status=OperationStatus.FAILED,
        failure_id=canonical_digest(descriptor),
        diagnostics=descriptor,
        cause=exc,
    )


@dataclass(slots=True)
class _RunRuntimeFrame:
    spec: ExperimentSpec
    identity: RunIdentity
    binder: ExperimentComponentBindingPort
    lifecycle: ParticipantSessionLifecyclePort
    trial: ExperimentTrialCycleExecutorPort
    checkpoint: RunCheckpointCoordinatorPort | None
    machine_journal: MachineJournalPort
    machine_snapshot_store: MachineSnapshotStorePort | None
    restore_checkpoint_id: str | None
    restore_cycle_identity: DecisionCycleIdentity | None
    context: ExecutionContext
    operations: list[OperationResult[JsonValue]] = field(default_factory=list)
    bound: BoundParticipants | None = None
    participant_sessions: list[ParticipantSessionBinding] = field(default_factory=list)
    cleanup_rows: list[OperationResult[JsonValue]] = field(default_factory=list)
    run_machine: RunMachineSession | None = None
    primary_error: BaseException | None = None

    @property
    def cleanup_report(self) -> RunCleanupReport:
        return RunCleanupReport(tuple(self.cleanup_rows))


def _frame(binding: object) -> _RunRuntimeFrame:
    if not isinstance(binding, _RunRuntimeFrame):
        raise TypeError("run RuntimeProgram binding is invalid")
    return binding


def _open_context(spec: ExperimentSpec, identity: RunIdentity) -> ExecutionContext:
    return ExecutionContext(
        identity.run_id,
        identity.trace_id,
        "run-open",
        study_id=spec.study_id,
    )


def _bind(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    frame = _frame(binding)
    try:
        bound = frame.binder.bind(frame.spec, frame.context)
        if bound is None:
            raise RuntimeError("run participant binder returned no bound participants")
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
            events=({"type": "run_runtime_bind_failed"},),
        )
    participant_ids = tuple(
        _component_ref(row.component)
        for row in bound.participants
    )
    return ProgramNodeResult(
        value={"participant_count": len(participant_ids)},
        state_update={
            "participant_ids": participant_ids,
            "open_cursor": 0,
            "close_cursor": -1,
            "opened_count": 0,
            "outcome": "opening",
        },
        events=({
            "type": "run_runtime_participants_bound",
            "participant_ids": participant_ids,
        },),
    )


def _open_next(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    frame = _frame(binding)
    if frame.bound is None:
        raise RuntimeError("run RuntimeProgram open requires bound participants")
    cursor = request.data.get("open_cursor", 0)
    if type(cursor) is not int or cursor < 0:
        raise ValueError("run RuntimeProgram open cursor is invalid")
    participants = frame.bound.participants
    if cursor >= len(participants):
        return ProgramNodeResult(
            value={"opened_count": len(frame.participant_sessions)},
            state_update={
                "opened_count": len(frame.participant_sessions),
                "close_cursor": len(frame.participant_sessions) - 1,
            },
            next_node="restore",
            events=({"type": "run_runtime_participants_ready"},),
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
                "type": "run_runtime_participant_open_failed",
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
            "type": "run_runtime_participant_opened",
            "participant_id": _component_ref(participant.component),
        },),
    )


def _require_restore_identity(
    frame: _RunRuntimeFrame,
) -> DecisionCycleIdentity:
    identity = frame.restore_cycle_identity
    if identity is None:
        raise ValueError(
            "restore_cycle_identity is required for exact checkpoint recovery"
        )
    expected = (
        frame.identity.run_id,
        frame.identity.session_id,
        frame.identity.trace_id,
    )
    actual = (
        identity.run_id,
        identity.session_id,
        identity.trace_id,
    )
    if actual != expected:
        raise ValueError(
            "restore cycle identity does not belong to requested run identity"
        )
    return identity


def _restore(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    frame = _frame(binding)
    checkpoint_id = frame.restore_checkpoint_id
    if checkpoint_id is None:
        return ProgramNodeResult(
            value={"restored": False},
            state_update={"restored": False},
            next_node="activate",
            events=({"type": "run_runtime_restore_skipped"},),
        )
    if frame.checkpoint is None:
        frame.primary_error = RuntimeError(
            "restore requested but run Runtime has no checkpoint store"
        )
        return ProgramNodeResult(
            value={"restored": False},
            state_update={
                "outcome": "failed",
                "failure_digest": canonical_digest({
                    "type": type(frame.primary_error).__name__,
                    "message": str(frame.primary_error),
                }),
            },
            next_node="close" if frame.participant_sessions else "finalize",
            events=({"type": "run_runtime_restore_failed"},),
        )
    if frame.bound is None:
        raise RuntimeError("run restore requires bound participants")

    try:
        cycle_identity = _require_restore_identity(frame)
        restore_context = identity_context(cycle_identity, frame.spec)
        restored = frame.checkpoint.restore(
            checkpoint_id,
            spec=frame.spec,
            bound=frame.bound,
            participant_sessions=tuple(frame.participant_sessions),
            context=restore_context,
            cycle_identity=cycle_identity,
        )
        frame.operations.extend(restored.operation_results)
        generations = tuple(sorted(
            (ref.role, ref.generation)
            for ref in restored.bundle.manifest.participant_snapshots
            if ref.generation is not None
        ))
        frame.context = replace(
            restore_context,
            checkpoint_id=checkpoint_id,
            participant_generations=generations,
        )
    except BaseException as exc:
        frame.primary_error = exc
        return ProgramNodeResult(
            value={"restored": False},
            state_update={
                "outcome": "failed",
                "failure_digest": canonical_digest({
                    "type": type(exc).__name__,
                    "message": str(exc),
                }),
            },
            next_node="close" if frame.participant_sessions else "finalize",
            events=({"type": "run_runtime_restore_failed"},),
        )

    return ProgramNodeResult(
        value={"restored": True, "checkpoint_id": checkpoint_id},
        state_update={
            "restored": True,
            "checkpoint_id": checkpoint_id,
            "participant_generations": frame.context.participant_generations,
        },
        next_node="activate",
        events=({
            "type": "run_runtime_restored",
            "checkpoint_id": checkpoint_id,
        },),
    )


def _activate(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    frame = _frame(binding)
    if frame.bound is None:
        raise RuntimeError("run activation requires bound participants")
    run_machine = RunMachineSession.open(
        binding=RunMachineBinding(
            identity=frame.identity,
            experiment_spec_digest=frame.spec.identity_digest(),
        ),
        initial_context=frame.context,
        journal=frame.machine_journal,
        snapshot_store=frame.machine_snapshot_store,
    )
    if run_machine.phase is RunPhase.CREATED:
        run_machine.control_running(
            operation_id=canonical_digest({
                "run_id": frame.identity.run_id,
                "runtime_program_digest": RUN_RUNTIME_PROGRAM.program_digest,
                "event": "lifetime-active",
            }),
        )
    elif run_machine.phase is not RunPhase.RUNNING:
        raise RuntimeError(
            "run Runtime cannot activate RunMachine from "
            f"phase={run_machine.phase.value}"
        )
    frame.run_machine = run_machine
    return ProgramNodeResult(
        value={
            "run_machine_revision": run_machine.control_revision,
        },
        state_update={
            "outcome": "active",
            "run_machine_revision": run_machine.control_revision,
            "close_cursor": len(frame.participant_sessions) - 1,
        },
        next_node="active",
        events=({
            "type": "run_runtime_activated",
            "run_machine_revision": run_machine.control_revision,
        },),
    )


def _wait_active(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    frame = _frame(binding)
    if frame.run_machine is None:
        raise RuntimeError("active run Runtime requires RunMachine")
    return ProgramNodeResult(
        value={"active": True},
        state_update={"outcome": "active"},
        next_node="close",
        status=MachineStatus.WAITING,
        wait_reason="run-session-active",
        events=({"type": "run_runtime_waiting"},),
    )


def _close_next(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    frame = _frame(binding)
    cursor = request.data.get(
        "close_cursor",
        len(frame.participant_sessions) - 1,
    )
    if type(cursor) is not int:
        raise TypeError("run Runtime close cursor must be int")
    if cursor < 0:
        return ProgramNodeResult(
            value={"cleanup_count": len(frame.cleanup_rows)},
            next_node="finalize",
            events=({"type": "run_runtime_cleanup_completed"},),
        )
    if cursor >= len(frame.participant_sessions):
        raise ValueError("run Runtime close cursor exceeds opened participants")

    participant = frame.participant_sessions[cursor]
    try:
        operation = frame.lifecycle.close_participant(
            participant,
            frame.context,
            frame.identity.session_id,
        )
    except BaseException as exc:
        operation = _failure_receipt(
            operation_id=(
                f"run-runtime:{frame.identity.run_id}:close:{cursor}"
            ),
            operation_type="participant.close",
            exc=exc,
        )
    frame.cleanup_rows.append(operation)
    frame.operations.append(operation)
    next_cursor = cursor - 1
    return ProgramNodeResult(
        value={
            "participant_id": _component_ref(
                participant.participant.component
            ),
            "cleanup_failed": operation.status is not OperationStatus.SUCCEEDED,
        },
        state_update={"close_cursor": next_cursor},
        next_node="close" if next_cursor >= 0 else "finalize",
        events=({
            "type": "run_runtime_participant_closed",
            "participant_id": _component_ref(
                participant.participant.component
            ),
            "failed": operation.status is not OperationStatus.SUCCEEDED,
        },),
    )


def _finalize(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    frame = _frame(binding)
    cleanup = frame.cleanup_report
    cleanup_digest = canonical_digest(cleanup.results)

    if frame.run_machine is not None and not frame.run_machine.closed:
        frame.run_machine.close(
            cleanup_succeeded=not cleanup.failures,
            cleanup_digest=cleanup_digest,
        )

    if frame.primary_error is not None:
        outcome = "failed"
        status = MachineStatus.FAILED
    elif cleanup.failures:
        outcome = "cleanup_failed"
        status = MachineStatus.FAILED
    else:
        outcome = "closed"
        status = MachineStatus.COMPLETED

    return ProgramNodeResult(
        value={"outcome": outcome},
        state_update={
            "outcome": outcome,
            "cleanup_digest": cleanup_digest,
            "cleanup_failure_ids": tuple(
                row.failure_id for row in cleanup.failures
            ),
        },
        status=status,
        events=({
            "type": "run_runtime_finalized",
            "outcome": outcome,
            "cleanup_failure_count": len(cleanup.failures),
        },),
    )


_RUN_RUNTIME_OPERATIONS = (
    ResearchHostOperation(
            "runtime.run-lifetime.bind",
            _bind,
            canonical_digest({
                "operation": "runtime.run-lifetime.bind",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.run-lifetime.open-next",
            _open_next,
            canonical_digest({
                "operation": "runtime.run-lifetime.open-next",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.run-lifetime.restore",
            _restore,
            canonical_digest({
                "operation": "runtime.run-lifetime.restore",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.run-lifetime.activate",
            _activate,
            canonical_digest({
                "operation": "runtime.run-lifetime.activate",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.run-lifetime.wait-active",
            _wait_active,
            canonical_digest({
                "operation": "runtime.run-lifetime.wait-active",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.run-lifetime.close-next",
            _close_next,
            canonical_digest({
                "operation": "runtime.run-lifetime.close-next",
                "implementation_revision": 1,
            }),
        ),
    ResearchHostOperation(
            "runtime.run-lifetime.finalize",
            _finalize,
            canonical_digest({
                "operation": "runtime.run-lifetime.finalize",
                "implementation_revision": 1,
            }),
        ),
)


class _RunRuntimeLifetime:
    """Process-local driver for the already authoritative Runtime Machine."""

    def __init__(
        self,
        session: ResearchMachineSession,
        frame: _RunRuntimeFrame,
    ) -> None:
        self._session = session
        self._frame = frame
        self._closed = False

    def close(
        self,
        context: ExecutionContext,
        *,
        trial_completed: bool,
    ) -> RunCleanupReport:
        if self._closed:
            return RunCleanupReport(())
        self._closed = True
        self._frame.context = context
        if self._session.status is not MachineStatus.WAITING:
            raise RuntimeError(
                "run Runtime Machine is not waiting at active lifetime boundary"
            )
        self._session.resume(
            command_id=f"{self._session.machine_id}:close:resume",
        )
        run = self._session.run_until_blocked(
            command_id_prefix=f"{self._session.machine_id}:close",
            payload={"source": "run-close"},
            max_steps=max(8, len(self._frame.participant_sessions) + 4),
        )
        self._session.checkpoint()
        cleanup = self._frame.cleanup_report
        if cleanup.failures:
            raise RunCleanupFailure(
                cleanup,
                trial_completed=trial_completed,
            )
        if run.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                "run Runtime Machine did not complete cleanup: "
                f"status={run.status.value}"
            )
        return cleanup


class RunRuntime:
    """Default run-lifetime preset over the universal ResearchProgramHost."""

    def __init__(
        self,
        binder: ExperimentComponentBindingPort,
        lifecycle: ParticipantSessionLifecyclePort,
        trial: ExperimentTrialCycleExecutorPort,
        checkpoint: RunCheckpointCoordinatorPort | None,
        *,
        machine_journal: MachineJournalPort,
        machine_snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        if not isinstance(machine_journal, MachineJournalPort):
            raise TypeError("RunRuntime requires MachineJournalPort")
        self._binder = binder
        self._lifecycle = lifecycle
        self._trial = trial
        self._checkpoint = checkpoint
        self._machine_journal = machine_journal
        self._machine_snapshot_store = machine_snapshot_store
        self._host = ResearchProgramHost(
            host_id="run-lifetime",
            program=RUN_RUNTIME_PROGRAM,
            operations=_RUN_RUNTIME_OPERATIONS,
            journal=machine_journal,
            snapshot_store=machine_snapshot_store,
            max_steps=4096,
            dependency_identity={
                "preset": "run-lifetime",
                "version": 1,
            },
        )

    def open(
        self,
        spec: ExperimentSpec,
        identity: RunIdentity,
        *,
        restore_checkpoint_id: str | None = None,
        restore_cycle_identity: DecisionCycleIdentity | None = None,
    ) -> RunSessionPort:
        if not isinstance(spec, ExperimentSpec):
            raise TypeError("RunRuntime.open requires ExperimentSpec")
        if not isinstance(identity, RunIdentity):
            raise TypeError("RunRuntime.open requires RunIdentity")

        frame = _RunRuntimeFrame(
            spec=spec,
            identity=identity,
            binder=self._binder,
            lifecycle=self._lifecycle,
            trial=self._trial,
            checkpoint=self._checkpoint,
            machine_journal=self._machine_journal,
            machine_snapshot_store=self._machine_snapshot_store,
            restore_checkpoint_id=restore_checkpoint_id,
            restore_cycle_identity=restore_cycle_identity,
            context=_open_context(spec, identity),
        )
        machine_id = (
            f"runtime-run:{identity.run_id}:"
            f"{RUN_RUNTIME_PROGRAM.program_digest[:16]}"
        )
        session = self._host.open_session(
            machine_id=machine_id,
            instance_identity={
                "run_id": identity.run_id,
                "session_id": identity.session_id,
                "experiment_spec_digest": spec.identity_digest(),
            },
            binding=frame,
        )
        if session.started:
            raise RuntimeError(
                "run Runtime Machine already exists; reopening an active run "
                "requires an explicit recovery policy"
            )
        session.start(
            {
                "run_id": identity.run_id,
                "session_id": identity.session_id,
                "experiment_spec_digest": spec.identity_digest(),
                "restore_requested": restore_checkpoint_id is not None,
                "outcome": "new",
            },
            command_id=f"{machine_id}:start",
        )
        run = session.run_until_blocked(
            command_id_prefix=f"{machine_id}:open",
            payload={"source": "run-open"},
            max_steps=4096,
        )
        session.checkpoint()

        cleanup = frame.cleanup_report
        if frame.primary_error is not None:
            if cleanup.results:
                try:
                    frame.primary_error.add_note(
                        "run Runtime cleanup after open failure: "
                        f"{len(cleanup.failures)} failures"
                    )
                except AttributeError:
                    pass
            raise frame.primary_error
        if cleanup.failures:
            raise RunCleanupFailure(cleanup, trial_completed=False)
        if run.status is not MachineStatus.WAITING:
            raise RuntimeError(
                "run Runtime did not reach active waiting boundary: "
                f"status={run.status.value}"
            )
        if frame.bound is None or frame.run_machine is None:
            raise RuntimeError(
                "run Runtime reached active state without bound resources"
            )

        cycle_executor = RunCycleExecutor(
            spec=spec,
            run_identity=identity,
            bound=frame.bound,
            trial=self._trial,
            checkpoint=self._checkpoint,
            participant_sessions=tuple(frame.participant_sessions),
        )
        return RunSession(
            spec=spec,
            identity=identity,
            cycle_executor=cycle_executor,
            lifetime=_RunRuntimeLifetime(session, frame),
            run_machine=frame.run_machine,
            open_operations=tuple(frame.operations),
            initial_context=frame.context,
        )


__all__ = [
    "RUN_RUNTIME_PROGRAM",
    "RunRuntime",
]
