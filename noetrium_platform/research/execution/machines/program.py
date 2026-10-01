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
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel.canonical import canonical_bytes, canonical_digest, freeze_json, require_sha256, thaw_json
from noetrium_platform.foundation.kernel.kernel.family import MachineFamilyDescriptor
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.kernel.json_value import JsonObject, JsonValue
from noetrium_platform.foundation.kernel.kernel.contracts import ChildMachineLink
from noetrium_platform.foundation.kernel.kernel.machine import (
    MachineCommand, MachineKind, MachineProgramRef, MachineSnapshot,
    MachineStateDelta, MachineStateMutation, MachineStatus, ProgramLock,
    STRUCTURED_STATE_DELTA_THRESHOLD_BYTES, TransitionProposal,
)

PROGRAM_COMMANDS = ("program.start", "program.step", "program.resume", "program.limit")
PROGRAMMABLE_MACHINE_FAMILY_VERSION = "1"
PROGRAMMABLE_MACHINE_STATE_SCHEMA_VERSION = "1"
PROGRAMMABLE_MACHINE_KINDS = (
    MachineKind.EXPERIMENT, MachineKind.RUN, MachineKind.RUNTIME,
    MachineKind.PARTICIPANT, MachineKind.MEMORY, MachineKind.ENVIRONMENT,
    MachineKind.EVALUATION, MachineKind.OPTIMIZATION, MachineKind.METHOD,
    MachineKind.ANALYSIS, MachineKind.PUBLICATION,
)
_PROGRAM_STATE_KEY = "_program"
# Platform-owned livelock detection. These are operational safety thresholds,
# not scientific budgets: they react only to explicit no-progress evidence.
PROGRAM_SAME_NO_PROGRESS_LIMIT = 3
PROGRAM_CONSECUTIVE_NO_PROGRESS_LIMIT = 8


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _mapping(value: object, field_name: str) -> Mapping[str, JsonValue]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


