"""Authoritative Run lifecycle as a programmable RUN Machine.

RunSession may materialize typed ExecutionContext values in-process, but all
scientific lifecycle facts (cycle boundaries, recovery state, checkpoint head,
completion count and closure) live in the Machine Journal.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    MachineCut,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.execution.machines import (
    MachineEvent,
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ProgramRule,
    ProgramRuleSet,
    ResearchMachineSession,
    ResearchProgramHost,
    ResearchProgram,
    RuleDispatchMode,
    RunConcern,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
)
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.lifecycle.api import (
    RunClosed,
    RunRecoveryRequired,
)


@dataclass(frozen=True, slots=True)
class RunMachineBinding:
    identity: RunIdentity
    experiment_spec_digest: str
    run_manifest_digest: str | None = None
    binding_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.identity, RunIdentity):
            raise TypeError("RunMachineBinding requires RunIdentity")
        experiment_digest = _text(
            self.experiment_spec_digest,
            "run machine experiment_spec_digest",
        )
        manifest_digest = self.run_manifest_digest
        if manifest_digest is not None:
            manifest_digest = _digest(
                manifest_digest,
                "run machine run_manifest_digest",
            )
            object.__setattr__(self, "run_manifest_digest", manifest_digest)
        expected = canonical_digest({
            "run_identity_digest": self.identity.digest(),
            "experiment_spec_digest": experiment_digest,
        })
        if self.binding_digest and self.binding_digest != expected:
            raise ValueError("RunMachineBinding digest mismatch")
        object.__setattr__(self, "experiment_spec_digest", experiment_digest)
        object.__setattr__(self, "binding_digest", expected)


class RunPhase(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    RECOVERY_REQUIRED = "recovery_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CLOSED = "closed"


def run_rule_set() -> ProgramRuleSet:
    return ProgramRuleSet(
        (
            ProgramRule("manifest-bound", "run.manifest_bound", "run.manifest_bound", priority=110, semantic=RunConcern.LIFECYCLE.value),
            ProgramRule("cycle-started", "run.cycle_started", "run.cycle_started", priority=100, semantic=RunConcern.CYCLE.value),
            ProgramRule("cycle-completed", "run.cycle_completed", "run.cycle_completed", priority=100, semantic=RunConcern.CYCLE.value),
            ProgramRule("cycle-failed", "run.cycle_failed", "run.cycle_failed", priority=100, semantic=RunConcern.RECOVERY.value),
            ProgramRule("restored", "run.restored", "run.restored", priority=100, semantic=RunConcern.RECOVERY.value),
            ProgramRule("control-prepare", "run.control.prepare", "run.control.prepare", priority=120, semantic=RunConcern.CONTROL.value),
            ProgramRule("control-resolve", "run.control.resolve", "run.control.resolve", priority=120, semantic=RunConcern.CONTROL.value),
            ProgramRule("control-running", "run.control.running", "run.control.running", priority=100, semantic=RunConcern.CONTROL.value),
            ProgramRule("control-stopped", "run.control.stopped", "run.control.stopped", priority=100, semantic=RunConcern.CONTROL.value),
            ProgramRule("control-recovery-required", "run.control.recovery_required", "run.control.recovery_required", priority=100, semantic=RunConcern.RECOVERY.value),
            ProgramRule("control-completed", "run.control.completed", "run.control.completed", priority=100, semantic=RunConcern.FINALIZATION.value),
            ProgramRule("control-failed", "run.control.failed", "run.control.failed", priority=100, semantic=RunConcern.FINALIZATION.value),
            ProgramRule("closed", "run.closed", "run.closed", priority=100, semantic=RunConcern.FINALIZATION.value),
        ),
        mode=RuleDispatchMode.FIRST,
        unhandled=UnhandledEventPolicy.ERROR,
    )


def compile_run_program() -> ResearchProgram:
    return compile_rule_program(
        program_id="research.run.lifecycle",
        kind=MachineKind.RUN,
        version="2",
        state_schema="research.run.lifecycle.state.v2",
        rules=run_rule_set(),
    )


RUN_PROGRAM = compile_run_program()


def run_initial_data(
    binding: RunMachineBinding,
    context: ExecutionContext,
) -> dict[str, object]:
    if not isinstance(binding, RunMachineBinding):
        raise TypeError("run initial data requires RunMachineBinding")
    if not isinstance(context, ExecutionContext):
        raise TypeError("run initial data requires ExecutionContext")
    if context.run_id != binding.identity.run_id:
        raise ValueError("run initial context belongs to another run")
    return {
        "phase": RunPhase.CREATED.value,
        "run_identity_digest": binding.identity.digest(),
        "experiment_spec_digest": binding.experiment_spec_digest,
        "run_manifest_digest": binding.run_manifest_digest,
        "run_binding_digest": binding.binding_digest,
        "completed_cycles": 0,
        "active_cycle_id": None,
        "latest_checkpoint_id": context.checkpoint_id,
        "latest_checkpoint_manifest_digest": None,
        "last_context_digest": canonical_digest(context),
        "last_result_digest": None,
        "failure_digest": None,
        "pending_control_operation": None,
        "last_control_action": None,
        "last_control_operation_id": None,
        "last_control_record_kind": None,
        "restored": context.checkpoint_id is not None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = dict(request.data)
    phase = value.get("phase")
    if phase not in {item.value for item in RunPhase}:
        raise ValueError("run machine phase is invalid")
    return value


def _payload(request: ProgramNodeRequest) -> dict[str, object]:
    if not isinstance(request.payload, Mapping):
        raise TypeError("run event payload must be an object")
    return dict(request.payload)


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _digest(value: object, field: str) -> str:
    text = _text(value, field)
    require_sha256(text, field)
    return text


def run_operation_handlers() -> ProgramHandlerRegistry:
    operations = ProgramHandlerRegistry()

    def manifest_bound(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        manifest_digest = _digest(
            payload.get("run_manifest_digest"),
            "run manifest digest",
        )
        existing = data.get("run_manifest_digest")
        if existing is not None and existing != manifest_digest:
            raise ValueError("Run Machine launch manifest identity drifted")
        return ProgramNodeResult(
            value={"run_manifest_digest": manifest_digest},
            state_update={"run_manifest_digest": manifest_digest},
            events=({
                "type": "run_manifest_bound",
                "run_manifest_digest": manifest_digest,
            },),
        )

    def cycle_started(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        phase = RunPhase(data["phase"])
        if phase is RunPhase.CLOSED:
            raise RunClosed("research run is closed")
        if phase is RunPhase.RECOVERY_REQUIRED:
            raise RunRecoveryRequired("research run requires recovery")
        if phase is not RunPhase.RUNNING:
            raise RuntimeError(
                f"research run cannot start a cycle from phase={phase.value}"
            )
        if data.get("active_cycle_id") is not None:
            raise RuntimeError("research run already has an active cycle")
        cycle_id = _text(payload.get("cycle_id"), "run cycle_id")
        return ProgramNodeResult(
            value={"cycle_id": cycle_id},
            state_update={"active_cycle_id": cycle_id, "failure_digest": None},
            events=({"type": "run_cycle_started", "cycle_id": cycle_id},),
        )

    def cycle_completed(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        cycle_id = _text(payload.get("cycle_id"), "run cycle_id")
        if data["phase"] != RunPhase.RUNNING.value:
            raise RuntimeError("only active run can complete a cycle")
        if data.get("active_cycle_id") != cycle_id:
            raise RuntimeError("run cycle completion does not match active cycle")
        count = data.get("completed_cycles", 0)
        if type(count) is not int or count < 0:
            raise ValueError("run completed_cycles is invalid")
        result_digest = _digest(payload.get("result_digest"), "run result_digest")
        context_digest = _digest(payload.get("context_digest"), "run context_digest")
        checkpoint_id = payload.get("checkpoint_id")
        if checkpoint_id is not None:
            checkpoint_id = _text(checkpoint_id, "run checkpoint_id")
        return ProgramNodeResult(
            value={
                "cycle_id": cycle_id,
                "completed_cycles": count + 1,
                "checkpoint_id": checkpoint_id,
            },
            state_update={
                "completed_cycles": count + 1,
                "active_cycle_id": None,
                "latest_checkpoint_id": checkpoint_id or data.get("latest_checkpoint_id"),
                "last_context_digest": context_digest,
                "last_result_digest": result_digest,
                "failure_digest": None,
            },
            events=({
                "type": "run_cycle_completed",
                "cycle_id": cycle_id,
                "completed_cycles": count + 1,
                "checkpoint_id": checkpoint_id,
                "result_digest": result_digest,
            },),
        )

    def cycle_failed(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        cycle_id = _text(payload.get("cycle_id"), "run cycle_id")
        if data["phase"] == RunPhase.CLOSED.value:
            raise RunClosed("research run is closed")
        active = data.get("active_cycle_id")
        if active not in (None, cycle_id):
            raise RuntimeError("run failure does not match active cycle")
        failure_digest = _digest(payload.get("failure_digest"), "run failure_digest")
        return ProgramNodeResult(
            value={"cycle_id": cycle_id, "failure_digest": failure_digest},
            state_update={
                "phase": RunPhase.RECOVERY_REQUIRED.value,
                "active_cycle_id": None,
                "failure_digest": failure_digest,
            },
            events=({
                "type": "run_cycle_failed",
                "cycle_id": cycle_id,
                "failure_digest": failure_digest,
            },),
        )

    def restored(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        phase = RunPhase(data["phase"])
        if phase is RunPhase.CLOSED:
            raise RunClosed("closed run cannot be restored in place")
        if phase is not RunPhase.RECOVERY_REQUIRED:
            raise RuntimeError(
                f"research run can restore only from recovery_required, got {phase.value}"
            )
        checkpoint_id = _text(payload.get("checkpoint_id"), "run checkpoint_id")
        context_digest = _digest(payload.get("context_digest"), "run context_digest")
        return ProgramNodeResult(
            value={"checkpoint_id": checkpoint_id},
            state_update={
                "phase": RunPhase.RUNNING.value,
                "active_cycle_id": None,
                "latest_checkpoint_id": checkpoint_id,
                "last_context_digest": context_digest,
                "failure_digest": None,
                "restored": True,
            },
            events=({
                "type": "run_restored",
                "checkpoint_id": checkpoint_id,
                "context_digest": context_digest,
            },),
        )


    def control_prepare(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        operation_id = _digest(
            payload.get("operation_id"),
            "run control operation_id",
        )
        action = _text(payload.get("action"), "run control action")
        existing = data.get("pending_control_operation")
        if existing is not None:
            if not isinstance(existing, Mapping):
                raise TypeError("pending run control operation must be an object")
            if existing.get("operation_id") != operation_id:
                raise RuntimeError("another run control operation is already pending")
            return ProgramNodeResult(
                value={"operation_id": operation_id, "created": False},
                events=({
                    "type": "run_control_prepare_replayed",
                    "operation_id": operation_id,
                    "action": action,
                },),
            )
        phase = RunPhase(data["phase"])
        if phase is RunPhase.CLOSED:
            raise RunClosed("closed run cannot accept control operations")
        restore_checkpoint_id = payload.get("restore_checkpoint_id")
        if restore_checkpoint_id is not None:
            restore_checkpoint_id = _text(
                restore_checkpoint_id,
                "run control restore_checkpoint_id",
            )
        restore_checkpoint_manifest_digest = _optional_digest(
            payload.get("restore_checkpoint_manifest_digest"),
            "run control restore_checkpoint_manifest_digest",
        )
        restore_cycle_identity_digest = _optional_digest(
            payload.get("restore_cycle_identity_digest"),
            "run control restore_cycle_identity_digest",
        )
        pending = {
            "operation_id": operation_id,
            "action": action,
            "base_phase": phase.value,
            "base_revision": request.snapshot.revision,
            "base_latest_checkpoint_id": data.get("latest_checkpoint_id"),
            "base_checkpoint_manifest_digest": data.get("latest_checkpoint_manifest_digest"),
            "restore_checkpoint_id": restore_checkpoint_id,
            "restore_checkpoint_manifest_digest": restore_checkpoint_manifest_digest,
            "restore_cycle_identity_digest": restore_cycle_identity_digest,
        }
        return ProgramNodeResult(
            value={"operation_id": operation_id, "created": True},
            state_update={
                "phase": RunPhase.RECOVERY_REQUIRED.value,
                "pending_control_operation": pending,
                "last_control_action": action,
                "last_control_operation_id": operation_id,
                "last_control_record_kind": "prepared",
            },
            events=({
                "type": "run_control_prepared",
                "operation_id": operation_id,
                "action": action,
                "base_phase": phase.value,
            },),
        )

    def control_resolve(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        operation_id = _digest(
            payload.get("operation_id"),
            "run control operation_id",
        )
        pending = data.get("pending_control_operation")
        if not isinstance(pending, Mapping):
            raise RuntimeError("run control resolve requires a pending operation")
        if pending.get("operation_id") != operation_id:
            raise RuntimeError("run control resolve operation identity mismatch")
        target_phase_text = _text(
            payload.get("phase"),
            "run control resolved phase",
        )
        target_phase = RunPhase(target_phase_text)
        if target_phase is RunPhase.CLOSED:
            raise ValueError("run control resolve cannot directly close the run")
        checkpoint_id = payload.get("checkpoint_id")
        if checkpoint_id is not None:
            checkpoint_id = _text(
                checkpoint_id,
                "run control checkpoint_id",
            )
        checkpoint_manifest_digest = _optional_digest(
            payload.get("checkpoint_manifest_digest"),
            "run control checkpoint_manifest_digest",
        )
        if (checkpoint_id is None) != (checkpoint_manifest_digest is None):
            raise ValueError("resolved run control checkpoint identity must be complete")
        update: dict[str, object] = {
            "phase": target_phase.value,
            "pending_control_operation": None,
            "last_control_action": pending.get("action"),
            "last_control_operation_id": operation_id,
            "last_control_record_kind": "terminal",
            "active_cycle_id": None,
        }
        if checkpoint_id is not None:
            update["latest_checkpoint_id"] = checkpoint_id
            update["latest_checkpoint_manifest_digest"] = checkpoint_manifest_digest
        failure_digest = _optional_digest(
            payload.get("failure_digest"),
            "run control failure_digest",
        )
        if target_phase in {RunPhase.FAILED, RunPhase.RECOVERY_REQUIRED}:
            update["failure_digest"] = failure_digest
        else:
            update["failure_digest"] = None
        return ProgramNodeResult(
            value={
                "operation_id": operation_id,
                "phase": target_phase.value,
            },
            state_update=update,
            events=({
                "type": "run_control_resolved",
                "operation_id": operation_id,
                "action": pending.get("action"),
                "phase": target_phase.value,
                "checkpoint_id": checkpoint_id,
            },),
        )

    def _optional_digest(value: object, field: str) -> str | None:
        if value is None:
            return None
        return _digest(value, field)

    def control_running(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        phase = RunPhase(data["phase"])
        if phase in {RunPhase.COMPLETED, RunPhase.FAILED, RunPhase.CLOSED}:
            raise RuntimeError(f"run cannot enter running from {phase.value}")
        checkpoint_id = payload.get("checkpoint_id")
        if checkpoint_id is not None:
            checkpoint_id = _text(checkpoint_id, "run control checkpoint_id")
        checkpoint_manifest_digest = _optional_digest(
            payload.get("checkpoint_manifest_digest"),
            "run control checkpoint_manifest_digest",
        )
        if (checkpoint_id is None) != (checkpoint_manifest_digest is None):
            raise ValueError("run control checkpoint identity must be complete")
        update: dict[str, object] = {
            "phase": RunPhase.RUNNING.value,
            "failure_digest": None,
        }
        if checkpoint_id is not None:
            update["latest_checkpoint_id"] = checkpoint_id
            update["latest_checkpoint_manifest_digest"] = checkpoint_manifest_digest
        return ProgramNodeResult(
            value={"phase": RunPhase.RUNNING.value},
            state_update=update,
            events=({
                "type": "run_control_running",
                "checkpoint_id": checkpoint_id,
                "checkpoint_manifest_digest": checkpoint_manifest_digest,
            },),
        )

    def control_stopped(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        if RunPhase(data["phase"]) is not RunPhase.RUNNING:
            raise RuntimeError("run can stop only while running")
        return ProgramNodeResult(
            value={"phase": RunPhase.STOPPED.value},
            state_update={"phase": RunPhase.STOPPED.value, "active_cycle_id": None},
            events=({"type": "run_control_stopped"},),
        )

    def control_recovery_required(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        phase = RunPhase(data["phase"])
        if phase in {RunPhase.COMPLETED, RunPhase.CLOSED}:
            raise RuntimeError(f"run cannot require recovery from {phase.value}")
        failure_digest = _optional_digest(
            payload.get("failure_digest"),
            "run control failure_digest",
        )
        return ProgramNodeResult(
            value={"phase": RunPhase.RECOVERY_REQUIRED.value},
            state_update={
                "phase": RunPhase.RECOVERY_REQUIRED.value,
                "active_cycle_id": None,
                "failure_digest": failure_digest,
            },
            events=({
                "type": "run_control_recovery_required",
                "failure_digest": failure_digest,
            },),
        )

    def control_completed(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        phase = RunPhase(data["phase"])
        if phase is RunPhase.CLOSED:
            raise RunClosed("closed run cannot become completed")
        return ProgramNodeResult(
            value={"phase": RunPhase.COMPLETED.value},
            state_update={"phase": RunPhase.COMPLETED.value, "active_cycle_id": None},
            events=({"type": "run_control_completed"},),
        )

    def control_failed(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        if RunPhase(data["phase"]) is RunPhase.CLOSED:
            raise RunClosed("closed run cannot become failed")
        failure_digest = _optional_digest(
            payload.get("failure_digest"),
            "run control failure_digest",
        )
        return ProgramNodeResult(
            value={"phase": RunPhase.FAILED.value},
            state_update={
                "phase": RunPhase.FAILED.value,
                "active_cycle_id": None,
                "failure_digest": failure_digest,
            },
            events=({
                "type": "run_control_failed",
                "failure_digest": failure_digest,
            },),
        )

    def closed(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _payload(request)
        if data["phase"] == RunPhase.CLOSED.value:
            raise RunClosed("research run is already closed")
        cleanup_digest = payload.get("cleanup_digest")
        if cleanup_digest is not None:
            cleanup_digest = _digest(cleanup_digest, "run cleanup_digest")
        cleanup_succeeded = payload.get("cleanup_succeeded")
        if not isinstance(cleanup_succeeded, bool):
            raise TypeError("run cleanup_succeeded must be boolean")
        return ProgramNodeResult(
            value={"cleanup_succeeded": cleanup_succeeded},
            state_update={
                "phase": RunPhase.CLOSED.value,
                "active_cycle_id": None,
                "cleanup_digest": cleanup_digest,
                "cleanup_succeeded": cleanup_succeeded,
            },
            status=MachineStatus.COMPLETED,
            events=({
                "type": "run_closed",
                "cleanup_succeeded": cleanup_succeeded,
                "cleanup_digest": cleanup_digest,
            },),
        )

    operations.register(
        "run.manifest_bound",
        manifest_bound,
        implementation_digest=canonical_digest({
            "operation": "run.manifest_bound",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.cycle_started",
        cycle_started,
        implementation_digest=canonical_digest({
            "operation": "run.cycle_started",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.cycle_completed",
        cycle_completed,
        implementation_digest=canonical_digest({
            "operation": "run.cycle_completed",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.cycle_failed",
        cycle_failed,
        implementation_digest=canonical_digest({
            "operation": "run.cycle_failed",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.restored",
        restored,
        implementation_digest=canonical_digest({
            "operation": "run.restored",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.control.prepare",
        control_prepare,
        implementation_digest=canonical_digest({
            "operation": "run.control.prepare",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.control.resolve",
        control_resolve,
        implementation_digest=canonical_digest({
            "operation": "run.control.resolve",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.control.running",
        control_running,
        implementation_digest=canonical_digest({
            "operation": "run.control.running",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.control.stopped",
        control_stopped,
        implementation_digest=canonical_digest({
            "operation": "run.control.stopped",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.control.recovery_required",
        control_recovery_required,
        implementation_digest=canonical_digest({
            "operation": "run.control.recovery_required",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.control.completed",
        control_completed,
        implementation_digest=canonical_digest({
            "operation": "run.control.completed",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.control.failed",
        control_failed,
        implementation_digest=canonical_digest({
            "operation": "run.control.failed",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "run.closed",
        closed,
        implementation_digest=canonical_digest({
            "operation": "run.closed",
            "implementation_revision": 1,
        }),
    )
    return operations


def run_handlers() -> ProgramHandlerRegistry:
    return build_rule_handlers(run_rule_set(), run_operation_handlers())


@dataclass(slots=True)
class RunMachineSession:
    session: ResearchMachineSession
    binding: RunMachineBinding

    @property
    def identity(self) -> RunIdentity:
        return self.binding.identity

    @classmethod
    def open(
        cls,
        *,
        binding: RunMachineBinding,
        initial_context: ExecutionContext,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> "RunMachineSession":
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("run machine journal must implement MachineJournalPort")
        if not isinstance(binding, RunMachineBinding):
            raise TypeError("run machine open requires RunMachineBinding")
        identity = binding.identity
        host = ResearchProgramHost(
            host_id="research.run.lifecycle",
            program=RUN_PROGRAM,
            journal=journal,
            snapshot_store=snapshot_store,
            base_handlers=run_handlers(),
            dependency_identity={
                "machine": "run",
                "rules": run_rule_set().rule_set_digest,
            },
        )
        session = host.open_session(
            machine_id=f"research-run:{identity.run_id}",
            instance_identity={
                "run_identity_digest": identity.digest(),
                "binding_digest": binding.binding_digest,
            },
            binding=None,
        )
        result = cls(session, binding)
        if not session.started:
            session.start(
                run_initial_data(binding, initial_context),
                command_id=f"{session.machine_id}:start",
            )
        else:
            result._validate_identity()
            if (
                binding.run_manifest_digest is not None
                and result.data.get("run_manifest_digest") is None
            ):
                result.bind_manifest(binding.run_manifest_digest)
            if (
                initial_context.checkpoint_id is not None
                and result.phase is RunPhase.RECOVERY_REQUIRED
            ):
                result.restored(initial_context)
        return result

    def _validate_identity(self) -> None:
        data = self.session.data
        if data.get("run_identity_digest") != self.identity.digest():
            raise ValueError("Run Machine belongs to another RunIdentity")
        if data.get("experiment_spec_digest") != self.binding.experiment_spec_digest:
            raise ValueError("Run Machine belongs to another experiment specification")
        existing_manifest = data.get("run_manifest_digest")
        if (
            existing_manifest is not None
            and self.binding.run_manifest_digest is not None
            and existing_manifest != self.binding.run_manifest_digest
        ):
            raise ValueError("Run Machine launch manifest identity drifted")
        if data.get("run_binding_digest") != self.binding.binding_digest:
            raise ValueError("Run Machine binding digest drifted")

    @property
    def data(self) -> dict[str, object]:
        return dict(self.session.data)

    @property
    def phase(self) -> RunPhase:
        return RunPhase(self.data["phase"])

    @property
    def closed(self) -> bool:
        return self.phase is RunPhase.CLOSED

    @property
    def stopped(self) -> bool:
        return self.phase is RunPhase.STOPPED

    @property
    def completed(self) -> bool:
        return self.phase is RunPhase.COMPLETED

    @property
    def failed(self) -> bool:
        return self.phase is RunPhase.FAILED

    @property
    def requires_recovery(self) -> bool:
        return self.phase is RunPhase.RECOVERY_REQUIRED

    @property
    def completed_cycles(self) -> int:
        value = self.data.get("completed_cycles", 0)
        if type(value) is not int or value < 0:
            raise ValueError("Run Machine completed_cycles is invalid")
        return value

    @property
    def latest_checkpoint_id(self) -> str | None:
        value = self.data.get("latest_checkpoint_id")
        if value is not None and type(value) is not str:
            raise TypeError("Run Machine checkpoint id must be text")
        return value

    @property
    def cut(self) -> MachineCut | None:
        head = self.session.machine.journal.latest(self.session.machine_id)
        return None if head is None else MachineCut.from_commit(head)

    def require_runnable(self) -> None:
        if self.closed:
            raise RunClosed("study run is closed")
        if self.requires_recovery:
            raise RunRecoveryRequired(
                "study run is in an uncertain state; restore from a verified checkpoint"
            )
        if self.phase is not RunPhase.RUNNING:
            raise RuntimeError(f"study run is not runnable: phase={self.phase.value}")
        if self.data.get("active_cycle_id") is not None:
            raise RuntimeError("study run already has an active cycle")

    def _event(self, kind: str, payload: dict[str, object], command_id: str):
        return self.session.step(
            {"event": MachineEvent(kind, payload, source=self.identity.run_id).as_payload()},
            command_id=command_id,
        )

    def bind_manifest(self, run_manifest_digest: str) -> None:
        manifest_digest = _digest(run_manifest_digest, "run manifest digest")
        existing = self.data.get("run_manifest_digest")
        if existing is not None:
            if existing != manifest_digest:
                raise ValueError("Run Machine launch manifest identity drifted")
            return
        self._event(
            "run.manifest_bound",
            {"run_manifest_digest": manifest_digest},
            f"{self.session.machine_id}:manifest:{manifest_digest[:16]}",
        )

    def cycle_started(self, cycle_id: str) -> None:
        self.require_runnable()
        self._event(
            "run.cycle_started",
            {"cycle_id": cycle_id},
            f"{self.session.machine_id}:cycle:{cycle_id}:start",
        )

    def cycle_completed(
        self,
        *,
        cycle_id: str,
        result_digest: str,
        final_context: ExecutionContext,
        checkpoint_id: str | None,
    ) -> None:
        self._event(
            "run.cycle_completed",
            {
                "cycle_id": cycle_id,
                "result_digest": result_digest,
                "context_digest": canonical_digest(final_context),
                "checkpoint_id": checkpoint_id,
            },
            f"{self.session.machine_id}:cycle:{cycle_id}:complete",
        )

    def cycle_failed(self, *, cycle_id: str, failure_digest: str) -> None:
        self._event(
            "run.cycle_failed",
            {"cycle_id": cycle_id, "failure_digest": failure_digest},
            f"{self.session.machine_id}:cycle:{cycle_id}:failed",
        )

    def restored(self, context: ExecutionContext) -> None:
        if context.checkpoint_id is None:
            raise ValueError("Run Machine restore requires checkpoint-bound context")
        self._event(
            "run.restored",
            {
                "checkpoint_id": context.checkpoint_id,
                "context_digest": canonical_digest(context),
            },
            f"{self.session.machine_id}:restore:{canonical_digest(context)[:16]}",
        )


    @property
    def pending_control_operation(self) -> dict[str, object] | None:
        value = self.data.get("pending_control_operation")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise TypeError("pending run control operation must be an object")
        return dict(value)

    def prepare_control(
        self,
        *,
        operation_id: str,
        action: str,
        restore_checkpoint_id: str | None = None,
        restore_checkpoint_manifest_digest: str | None = None,
        restore_cycle_identity_digest: str | None = None,
    ) -> bool:
        before = self.session.revision
        self._event(
            "run.control.prepare",
            {
                "operation_id": operation_id,
                "action": action,
                "restore_checkpoint_id": restore_checkpoint_id,
                "restore_checkpoint_manifest_digest": restore_checkpoint_manifest_digest,
                "restore_cycle_identity_digest": restore_cycle_identity_digest,
            },
            f"{self.session.machine_id}:control:{operation_id}:prepare",
        )
        return self.session.revision > before

    def resolve_control(
        self,
        *,
        operation_id: str,
        phase: RunPhase,
        checkpoint_id: str | None = None,
        checkpoint_manifest_digest: str | None = None,
        failure_digest: str | None = None,
    ) -> None:
        if not isinstance(phase, RunPhase):
            raise TypeError("resolved run control phase must be RunPhase")
        self._event(
            "run.control.resolve",
            {
                "operation_id": operation_id,
                "phase": phase.value,
                "checkpoint_id": checkpoint_id,
                "checkpoint_manifest_digest": checkpoint_manifest_digest,
                "failure_digest": failure_digest,
            },
            f"{self.session.machine_id}:control:{operation_id}:resolve:{phase.value}",
        )

    @property
    def latest_checkpoint_manifest_digest(self) -> str | None:
        value = self.data.get("latest_checkpoint_manifest_digest")
        if value is not None:
            _digest(value, "run checkpoint manifest digest")
        return value

    @property
    def control_revision(self) -> int:
        return self.session.revision

    def control_running(
        self,
        *,
        checkpoint_id: str | None = None,
        checkpoint_manifest_digest: str | None = None,
        operation_id: str,
    ) -> None:
        self._event(
            "run.control.running",
            {
                "checkpoint_id": checkpoint_id,
                "checkpoint_manifest_digest": checkpoint_manifest_digest,
            },
            f"{self.session.machine_id}:control:{operation_id}:running",
        )

    def control_stopped(self, *, operation_id: str) -> None:
        self._event(
            "run.control.stopped",
            {},
            f"{self.session.machine_id}:control:{operation_id}:stopped",
        )

    def control_recovery_required(
        self,
        *,
        operation_id: str,
        failure_digest: str | None = None,
    ) -> None:
        self._event(
            "run.control.recovery_required",
            {"failure_digest": failure_digest},
            f"{self.session.machine_id}:control:{operation_id}:recovery",
        )

    def control_completed(self, *, operation_id: str) -> None:
        self._event(
            "run.control.completed",
            {},
            f"{self.session.machine_id}:control:{operation_id}:completed",
        )

    def control_failed(
        self,
        *,
        operation_id: str,
        failure_digest: str | None = None,
    ) -> None:
        self._event(
            "run.control.failed",
            {"failure_digest": failure_digest},
            f"{self.session.machine_id}:control:{operation_id}:failed",
        )

    def close(self, *, cleanup_succeeded: bool, cleanup_digest: str | None) -> None:
        if self.closed:
            return
        self._event(
            "run.closed",
            {
                "cleanup_succeeded": cleanup_succeeded,
                "cleanup_digest": cleanup_digest,
            },
            f"{self.session.machine_id}:close",
        )


__all__ = [
    "RUN_PROGRAM",
    "RunMachineBinding",
    "RunMachineSession",
    "RunPhase",
    "compile_run_program",
    "run_handlers",
    "run_initial_data",
    "run_operation_handlers",
    "run_rule_set",
]
