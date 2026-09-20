"""Low-friction authoring helpers that compile into the canonical MethodProgram ABI."""

from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest
from .method_machine import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)


@dataclass(frozen=True, slots=True)
class AgentPhaseSpec:
    """One paper-owned agentic phase compiled into a normal MethodProgram node."""

    phase_id: str
    agent_id: str
    instruction: str
    max_visits: int = 1

    def __post_init__(self) -> None:
        for field_name, value in (
            ("phase_id", self.phase_id),
            ("agent_id", self.agent_id),
            ("instruction", self.instruction),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"agent phase {field_name} must be non-empty text")
        if type(self.max_visits) is not int or self.max_visits < 1:
            raise ValueError("agent phase max_visits must be positive")


def _phase_view(phase: AgentPhaseSpec):
    def view(request: MethodNodeRequest) -> JsonObject:
        return {
            "phase_id": phase.phase_id,
            "instruction": phase.instruction,
            "input": request.input_value,
            "previous": request.previous_value,
            "state": request.state,
        }
    return view


def _return_view(method_id: str, phase_ids: tuple[str, ...]):
    def handler(request: MethodNodeRequest) -> MethodNodeResult:
        return MethodNodeResult(
            value={
                "method_id": method_id,
                "phase_ids": phase_ids,
                "result": request.previous_value,
            }
        )
    return handler


def build_agent_phase_program(
    *,
    method_id: str,
    implementation_version: str,
    schema_version: str,
    phases: tuple[AgentPhaseSpec, ...],
    configuration: JsonObject | None = None,
    evidence_obligations: tuple[str, ...] = (),
    metric_names: tuple[str, ...] = (),
    artifact_kinds: tuple[str, ...] = (),
) -> MethodProgram:
    """Compile a sequential agentic phase specification into MethodProgram.

    This is an authoring convenience only. Runtime authority, transitions,
    evidence and replay remain owned by the normal MethodProgram/Machine Journal
    path.
    """

    if type(phases) is not tuple or not phases:
        raise ValueError("agent phase program requires at least one phase")
    if any(type(row) is not AgentPhaseSpec for row in phases):
        raise TypeError("phases must contain AgentPhaseSpec")
    phase_ids = tuple(row.phase_id for row in phases)
    if len(phase_ids) != len(set(phase_ids)):
        raise ValueError("agent phase ids must be unique")

    cfg: JsonObject = {
        "authoring_form": "agent_phase_sequence.v1",
        "phases": tuple(
            {
                "phase_id": row.phase_id,
                "agent_id": row.agent_id,
                "instruction": row.instruction,
                "max_visits": row.max_visits,
            }
            for row in phases
        ),
    }
    if configuration:
        cfg = {**cfg, **configuration}

    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id=method_id,
            implementation_version=implementation_version,
            abi_version="noetrium.method-machine.v1",
            schema_version=schema_version,
        ),
        configuration_digest=canonical_digest(cfg),
    )
    builder = MethodProgramBuilder(identity, entrypoint=phase_ids[0])
    for index, phase in enumerate(phases):
        next_id = phase_ids[index + 1] if index + 1 < len(phases) else "return"
        builder.agent(
            phase.phase_id,
            f"{method_id}.{phase.phase_id}",
            phase.agent_id,
            (next_id,),
            view_handler=_phase_view(phase),
            max_visits=phase.max_visits,
            evidence_obligations=(f"{method_id}.{phase.phase_id}",),
        )
    builder.return_node(
        "return",
        f"{method_id}.return",
        _return_view(method_id, phase_ids),
    )
    return builder.build(
        configuration=cfg,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=evidence_obligations or tuple(
            f"{method_id}.{phase_id}" for phase_id in phase_ids
        ),
        metric_names=metric_names,
        artifact_kinds=artifact_kinds,
    )


__all__ = ["AgentPhaseSpec", "build_agent_phase_program"]
