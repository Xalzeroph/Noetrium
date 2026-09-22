"""Low-friction authoring helpers that compile into the canonical MethodProgram ABI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
)
from .method_machine import (
    MethodAgentTargetHandler,
    MethodAgentViewHandler,
    MethodCapabilityTargetHandler,
    MethodExecutionClass,
    MethodNodeHandler,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
    MethodRuntimePort,
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


def _workflow_next(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is str:
        if not value.strip():
            raise ValueError("method workflow next node must be non-empty")
        return (value,)
    if type(value) is not tuple or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise TypeError("method workflow next nodes must be text or text tuple")
    if len(value) != len(set(value)):
        raise ValueError("method workflow next nodes must be unique")
    return value


def _instruction_view(instruction: str) -> MethodAgentViewHandler:
    if type(instruction) is not str or not instruction.strip():
        raise ValueError("method workflow agent instruction must be non-empty")

    def view(request: MethodNodeRequest) -> JsonObject:
        return {
            "instruction": instruction,
            "input": request.input_value,
            "previous": request.previous_value,
            "state": request.state,
        }

    return view


class MethodWorkflow:
    """Fluent paper-facing authoring over the canonical MethodProgram ABI.

    This class owns no runtime semantics. It only removes identity/digest/wiring
    boilerplate while delegating every node to MethodProgramBuilder at build time.
    Advanced authors can always drop to MethodProgramBuilder without changing the
    runtime, checkpoint, evidence, or replay contract.
    """

    def __init__(
        self,
        method_id: str,
        *,
        entrypoint: str | None = None,
        implementation_version: str = "paper-method-v1",
        schema_version: str | None = None,
        configuration: JsonObject | None = None,
        state_schema: str = "json",
        input_schema: str = "json",
        output_schema: str = "json",
        execution_class: MethodExecutionClass = MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations: tuple[str, ...] = (),
        metric_names: tuple[str, ...] = (),
        artifact_kinds: tuple[str, ...] = (),
    ) -> None:
        for field_name, value in (
            ("method_id", method_id),
            ("implementation_version", implementation_version),
            ("state_schema", state_schema),
            ("input_schema", input_schema),
            ("output_schema", output_schema),
        ):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(f"method workflow {field_name} must be canonical text")
        resolved_schema = schema_version or f"{method_id}.method-workflow.v1"
        if type(resolved_schema) is not str or not resolved_schema.strip():
            raise ValueError("method workflow schema_version must be non-empty")
        if entrypoint is not None and (
            type(entrypoint) is not str or not entrypoint.strip()
        ):
            raise ValueError("method workflow entrypoint must be non-empty when set")
        if not isinstance(execution_class, MethodExecutionClass):
            raise TypeError("method workflow execution_class must be MethodExecutionClass")
        frozen = freeze_json({} if configuration is None else configuration)
        if not isinstance(frozen, Mapping):
            raise TypeError("method workflow configuration must be a JSON object")
        self.method_id = method_id
        self.implementation_version = implementation_version
        self.schema_version = resolved_schema
        self.configuration = frozen
        self.state_schema = state_schema
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.execution_class = execution_class
        self.evidence_obligations = _canonical_text_tuple(
            evidence_obligations, "method workflow evidence obligations"
        )
        self.metric_names = _canonical_text_tuple(
            metric_names, "method workflow metric names"
        )
        self.artifact_kinds = _canonical_text_tuple(
            artifact_kinds, "method workflow artifact kinds"
        )
        self._entrypoint = entrypoint
        self._node_ids: list[str] = []
        self._operations: list[object] = []
        self._required_capabilities: set[str] = set()
        self._required_runtime_ports: set[MethodRuntimePort] = set()

    def _add(self, node_id: str, operation) -> "MethodWorkflow":
        if type(node_id) is not str or not node_id.strip():
            raise ValueError("method workflow node_id must be non-empty")
        if node_id in self._node_ids:
            raise ValueError(f"method workflow node id is duplicated: {node_id}")
        if self._entrypoint is None:
            self._entrypoint = node_id
        self._node_ids.append(node_id)
        self._operations.append(operation)
        return self

    def requires_runtime(self, *ports: MethodRuntimePort) -> "MethodWorkflow":
        if any(not isinstance(port, MethodRuntimePort) for port in ports):
            raise TypeError("method workflow runtime requirements must be MethodRuntimePort")
        self._required_runtime_ports.update(ports)
        return self

    def requires_capabilities(self, *capability_ids: str) -> "MethodWorkflow":
        if any(type(value) is not str or not value.strip() for value in capability_ids):
            raise ValueError("method workflow capability requirements must be non-empty text")
        self._required_capabilities.update(capability_ids)
        return self

    def compute(
        self,
        node_id: str,
        handler: MethodNodeHandler,
        *,
        next: str | tuple[str, ...] | None = None,
        operation_type: str | None = None,
        max_visits: int = 1,
        input_schema: str = "json",
        output_schema: str = "json",
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodWorkflow":
        op = operation_type or f"{self.method_id}.{node_id}"
        successors = _workflow_next(next)
        return self._add(node_id, lambda builder: builder.compute(
            node_id, op, handler, successors,
            max_visits=max_visits,
            input_schema=input_schema,
            output_schema=output_schema,
            evidence_obligations=evidence_obligations,
        ))

    def agent(
        self,
        node_id: str,
        agent_id: str,
        *,
        instruction: str | None = None,
        view: MethodAgentViewHandler | None = None,
        next: str | tuple[str, ...] | None = None,
        operation_type: str | None = None,
        max_visits: int = 1,
        input_schema: str = "json",
        output_schema: str = "json",
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodWorkflow":
        if (instruction is None) == (view is None):
            raise ValueError("method workflow agent requires exactly one of instruction or view")
        resolved_view = _instruction_view(instruction) if instruction is not None else view
        assert resolved_view is not None
        op = operation_type or f"{self.method_id}.{node_id}"
        successors = _workflow_next(next)
        self._required_runtime_ports.add(MethodRuntimePort.AGENT_LOOP)
        return self._add(node_id, lambda builder: builder.agent(
            node_id, op, agent_id, successors,
            view_handler=resolved_view,
            max_visits=max_visits,
            input_schema=input_schema,
            output_schema=output_schema,
            evidence_obligations=evidence_obligations,
        ))

    def dynamic_agent(
        self,
        node_id: str,
        agent_ids: tuple[str, ...],
        target: MethodAgentTargetHandler,
        *,
        instruction: str | None = None,
        view: MethodAgentViewHandler | None = None,
        next: str | tuple[str, ...] | None = None,
        operation_type: str | None = None,
        max_visits: int = 1,
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodWorkflow":
        if (instruction is None) == (view is None):
            raise ValueError("dynamic agent requires exactly one of instruction or view")
        resolved_view = _instruction_view(instruction) if instruction is not None else view
        assert resolved_view is not None
        op = operation_type or f"{self.method_id}.{node_id}"
        successors = _workflow_next(next)
        self._required_runtime_ports.add(MethodRuntimePort.AGENT_LOOP)
        return self._add(node_id, lambda builder: builder.dynamic_agent(
            node_id, op, agent_ids, target, successors,
            view_handler=resolved_view,
            max_visits=max_visits,
            evidence_obligations=evidence_obligations,
        ))

    def capability(
        self,
        node_id: str,
        capability_id: str,
        *,
        next: str | tuple[str, ...] | None = None,
        operation_type: str | None = None,
        effect_class: EffectClass = EffectClass.PURE,
        max_visits: int = 1,
        input_schema: str = "json",
        output_schema: str = "json",
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodWorkflow":
        op = operation_type or f"{self.method_id}.{node_id}"
        successors = _workflow_next(next)
        self._required_capabilities.add(capability_id)
        self._required_runtime_ports.add(MethodRuntimePort.CAPABILITIES)
        return self._add(node_id, lambda builder: builder.capability(
            node_id, op, capability_id, successors,
            effect_class=effect_class,
            max_visits=max_visits,
            input_schema=input_schema,
            output_schema=output_schema,
            evidence_obligations=evidence_obligations,
        ))

    def dynamic_capability(
        self,
        node_id: str,
        capability_ids: tuple[str, ...],
        target: MethodCapabilityTargetHandler,
        *,
        next: str | tuple[str, ...] | None = None,
        operation_type: str | None = None,
        effect_class: EffectClass = EffectClass.NON_IDEMPOTENT,
        max_visits: int = 1,
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodWorkflow":
        op = operation_type or f"{self.method_id}.{node_id}"
        successors = _workflow_next(next)
        self._required_capabilities.update(capability_ids)
        self._required_runtime_ports.add(MethodRuntimePort.CAPABILITIES)
        return self._add(node_id, lambda builder: builder.dynamic_capability(
            node_id, op, capability_ids, target, successors,
            effect_class=effect_class,
            max_visits=max_visits,
            evidence_obligations=evidence_obligations,
        ))

    def route(
        self,
        node_id: str,
        handler: MethodNodeHandler,
        next: tuple[str, ...],
        *,
        operation_type: str | None = None,
        max_visits: int = 1,
    ) -> "MethodWorkflow":
        successors = _workflow_next(next)
        if not successors:
            raise ValueError("method workflow route requires successor closure")
        op = operation_type or f"{self.method_id}.{node_id}"
        return self._add(node_id, lambda builder: builder.route(
            node_id, op, handler, successors, max_visits=max_visits
        ))

    def checkpoint(
        self,
        node_id: str,
        *,
        next: str | tuple[str, ...] | None = None,
        max_visits: int = 1,
    ) -> "MethodWorkflow":
        successors = _workflow_next(next)
        return self._add(node_id, lambda builder: builder.checkpoint(
            node_id, successors, max_visits=max_visits
        ))

    def interrupt(
        self,
        node_id: str,
        *,
        next: str | tuple[str, ...] | None = None,
        max_visits: int = 1,
    ) -> "MethodWorkflow":
        successors = _workflow_next(next)
        return self._add(node_id, lambda builder: builder.interrupt(
            node_id, successors, max_visits=max_visits
        ))

    def return_(
        self,
        node_id: str = "return",
        *,
        handler: MethodNodeHandler | None = None,
        operation_type: str | None = None,
    ) -> "MethodWorkflow":
        if handler is None:
            def handler(request: MethodNodeRequest) -> MethodNodeResult:
                return MethodNodeResult(value=request.previous_value)
        op = operation_type or f"{self.method_id}.{node_id}"
        return self._add(node_id, lambda builder: builder.return_node(node_id, op, handler))

    def build(self) -> MethodProgram:
        if not self._node_ids or self._entrypoint is None:
            raise ValueError("method workflow requires at least one node")
        if self._entrypoint not in self._node_ids:
            raise ValueError("method workflow entrypoint is not a declared node")
        cfg: JsonObject = {
            "authoring_form": "method_workflow.v1",
            **dict(self.configuration),
        }
        identity = MethodProgramIdentity(
            MethodIdentity(
                method_id=self.method_id,
                implementation_version=self.implementation_version,
                abi_version="noetrium.method-machine.v1",
                schema_version=self.schema_version,
            ),
            configuration_digest=canonical_digest(cfg),
        )
        builder = MethodProgramBuilder(identity, entrypoint=self._entrypoint)
        for operation in self._operations:
            operation(builder)
        return builder.build(
            configuration=cfg,
            state_schema=self.state_schema,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            required_capabilities=tuple(sorted(self._required_capabilities)),
            required_runtime_ports=tuple(
                sorted(self._required_runtime_ports, key=lambda value: value.value)
            ),
            execution_class=self.execution_class,
            evidence_obligations=self.evidence_obligations,
            metric_names=self.metric_names,
            artifact_kinds=self.artifact_kinds,
        )


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
