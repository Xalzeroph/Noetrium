"""The universal method-machine ABI.

This module is deliberately small: a downstream method supplies a bounded
state machine and node functions, while Noetrium owns operation envelopes,
capability access, checkpoints, interrupts, and deterministic evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import inspect
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityPort,
    CapabilityResult,
)
from noetrium_platform.capabilities.participant.method.api import MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)

from .dispatch import OperationDispatchPort


class MethodNodeKind(StrEnum):
    COMPUTE = "compute"
    CAPABILITY = "capability"
    AGENT = "agent"
    ROUTE = "route"
    CHECKPOINT = "checkpoint"
    INTERRUPT = "interrupt"
    RETURN = "return"


class MethodRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    LIMIT_REACHED = "limit_reached"


class MethodExecutionClass(StrEnum):
    DETERMINISTIC = "deterministic"
    CHECKPOINTABLE = "checkpointable"
    EFFECT_RECORDED = "effect_recorded"
    LIVE = "live"


class MethodEvidenceStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


METHOD_AGENT_CHECKPOINTS_STATE_KEY = "__noetrium_agent_checkpoints"


@dataclass(frozen=True, slots=True)
class MethodEvent:
    kind: str
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("method event kind is required")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class MethodInterrupt:
    interrupt_id: str
    node_id: str
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.interrupt_id, self.node_id)):
            raise ValueError("method interrupt identity fields are required")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class MethodNodeResult:
    """A node's semantic result; infrastructure fields are filled by the host."""

    value: JsonValue = None
    state_update: JsonObject = field(default_factory=dict)
    next_node: str | None = None
    checkpoint: bool = False
    events: tuple[MethodEvent, ...] = ()
    interrupt: MethodInterrupt | None = None
    effect_receipts: tuple[EffectReceipt, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state_update, Mapping):
            raise TypeError("method node state_update must be a mapping")
        if not isinstance(self.checkpoint, bool):
            raise TypeError("method node checkpoint must be boolean")
        if self.next_node is not None and (not isinstance(self.next_node, str) or not self.next_node.strip()):
            raise ValueError("method node next_node must be non-empty when provided")
        if not isinstance(self.events, tuple) or any(not isinstance(event, MethodEvent) for event in self.events):
            raise TypeError("method node events must be a tuple of MethodEvent")
        if self.interrupt is not None and not isinstance(self.interrupt, MethodInterrupt):
            raise TypeError("method node interrupt must be MethodInterrupt")
        if not isinstance(self.effect_receipts, tuple) or any(
            not isinstance(receipt, EffectReceipt) for receipt in self.effect_receipts
        ):
            raise TypeError("method node effect_receipts must be a tuple of EffectReceipt")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "state_update", freeze_json(self.state_update))


@dataclass(frozen=True, slots=True)
class MethodNodeRequest:
    node_id: str
    visit: int
    state: JsonObject
    input_value: JsonValue
    context: ExecutionContext
    previous_value: JsonValue = None
    capabilities: CapabilityPort | None = None
    visit_counts: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("method node request node_id is required")
        if type(self.visit) is not int or self.visit < 0:
            raise ValueError("method node request visit must be a non-negative integer")
        if not isinstance(self.state, Mapping):
            raise TypeError("method node request state must be a mapping")
        if not isinstance(self.context, ExecutionContext):
            raise TypeError("method node request context must be ExecutionContext")
        if not isinstance(self.visit_counts, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2
            or not isinstance(item[0], str) or not item[0].strip()
            or type(item[1]) is not int or item[1] < 0
            for item in self.visit_counts
        ):
            raise TypeError("method node request visit_counts must be typed pairs")
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(self, "input_value", freeze_json(self.input_value))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))


MethodNodeHandler = Callable[[MethodNodeRequest], MethodNodeResult]