@dataclass(frozen=True, slots=True)
class ProgramNode:
    node_id: str
    operation: str
    configuration: JsonObject = field(default_factory=dict)
    next_node: str | None = None
    allowed_next_nodes: tuple[str, ...] = ()
    max_visits: int | None = None
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "program node_id"))
        object.__setattr__(self, "operation", _text(self.operation, "program operation"))
        if not isinstance(self.configuration, Mapping):
            raise TypeError("program node configuration must be an object")
        if self.next_node is not None:
            object.__setattr__(self, "next_node", _text(self.next_node, "program next_node"))
        if type(self.allowed_next_nodes) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.allowed_next_nodes
        ):
            raise TypeError("program node allowed_next_nodes must be a text tuple")
        if len(set(self.allowed_next_nodes)) != len(self.allowed_next_nodes):
            raise ValueError("program node allowed_next_nodes must be unique")
        if (
            self.next_node is not None
            and self.allowed_next_nodes
            and self.next_node not in self.allowed_next_nodes
        ):
            raise ValueError("program node next_node must belong to allowed_next_nodes")
        if self.max_visits is not None and (
            type(self.max_visits) is not int or self.max_visits < 1
        ):
            raise ValueError("program node max_visits must be a positive integer or None")
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
    _node_index: Mapping[str, ProgramNode] = field(
        init=False, repr=False, compare=False, metadata={"transient": True}
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("program_id", self.program_id), ("version", self.version),
            ("state_schema", self.state_schema), ("entrypoint", self.entrypoint),
        ):
            object.__setattr__(self, name, _text(value, f"research program {name}"))
        if not isinstance(self.kind, MachineKind):
            raise TypeError("research program kind must be MachineKind")
        if self.kind not in PROGRAMMABLE_MACHINE_KINDS:
            raise ValueError(f"unsupported programmable MachineKind: {self.kind.value}")
        if type(self.nodes) is not tuple or not self.nodes or any(
            not isinstance(node, ProgramNode) for node in self.nodes
        ):
            raise TypeError("research program nodes must be a non-empty ProgramNode tuple")
        node_map = {node.node_id: node for node in self.nodes}
        if len(node_map) != len(self.nodes):
            raise ValueError("research program node ids must be unique")
        if self.entrypoint not in node_map:
            raise ValueError("research program entrypoint does not exist")
        object.__setattr__(self, "_node_index", MappingProxyType(node_map))
        missing = sorted({
            target
            for node in self.nodes
            for target in (
                (() if node.next_node is None else (node.next_node,))
                + node.allowed_next_nodes
            )
            if target not in node_map
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
                "allowed_next_nodes": node.allowed_next_nodes,
                "max_visits": node.max_visits,
                "required_capabilities": node.required_capabilities,
            } for node in self.nodes),
        }))

    def node(self, node_id: str) -> ProgramNode:
        node_id = _text(node_id, "research program node_id")
        try:
            return self._node_index[node_id]
        except KeyError as exc:
            raise KeyError(node_id) from exc

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
        if not isinstance(kind, MachineKind) or kind not in PROGRAMMABLE_MACHINE_KINDS:
            raise ValueError("program builder requires a programmable MachineKind")
        self._kind = kind
        self._version = _text(version, "program version")
        self._state_schema = _text(state_schema, "program state_schema")
        self._entrypoint = _text(entrypoint, "program entrypoint")
        self._required_capabilities = required_capabilities
        self._nodes: list[ProgramNode] = []

    def node(self, node_id: str, operation: str, *, configuration: JsonObject | None = None,
             next_node: str | None = None,
             allowed_next_nodes: tuple[str, ...] = (),
             max_visits: int | None = None,
             required_capabilities: tuple[str, ...] = ()) -> "ResearchProgramBuilder":
        self._nodes.append(ProgramNode(
            node_id=node_id, operation=operation,
            configuration={} if configuration is None else configuration,
            next_node=next_node,
            allowed_next_nodes=allowed_next_nodes,
            max_visits=max_visits,
            required_capabilities=required_capabilities,
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
    visit_counts: Mapping[str, int] = field(default_factory=dict)
    checkpoint_value: JsonValue = None
    semantic_state: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.program, ResearchProgram) or not isinstance(self.node, ProgramNode):
            raise TypeError("program node request requires program and node")
        if not isinstance(self.snapshot, MachineSnapshot):
            raise TypeError("program node request requires MachineSnapshot")
        if type(self.visit) is not int or self.visit <= 0:
            raise ValueError("program node request visit must be positive")
        if not isinstance(self.visit_counts, Mapping) or any(
            type(key) is not str
            or not key.strip()
            or type(count) is not int
            or count < 0
            for key, count in self.visit_counts.items()
        ):
            raise TypeError("program node request visit_counts must be a non-negative mapping")
        object.__setattr__(self, "visit_counts", freeze_json(self.visit_counts))
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "data", freeze_json(self.data))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))
        object.__setattr__(self, "checkpoint_value", freeze_json(self.checkpoint_value))
        if not isinstance(self.semantic_state, Mapping):
            raise TypeError("program node request semantic_state must be an object")
        object.__setattr__(self, "semantic_state", freeze_json(self.semantic_state))


