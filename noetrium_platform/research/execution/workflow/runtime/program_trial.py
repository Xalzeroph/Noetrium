"""Experiment Trial adapter over the universal ResearchProgramHost.

Trial owns only the ExperimentTrialProtocol-shaped frame/result projection.
Runtime Machine construction, journal authority and bounded Program driving are
provided by ResearchProgramHost.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    JsonInput,
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineKind,
    MachineSnapshotStorePort,
    MachineStatus,
    OperationResult,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.execution.machines import (
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchProgram,
    ResearchHostOperation,
    ResearchProgramHost,
)
from noetrium_platform.research.execution.workflow.api.trial import TrialCycleExecution


@dataclass(slots=True)
class TrialProgramFrame:
    """Process-local typed materialization referenced by Runtime Machine facts."""

    context: ExecutionContext
    task: object
    input_kind: str
    input_payload: JsonInput
    context_text: str = ""
    primary_result: object | None = None
    operation_results: list[OperationResult[JsonValue]] = field(default_factory=list)
    scratch: dict[str, object] = field(default_factory=dict)

    def finish(self) -> TrialCycleExecution:
        if self.primary_result is None:
            raise RuntimeError("trial RuntimeProgram completed without a primary_result")
        return TrialCycleExecution(
            context_text=self.context_text,
            primary_result=self.primary_result,
            final_context=self.context,
            operation_results=tuple(self.operation_results),
        )


TrialProgramHandler = Callable[
    [ProgramNodeRequest, object, TrialProgramFrame],
    ProgramNodeResult,
]
TrialProgramRestorer = Callable[
    [object, TrialProgramFrame, JsonObject, JsonValue],
    None,
]


@dataclass(frozen=True, slots=True)
class TrialProgramOperation:
    operation: str
    handler: TrialProgramHandler
    implementation_digest: str

    def __post_init__(self) -> None:
        if type(self.operation) is not str or not self.operation.strip():
            raise ValueError("trial RuntimeProgram operation name is required")
        object.__setattr__(self, "operation", self.operation.strip())
        if not callable(self.handler):
            raise TypeError("trial RuntimeProgram handler must be callable")
        object.__setattr__(
            self,
            "implementation_digest",
            require_sha256(
                self.implementation_digest,
                "trial RuntimeProgram operation implementation_digest",
            ),
        )


@dataclass(slots=True)
class _TrialBinding:
    surface: object
    frame: TrialProgramFrame


class RuntimeProgramTrialProtocol:
    """ExperimentTrialProtocol adapter backed by one Runtime Machine per cycle."""

    def __init__(
        self,
        *,
        protocol_id: str,
        surface_id: str,
        program: ResearchProgram,
        operations: tuple[TrialProgramOperation, ...],
        max_steps: int = 256,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
        restorer: TrialProgramRestorer | None = None,
        restorer_implementation_digest: str | None = None,
    ) -> None:
        if type(protocol_id) is not str or not protocol_id.strip():
            raise ValueError("trial protocol_id is required")
        if type(surface_id) is not str or not surface_id.strip():
            raise ValueError("trial surface_id is required")
        if not isinstance(program, ResearchProgram) or program.kind is not MachineKind.RUNTIME:
            raise TypeError("trial protocol requires a RUNTIME ResearchProgram")
        if type(operations) is not tuple or any(
            not isinstance(item, TrialProgramOperation) for item in operations
        ):
            raise TypeError("trial operations must be TrialProgramOperation tuple")
        names = tuple(item.operation for item in operations)
        if len(names) != len(set(names)):
            raise ValueError("trial operation names must be unique")
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("trial max_steps must be positive")
        if restorer is not None and not callable(restorer):
            raise TypeError("trial restorer must be callable")
        if restorer is None:
            if restorer_implementation_digest is not None:
                raise ValueError(
                    "trial restorer implementation digest requires a restorer"
                )
        else:
            if restorer_implementation_digest is None:
                raise ValueError(
                    "trial restorer requires implementation identity"
                )
            restorer_implementation_digest = require_sha256(
                restorer_implementation_digest,
                "trial restorer implementation_digest",
            )

        self.protocol_id = protocol_id.strip()
        self.surface_id = surface_id.strip()
        self.program = program
        self.operations = operations
        self.max_steps = max_steps
        owned_journal = journal if journal is not None else InMemoryMachineJournal()
        runtime_operations: list[ResearchHostOperation] = []
        for item in operations:
            def invoke(
                request: ProgramNodeRequest,
                binding: object,
                *,
                _handler: TrialProgramHandler = item.handler,
            ) -> ProgramNodeResult:
                if not isinstance(binding, _TrialBinding):
                    raise TypeError("trial RuntimeProgram host binding is invalid")
                return _handler(request, binding.surface, binding.frame)

            runtime_operations.append(
                ResearchHostOperation(
                    item.operation,
                    invoke,
                    item.implementation_digest,
                )
            )

        binding_restorer = None
        if restorer is not None:
            def restore_binding(
                binding: object,
                data: JsonObject,
                previous_value: JsonValue,
            ) -> None:
                if not isinstance(binding, _TrialBinding):
                    raise TypeError("trial RuntimeProgram restore binding is invalid")
                restorer(
                    binding.surface,
                    binding.frame,
                    data,
                    previous_value,
                )
            binding_restorer = restore_binding

        self._host = ResearchProgramHost(
            host_id=f"trial:{self.protocol_id}",
            program=self.program,
            operations=tuple(runtime_operations),
            journal=owned_journal,
            snapshot_store=snapshot_store,
            max_steps=self.max_steps,
            dependency_identity={
                "surface_id": self.surface_id,
                "operation_implementations": tuple(
                    (item.operation, item.implementation_digest)
                    for item in operations
                ),
                "restorer_implementation_digest": (
                    restorer_implementation_digest
                ),
            },
            binding_restorer=binding_restorer,
        )
        self.configuration_digest = canonical_digest({
            "program_digest": program.program_digest,
            "surface_id": self.surface_id,
            "max_steps": max_steps,
            "operation_implementations": tuple(
                (item.operation, item.implementation_digest)
                for item in operations
            ),
            "restorer_implementation_digest": restorer_implementation_digest,
        })

    @staticmethod
    def _initial_data(
        context: ExecutionContext,
        *,
        task: object,
        input_kind: str,
        input_payload: JsonInput,
    ) -> JsonObject:
        if type(input_kind) is not str or not input_kind.strip():
            raise ValueError("trial input_kind is required")
        return {
            "run_id": context.run_id,
            "decision_cycle_id": context.decision_cycle_id,
            "task_id": context.task_id,
            "input_kind": input_kind,
            "task_digest": canonical_digest(task),
            "input_digest": canonical_digest(input_payload),
            "participant_generations": context.participant_generations,
        }

    def run(
        self,
        surface: object,
        context: ExecutionContext,
        *,
        task: object,
        input_kind: str,
        input_payload: JsonInput,
    ) -> TrialCycleExecution:
        if not isinstance(context, ExecutionContext):
            raise TypeError("trial RuntimeProgram requires ExecutionContext")
        cycle_id = context.decision_cycle_id or context.span_id
        machine_id = (
            f"trial-runtime:{context.run_id}:{cycle_id}:"
            f"{self.program.program_digest[:16]}"
        )
        frame = TrialProgramFrame(context, task, input_kind, input_payload)
        execution = self._host.execute(
            machine_id=machine_id,
            instance_identity={
                "run_id": context.run_id,
                "decision_cycle_id": cycle_id,
                "task_id": context.task_id,
                "surface_id": self.surface_id,
            },
            binding=_TrialBinding(surface, frame),
            initial_data=self._initial_data(
                context,
                task=task,
                input_kind=input_kind,
                input_payload=input_payload,
            ),
            payload={"source": "trial-program"},
            command_id_prefix=machine_id,
        )
        if execution.status is MachineStatus.FAILED:
            raise RuntimeError("trial RuntimeProgram entered FAILED state")
        if execution.status in {MachineStatus.WAITING, MachineStatus.INTERRUPTED}:
            raise RuntimeError(
                f"trial RuntimeProgram suspended with status={execution.status.value}"
            )
        if execution.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                "trial RuntimeProgram stopped with unexpected "
                f"status={execution.status.value}"
            )
        return frame.finish()


__all__ = [
    "RuntimeProgramTrialProtocol",
    "TrialProgramFrame",
    "TrialProgramHandler",
    "TrialProgramOperation",
    "TrialProgramRestorer",
]