@dataclass(frozen=True, slots=True)
class MethodAgentRequest:
    """The platform-owned agent-loop input for an ``AGENT`` node."""

    agent_id: str
    goal: JsonValue
    state: JsonObject
    input_value: JsonValue
    previous_value: JsonValue
    context: ExecutionContext
    checkpoint: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise ValueError("method agent request agent_id is required")
        if not isinstance(self.state, Mapping):
            raise TypeError("method agent request state must be a mapping")
        if not isinstance(self.context, ExecutionContext):
            raise TypeError("method agent request context must be ExecutionContext")
        object.__setattr__(self, "goal", freeze_json(self.goal))
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(self, "input_value", freeze_json(self.input_value))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))
        object.__setattr__(self, "checkpoint", freeze_json(self.checkpoint))


@dataclass(frozen=True, slots=True)
class MethodAgentResult:
    """Normalized result returned by a platform agent loop."""

    value: JsonValue = None
    state_update: JsonObject = field(default_factory=dict)
    events: tuple[MethodEvent, ...] = ()
    effect_receipts: tuple[EffectReceipt, ...] = ()
    checkpoint: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.state_update, Mapping):
            raise TypeError("method agent state_update must be a mapping")
        if not isinstance(self.events, tuple) or any(not isinstance(event, MethodEvent) for event in self.events):
            raise TypeError("method agent events must be a tuple of MethodEvent")
        if not isinstance(self.effect_receipts, tuple) or any(
            not isinstance(receipt, EffectReceipt) for receipt in self.effect_receipts
        ):
            raise TypeError("method agent effect_receipts must be a tuple of EffectReceipt")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "state_update", freeze_json(self.state_update))
        object.__setattr__(self, "checkpoint", freeze_json(self.checkpoint))


@runtime_checkable
class MethodAgentLoopPort(Protocol):
    def run(self, request: MethodAgentRequest) -> MethodAgentResult: ...


@runtime_checkable
class AsyncMethodAgentLoopPort(Protocol):
    async def run_async(self, request: MethodAgentRequest) -> MethodAgentResult: ...


@runtime_checkable
class MethodSchemaPort(Protocol):
    def validate(self, schema_id: str, value: JsonValue, *, location: str) -> None: ...


@runtime_checkable
class MethodEvidenceValidationPort(Protocol):
    def validate_result(self, result: "MethodRunResult", obligations: tuple[str, ...]) -> MethodEvidenceStatus: ...


def _handler_digest(handler: MethodNodeHandler | None) -> str:
    """Bind checkpoint identity to implementation text when source is available."""

    if handler is None:
        return canonical_digest({"handler": None})
    try:
        source = inspect.getsource(handler)
    except (OSError, TypeError):
        source = ""
    identity = {
        "module": getattr(handler, "__module__", ""),
        "qualname": getattr(handler, "__qualname__", ""),
        "source": source,
    }
    if not source:
        handler_type = type(handler)
        identity["handler_type"] = (
            getattr(handler_type, "__module__", ""),
            getattr(handler_type, "__qualname__", ""),
        )
    return canonical_digest(identity)