@dataclass(frozen=True, slots=True)
class ProgramNodeResult:
    value: JsonValue = None
    state_update: JsonObject = field(default_factory=dict)
    next_node: str | None = None
    status: MachineStatus | None = None
    wait_reason: str | None = None
    checkpoint_requested: bool = False
    checkpoint_value: JsonValue = None
    semantic_state_update: JsonObject = field(default_factory=dict)
    emitted_commands: tuple[MachineCommand, ...] = ()
    events: tuple[JsonValue, ...] = ()
    output_refs: tuple[str, ...] = ()
    effect_intent_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    child_links: tuple[ChildMachineLink, ...] = ()
    progress: bool | None = None
    progress_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state_update, Mapping):
            raise TypeError("program node state_update must be an object")
        if self.next_node is not None:
            object.__setattr__(self, "next_node", _text(self.next_node, "program result next_node"))
        if self.status is not None and not isinstance(self.status, MachineStatus):
            raise TypeError("program node status must be MachineStatus")
        if self.wait_reason is not None:
            object.__setattr__(self, "wait_reason", _text(self.wait_reason, "program wait_reason"))
        if type(self.checkpoint_requested) is not bool:
            raise TypeError("program checkpoint_requested must be boolean")
        if not isinstance(self.semantic_state_update, Mapping):
            raise TypeError("program semantic_state_update must be an object")
        if type(self.child_links) is not tuple or any(
            not isinstance(item, ChildMachineLink) for item in self.child_links
        ):
            raise TypeError("program child_links must be ChildMachineLink tuple")
        if self.progress is not None and type(self.progress) is not bool:
            raise TypeError("program progress must be boolean or None")
        if self.progress_fingerprint is not None:
            require_sha256(
                self.progress_fingerprint,
                "program progress_fingerprint",
            )
        if self.progress is None and self.progress_fingerprint is not None:
            raise ValueError(
                "program progress_fingerprint requires an explicit progress signal"
            )
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "state_update", freeze_json(self.state_update))
        object.__setattr__(self, "checkpoint_value", freeze_json(self.checkpoint_value))
        object.__setattr__(
            self,
            "semantic_state_update",
            freeze_json(self.semantic_state_update),
        )
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
        self._handlers: Mapping[str, tuple[ProgramOperationHandler, str]] = {}
        self._lock = RLock()
        self._sealed = False
        self._operations: tuple[str, ...] | None = None
        self._identity_digest: str | None = None

    @property
    def sealed(self) -> bool:
        return self._sealed

    def seal(self) -> "ProgramHandlerRegistry":
        with self._lock:
            if self._sealed:
                return self
            ordered = tuple(sorted(self._handlers.items()))
            self._operations = tuple(operation for operation, _ in ordered)
            self._identity_digest = canonical_digest(tuple(
                (operation, implementation_digest)
                for operation, (_, implementation_digest) in ordered
            ))
            self._handlers = MappingProxyType(dict(ordered))
            self._sealed = True
            return self

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
            if self._sealed:
                raise RuntimeError("program handler registry is sealed")
            current = self._handlers.get(operation)
            if current is not None and current != value:
                raise ValueError(f"program operation already registered: {operation}")
            self._handlers[operation] = value

    def resolve(self, operation: str) -> ProgramOperationHandler:
        operation = _text(operation, "program operation")
        if self._sealed:
            try:
                return self._handlers[operation][0]
            except KeyError as exc:
                raise KeyError(f"unbound research-program operation: {operation}") from exc
        with self._lock:
            try:
                return self._handlers[operation][0]
            except KeyError as exc:
                raise KeyError(f"unbound research-program operation: {operation}") from exc

    def implementation_digest(self, operation: str) -> str:
        operation = _text(operation, "program operation")
        if self._sealed:
            try:
                return self._handlers[operation][1]
            except KeyError as exc:
                raise KeyError(f"unbound research-program operation: {operation}") from exc
        with self._lock:
            try:
                return self._handlers[operation][1]
            except KeyError as exc:
                raise KeyError(f"unbound research-program operation: {operation}") from exc

    def operations(self) -> tuple[str, ...]:
        if self._sealed:
            assert self._operations is not None
            return self._operations
        with self._lock:
            return tuple(sorted(self._handlers))

    @property
    def identity_digest(self) -> str:
        if self._sealed:
            assert self._identity_digest is not None
            return self._identity_digest
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


