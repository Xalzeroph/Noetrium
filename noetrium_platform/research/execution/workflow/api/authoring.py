"""Low-friction authoring helpers that compile into the canonical MethodProgram ABI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest, freeze_json
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


def _canonical_text_tuple(value: tuple[str, ...], field: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    if any(type(item) is not str or not item for item in value):
        raise ValueError(f"{field} must contain non-empty text")
    rows = tuple(item.strip() for item in value)
    if rows != value:
        raise ValueError(f"{field} values must already be stripped")
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} values must be unique")
    return rows


@dataclass(frozen=True, slots=True)
class AgentMethodSpec:
    """Canonical low-friction declaration for phase-based agent methods.

    Downstream authors declare method-owned phases and scientific surfaces once.
    Compilation owns MethodProgram identity, canonical configuration, bounded
    cycle wiring, default evidence obligations, and artifact/metric attachment.
    """

    method_id: str
    phases: tuple[AgentPhaseSpec, ...]
    implementation_version: str = "paper-method-v1"
    schema_version: str | None = None
    max_cycles: int | None = None
    configuration: JsonObject | None = None
    evidence_obligations: tuple[str, ...] = ()
    metric_names: tuple[str, ...] = ()
    artifact_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("method_id", self.method_id),
            ("implementation_version", self.implementation_version),
        ):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(f"agent method {field_name} must be canonical non-empty text")
        schema = self.schema_version
        if schema is None:
            schema = f"{self.method_id}.agent-method.v1"
        if type(schema) is not str or not schema.strip() or schema != schema.strip():
            raise ValueError("agent method schema_version must be canonical non-empty text")
        object.__setattr__(self, "schema_version", schema)

        if type(self.phases) is not tuple or not self.phases:
            raise ValueError("agent method requires at least one phase")
        if any(type(row) is not AgentPhaseSpec for row in self.phases):
            raise TypeError("agent method phases must contain AgentPhaseSpec")
        phase_ids = tuple(row.phase_id for row in self.phases)
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("agent method phase ids must be unique")

        if self.max_cycles is not None and (
            type(self.max_cycles) is not int or self.max_cycles < 1
        ):
            raise ValueError("agent method max_cycles must be positive or None")

        cfg = {} if self.configuration is None else dict(self.configuration)
        frozen_cfg = freeze_json(cfg)
        if not isinstance(frozen_cfg, Mapping):
            raise TypeError("agent method configuration must be a JSON object")
        object.__setattr__(self, "configuration", frozen_cfg)
        object.__setattr__(
            self,
            "evidence_obligations",
            _canonical_text_tuple(self.evidence_obligations, "agent method evidence obligations"),
        )
        object.__setattr__(
            self,
            "metric_names",
            _canonical_text_tuple(self.metric_names, "agent method metric names"),
        )
        object.__setattr__(
            self,
            "artifact_kinds",
            _canonical_text_tuple(self.artifact_kinds, "agent method artifact kinds"),
        )

    @property
    def cyclic(self) -> bool:
        return self.max_cycles is not None

    def compile(self) -> MethodProgram:
        common = {
            "method_id": self.method_id,
            "implementation_version": self.implementation_version,
            "schema_version": self.schema_version,
            "phases": self.phases,
            "configuration": self.configuration,
            "evidence_obligations": self.evidence_obligations,
            "metric_names": self.metric_names,
            "artifact_kinds": self.artifact_kinds,
        }
        if self.max_cycles is None:
            return _compile_agent_phase_program(**common)
        return _compile_agent_cycle_program(max_cycles=self.max_cycles, **common)


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


def _compile_agent_phase_program(
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


def _cycle_route(first_phase_id: str, max_cycles: int):
    def handler(request: MethodNodeRequest) -> MethodNodeResult:
        previous_count = request.state.get("__agent_cycle_count", 0)
        if type(previous_count) is not int or previous_count < 0:
            raise ValueError("agent cycle count must be a non-negative integer")
        completed = previous_count + 1
        return MethodNodeResult(
            value={
                "completed_cycles": completed,
                "last_result": request.previous_value,
            },
            state_update={"__agent_cycle_count": completed},
            next_node="return" if completed >= max_cycles else first_phase_id,
        )
    return handler


def _compile_agent_cycle_program(
    *,
    method_id: str,
    implementation_version: str,
    schema_version: str,
    phases: tuple[AgentPhaseSpec, ...],
    max_cycles: int,
    configuration: JsonObject | None = None,
    evidence_obligations: tuple[str, ...] = (),
    metric_names: tuple[str, ...] = (),
    artifact_kinds: tuple[str, ...] = (),
) -> MethodProgram:
    """Compile a bounded repeated phase cycle into the canonical MethodProgram ABI."""

    if type(max_cycles) is not int or max_cycles < 1:
        raise ValueError("agent cycle max_cycles must be positive")
    if type(phases) is not tuple or not phases:
        raise ValueError("agent cycle program requires at least one phase")
    if any(type(row) is not AgentPhaseSpec for row in phases):
        raise TypeError("phases must contain AgentPhaseSpec")
    phase_ids = tuple(row.phase_id for row in phases)
    if len(phase_ids) != len(set(phase_ids)):
        raise ValueError("agent cycle phase ids must be unique")

    cfg: JsonObject = {
        "authoring_form": "agent_phase_cycle.v1",
        "max_cycles": max_cycles,
        "phases": tuple(
            {
                "phase_id": row.phase_id,
                "agent_id": row.agent_id,
                "instruction": row.instruction,
                "max_visits": max(row.max_visits, max_cycles),
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
        next_id = phase_ids[index + 1] if index + 1 < len(phases) else "cycle_route"
        builder.agent(
            phase.phase_id,
            f"{method_id}.{phase.phase_id}",
            phase.agent_id,
            (next_id,),
            view_handler=_phase_view(phase),
            max_visits=max(phase.max_visits, max_cycles),
            evidence_obligations=(f"{method_id}.{phase.phase_id}",),
        )
    builder.route(
        "cycle_route",
        f"{method_id}.cycle-route",
        _cycle_route(phase_ids[0], max_cycles),
        (phase_ids[0], "return"),
        max_visits=max_cycles,
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


__all__ = [
    "AgentMethodSpec",
    "AgentPhaseSpec",
]