@dataclass(frozen=True, slots=True)
class MethodNodeSpec:
    node_id: str
    operation_type: str
    next_nodes: tuple[str, ...] = ()
    handler: MethodNodeHandler | None = None
    kind: MethodNodeKind = MethodNodeKind.COMPUTE
    capability_id: str | None = None
    effect_class: EffectClass = EffectClass.PURE
    max_visits: int = 1
    input_schema: str = "json"
    output_schema: str = "json"
    evidence_obligations: tuple[str, ...] = ()
    agent_id: str | None = None
    implementation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.node_id, self.operation_type)):
            raise ValueError("method node identity fields are required")
        if not isinstance(self.next_nodes, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.next_nodes
        ) or len(set(self.next_nodes)) != len(self.next_nodes):
            raise ValueError("method node next_nodes must be unique non-empty text")
        if not isinstance(self.kind, MethodNodeKind):
            raise TypeError("method node kind must be MethodNodeKind")
        if not isinstance(self.effect_class, EffectClass):
            raise TypeError("method node effect_class must be EffectClass")
        if type(self.max_visits) is not int or self.max_visits < 1:
            raise ValueError("method node max_visits must be a positive integer")
        if any(not isinstance(value, str) or not value.strip() for value in (self.input_schema, self.output_schema)):
            raise ValueError("method node schemas must be non-empty text")
        if not isinstance(self.evidence_obligations, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.evidence_obligations
        ) or len(set(self.evidence_obligations)) != len(self.evidence_obligations):
            raise ValueError("method node evidence_obligations must be unique non-empty text")
        if self.kind is MethodNodeKind.CAPABILITY:
            if not isinstance(self.capability_id, str) or not self.capability_id.strip():
                raise ValueError("capability nodes require capability_id")
            if self.handler is not None:
                raise ValueError("capability nodes are invoked by the host, not a handler")
            if self.agent_id is not None:
                raise ValueError("agent_id is valid only for agent nodes")
        elif self.kind is MethodNodeKind.AGENT:
            if not isinstance(self.agent_id, str) or not self.agent_id.strip():
                raise ValueError("agent nodes require agent_id")
            if self.handler is not None or self.capability_id is not None:
                raise ValueError("agent nodes are invoked by the host, not a handler or capability")
        else:
            if self.capability_id is not None or self.agent_id is not None:
                raise ValueError("capability_id/agent_id are valid only for capability/agent nodes")
            if self.kind not in {MethodNodeKind.CHECKPOINT, MethodNodeKind.INTERRUPT} and not callable(self.handler):
                raise ValueError("non-capability method nodes require a callable handler")
        object.__setattr__(self, "implementation_digest", _handler_digest(self.handler))
        if self.kind is MethodNodeKind.RETURN and self.next_nodes:
            raise ValueError("return nodes cannot have next_nodes")


@dataclass(frozen=True, slots=True)
class MethodGraph:
    """A bounded state graph; unlike a workflow DAG it intentionally permits loops."""

    nodes: tuple[MethodNodeSpec, ...]
    entrypoint: str
    graph_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("method graph requires at least one node")
        if not isinstance(self.entrypoint, str) or not self.entrypoint.strip():
            raise ValueError("method graph entrypoint is required")
        mapping = {node.node_id: node for node in self.nodes}
        if len(mapping) != len(self.nodes):
            raise ValueError("method graph node ids must be unique")
        if self.entrypoint not in mapping:
            raise ValueError("method graph entrypoint must reference a node")
        missing = sorted({target for node in self.nodes for target in node.next_nodes if target not in mapping})
        if missing:
            raise ValueError(f"method graph references unknown nodes: {missing}")
        object.__setattr__(
            self,
            "graph_digest",
            canonical_digest({
                "entrypoint": self.entrypoint,
                "nodes": tuple({
                    "node_id": node.node_id,
                    "operation_type": node.operation_type,
                    "next_nodes": node.next_nodes,
                    "kind": node.kind.value,
                    "capability_id": node.capability_id,
                    "effect_class": node.effect_class.value,
                    "max_visits": node.max_visits,
                    "input_schema": node.input_schema,
                    "output_schema": node.output_schema,
                    "evidence_obligations": node.evidence_obligations,
                    "agent_id": node.agent_id,
                    "implementation_digest": node.implementation_digest,
                } for node in self.nodes),
            }),
        )

    def node(self, node_id: str) -> MethodNodeSpec:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)


