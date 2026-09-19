from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    ParticipantConcern,
    ParticipantProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import FLOW_FIDELITY


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Flow subtask {field_name} must be text")
    return value if allow_empty else value.strip()


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Flow subtask {field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"Flow subtask {field_name} must decode to an object")
    return decoded


def _history(value: object) -> tuple[JsonValue, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError("Flow subtask history must be a sequence")
    return tuple(freeze_json(row) for row in value)


@dataclass(frozen=True, slots=True)
class FlowSubtaskExecutionRequest:
    task_id: str
    overall_task: str
    objective: str
    assigned_role: str
    output_format: str
    parent_context: tuple[JsonObject, ...]
    history: tuple[JsonValue, ...]
    feedback: str
    attempt: int

    def __post_init__(self) -> None:
        for name in (
            "task_id",
            "overall_task",
            "objective",
            "assigned_role",
        ):
            _text(getattr(self, name), name)
        _text(self.output_format, "output_format", allow_empty=True)
        _text(self.feedback, "feedback", allow_empty=True)
        if type(self.parent_context) is not tuple or any(
            not isinstance(row, Mapping) for row in self.parent_context
        ):
            raise TypeError("Flow subtask parent_context must be object tuple")
        if type(self.history) is not tuple:
            raise TypeError("Flow subtask history must be tuple")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("Flow subtask attempt must be positive")


@dataclass(frozen=True, slots=True)
class FlowSubtaskValidationRequest:
    task_id: str
    overall_task: str
    objective: str
    result: JsonValue
    history: tuple[JsonValue, ...]
    attempt: int

    def __post_init__(self) -> None:
        for name in ("task_id", "overall_task", "objective"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "result", freeze_json(self.result))
        if type(self.history) is not tuple:
            raise TypeError("Flow subtask validation history must be tuple")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("Flow subtask validation attempt must be positive")


@dataclass(frozen=True, slots=True)
class FlowSubtaskValidationResult:
    valid: bool
    feedback: str = ""
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.valid) is not bool:
            raise TypeError("Flow subtask validation valid must be boolean")
        _text(self.feedback, "validation feedback", allow_empty=True)
        for name in ("evidence_refs", "artifact_refs"):
            values = getattr(self, name)
            if type(values) is not tuple or any(
                type(row) is not str or not row.strip() for row in values
            ):
                raise TypeError(f"Flow subtask {name} must be text tuple")
            if len(values) != len(set(values)):
                raise ValueError(f"Flow subtask {name} must be unique")


@runtime_checkable
class FlowSubtaskRuntimePort(Protocol):
    """Mechanics/model binding for one paper-owned subtask program."""

    @property
    def identity_digest(self) -> str: ...

    def execute(
        self,
        request: FlowSubtaskExecutionRequest,
    ) -> JsonValue: ...

    def validate(
        self,
        request: FlowSubtaskValidationRequest,
    ) -> FlowSubtaskValidationResult: ...


@dataclass(frozen=True, slots=True)
class FlowSubtaskBinding:
    runtime: FlowSubtaskRuntimePort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.runtime, FlowSubtaskRuntimePort):
            raise TypeError("Flow subtask binding requires FlowSubtaskRuntimePort")
        identity = require_sha256(
            self.runtime.identity_digest,
            "Flow subtask runtime identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "fidelity_digest": FLOW_FIDELITY.fidelity_digest,
                "runtime_identity_digest": identity,
            }),
        )


def flow_subtask_initial_data(
    *,
    task_id: str,
    overall_task: str,
    objective: str,
    assigned_role: str,
    output_format: str,
    parent_context: tuple[JsonObject, ...],
    history: tuple[JsonValue, ...] = (),
) -> JsonObject:
    return {
        "fidelity_digest": FLOW_FIDELITY.fidelity_digest,
        "task_id": _text(task_id, "task_id"),
        "overall_task": _text(overall_task, "overall_task"),
        "objective": _text(objective, "objective"),
        "assigned_role": _text(assigned_role, "assigned_role"),
        "output_format": _text(
            output_format,
            "output_format",
            allow_empty=True,
        ),
        "parent_context": tuple(freeze_json(row) for row in parent_context),
        "history": _history(history),
        "attempt": 0,
        "feedback": "",
        "pending_result": None,
        "valid": False,
    }


def build_flow_subtask_program() -> ResearchProgram:
    return (
        ParticipantProgramBuilder.create(
            program_id="flow.subtask",
            version="1",
            state_schema="flow.subtask.state.v1",
            entrypoint="execute",
        )
        .semantic(
            "execute",
            ParticipantConcern.TURN,
            "flow.subtask.execute",
            next_node="validate",
        )
        .semantic(
            "validate",
            ParticipantConcern.TURN,
            "flow.subtask.validate",
            next_node="execute",
        )
        .build()
    )


FLOW_SUBTASK_PROGRAM = build_flow_subtask_program()


def _binding(value: object) -> FlowSubtaskBinding:
    if not isinstance(value, FlowSubtaskBinding):
        raise TypeError("Flow subtask host requires FlowSubtaskBinding")
    return value