def _core_program_handler_digest(operation: str, *, revision: int = 1) -> str:
    if type(revision) is not int or revision < 1:
        raise ValueError("core program handler revision must be positive")
    return canonical_digest({
        "handler_family": "core-program",
        "operation": operation,
        "implementation_revision": revision,
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
        if "value" in config:
            value = config["value"]
        elif request.payload is not None:
            value = request.payload
        else:
            value = request.previous_value
        return ProgramNodeResult(value=value, status=MachineStatus.COMPLETED)

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
        implementation_digest=_core_program_handler_digest("core.return", revision=2),
    )
    return registry


class ProgrammableMachineInterpreter:
    def __init__(
        self,
        program: ResearchProgram,
        handlers: ProgramHandlerRegistryPort,
        *,
        handler_binding_digest: str | None = None,
    ) -> None:
        if not isinstance(program, ResearchProgram):
            raise TypeError("programmable interpreter requires ResearchProgram")
        if not isinstance(handlers, ProgramHandlerRegistryPort):
            raise TypeError("programmable interpreter requires ProgramHandlerRegistryPort")
        self.program = program
        if isinstance(handlers, ProgramHandlerRegistry):
            handlers.seal()
        self.handlers = handlers
        if handler_binding_digest is None:
            handler_binding_digest = program_handler_binding_digest(
                program,
                handlers,
            )
        else:
            handler_binding_digest = require_sha256(
                handler_binding_digest,
                "program handler_binding_digest",
            )
        self.handler_binding_digest = handler_binding_digest

    def _state(self, snapshot: MachineSnapshot) -> Mapping[str, JsonValue]:
        value = snapshot.state.get(_PROGRAM_STATE_KEY)
        if value is None:
            raise ValueError("research program has not been started")
        state = _mapping(value, "research program state")
        if state.get("program_digest") != self.program.program_digest:
            raise ValueError("machine state belongs to a different ResearchProgram")
        return state

    def _resolve_dynamic_next_node(self, node: ProgramNode, requested: str) -> str:
        """Resolve handler-selected nodes, including RuntimeModule-local ids.

        Static module edges are namespace-qualified by RuntimeProgramComposer at
        compile time. Dynamic handler edges cannot be known then, so a handler
        may return a local node id and the interpreter resolves it against the
        module metadata injected by the composer. Exact global ids always win.
        """
        requested = _text(requested, "program dynamic next_node")
        try:
            self.program.node(requested)
            return requested
        except KeyError as original:
            configuration = node.configuration
            if isinstance(configuration, Mapping):
                module_id = configuration.get("runtime_module")
                if type(module_id) is str and module_id.strip():
                    qualified = f"{module_id}.{requested}"
                    try:
                        self.program.node(qualified)
                    except KeyError:
                        pass
                    else:
                        return qualified
            raise original

    def _failure_proposal(
        self,
        command: MachineCommand,
        state: MachineSnapshot,
        current: Mapping[str, JsonValue],
        *,
        code: str,
        message: str,
        cursor: str | None = None,
        visit: int | None = None,
        error_digest: str | None = None,
        extra_events: tuple[JsonValue, ...] = (),
        effect_intent_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
        child_links: tuple[ChildMachineLink, ...] = (),
    ) -> TransitionProposal:
        failure = {
            "code": code,
            "message": message,
            "error_digest": error_digest,
            "cursor": cursor,
            "visit": visit,
        }
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta=MachineStateDelta((
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "cursor"),
                    None,
                ),
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "semantic", "program_failure"),
                    failure,
                ),
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "status"),
                    MachineStatus.FAILED.value,
                ),
            )),
            event_payloads=({
                "type": "research_program_failed",
                "program_id": self.program.program_id,
                **failure,
            }, *extra_events),
            effect_intent_refs=effect_intent_refs,
            accepted_status=MachineStatus.FAILED,
            evidence_refs=evidence_refs,
            artifact_refs=artifact_refs,
            child_links=child_links,
        )

    def propose(self, command: MachineCommand, state: MachineSnapshot) -> TransitionProposal:
        if state.program.program_digest != self.program.program_digest:
            raise ValueError("MachineProgramRef does not match ResearchProgram")

        if command.kind == "program.start":
            root = state.state
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
                "checkpoint_value": None,
                "semantic": {},
                "progress_watchdog": {
                    "consecutive_no_progress": 0,
                    "same_fingerprint": 0,
                    "last_fingerprint": None,
                },
            }
            return TransitionProposal(
                machine_id=state.machine_id, command_id=command.command_id,
                base_revision=state.revision,
                state_delta=MachineStateDelta.set(
                    (_PROGRAM_STATE_KEY,),
                    program_state,
                ),
                event_payloads=({"type": "research_program_started", "program_id": self.program.program_id,
                                 "kind": self.program.kind.value, "entrypoint": self.program.entrypoint},),
                accepted_status=MachineStatus.RUNNABLE,
            )

        current = self._state(state)
        if command.kind == "program.limit":
            if current.get("status") != MachineStatus.RUNNABLE.value:
                raise ValueError("program.limit requires a runnable program")
            return self._failure_proposal(
                command,
                state,
                current,
                code="program.step_limit",
                message="research program exceeded its bounded step limit",
                cursor=(
                    str(current.get("cursor"))
                    if current.get("cursor") is not None
                    else None
                ),
            )
        if command.kind == "program.resume":
            if current.get("status") not in {MachineStatus.WAITING.value, MachineStatus.INTERRUPTED.value}:
                raise ValueError("only waiting/interrupted program can resume")
            return TransitionProposal(
                machine_id=state.machine_id, command_id=command.command_id,
                base_revision=state.revision,
                state_delta=MachineStateDelta.set(
                    (_PROGRAM_STATE_KEY, "status"),
                    MachineStatus.RUNNABLE.value,
                ),
                event_payloads=({"type": "research_program_resumed"},),
                accepted_status=MachineStatus.RUNNABLE,
            )

        if command.kind != "program.step":
            raise ValueError(f"unsupported programmable-machine command: {command.kind}")
        if current.get("status") != MachineStatus.RUNNABLE.value:
            raise ValueError("research program must be runnable before stepping")

        cursor = _text(current.get("cursor"), "research program cursor")
        node = self.program.node(cursor)
        visits = dict(_mapping(current.get("visits", {}), "program visits"))
        visit = visits.get(cursor, 0)
        if type(visit) is not int or visit < 0:
            raise ValueError("program visit count is invalid")
        visit += 1
        if node.max_visits is not None and visit > node.max_visits:
            return self._failure_proposal(
                command,
                state,
                current,
                code="program.node_visit_limit",
                message=(
                    f"program node visit limit reached: {node.node_id} "
                    f"({visit}>{node.max_visits})"
                ),
                cursor=node.node_id,
                visit=visit,
            )
        data = _mapping(current.get("data", {}), "program data")
        request = ProgramNodeRequest(
            program=self.program, node=node, snapshot=state, payload=command.payload,
            data=data, previous_value=current.get("previous_value"), visit=visit,
            visit_counts=visits,
            checkpoint_value=current.get("checkpoint_value"),
            semantic_state=_mapping(
                current.get("semantic", {}),
                "program semantic state",
            ),
        )
        try:
            result = self.handlers.resolve(node.operation)(request)
            if not isinstance(result, ProgramNodeResult):
                raise TypeError("program handler must return ProgramNodeResult")
        except BaseException as exc:
            description = describe_exception(exc)
            cause = exc.__cause__
            cause_description = (
                None if cause is None else describe_exception(cause)
            )
            message = (
                f"{description.qualified_type}: "
                f"{description.safe_message}"
            )
            if cause_description is not None:
                message += (
                    " <- caused by "
                    f"{cause_description.qualified_type}: "
                    f"{cause_description.safe_message}"
                )
            return self._failure_proposal(
                command,
                state,
                current,
                code="program.node_exception",
                message=message,
                cursor=node.node_id,
                visit=visit,
                error_digest=description.error_digest,
            )

        raw_watchdog = _mapping(
            current.get("progress_watchdog", {}),
            "program progress watchdog",
        )
        consecutive_no_progress = int(
            raw_watchdog.get("consecutive_no_progress", 0)
        )
        same_fingerprint = int(raw_watchdog.get("same_fingerprint", 0))
        last_fingerprint = raw_watchdog.get("last_fingerprint")
        if last_fingerprint is not None and type(last_fingerprint) is not str:
            raise TypeError("program progress watchdog fingerprint is invalid")
        if result.progress is True:
            progress_watchdog = {
                "consecutive_no_progress": 0,
                "same_fingerprint": 0,
                "last_fingerprint": None,
            }
        elif result.progress is False:
            fingerprint = result.progress_fingerprint or canonical_digest({
                "program_digest": self.program.program_digest,
                "node_id": cursor,
                "operation": node.operation,
                "effect_intent_refs": result.effect_intent_refs,
                "value": result.value,
            })
            consecutive_no_progress += 1
            same_fingerprint = (
                same_fingerprint + 1
                if fingerprint == last_fingerprint
                else 1
            )
            progress_watchdog = {
                "consecutive_no_progress": consecutive_no_progress,
                "same_fingerprint": same_fingerprint,
                "last_fingerprint": fingerprint,
            }
            if (
                same_fingerprint >= PROGRAM_SAME_NO_PROGRESS_LIMIT
                or consecutive_no_progress >= PROGRAM_CONSECUTIVE_NO_PROGRESS_LIMIT
            ):
                return self._failure_proposal(
                    command,
                    state,
                    current,
                    code="program.no_progress_livelock",
                    message=(
                        "research program made no verified progress across "
                        "repeated effect attempts"
                    ),
                    cursor=node.node_id,
                    visit=visit,
                    extra_events=result.events,
                    effect_intent_refs=result.effect_intent_refs,
                    evidence_refs=result.evidence_refs,
                    artifact_refs=result.artifact_refs,
                    child_links=result.child_links,
                )
        else:
            progress_watchdog = dict(raw_watchdog)

        state_update = _mapping(
            result.state_update,
            "program state_update",
        )
        semantic_update = _mapping(
            result.semantic_state_update,
            "program semantic_state_update",
        )
        next_node = (
            self._resolve_dynamic_next_node(node, result.next_node)
            if result.next_node is not None
            else node.next_node
        )
        accepted = result.status or (MachineStatus.COMPLETED if next_node is None else MachineStatus.RUNNABLE)
        if result.wait_reason is not None and accepted is not MachineStatus.WAITING:
            raise ValueError("wait_reason requires WAITING status")
        if accepted in {MachineStatus.COMPLETED, MachineStatus.FAILED}:
            next_node = None
        elif accepted in {MachineStatus.RUNNABLE, MachineStatus.WAITING, MachineStatus.INTERRUPTED} and next_node is None:
            next_node = cursor
        if next_node is not None:
            self.program.node(next_node)
            if node.allowed_next_nodes and next_node not in node.allowed_next_nodes:
                return self._failure_proposal(
                    command,
                    state,
                    current,
                    code="program.invalid_transition",
                    message=(
                        "program node selected non-adjacent next node: "
                        + next_node
                    ),
                    cursor=node.node_id,
                    visit=visit,
                )

        if (
            len(canonical_bytes(state.state))
            <= STRUCTURED_STATE_DELTA_THRESHOLD_BYTES
        ):
            merged = dict(data)
            merged.update(state_update)
            semantic = dict(
                _mapping(
                    current.get("semantic", {}),
                    "program semantic state",
                )
            )
            semantic.update(semantic_update)
            visits[cursor] = visit
            updated: JsonObject = {
                "program_digest": self.program.program_digest,
                "initial_data_digest": current["initial_data_digest"],
                "cursor": next_node,
                "status": accepted.value,
                "visits": visits,
                "data": merged,
                "previous_value": result.value,
                "checkpoint_value": (
                    result.checkpoint_value
                    if (
                        result.checkpoint_requested
                        or result.checkpoint_value is not None
                    )
                    else current.get("checkpoint_value")
                ),
                "semantic": semantic,
                "progress_watchdog": progress_watchdog,
            }
            state_delta = MachineStateDelta.set(
                (_PROGRAM_STATE_KEY,),
                updated,
            )
        else:
            granular_delta = [
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "cursor"),
                    next_node,
                ),
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "previous_value"),
                    result.value,
                ),
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "status"),
                    accepted.value,
                ),
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "visits", cursor),
                    visit,
                ),
            ]
            granular_delta.extend(
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "data", key),
                    value,
                )
                for key, value in state_update.items()
            )
            granular_delta.extend(
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "semantic", key),
                    value,
                )
                for key, value in semantic_update.items()
            )
            granular_delta.append(
                MachineStateMutation.set(
                    (_PROGRAM_STATE_KEY, "progress_watchdog"),
                    progress_watchdog,
                )
            )
            if (
                result.checkpoint_requested
                or result.checkpoint_value is not None
            ):
                granular_delta.append(
                    MachineStateMutation.set(
                        (_PROGRAM_STATE_KEY, "checkpoint_value"),
                        result.checkpoint_value,
                    )
                )
            state_delta = MachineStateDelta(tuple(granular_delta))
        return TransitionProposal(
            machine_id=state.machine_id, command_id=command.command_id,
            base_revision=state.revision,
            state_delta=state_delta,
            emitted_commands=result.emitted_commands, output_refs=result.output_refs,
            event_payloads=({
                "type": "research_program_node_executed", "program_id": self.program.program_id,
                "node_id": cursor, "operation": node.operation, "visit": visit,
                "next_node": next_node, "status": accepted.value,
                "checkpoint_requested": result.checkpoint_requested,
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