@dataclass(frozen=True, slots=True)
class MethodProgram:
    """Immutable downstream program definition hosted by UniversalMethodMachine."""

    program_identity: MethodProgramIdentity
    graph: MethodGraph
    configuration: JsonObject = field(default_factory=dict)
    state_schema: str = "json"
    input_schema: str = "json"
    output_schema: str = "json"
    required_capabilities: tuple[str, ...] = ()
    execution_class: MethodExecutionClass = MethodExecutionClass.EFFECT_RECORDED
    evidence_obligations: tuple[str, ...] = ()
    metric_names: tuple[str, ...] = ()
    artifact_kinds: tuple[str, ...] = ()
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.program_identity, MethodProgramIdentity):
            raise TypeError("method program identity must be MethodProgramIdentity")
        if not isinstance(self.graph, MethodGraph):
            raise TypeError("method program graph must be MethodGraph")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("method program configuration must be a mapping")
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.state_schema, self.input_schema, self.output_schema,
        )):
            raise ValueError("method program schemas must be non-empty text")
        if not isinstance(self.required_capabilities, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.required_capabilities
        ) or len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise ValueError("method program required_capabilities must be unique non-empty text")
        if not isinstance(self.execution_class, MethodExecutionClass):
            raise TypeError("method program execution_class must be MethodExecutionClass")
        for name, values in (
            ("evidence_obligations", self.evidence_obligations),
            ("metric_names", self.metric_names),
            ("artifact_kinds", self.artifact_kinds),
        ):
            if not isinstance(values, tuple) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"method program {name} must be a tuple of non-empty text")
            if len(set(values)) != len(values):
                raise ValueError(f"method program {name} must be unique")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "identity": self.program_identity,
                "graph_digest": self.graph.graph_digest,
                "configuration": self.configuration,
                "state_schema": self.state_schema,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "required_capabilities": self.required_capabilities,
                "execution_class": self.execution_class.value,
                "evidence_obligations": self.evidence_obligations,
                "metric_names": self.metric_names,
                "artifact_kinds": self.artifact_kinds,
            }),
        )


