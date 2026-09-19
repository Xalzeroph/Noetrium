"""Universal programmable Machine IR for research semantics.

Downstream papers define Programs and operation handlers. The kernel owns
acceptance, journaling, replay and effect truth. Runtime, Participant,
Environment, Memory, Evaluation, Optimization, Experiment and Research Run all
share this Program -> Interpreter -> Machine path.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel.canonical import canonical_digest, freeze_json, require_sha256, thaw_json
from noetrium_platform.foundation.kernel.kernel.family import MachineFamilyDescriptor
from noetrium_platform.foundation.kernel.kernel.json_value import JsonObject, JsonValue
from noetrium_platform.foundation.kernel.kernel.contracts import ChildMachineLink
from noetrium_platform.foundation.kernel.kernel.machine import (
    MachineCommand, MachineKind, MachineProgramRef, MachineSnapshot,
    MachineStatus, ProgramLock, TransitionProposal,
)

PROGRAM_COMMANDS = ("program.start", "program.step", "program.resume")
PROGRAMMABLE_MACHINE_FAMILY_VERSION = "1"
PROGRAMMABLE_MACHINE_STATE_SCHEMA_VERSION = "1"
PROGRAMMABLE_MACHINE_KINDS = (
    MachineKind.EXPERIMENT, MachineKind.RUN, MachineKind.RUNTIME,
    MachineKind.PARTICIPANT, MachineKind.MEMORY, MachineKind.ENVIRONMENT,
    MachineKind.EVALUATION, MachineKind.OPTIMIZATION,
)
_PROGRAM_STATE_KEY = "_program"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


@dataclass(frozen=True, slots=True)
class ProgramNode:
    node_id: str
    operation: str
    configuration: JsonObject = field(default_factory=dict)
    next_node: str | None = None
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "program node_id"))
        object.__setattr__(self, "operation", _text(self.operation, "program operation"))
        if not isinstance(self.configuration, Mapping):
            raise TypeError("program node configuration must be an object")
        if self.next_node is not None:
            object.__setattr__(self, "next_node", _text(self.next_node, "program next_node"))
        if type(self.required_capabilities) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.required_capabilities
        ):
            raise TypeError("program node required_capabilities must be a text tuple")
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise ValueError("program node required_capabilities must be unique")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))


@dataclass(frozen=True, slots=True)
class ResearchProgram:
    program_id: str
    kind: MachineKind
    version: str
    state_schema: str
    entrypoint: str
    nodes: tuple[ProgramNode, ...]
    required_capabilities: tuple[str, ...] = ()
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("program_id", self.program_id), ("version", self.version),
            ("state_schema", self.state_schema), ("entrypoint", self.entrypoint),
        ):
            object.__setattr__(self, name, _text(value, f"research program {name}"))
        if not isinstance(self.kind, MachineKind):
            raise TypeError("research program kind must be MachineKind")
        if self.kind is MachineKind.METHOD:
            raise ValueError("Method uses MethodProgram/UMM")
        if type(self.nodes) is not tuple or not self.nodes or any(
            not isinstance(node, ProgramNode) for node in self.nodes
        ):
            raise TypeError("research program nodes must be a non-empty ProgramNode tuple")
        node_map = {node.node_id: node for node in self.nodes}
        if len(node_map) != len(self.nodes):
            raise ValueError("research program node ids must be unique")
        if self.entrypoint not in node_map:
            raise ValueError("research program entrypoint does not exist")
        missing = sorted({
            node.next_node for node in self.nodes
            if node.next_node is not None and node.next_node not in node_map
        })
        if missing:
            raise ValueError(f"research program references missing nodes: {missing}")
        if type(self.required_capabilities) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.required_capabilities
        ):
            raise TypeError("research program required_capabilities must be a text tuple")
        object.__setattr__(self, "program_digest", canonical_digest({
            "program_id": self.program_id, "kind": self.kind.value,
            "version": self.version, "state_schema": self.state_schema,
            "entrypoint": self.entrypoint,
            "required_capabilities": self.required_capabilities,
            "nodes": tuple({
                "node_id": node.node_id, "operation": node.operation,
                "configuration": thaw_json(node.configuration),
                "next_node": node.next_node,
                "required_capabilities": node.required_capabilities,
            } for node in self.nodes),
        }))

    def node(self, node_id: str) -> ProgramNode:
        node_id = _text(node_id, "research program node_id")
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    def machine_program_ref(self, lock: ProgramLock) -> MachineProgramRef:
        if not isinstance(lock, ProgramLock):
            raise TypeError("research program lock must be ProgramLock")
        return MachineProgramRef(
            program_digest=self.program_digest, schema_id=self.state_schema,
            program_kind=self.kind.value, program_version=self.version,
            program_lock=lock,
        )


class ResearchProgramBuilder:
    def __init__(self, *, program_id: str, kind: MachineKind, version: str,
                 state_schema: str, entrypoint: str,
                 required_capabilities: tuple[str, ...] = ()) -> None:
        self._program_id = _text(program_id, "program_id")
        if not isinstance(kind, MachineKind) or kind is MachineKind.METHOD:
            raise ValueError("program builder requires a non-Method MachineKind")
        self._kind = kind
        self._version = _text(version, "program version")
        self._state_schema = _text(state_schema, "program state_schema")
        self._entrypoint = _text(entrypoint, "program entrypoint")
        self._required_capabilities = required_capabilities
        self._nodes: list[ProgramNode] = []

    def node(self, node_id: str, operation: str, *, configuration: JsonObject | None = None,
             next_node: str | None = None,
             required_capabilities: tuple[str, ...] = ()) -> "ResearchProgramBuilder":
        self._nodes.append(ProgramNode(
            node_id=node_id, operation=operation,
            configuration={} if configuration is None else configuration,
            next_node=next_node, required_capabilities=required_capabilities,
        ))
        return self

    def build(self) -> ResearchProgram:
        return ResearchProgram(
            program_id=self._program_id, kind=self._kind, version=self._version,
            state_schema=self._state_schema, entrypoint=self._entrypoint,
            nodes=tuple(self._nodes), required_capabilities=self._required_capabilities,
        )


@dataclass(frozen=True, slots=True)
class ProgramNodeRequest:
    program: ResearchProgram
    node: ProgramNode
    snapshot: MachineSnapshot
    payload: JsonValue
    data: JsonObject
    previous_value: JsonValue
    visit: int

    def __post_init__(self) -> None:
        if not isinstance(self.program, ResearchProgram) or not isinstance(self.node, ProgramNode):
            raise TypeError("program node request requires program and node")
        if not isinstance(self.snapshot, MachineSnapshot):
            raise TypeError("program node request requires MachineSnapshot")
        if type(self.visit) is not int or self.visit <= 0:
            raise ValueError("program node request visit must be positive")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "data", freeze_json(self.data))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))


@dataclass(frozen=True, slots=True)
class ProgramNodeResult:
    value: JsonValue = None
    state_update: JsonObject = field(default_factory=dict)
    next_node: str | None = None
    status: MachineStatus | None = None
    wait_reason: str | None = None
    emitted_commands: tuple[MachineCommand, ...] = ()
    events: tuple[JsonValue, ...] = ()
    output_refs: tuple[str, ...] = ()
    effect_intent_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    child_links: tuple[ChildMachineLink, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state_update, Mapping):
            raise TypeError("program node state_update must be an object")
        if self.next_node is not None:
            object.__setattr__(self, "next_node", _text(self.next_node, "program result next_node"))
        if self.status is not None and not isinstance(self.status, MachineStatus):
            raise TypeError("program node status must be MachineStatus")
        if self.wait_reason is not None:
            object.__setattr__(self, "wait_reason", _text(self.wait_reason, "program wait_reason"))
        if type(self.child_links) is not tuple or any(
            not isinstance(item, ChildMachineLink) for item in self.child_links
        ):
            raise TypeError("program child_links must be ChildMachineLink tuple")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "state_update", freeze_json(self.state_update))
        object.__setattr__(self, "events", tuple(freeze_json(item) for item in self.events))


ProgramOperationHandler = Callable[[ProgramNodeRequest], ProgramNodeResult]


@runtime_checkable
class ProgramHandlerRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, operation: str) -> ProgramOperationHandler: ...

    def implementation_digest(self, operation: str) -> str: ...


class ProgramHandlerRegistry(ProgramHandlerRegistryPort):
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[ProgramOperationHandler, str]] = {}
        self._lock = RLock()

    def register(
        self,
        operation: str,
        handler: ProgramOperationHandler,
        *,
        implementation_digest: str,
    ) -> None:
        operation = _text(operation, "program operation")
        if not callable(handler):
            raise TypeError("program operation handler must be callable")
        digest = require_sha256(
            implementation_digest,
            "program operation implementation_digest",
        )
        value = (handler, digest)
        with self._lock:
            current = self._handlers.get(operation)
            if current is not None and current != value:
                raise ValueError(f"program operation already registered: {operation}")
            self._handlers[operation] = value

    def resolve(self, operation: str) -> ProgramOperationHandler:
        operation = _text(operation, "program operation")
        with self._lock:
            try:
                return self._handlers[operation][0]
            except KeyError as exc:
                raise KeyError(f"unbound research-program operation: {operation}") from exc

    def implementation_digest(self, operation: str) -> str:
        operation = _text(operation, "program operation")
        with self._lock:
            try:
                return self._handlers[operation][1]
            except KeyError as exc:
                raise KeyError(f"unbound research-program operation: {operation}") from exc

    def operations(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handlers))

    @property
    def identity_digest(self) -> str:
        with self._lock:
            return canonical_digest(tuple(
                (operation, implementation_digest)
                for operation, (_, implementation_digest)
                in sorted(self._handlers.items())
            ))


def program_handler_binding_digest(
    program: ResearchProgram,
    handlers: ProgramHandlerRegistryPort,
) -> str:
    """Bind a ResearchProgram to exact implementations of referenced operations."""

    if not isinstance(program, ResearchProgram):
        raise TypeError("program handler binding requires ResearchProgram")
    if not isinstance(handlers, ProgramHandlerRegistryPort):
        raise TypeError(
            "program handler binding requires ProgramHandlerRegistryPort"
        )
    require_sha256(
        handlers.identity_digest,
        "program handler registry identity_digest",
    )
    operation_ids = tuple(sorted({node.operation for node in program.nodes}))
    implementations = tuple(
        (
            operation,
            require_sha256(
                handlers.implementation_digest(operation),
                "program operation implementation_digest",
            ),
        )
        for operation in operation_ids
    )
    return canonical_digest({
        "research_program_digest": program.program_digest,
        "operation_implementations": implementations,
    })


def _core_program_handler_digest(operation: str) -> str:
    return canonical_digest({
        "handler_family": "core-program",
        "operation": operation,
        "implementation_revision": 1,
    })


def core_program_handlers() -> ProgramHandlerRegistry:
    registry = ProgramHandlerRegistry()

    registry.register(
        "core.noop",
        lambda request: ProgramNodeResult(value=request.payload),
        implementation_digest=_core_program_handler_digest("core.noop"),
    )

    def assign(request: ProgramNodeRequest) -> ProgramNodeResult:
        config = _mapping(request.node.configuration, "assign configuration")
        values = _mapping(config.get("values", {}), "assign values")
        return ProgramNodeResult(value=values, state_update=values)

    def emit(request: ProgramNodeRequest) -> ProgramNodeResult:
        config = _mapping(request.node.configuration, "emit configuration")
        return ProgramNodeResult(value=request.payload, events=(config.get("event", request.payload),))

    def route(request: ProgramNodeRequest) -> ProgramNodeResult:
        config = _mapping(request.node.configuration, "route configuration")
        field_name = _text(config.get("field"), "route field")
        source = _mapping(request.payload if config.get("source", "payload") == "payload" else request.data, "route source")
        cases = _mapping(config.get("cases", {}), "route cases")
        target = cases.get(str(source.get(field_name)), config.get("default"))
        if target is None:
            raise ValueError("route has no matching target")
        return ProgramNodeResult(value=source.get(field_name), next_node=_text(target, "route target"))

    def wait(request: ProgramNodeRequest) -> ProgramNodeResult:
        config = _mapping(request.node.configuration, "wait configuration")
        return ProgramNodeResult(value=request.payload, status=MachineStatus.WAITING,
                                 wait_reason=_text(config.get("reason", request.node.node_id), "wait reason"))

    def finish(request: ProgramNodeRequest) -> ProgramNodeResult:
        config = _mapping(request.node.configuration, "return configuration")
        return ProgramNodeResult(value=config.get("value", request.payload), status=MachineStatus.COMPLETED)

    registry.register(
        "core.assign",
        assign,
        implementation_digest=_core_program_handler_digest("core.assign"),
    )
    registry.register(
        "core.emit",
        emit,
        implementation_digest=_core_program_handler_digest("core.emit"),
    )
    registry.register(
        "core.route",
        route,
        implementation_digest=_core_program_handler_digest("core.route"),
    )
    registry.register(
        "core.wait",
        wait,
        implementation_digest=_core_program_handler_digest("core.wait"),
    )
    registry.register(
        "core.return",
        finish,
        implementation_digest=_core_program_handler_digest("core.return"),
    )
    return registry


class ProgrammableMachineInterpreter:
    def __init__(self, program: ResearchProgram, handlers: ProgramHandlerRegistryPort) -> None:
        if not isinstance(program, ResearchProgram):
            raise TypeError("programmable interpreter requires ResearchProgram")
        if not isinstance(handlers, ProgramHandlerRegistryPort):
            raise TypeError("programmable interpreter requires ProgramHandlerRegistryPort")
        self.program = program
        self.handlers = handlers
        self.handler_binding_digest = program_handler_binding_digest(
            program,
            handlers,
        )

    def _state(self, snapshot: MachineSnapshot) -> dict[str, JsonValue]:
        root = _mapping(snapshot.state, "machine state")
        value = root.get(_PROGRAM_STATE_KEY)
        if value is None:
            raise ValueError("research program has not been started")
        state = _mapping(value, "research program state")
        if state.get("program_digest") != self.program.program_digest:
            raise ValueError("machine state belongs to a different ResearchProgram")
        return state

    def propose(self, command: MachineCommand, state: MachineSnapshot) -> TransitionProposal:
        if state.program.program_digest != self.program.program_digest:
            raise ValueError("MachineProgramRef does not match ResearchProgram")

        if command.kind == "program.start":
            root = _mapping(state.state, "machine state")
            if _PROGRAM_STATE_KEY in root:
                raise ValueError("research program is already started")
            payload = _mapping(command.payload, "program.start payload")
            initial_data = _mapping(payload.get("initial_data", {}), "program initial_data")
            program_state: JsonObject = {
                "program_digest": self.program.program_digest,
                "initial_data_digest": canonical_digest(initial_data),
                "cursor": self.program.entrypoint,
                "status": MachineStatus.RUNNABLE.value,
                "visits": {},
                "data": initial_data,
                "previous_value": None,
            }
            return TransitionProposal(
                machine_id=state.machine_id, command_id=command.command_id,
                base_revision=state.revision, state_delta={_PROGRAM_STATE_KEY: program_state},
                event_payloads=({"type": "research_program_started", "program_id": self.program.program_id,
                                 "kind": self.program.kind.value, "entrypoint": self.program.entrypoint},),
                accepted_status=MachineStatus.RUNNABLE,
            )

        current = self._state(state)
        if command.kind == "program.resume":
            if current.get("status") not in {MachineStatus.WAITING.value, MachineStatus.INTERRUPTED.value}:
                raise ValueError("only waiting/interrupted program can resume")
            updated = dict(current)
            updated["status"] = MachineStatus.RUNNABLE.value
            return TransitionProposal(
                machine_id=state.machine_id, command_id=command.command_id,
                base_revision=state.revision, state_delta={_PROGRAM_STATE_KEY: updated},
                event_payloads=({"type": "research_program_resumed"},),
                accepted_status=MachineStatus.RUNNABLE,
            )

        if command.kind != "program.step":
            raise ValueError(f"unsupported programmable-machine command: {command.kind}")
        if current.get("status") != MachineStatus.RUNNABLE.value:
            raise ValueError("research program must be runnable before stepping")

        cursor = _text(current.get("cursor"), "research program cursor")
        node = self.program.node(cursor)
        visits = _mapping(current.get("visits", {}), "program visits")
        visit = visits.get(cursor, 0)
        if type(visit) is not int or visit < 0:
            raise ValueError("program visit count is invalid")
        visit += 1
        data = _mapping(current.get("data", {}), "program data")
        result = self.handlers.resolve(node.operation)(ProgramNodeRequest(
            program=self.program, node=node, snapshot=state, payload=command.payload,
            data=data, previous_value=current.get("previous_value"), visit=visit,
        ))
        if not isinstance(result, ProgramNodeResult):
            raise TypeError("program handler must return ProgramNodeResult")

        merged = dict(data)
        merged.update(_mapping(result.state_update, "program state_update"))
        visits[cursor] = visit
        next_node = result.next_node if result.next_node is not None else node.next_node
        accepted = result.status or (MachineStatus.COMPLETED if next_node is None else MachineStatus.RUNNABLE)
        if result.wait_reason is not None and accepted is not MachineStatus.WAITING:
            raise ValueError("wait_reason requires WAITING status")
        if accepted in {MachineStatus.COMPLETED, MachineStatus.FAILED}:
            next_node = None
        elif accepted in {MachineStatus.RUNNABLE, MachineStatus.WAITING, MachineStatus.INTERRUPTED} and next_node is None:
            next_node = cursor
        if next_node is not None:
            self.program.node(next_node)

        initial_data_digest = require_sha256(
            _text(
                current.get("initial_data_digest"),
                "research program initial_data_digest",
            ),
            "research program initial_data_digest",
        )
        updated: JsonObject = {
            "program_digest": self.program.program_digest,
            "initial_data_digest": initial_data_digest,
            "cursor": next_node,
            "status": accepted.value,
            "visits": visits,
            "data": merged,
            "previous_value": result.value,
        }
        return TransitionProposal(
            machine_id=state.machine_id, command_id=command.command_id,
            base_revision=state.revision, state_delta={_PROGRAM_STATE_KEY: updated},
            emitted_commands=result.emitted_commands, output_refs=result.output_refs,
            event_payloads=({
                "type": "research_program_node_executed", "program_id": self.program.program_id,
                "node_id": cursor, "operation": node.operation, "visit": visit,
                "next_node": next_node, "status": accepted.value,
            }, *result.events),
            effect_intent_refs=result.effect_intent_refs, wait_reason=result.wait_reason,
            accepted_status=accepted, evidence_refs=result.evidence_refs,
            artifact_refs=result.artifact_refs,
            child_links=result.child_links,
        )


def programmable_machine_family(kind: MachineKind) -> MachineFamilyDescriptor:
    if kind not in PROGRAMMABLE_MACHINE_KINDS:
        raise ValueError(f"not a programmable research-machine kind: {kind}")
    return MachineFamilyDescriptor(
        family_id=(
            f"{kind.value}.program.v{PROGRAMMABLE_MACHINE_FAMILY_VERSION}"
        ),
        kind=kind,
        implementation_version=PROGRAMMABLE_MACHINE_FAMILY_VERSION,
        state_schema=(
            f"{kind.value}.program-state.v"
            f"{PROGRAMMABLE_MACHINE_STATE_SCHEMA_VERSION}"
        ),
        command_kinds=PROGRAM_COMMANDS,
    )


def programmable_machine_families() -> tuple[MachineFamilyDescriptor, ...]:
    return tuple(programmable_machine_family(kind) for kind in PROGRAMMABLE_MACHINE_KINDS)


__all__ = [
    "program_handler_binding_digest",
    "PROGRAM_COMMANDS", "PROGRAMMABLE_MACHINE_KINDS", "ProgramHandlerRegistry",
    "ProgramHandlerRegistryPort", "ProgramNode", "ProgramNodeRequest",
    "ProgramNodeResult", "ProgramOperationHandler", "ProgrammableMachineInterpreter",
    "ResearchProgram", "ResearchProgramBuilder", "core_program_handlers",
    "programmable_machine_family", "programmable_machine_families",
]