def _execute(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    b = _binding(binding)
    attempt = request.data.get("attempt", 0)
    if type(attempt) is not int or attempt < 0:
        raise ValueError("Flow subtask attempt state must be non-negative")
    attempt += 1
    parent_context = request.data.get("parent_context", ())
    if isinstance(parent_context, (str, bytes, bytearray)) or not isinstance(
        parent_context,
        Sequence,
    ):
        raise TypeError("Flow subtask parent_context must be a sequence")
    result = b.runtime.execute(
        FlowSubtaskExecutionRequest(
            task_id=_text(request.data.get("task_id"), "task_id"),
            overall_task=_text(
                request.data.get("overall_task"),
                "overall_task",
            ),
            objective=_text(request.data.get("objective"), "objective"),
            assigned_role=_text(
                request.data.get("assigned_role"),
                "assigned_role",
            ),
            output_format=_text(
                request.data.get("output_format", ""),
                "output_format",
                allow_empty=True,
            ),
            parent_context=tuple(
                freeze_json(_mapping(row, "parent context"))
                for row in parent_context
            ),
            history=_history(request.data.get("history", ())),
            feedback=_text(
                request.data.get("feedback", ""),
                "feedback",
                allow_empty=True,
            ),
            attempt=attempt,
        )
    )
    return ProgramNodeResult(
        value=result,
        state_update={
            "attempt": attempt,
            "pending_result": freeze_json(result),
        },
        next_node="validate",
        events=({
            "type": "flow_subtask_executed",
            "task_id": request.data.get("task_id"),
            "attempt": attempt,
        },),
    )


def _validate(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    b = _binding(binding)
    attempt = request.data.get("attempt")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("Flow subtask validation requires positive attempt")
    result = b.runtime.validate(
        FlowSubtaskValidationRequest(
            task_id=_text(request.data.get("task_id"), "task_id"),
            overall_task=_text(
                request.data.get("overall_task"),
                "overall_task",
            ),
            objective=_text(request.data.get("objective"), "objective"),
            result=request.data.get("pending_result"),
            history=_history(request.data.get("history", ())),
            attempt=attempt,
        )
    )
    if not isinstance(result, FlowSubtaskValidationResult):
        raise TypeError(
            "Flow subtask runtime validate must return "
            "FlowSubtaskValidationResult"
        )
    history = _history(request.data.get("history", ())) + (
        freeze_json({
            "attempt": attempt,
            "result": request.data.get("pending_result"),
            "valid": result.valid,
            "feedback": result.feedback,
        }),
    )
    state_update = {
        "history": history,
        "valid": result.valid,
        "feedback": result.feedback,
    }
    value = {
        "task_id": request.data.get("task_id"),
        "valid": result.valid,
        "result": request.data.get("pending_result"),
        "validation_attempts": attempt,
        "feedback": result.feedback,
        "history": history,
    }
    if result.valid:
        return ProgramNodeResult(
            value=value,
            state_update=state_update,
            status=MachineStatus.COMPLETED,
            evidence_refs=result.evidence_refs,
            artifact_refs=result.artifact_refs,
            events=({
                "type": "flow_subtask_validated",
                "task_id": request.data.get("task_id"),
                "attempt": attempt,
                "valid": True,
            },),
        )
    if attempt >= FLOW_FIDELITY.max_validation_iterations:
        return ProgramNodeResult(
            value=value,
            state_update=state_update,
            status=MachineStatus.FAILED,
            evidence_refs=result.evidence_refs,
            artifact_refs=result.artifact_refs,
            events=({
                "type": "flow_subtask_validation_exhausted",
                "task_id": request.data.get("task_id"),
                "attempt": attempt,
            },),
        )
    return ProgramNodeResult(
        value=value,
        state_update=state_update,
        next_node="execute",
        evidence_refs=result.evidence_refs,
        artifact_refs=result.artifact_refs,
        events=({
            "type": "flow_subtask_retry_requested",
            "task_id": request.data.get("task_id"),
            "attempt": attempt,
            "feedback": result.feedback,
        },),
    )


def flow_subtask_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "flow.subtask.execute",
            _execute,
            canonical_digest({
                "operation": "flow.subtask.execute",
                "implementation_revision": 1,
                "fidelity_digest": FLOW_FIDELITY.fidelity_digest,
            }),
        ),
        ResearchHostOperation(
            "flow.subtask.validate",
            _validate,
            canonical_digest({
                "operation": "flow.subtask.validate",
                "implementation_revision": 1,
                "fidelity_digest": FLOW_FIDELITY.fidelity_digest,
            }),
        ),
    )


def flow_subtask_host(
    *,
    journal: MachineJournalPort,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="flow.subtask",
        program=FLOW_SUBTASK_PROGRAM,
        operations=flow_subtask_operations(),
        journal=journal,
        max_steps=FLOW_FIDELITY.max_validation_iterations * 2 + 2,
        dependency_identity={
            "paper": "Flow ICLR 2025",
            "fidelity_digest": FLOW_FIDELITY.fidelity_digest,
        },
    )


__all__ = [
    "FLOW_SUBTASK_PROGRAM",
    "FlowSubtaskBinding",
    "FlowSubtaskExecutionRequest",
    "FlowSubtaskRuntimePort",
    "FlowSubtaskValidationRequest",
    "FlowSubtaskValidationResult",
    "build_flow_subtask_program",
    "flow_subtask_host",
    "flow_subtask_initial_data",
    "flow_subtask_operations",
]