class MethodProgramBuilder:
    """Low-boilerplate composition helper; it produces only typed immutable data."""

    def __init__(self, program_identity: MethodProgramIdentity, *, entrypoint: str) -> None:
        self._identity = program_identity
        self._entrypoint = entrypoint
        self._nodes: list[MethodNodeSpec] = []

    def add(self, node: MethodNodeSpec) -> "MethodProgramBuilder":
        if not isinstance(node, MethodNodeSpec):
            raise TypeError("method program builder accepts MethodNodeSpec")
        self._nodes.append(node)
        return self

    def compute(
        self,
        node_id: str,
        operation_type: str,
        handler: MethodNodeHandler,
        next_nodes: tuple[str, ...] = (),
        *,
        max_visits: int = 1,
        input_schema: str = "json",
        output_schema: str = "json",
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodProgramBuilder":
        return self.add(MethodNodeSpec(
            node_id, operation_type, next_nodes, handler,
            kind=MethodNodeKind.COMPUTE, max_visits=max_visits,
            input_schema=input_schema, output_schema=output_schema,
            evidence_obligations=evidence_obligations,
        ))

    def capability(
        self,
        node_id: str,
        operation_type: str,
        capability_id: str,
        next_nodes: tuple[str, ...] = (),
        *,
        effect_class: EffectClass = EffectClass.PURE,
        max_visits: int = 1,
        input_schema: str = "json",
        output_schema: str = "json",
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodProgramBuilder":
        return self.add(MethodNodeSpec(
            node_id, operation_type, next_nodes, kind=MethodNodeKind.CAPABILITY,
            capability_id=capability_id, effect_class=effect_class,
            max_visits=max_visits, input_schema=input_schema,
            output_schema=output_schema, evidence_obligations=evidence_obligations,
        ))

    def agent(
        self,
        node_id: str,
        operation_type: str,
        agent_id: str,
        next_nodes: tuple[str, ...] = (),
        *,
        effect_class: EffectClass = EffectClass.PURE,
        max_visits: int = 1,
        input_schema: str = "json",
        output_schema: str = "json",
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodProgramBuilder":
        return self.add(MethodNodeSpec(
            node_id, operation_type, next_nodes, kind=MethodNodeKind.AGENT,
            agent_id=agent_id, effect_class=effect_class, max_visits=max_visits,
            input_schema=input_schema, output_schema=output_schema,
            evidence_obligations=evidence_obligations,
        ))

    def route(
        self,
        node_id: str,
        operation_type: str,
        handler: MethodNodeHandler,
        next_nodes: tuple[str, ...],
        *,
        max_visits: int = 1,
    ) -> "MethodProgramBuilder":
        return self.add(MethodNodeSpec(
            node_id, operation_type, next_nodes, handler,
            kind=MethodNodeKind.ROUTE, max_visits=max_visits,
        ))

    def checkpoint(self, node_id: str, next_nodes: tuple[str, ...] = ()) -> "MethodProgramBuilder":
        return self.add(MethodNodeSpec(
            node_id, "method.checkpoint", next_nodes, kind=MethodNodeKind.CHECKPOINT,
        ))

    def interrupt(self, node_id: str, next_nodes: tuple[str, ...] = ()) -> "MethodProgramBuilder":
        return self.add(MethodNodeSpec(
            node_id, "method.interrupt", next_nodes, kind=MethodNodeKind.INTERRUPT,
        ))

    def return_node(
        self,
        node_id: str,
        operation_type: str,
        handler: MethodNodeHandler,
        *,
        input_schema: str = "json",
        output_schema: str = "json",
        evidence_obligations: tuple[str, ...] = (),
    ) -> "MethodProgramBuilder":
        return self.add(MethodNodeSpec(
            node_id, operation_type, (), handler, kind=MethodNodeKind.RETURN,
            input_schema=input_schema, output_schema=output_schema,
            evidence_obligations=evidence_obligations,
        ))

    def build(
        self,
        *,
        configuration: Mapping[str, JsonValue] | None = None,
        state_schema: str = "json",
        input_schema: str = "json",
        output_schema: str = "json",
        required_capabilities: tuple[str, ...] = (),
        execution_class: MethodExecutionClass = MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations: tuple[str, ...] = (),
        metric_names: tuple[str, ...] = (),
        artifact_kinds: tuple[str, ...] = (),
    ) -> MethodProgram:
        return MethodProgram(
            self._identity,
            MethodGraph(tuple(self._nodes), self._entrypoint),
            configuration or {},
            state_schema,
            input_schema,
            output_schema,
            required_capabilities,
            execution_class,
            evidence_obligations,
            metric_names,
            artifact_kinds,
        )


@dataclass(frozen=True, slots=True)
class MethodCheckpoint:
    run_id: str
    program_digest: str
    sequence: int
    current_node: str
    state: JsonObject
    previous_value: JsonValue = None
    next_node: str | None = None
    visit_counts: tuple[tuple[str, int], ...] = ()
    events: tuple[MethodEvent, ...] = ()
    binding_plan_digest: str | None = None
    runtime_binding_digest: str | None = None
    schema_digest: str | None = None
    effect_receipts: tuple[EffectReceipt, ...] = ()
    evidence_status: MethodEvidenceStatus = MethodEvidenceStatus.UNKNOWN
    checkpoint_id: str = field(init=False)

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.run_id, self.program_digest, self.current_node)):
            raise ValueError("method checkpoint identity fields are required")
        require_sha256(self.program_digest, "method checkpoint program_digest")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("method checkpoint sequence must be non-negative")
        if not isinstance(self.state, Mapping):
            raise TypeError("method checkpoint state must be a mapping")
        if not isinstance(self.visit_counts, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2
            or not isinstance(item[0], str) or not item[0].strip()
            or type(item[1]) is not int or item[1] < 0
            for item in self.visit_counts
        ):
            raise TypeError("method checkpoint visit_counts must be typed pairs")
        if not isinstance(self.events, tuple) or any(not isinstance(event, MethodEvent) for event in self.events):
            raise TypeError("method checkpoint events must be a tuple of MethodEvent")
        if not isinstance(self.effect_receipts, tuple) or any(
            not isinstance(receipt, EffectReceipt) for receipt in self.effect_receipts
        ):
            raise TypeError("method checkpoint effect_receipts must be a tuple of EffectReceipt")
        if not isinstance(self.evidence_status, MethodEvidenceStatus):
            raise TypeError("method checkpoint evidence_status must be MethodEvidenceStatus")
        for name, value in (
            ("binding_plan_digest", self.binding_plan_digest),
            ("runtime_binding_digest", self.runtime_binding_digest),
            ("schema_digest", self.schema_digest),
        ):
            if value is not None:
                require_sha256(value, f"method checkpoint {name}")
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))
        object.__setattr__(self, "checkpoint_id", canonical_digest({
            "run_id": self.run_id,
            "program_digest": self.program_digest,
            "sequence": self.sequence,
            "current_node": self.current_node,
            "state": self.state,
            "previous_value": self.previous_value,
            "next_node": self.next_node,
            "visit_counts": self.visit_counts,
            "events": self.events,
            "binding_plan_digest": self.binding_plan_digest,
            "runtime_binding_digest": self.runtime_binding_digest,
            "schema_digest": self.schema_digest,
            "effect_receipts": self.effect_receipts,
            "evidence_status": self.evidence_status.value,
        }))


