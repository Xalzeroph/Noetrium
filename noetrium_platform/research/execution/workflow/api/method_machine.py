"""The universal method-machine ABI.

This module is deliberately small: a downstream method supplies a bounded
state machine and node functions, while Noetrium owns operation envelopes,
capability access, checkpoints, interrupts, and deterministic evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
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
    ROUTE = "route"
    CHECKPOINT = "checkpoint"
    INTERRUPT = "interrupt"
    RETURN = "return"


class MethodRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    LIMIT_REACHED = "limit_reached"


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

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("method node request node_id is required")
        if type(self.visit) is not int or self.visit < 0:
            raise ValueError("method node request visit must be a non-negative integer")
        if not isinstance(self.state, Mapping):
            raise TypeError("method node request state must be a mapping")
        if not isinstance(self.context, ExecutionContext):
            raise TypeError("method node request context must be ExecutionContext")
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(self, "input_value", freeze_json(self.input_value))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))


MethodNodeHandler = Callable[[MethodNodeRequest], MethodNodeResult]


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
        if self.kind is MethodNodeKind.CAPABILITY:
            if not isinstance(self.capability_id, str) or not self.capability_id.strip():
                raise ValueError("capability nodes require capability_id")
            if self.handler is not None:
                raise ValueError("capability nodes are invoked by the host, not a handler")
        elif self.capability_id is not None:
            raise ValueError("capability_id is valid only for capability nodes")
        elif self.kind not in {MethodNodeKind.CHECKPOINT, MethodNodeKind.INTERRUPT} and not callable(self.handler):
            raise ValueError("non-capability method nodes require a callable handler")
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
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.program_identity, MethodProgramIdentity):
            raise TypeError("method program identity must be MethodProgramIdentity")
        if not isinstance(self.graph, MethodGraph):
            raise TypeError("method program graph must be MethodGraph")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("method program configuration must be a mapping")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "identity": self.program_identity,
                "graph_digest": self.graph.graph_digest,
                "configuration": self.configuration,
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

    def build(self, *, configuration: Mapping[str, JsonValue] | None = None) -> MethodProgram:
        return MethodProgram(
            self._identity,
            MethodGraph(tuple(self._nodes), self._entrypoint),
            configuration or {},
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
    checkpoint_id: str = field(init=False)

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (self.run_id, self.program_digest, self.current_node)):
            raise ValueError("method checkpoint identity fields are required")
        require_sha256(self.program_digest, "method checkpoint program_digest")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("method checkpoint sequence must be non-negative")
        if not isinstance(self.state, Mapping):
            raise TypeError("method checkpoint state must be a mapping")
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
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "state", freeze_json(self.state))


@dataclass(frozen=True, slots=True)
class MethodRuntimeContext:
    """Explicit dependency bundle; there is no ambient service registry."""

    execution: ExecutionContext
    capabilities: CapabilityPort | None = None
    dispatcher: OperationDispatchPort | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ExecutionContext):
            raise TypeError("method runtime execution must be ExecutionContext")


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
    "AsyncOperationDispatchPort", "MethodCheckpoint", "MethodCheckpointStorePort", "MethodEvent",
    "MethodGraph", "MethodInterrupt", "MethodNodeHandler", "MethodNodeKind", "MethodNodeRequest",
    "MethodNodeResult", "MethodNodeSpec", "MethodProgram", "MethodProgramBuilder", "MethodRunResult",
    "MethodMachinePort", "MethodRunStatus", "MethodRuntimeContext",
]