@runtime_checkable
class MethodCheckpointStorePort(Protocol):
    def save(self, checkpoint: MethodCheckpoint) -> None: ...
    def load(self, run_id: str) -> MethodCheckpoint | None: ...


@dataclass(frozen=True, slots=True)
class MethodRunResult:
    status: MethodRunStatus
    run_id: str
    program_digest: str
    value: JsonValue = None
    state: JsonObject = field(default_factory=dict)
    events: tuple[MethodEvent, ...] = ()
    checkpoint: MethodCheckpoint | None = None
    interrupt: MethodInterrupt | None = None
    failure: str | None = None
    effect_receipts: tuple[EffectReceipt, ...] = ()
    step_count: int = 0
    visit_counts: tuple[tuple[str, int], ...] = ()
    evidence_status: MethodEvidenceStatus = MethodEvidenceStatus.UNKNOWN
    binding_plan_digest: str | None = None
    runtime_binding_digest: str | None = None
    schema_digest: str | None = None
    failure_code: str | None = None
    failure_phase: str | None = None
    diagnostics: JsonObject = field(default_factory=dict)
    run_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, MethodRunStatus):
            raise TypeError("method run status must be MethodRunStatus")
        if any(not isinstance(value, str) or not value.strip() for value in (self.run_id, self.program_digest)):
            raise ValueError("method run identity fields are required")
        require_sha256(self.program_digest, "method run program_digest")
        if not isinstance(self.state, Mapping):
            raise TypeError("method run state must be a mapping")
        if not isinstance(self.events, tuple) or any(not isinstance(event, MethodEvent) for event in self.events):
            raise TypeError("method run events must be a tuple of MethodEvent")
        if not isinstance(self.effect_receipts, tuple) or any(
            not isinstance(receipt, EffectReceipt) for receipt in self.effect_receipts
        ):
            raise TypeError("method run effect_receipts must be a tuple of EffectReceipt")
        if type(self.step_count) is not int or self.step_count < 0:
            raise ValueError("method run step_count must be non-negative")
        if not isinstance(self.visit_counts, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2
            or not isinstance(item[0], str) or not item[0].strip()
            or type(item[1]) is not int or item[1] < 0
            for item in self.visit_counts
        ):
            raise TypeError("method run visit_counts must be typed pairs")
        if not isinstance(self.evidence_status, MethodEvidenceStatus):
            raise TypeError("method run evidence_status must be MethodEvidenceStatus")
        if not isinstance(self.diagnostics, Mapping):
            raise TypeError("method run diagnostics must be a mapping")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(self, "diagnostics", freeze_json(self.diagnostics))
        object.__setattr__(self, "run_digest", canonical_digest({
            "status": self.status.value,
            "run_id": self.run_id,
            "program_digest": self.program_digest,
            "value": self.value,
            "state": self.state,
            "events": self.events,
            "checkpoint_id": None if self.checkpoint is None else self.checkpoint.checkpoint_id,
            "interrupt": self.interrupt,
            "failure": self.failure,
            "effect_receipts": self.effect_receipts,
            "step_count": self.step_count,
            "visit_counts": self.visit_counts,
            "evidence_status": self.evidence_status.value,
            "binding_plan_digest": self.binding_plan_digest,
            "runtime_binding_digest": self.runtime_binding_digest,
            "schema_digest": self.schema_digest,
            "failure_code": self.failure_code,
            "failure_phase": self.failure_phase,
            "diagnostics": self.diagnostics,
        }))


@runtime_checkable
class MethodEvidencePort(Protocol):
    """Authoritative evidence sink injected by composition."""

    def record_checkpoint(self, checkpoint: MethodCheckpoint) -> None: ...
    def record_result(self, result: MethodRunResult) -> None: ...


@runtime_checkable
class MethodObservationPort(Protocol):
    """Non-authoritative observation sink; failures must not change method truth."""

    def publish(self, event: MethodEvent, context: ExecutionContext) -> None: ...


@dataclass(frozen=True, slots=True)
class MethodRuntimeContext:
    """Explicit dependency bundle; there is no ambient service registry."""

    execution: ExecutionContext
    capabilities: CapabilityPort | None = None
    dispatcher: OperationDispatchPort | None = None
    evidence: MethodEvidencePort | None = None
    observation: MethodObservationPort | None = None
    agent_loop: MethodAgentLoopPort | AsyncMethodAgentLoopPort | None = None
    schemas: MethodSchemaPort | None = None
    async_dispatcher: "AsyncOperationDispatchPort | None" = None
    binding_plan_digest: str | None = None
    runtime_binding_digest: str | None = None
    schema_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ExecutionContext):
            raise TypeError("method runtime execution must be ExecutionContext")
        for name, value in (
            ("binding_plan_digest", self.binding_plan_digest),
            ("runtime_binding_digest", self.runtime_binding_digest),
            ("schema_digest", self.schema_digest),
        ):
            if value is not None:
                require_sha256(value, f"method runtime {name}")


@runtime_checkable
class MethodMachinePort(Protocol):
    """Public host seam; composition chooses the concrete runtime provider."""

    def run(
        self,
        program: MethodProgram,
        *,
        runtime: MethodRuntimeContext,
        input_value: JsonValue = None,
        initial_state: Mapping[str, JsonValue] | None = None,
        resume: bool = False,
    ) -> MethodRunResult: ...

    async def run_async(
        self,
        program: MethodProgram,
        *,
        runtime: MethodRuntimeContext,
        input_value: JsonValue = None,
        initial_state: Mapping[str, JsonValue] | None = None,
        resume: bool = False,
    ) -> MethodRunResult: ...


@runtime_checkable
class AsyncOperationDispatchPort(Protocol):
    async def dispatch_async(self, **kwargs: object) -> object: ...


__all__ = [
    "AsyncMethodAgentLoopPort", "AsyncOperationDispatchPort", "MethodAgentLoopPort", "MethodAgentRequest", "MethodAgentResult",
    "METHOD_AGENT_CHECKPOINTS_STATE_KEY", "MethodCheckpoint", "MethodCheckpointStorePort", "MethodEvidencePort", "MethodEvidenceStatus", "MethodEvidenceValidationPort", "MethodEvent",
    "MethodExecutionClass", "MethodGraph", "MethodInterrupt", "MethodNodeHandler", "MethodNodeKind", "MethodNodeRequest",
    "MethodNodeResult", "MethodNodeSpec", "MethodObservationPort", "MethodProgram", "MethodProgramBuilder",
    "MethodRunResult", "MethodMachinePort", "MethodRunStatus", "MethodRuntimeContext", "MethodSchemaPort",
]
