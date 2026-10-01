from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import inspect
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonInput,
    JsonValue,
    MachineKind,
    MachineStatus,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.research.execution.machines.api import (
    ChildResearchMachineExecution,
    ChildResearchMachineRequest,
    ResearchProgramBuilder as MachineResearchProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram as MachineResearchProgram,
)
from noetrium_platform.research.execution.workflow.api import (
    environment_action_capability_payload,
)
from noetrium_platform.capabilities.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.research.execution.workflow.api.method_machine import (
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
    MethodRuntimePort,
)


@dataclass(frozen=True, slots=True)
class ResearchEvent:
    kind: str
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or not self.kind.strip():
            raise ValueError("research event kind must be non-empty")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class ResearchComponentResult:
    status: str
    result: JsonValue
    component_instance_id: str
    _execution: ChildResearchMachineExecution = field(
        repr=False,
        compare=False,
    )

    @property
    def failed(self) -> bool:
        return self.status == MachineStatus.FAILED.value

    @property
    def runnable(self) -> bool:
        return self.status in {
            MachineStatus.RUNNABLE.value,
            MachineStatus.WAITING.value,
        }


class MemoryScope(StrEnum):
    """Durable scope for one Method-owned Memory Machine instance."""

    METHOD = "method"
    STUDY = "study"
    RUN = "run"
    TASK = "task"
    LIFETIME = "lifetime"
    CONDITION = "condition"
    REPETITION = "repetition"
    DECISION = "decision"
    BRANCH = "branch"
    PARTICIPANT = "participant"
    TENANT = "tenant"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class ResearchMethodCall:
    node_id: str
    visit: int
    state: Mapping[str, JsonValue]
    input_value: JsonValue
    previous_value: JsonValue
    effect_receipts: tuple[Mapping[str, JsonValue], ...]
    run_id: str
    trace_id: str
    study_id: str | None
    condition_id: str | None
    condition_selections: tuple[tuple[str, str], ...]
    intervention_values: tuple[tuple[str, JsonValue], ...]
    assignment_seed: str | None
    repetition: int | None
    participant_context: Mapping[str, JsonValue]
    replay_level: str | None
    trial_budget: Mapping[str, JsonValue]
    lifetime_id: str | None
    branch_id: str | None
    task_id: str | None
    decision_cycle_id: str | None
    checkpoint_id: str | None
    operation_id: str | None
    component_id: str | None
    execution_tenant_id: str | None
    parent_machine_id: str | None
    checkpoint: JsonValue
    _request: MethodNodeRequest = field(repr=False, compare=False)

    @classmethod
    def _from_internal(cls, request: MethodNodeRequest) -> "ResearchMethodCall":
        return cls(
            node_id=request.node_id,
            visit=request.visit,
            state=request.state,
            input_value=request.input_value,
            previous_value=request.previous_value,
            effect_receipts=tuple(
                {
                    "effect_id": receipt.effect_id,
                    "request_digest": receipt.request_digest,
                    "effect_class": receipt.effect_class.value,
                    "certainty": receipt.certainty.value,
                    "provider_instance_id": receipt.provider_instance_id,
                    "verification_required": receipt.verification_required,
                    "before_artifact": receipt.before_artifact,
                    "after_artifact": receipt.after_artifact,
                    "provider_receipt": receipt.provider_receipt,
                }
                for receipt in request.effect_receipts
            ),
            run_id=request.context.run_id,
            trace_id=request.context.trace_id,
            study_id=request.context.study_id,
            condition_id=request.context.condition_id,
            condition_selections=request.context.condition_selections,
            intervention_values=request.context.intervention_values,
            assignment_seed=request.context.assignment_seed,
            repetition=request.context.repetition,
            participant_context=request.context.participant_context,
            replay_level=request.context.replay_level,
            trial_budget=request.context.trial_budget,
            lifetime_id=request.context.lifetime_id,
            branch_id=request.context.branch_id,
            task_id=request.context.task_id,
            decision_cycle_id=request.context.decision_cycle_id,
            checkpoint_id=request.context.checkpoint_id,
            operation_id=request.context.operation_id,
            component_id=request.context.component_id,
            execution_tenant_id=request.context.execution_tenant_id,
            parent_machine_id=request.parent_machine_id,
            checkpoint=request.checkpoint,
            _request=request,
        )

    def memory_scope_identity(
        self,
        scope: MemoryScope | str,
        *,
        scope_key: JsonValue = None,
    ) -> dict[str, JsonValue]:
        """Resolve one deterministic Method-owned memory lifetime identity.

        The child-runtime identity isolates identical logical memory names
        across different frozen Method implementations. Standard scopes are
        derived only from immutable ExecutionContext identities; participant
        and custom scopes require an explicit paper-owned key.
        """

        try:
            resolved = scope if isinstance(scope, MemoryScope) else MemoryScope(scope)
        except ValueError as exc:
            raise ValueError(f"unknown memory scope: {scope!r}") from exc

        context_key: JsonValue
        if resolved is MemoryScope.METHOD:
            context_key = "method"
        elif resolved is MemoryScope.STUDY:
            context_key = self.study_id
        elif resolved is MemoryScope.RUN:
            context_key = self.run_id
        elif resolved is MemoryScope.TASK:
            context_key = self.task_id
        elif resolved is MemoryScope.LIFETIME:
            context_key = self.lifetime_id
        elif resolved is MemoryScope.CONDITION:
            context_key = self.condition_id
        elif resolved is MemoryScope.REPETITION:
            context_key = {
                "study_id": self.study_id,
                "run_id": self.run_id,
                "assignment_seed": self.assignment_seed,
                "repetition": self.repetition,
            }
        elif resolved is MemoryScope.DECISION:
            context_key = {
                "run_id": self.run_id,
                "task_id": self.task_id,
                "decision_cycle_id": self.decision_cycle_id,
            }
        elif resolved is MemoryScope.BRANCH:
            context_key = self.branch_id
        elif resolved is MemoryScope.TENANT:
            context_key = self.execution_tenant_id
        elif resolved in {MemoryScope.PARTICIPANT, MemoryScope.CUSTOM}:
            context_key = scope_key
        else:  # pragma: no cover - enum exhaustiveness
            raise AssertionError(resolved)

        if resolved not in {MemoryScope.PARTICIPANT, MemoryScope.CUSTOM} and scope_key is not None:
            raise ValueError(
                f"memory scope {resolved.value!r} derives its identity from ExecutionContext"
            )
        if context_key is None:
            raise ValueError(
                f"memory scope {resolved.value!r} is unavailable in this execution context"
            )

        child_runtime = self._request.child_machines
        if child_runtime is None:
            raise RuntimeError(
                "memory scope identity requires the Method component runtime"
            )
        return {
            "schema": "noetrium.method-memory-scope.v1",
            "scope": resolved.value,
            "scope_key": freeze_json(context_key),
            "component_runtime_digest": child_runtime.identity_digest,
        }

    def memory_component_identity(
        self,
        *,
        host_id: str,
        memory_id: str,
        scope: MemoryScope | str,
        scope_key: JsonValue = None,
    ) -> tuple[str, dict[str, JsonValue]]:
        """Resolve the stable durable identity for one Method-owned memory."""

        if type(memory_id) is not str or not memory_id.strip():
            raise ValueError("research memory_id must be non-empty")
        if type(host_id) is not str or not host_id.strip():
            raise ValueError("research memory host_id must be non-empty")
        identity = self.memory_scope_identity(scope, scope_key=scope_key)
        logical_identity = {
            "memory_id": memory_id.strip(),
            "host_id": host_id.strip(),
            "scope": identity,
        }
        component_instance_id = (
            "memory:"
            + memory_id.strip()
            + ":"
            + canonical_digest(logical_identity)[:24]
        )
        return component_instance_id, logical_identity

    def memory_component(
        self,
        *,
        host_id: str,
        memory_id: str,
        scope: MemoryScope | str,
        initial_data: Mapping[str, JsonValue],
        payload: JsonValue = None,
        scope_key: JsonValue = None,
        command_id_prefix: str | None = None,
    ) -> "ResearchComponentResult":
        """Step one durable Method-owned Memory Machine with explicit scope."""

        component_instance_id, logical_identity = self.memory_component_identity(
            host_id=host_id,
            memory_id=memory_id,
            scope=scope,
            scope_key=scope_key,
        )
        return self.component(
            host_id=host_id.strip(),
            component_instance_id=component_instance_id,
            instance_identity=logical_identity,
            initial_data=initial_data,
            payload=payload,
            command_id_prefix=command_id_prefix,
        )

    def environment_action(
        self,
        action_type: str,
        payload: JsonInput,
    ) -> dict[str, JsonInput]:
        return environment_action_capability_payload(action_type, payload)

    def describe_capability(self, capability_id: str) -> dict[str, JsonValue]:
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("research method capability_id must be non-empty")
        capabilities = self._request.capabilities
        if capabilities is None:
            raise RuntimeError(
                "research method describe_capability() requires capability runtime"
            )
        descriptor = capabilities.describe(capability_id)
        return {
            "capability_id": descriptor.capability_id,
            "interface_version": descriptor.interface_version,
            "request_schema": descriptor.request_schema,
            "result_schema": descriptor.result_schema,
            "effect_class": descriptor.effect_class.value,
            "deterministic": descriptor.deterministic,
            "metadata": descriptor.metadata,
        }

    def event(self, kind: str, payload: JsonInput = None) -> "ResearchEvent":
        return ResearchEvent(kind, payload)

    def transition(
        self,
        *,
        value: JsonInput = None,
        state_update: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
        checkpoint: bool = False,
        checkpoint_value: JsonInput = None,
        events: tuple["ResearchEvent", ...] = (),
        children: tuple["ResearchComponentResult", ...] = (),
    ) -> "ResearchMethodTransition":
        return ResearchMethodTransition(
            value=value,
            state_update={} if state_update is None else state_update,
            next_node=next_node,
            checkpoint=checkpoint,
            checkpoint_value=checkpoint_value,
            events=events,
            components=children,
        )

    def component(
        self,
        *,
        host_id: str,
        component_instance_id: str,
        instance_identity: JsonValue,
        initial_data: Mapping[str, JsonValue],
        payload: JsonValue = None,
        command_id_prefix: str | None = None,
    ) -> ResearchComponentResult:
        request = self._request
        if request.child_machines is None or request.parent_machine_id is None:
            raise RuntimeError(
                "research method component() requires the Method component runtime"
            )
        execution = request.child_machines.step_once(
            ChildResearchMachineRequest(
                host_id=host_id,
                parent_machine_id=request.parent_machine_id,
                child_machine_id=component_instance_id,
                instance_identity=instance_identity,
                initial_data=dict(initial_data),
                payload=payload,
                command_id_prefix=command_id_prefix,
            )
        )
        if not isinstance(execution, ChildResearchMachineExecution):
            raise TypeError("Method component runtime returned invalid execution")
        return ResearchComponentResult(
            execution.status.value,
            execution.result,
            execution.link.child_machine_id,
            execution,
        )


@dataclass(frozen=True, slots=True)
class ResearchMethodTransition:
    value: JsonValue = None
    state_update: Mapping[str, JsonValue] = field(default_factory=dict)
    next_node: str | None = None
    checkpoint: bool = False
    checkpoint_value: JsonValue = None
    events: tuple[ResearchEvent, ...] = ()
    components: tuple[ResearchComponentResult, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state_update, Mapping):
            raise TypeError("research method state_update must be a mapping")
        if type(self.checkpoint) is not bool:
            raise TypeError("research method checkpoint must be boolean")
        if self.next_node is not None and (
            type(self.next_node) is not str or not self.next_node.strip()
        ):
            raise ValueError("research method next_node must be non-empty")
        if type(self.events) is not tuple or any(
            type(row) is not ResearchEvent for row in self.events
        ):
            raise TypeError("research method events must be ResearchEvent tuple")
        if type(self.components) is not tuple or any(
            type(row) is not ResearchComponentResult for row in self.components
        ):
            raise TypeError(
                "research method components must be ResearchComponentResult tuple"
            )


def _handler_digest(handler: Callable[..., object]) -> str:
    if not callable(handler):
        raise TypeError("research component handler must be callable")
    module = getattr(handler, "__module__", "")
    qualname = getattr(handler, "__qualname__", "")
    if not module or not qualname or "<locals>" in qualname or "<lambda>" in qualname:
        raise ValueError("research component handler must be a named module-level callable")
    try:
        source = inspect.getsource(handler)
    except (OSError, TypeError) as exc:
        raise ValueError("research component handler source cannot be resolved") from exc
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    return canonical_digest({
        "module": module,
        "qualname": qualname,
        "source_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    })


@dataclass(frozen=True, slots=True)
class ResearchComponentCall:
    payload: JsonValue
    data: Mapping[str, JsonValue]
    previous_value: JsonValue
    visit: int
    _request: ProgramNodeRequest = field(repr=False, compare=False)

    @classmethod
    def _from_internal(cls, request: ProgramNodeRequest) -> "ResearchComponentCall":
        return cls(
            payload=request.payload,
            data=request.data,
            previous_value=request.previous_value,
            visit=request.visit,
            _request=request,
        )

    def transition(
        self,
        *,
        value: JsonInput = None,
        state_update: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
        events: tuple[JsonValue, ...] = (),
    ) -> "ResearchComponentTransition":
        return ResearchComponentTransition(
            value=value,
            state_update={} if state_update is None else state_update,
            next_node=next_node,
            events=events,
        )


@dataclass(frozen=True, slots=True)
class ResearchComponentTransition:
    value: JsonValue = None
    state_update: Mapping[str, JsonValue] = field(default_factory=dict)
    next_node: str | None = None
    events: tuple[JsonValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchComponent:
    host_id: str
    domain: MachineKind
    program: MachineResearchProgram = field(repr=False)
    operations: tuple[ResearchHostOperation, ...] = field(repr=False)
    artifact_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.host_id) is not str or not self.host_id.strip():
            raise ValueError("research component host_id must be non-empty")
        if not isinstance(self.domain, MachineKind) or self.domain not in _METHOD_COMPONENT_KINDS:
            raise ValueError(
                "research component domain must belong to the Method harness: "
                "runtime/participant/memory/environment/optimization"
            )
        if not isinstance(self.program, MachineResearchProgram):
            raise TypeError("research component requires Machine ResearchProgram")
        if self.program.kind is not self.domain:
            raise ValueError("research component domain must match program kind")
        if type(self.operations) is not tuple or any(
            not isinstance(row, ResearchHostOperation) for row in self.operations
        ):
            raise TypeError("research component operations must be ResearchHostOperation tuple")
        identities = tuple(
            sorted((row.operation, row.implementation_digest) for row in self.operations)
        )
        if len({name for name, _digest in identities}) != len(identities):
            raise ValueError("research component operations must be unique")
        object.__setattr__(
            self,
            "artifact_digest",
            canonical_digest({
                "host_id": self.host_id,
                "domain": self.domain.value,
                "program_digest": self.program.program_digest,
                "operations": identities,
            }),
        )


@dataclass(frozen=True, slots=True)
class ResearchMethod:
    program: MethodProgram = field(repr=False)
    components: tuple[ResearchComponent, ...] = ()
    artifact_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.program, MethodProgram):
            raise TypeError("research method requires MethodProgram")
        if type(self.components) is not tuple or any(
            type(row) is not ResearchComponent for row in self.components
        ):
            raise TypeError("research method components must be ResearchComponent tuple")
        components = tuple(
            sorted(self.components, key=lambda row: (row.domain.value, row.host_id))
        )
        if len({row.host_id for row in components}) != len(components):
            raise ValueError("research method component host ids must be unique")
        object.__setattr__(self, "components", components)
        object.__setattr__(
            self,
            "artifact_digest",
            canonical_digest({
                "method_program_digest": self.program.program_digest,
                "component_artifacts": tuple(
                    (row.domain.value, row.artifact_digest) for row in components
                ),
            }),
        )

    @property
    def method_program_digest(self) -> str:
        return self.program.program_digest

    @property
    def program_digest(self) -> str:
        return self.artifact_digest

    @property
    def implementation_digest(self) -> str:
        return self.artifact_digest


_METHOD_COMPONENT_KINDS = frozenset({
    MachineKind.RUNTIME,
    MachineKind.PARTICIPANT,
    MachineKind.MEMORY,
    MachineKind.ENVIRONMENT,
    MachineKind.OPTIMIZATION,
})


class ResearchComponentBuilder:
    """Method-owned component authoring over the shared Machine kernel."""

    def __init__(
        self,
        parent: "ResearchMethodBuilder",
        host_id: str,
        *,
        domain: str,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
        required_capabilities: tuple[str, ...] = (),
    ) -> None:
        if type(host_id) is not str or not host_id.strip():
            raise ValueError("research component host_id must be non-empty")
        try:
            kind = MachineKind(domain)
        except ValueError as exc:
            raise ValueError(f"unknown research component domain: {domain!r}") from exc
        if kind not in _METHOD_COMPONENT_KINDS:
            raise ValueError(
                "Method-owned component domain must be one of "
                "runtime/participant/memory/environment/optimization"
            )
        self._parent = parent
        self._host_id = host_id.strip()
        self._domain = kind
        if required_capabilities:
            raise ValueError(
                "Method-owned components cannot require external capabilities; "
                "effects belong to explicit parent Method nodes"
            )
        self._builder = MachineResearchProgramBuilder(
            program_id=self._host_id,
            kind=kind,
            version=version,
            state_schema=state_schema,
            entrypoint=entrypoint,
            required_capabilities=(),
        )
        self._operations: dict[str, ResearchHostOperation] = {}

    @staticmethod
    def _adapt(
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
    ) -> Callable[[ProgramNodeRequest, object], ProgramNodeResult]:
        digest = _handler_digest(handler)

        def wrapped(request: ProgramNodeRequest, _bindings: object) -> ProgramNodeResult:
            value = handler(ResearchComponentCall._from_internal(request))
            if isinstance(value, Mapping):
                value = ResearchComponentTransition(
                    value=value.get("value"),
                    state_update=value.get("state_update", {}),
                    next_node=value.get("next_node"),
                    events=tuple(value.get("events", ())),
                )
            if type(value) is not ResearchComponentTransition:
                raise TypeError(
                    "component handler must return a mapping or ResearchComponentTransition"
                )
            return ProgramNodeResult(
                value=value.value,
                state_update=dict(value.state_update),
                next_node=value.next_node,
                events=value.events,
            )

        setattr(wrapped, "__noetrium_handler_digest__", digest)
        return wrapped

    def semantic(
        self,
        node_id: str,
        concern: str,
        operation: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "ResearchComponentBuilder":

        if type(concern) is not str or not concern.strip():
            raise ValueError("research component concern must be non-empty")
        config = {} if configuration is None else dict(configuration)
        config[f"{self._domain.value}_concern"] = concern.strip()
        return self.custom(
            node_id,
            operation,
            handler,
            configuration=config,
            next_node=next_node,
            required_capabilities=required_capabilities,
        )

    def custom(
        self,
        node_id: str,
        operation: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "ResearchComponentBuilder":
        if required_capabilities:
            raise ValueError(
                "Method-owned component nodes cannot own external capability effects"
            )
        self._builder.node(
            node_id,
            operation,
            configuration=None if configuration is None else dict(configuration),
            next_node=next_node,
            required_capabilities=(),
        )
        wrapped = self._adapt(handler)
        self._operations[operation] = ResearchHostOperation(
            operation,
            wrapped,
            getattr(wrapped, "__noetrium_handler_digest__"),
        )
        return self

    def build(self) -> ResearchComponent:
        return ResearchComponent(
            self._host_id,
            self._domain,
            self._builder.build(),
            tuple(self._operations.values()),
        )

    def end(self) -> "ResearchMethodBuilder":
        self._parent._register_component(self.build())
        return self._parent



def _adapt_transition(value: object) -> MethodNodeResult:
    if type(value) is ResearchMethodTransition:
        transition = value
    elif isinstance(value, Mapping):
        raw_events = value.get("events", ())
        events: list[ResearchEvent] = []
        for row in raw_events:
            if type(row) is ResearchEvent:
                events.append(row)
            elif isinstance(row, tuple) and len(row) == 2 and isinstance(row[0], str):
                events.append(ResearchEvent(row[0], row[1]))
            elif isinstance(row, Mapping):
                events.append(ResearchEvent(str(row["kind"]), row.get("payload")))
            else:
                raise TypeError("research method event mapping is invalid")
        components = value.get("components", ())
        if type(components) is not tuple or any(
            type(row) is not ResearchComponentResult for row in components
        ):
            raise TypeError(
                "research method components must be ResearchComponentResult tuple"
            )
        transition = ResearchMethodTransition(
            value=value.get("value"),
            state_update=value.get("state_update", {}),
            next_node=value.get("next_node"),
            checkpoint=bool(value.get("checkpoint", False)),
            checkpoint_value=value.get("checkpoint_value"),
            events=tuple(events),
            components=components,
        )
    else:
        raise TypeError(
            "Research Method handler must return a mapping or ResearchMethodTransition"
        )
    return MethodNodeResult(
        value=transition.value,
        state_update=dict(transition.state_update),
        next_node=transition.next_node,
        checkpoint=transition.checkpoint,
        checkpoint_value=transition.checkpoint_value,
        events=tuple(MethodEvent(row.kind, row.payload) for row in transition.events),
        child_links=tuple(row._execution.link for row in transition.components),
    )


def _adapt_handler(
    handler: Callable[[ResearchMethodCall], ResearchMethodTransition],
) -> Callable[[MethodNodeRequest], MethodNodeResult]:
    if not callable(handler):
        raise TypeError("research method handler must be callable")

    def wrapped(request: MethodNodeRequest) -> MethodNodeResult:
        return _adapt_transition(
            handler(ResearchMethodCall._from_internal(request))
        )

    frozen = getattr(handler, "__noetrium_handler_digest__", None)
    if type(frozen) is str:
        setattr(wrapped, "__noetrium_handler_digest__", frozen)
    return wrapped


def _adapt_view(
    handler: Callable[[ResearchMethodCall], Mapping[str, JsonValue]],
) -> Callable[[MethodNodeRequest], Mapping[str, JsonValue]]:
    if not callable(handler):
        raise TypeError("research method view handler must be callable")

    def wrapped(request: MethodNodeRequest) -> Mapping[str, JsonValue]:
        value = handler(ResearchMethodCall._from_internal(request))
        if not isinstance(value, Mapping):
            raise TypeError("research method agent view must be a mapping")
        return dict(value)

    frozen = getattr(handler, "__noetrium_handler_digest__", None)
    if type(frozen) is str:
        setattr(wrapped, "__noetrium_handler_digest__", frozen)
    return wrapped


def _adapt_target(
    handler: Callable[[ResearchMethodCall], str],
) -> Callable[[MethodNodeRequest], str]:
    if not callable(handler):
        raise TypeError("research method target handler must be callable")

    def wrapped(request: MethodNodeRequest) -> str:
        value = handler(ResearchMethodCall._from_internal(request))
        if type(value) is not str or not value.strip():
            raise TypeError("research method dynamic target must be non-empty text")
        return value

    frozen = getattr(handler, "__noetrium_handler_digest__", None)
    if type(frozen) is str:
        setattr(wrapped, "__noetrium_handler_digest__", frozen)
    return wrapped


class ResearchMethodBuilder:
    """Research-OS-owned method authoring surface.

    The builder absorbs Method Machine identities, runtime-port requirements,
    capability closure and lower MethodNode request/result contracts.
    """

    def __init__(
        self,
        method_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        semantic_contract: str = "research.method.v1",
        configuration: Mapping[str, JsonValue] | None = None,
    ) -> None:
        if type(method_id) is not str or not method_id.strip():
            raise ValueError("research method_id must be non-empty")
        if type(entrypoint) is not str or not entrypoint.strip():
            raise ValueError("research method entrypoint must be non-empty")
        if type(version) is not str or not version.strip():
            raise ValueError("research method version must be non-empty")
        if type(semantic_contract) is not str or not semantic_contract.strip():
            raise ValueError("research method semantic_contract must be non-empty")
        config = dict(configuration or {})
        identity = MethodProgramIdentity(
            MethodIdentity(
                method_id,
                version,
                "noetrium.method-machine.v1",
                semantic_contract,
            ),
            canonical_digest(config),
        )
        self._method_id = method_id.strip()
        self._builder = MethodProgramBuilder(identity, entrypoint=entrypoint)
        self._configuration = config
        self._capabilities: set[str] = set()
        self._runtime_ports: set[MethodRuntimePort] = set()
        self._components: dict[str, ResearchComponent] = {}
        self._execution = "effect_recorded"
        self._evidence: tuple[str, ...] = ()
        self._metrics: tuple[str, ...] = ()
        self._artifacts: tuple[str, ...] = ()
        self._state_schema = "json"
        self._input_schema = "json"
        self._output_schema = "json"

    def configure(self, values: Mapping[str, JsonValue]) -> "ResearchMethodBuilder":
        if not isinstance(values, Mapping):
            raise TypeError("research method configuration must be a mapping")
        self._configuration.update(dict(values))
        return self

    def requires(self, *capability_ids: str) -> "ResearchMethodBuilder":
        for capability_id in capability_ids:
            if type(capability_id) is not str or not capability_id.strip():
                raise ValueError("research method capability requirement must be non-empty")
            self._capabilities.add(capability_id.strip())
        return self

    def policy(
        self,
        *,
        execution: str | None = None,
        evidence: tuple[str, ...] | None = None,
        metrics: tuple[str, ...] | None = None,
        artifacts: tuple[str, ...] | None = None,
        state_schema: str | None = None,
        input_schema: str | None = None,
        output_schema: str | None = None,
    ) -> "ResearchMethodBuilder":
        if execution is not None:
            MethodExecutionClass(execution)
            self._execution = execution
        for name, value in (("evidence", evidence), ("metrics", metrics), ("artifacts", artifacts)):
            if value is None:
                continue
            if type(value) is not tuple or any(type(row) is not str or not row.strip() for row in value):
                raise TypeError(f"research method {name} must be a text tuple")
            setattr(self, f"_{name}", value)
        for name, value in (("state_schema", state_schema), ("input_schema", input_schema), ("output_schema", output_schema)):
            if value is None:
                continue
            if type(value) is not str or not value.strip():
                raise ValueError(f"research method {name} must be non-empty")
            setattr(self, f"_{name}", value.strip())
        return self

    def _register_component(self, component: ResearchComponent) -> None:
        if component.host_id in self._components:
            raise ValueError(
                f"duplicate method component: {component.host_id}"
            )
        self._components[component.host_id] = component
        self._runtime_ports.add(MethodRuntimePort.CHILD_MACHINES)

    def component(
        self,
        host_id: str,
        *,
        domain: str,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
        required_capabilities: tuple[str, ...] = (),
    ) -> ResearchComponentBuilder:
        return ResearchComponentBuilder(
            self,
            host_id,
            domain=domain,
            entrypoint=entrypoint,
            version=version,
            state_schema=state_schema,
            required_capabilities=required_capabilities,
        )

    def memory(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
        required_capabilities: tuple[str, ...] = (),
    ) -> ResearchComponentBuilder:
        return self.component(
            host_id,
            domain=MachineKind.MEMORY.value,
            entrypoint=entrypoint,
            version=version,
            state_schema=state_schema,
            required_capabilities=required_capabilities,
        )

    def runtime(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentBuilder:
        return self.component(
            host_id,
            domain=MachineKind.RUNTIME.value,
            entrypoint=entrypoint,
            version=version,
            state_schema=state_schema,
        )

    def participant(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentBuilder:
        return self.component(
            host_id,
            domain=MachineKind.PARTICIPANT.value,
            entrypoint=entrypoint,
            version=version,
            state_schema=state_schema,
        )

    def environment(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentBuilder:
        return self.component(
            host_id,
            domain=MachineKind.ENVIRONMENT.value,
            entrypoint=entrypoint,
            version=version,
            state_schema=state_schema,
        )

    def optimization(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentBuilder:
        return self.component(
            host_id,
            domain=MachineKind.OPTIMIZATION.value,
            entrypoint=entrypoint,
            version=version,
            state_schema=state_schema,
        )

    def compute(
        self,
        node_id: str,
        operation: str,
        handler: Callable[[ResearchMethodCall], ResearchMethodTransition],
        next_nodes: tuple[str, ...] = (),
        *,
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodBuilder":
        self._builder.compute(
            node_id,
            operation,
            _adapt_handler(handler),
            next_nodes,
            max_visits=max_visits,
            evidence_obligations=evidence,
        )
        return self

    def dynamic_capability(
        self,
        node_id: str,
        operation: str,
        capability_ids: tuple[str, ...],
        target: Callable[[ResearchMethodCall], str],
        next_nodes: tuple[str, ...] = (),
        *,
        effect: str = "non_idempotent",
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodBuilder":
        if type(capability_ids) is not tuple or not capability_ids or any(
            type(row) is not str or not row.strip() for row in capability_ids
        ):
            raise ValueError("research method dynamic capability closure must be non-empty text tuple")
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("research method dynamic capability closure must be unique")
        try:
            effect_class = EffectClass(effect)
        except ValueError as exc:
            raise ValueError(f"unknown research method effect policy: {effect!r}") from exc
        self._runtime_ports.add(MethodRuntimePort.CAPABILITIES)
        self._capabilities.update(capability_ids)
        self._builder.dynamic_capability(
            node_id, operation, capability_ids, _adapt_target(target), next_nodes,
            effect_class=effect_class, max_visits=max_visits,
            evidence_obligations=evidence,
        )
        return self

    def agent(
        self,
        node_id: str,
        operation: str,
        role: str,
        next_nodes: tuple[str, ...] = (),
        *,
        view: Callable[[ResearchMethodCall], Mapping[str, JsonValue]],
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodBuilder":
        self._runtime_ports.add(MethodRuntimePort.AGENT_LOOP)
        self._builder.agent(
            node_id,
            operation,
            role,
            next_nodes,
            view_handler=_adapt_view(view),
            max_visits=max_visits,
            evidence_obligations=evidence,
        )
        return self

    def dynamic_agent(
        self,
        node_id: str,
        operation: str,
        agent_ids: tuple[str, ...],
        target: Callable[[ResearchMethodCall], str],
        next_nodes: tuple[str, ...] = (),
        *,
        view: Callable[[ResearchMethodCall], Mapping[str, JsonValue]],
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodBuilder":
        if type(agent_ids) is not tuple or not agent_ids or any(
            type(row) is not str or not row.strip() for row in agent_ids
        ):
            raise ValueError("research method dynamic agent closure must be non-empty text tuple")
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("research method dynamic agent closure must be unique")
        self._runtime_ports.add(MethodRuntimePort.AGENT_LOOP)
        self._builder.dynamic_agent(
            node_id, operation, agent_ids, _adapt_target(target), next_nodes,
            view_handler=_adapt_view(view), max_visits=max_visits,
            evidence_obligations=evidence,
        )
        return self

    def phases(
        self,
        phases: tuple[Mapping[str, JsonValue], ...],
        *,
        max_cycles: int | None = None,
    ) -> "ResearchMethodBuilder":
        """Compile a declarative agent phase sequence into this Method.

        This is Method-owned sugar, not a second Method implementation.  The
        emitted nodes execute on the same MethodMachine and Machine kernel.
        """

        if type(phases) is not tuple or not phases:
            raise TypeError("research method phases must be a non-empty tuple")
        rows: list[dict[str, JsonValue]] = []
        for value in phases:
            if not isinstance(value, Mapping):
                raise TypeError("research method phase must be a mapping")
            phase_id = value.get("phase_id")
            role = value.get("role", value.get("agent_id"))
            instruction = value.get("instruction")
            max_visits = value.get("max_visits", 1)
            for field_name, field_value in (
                ("phase_id", phase_id),
                ("role", role),
                ("instruction", instruction),
            ):
                if type(field_value) is not str or not field_value.strip():
                    raise ValueError(
                        f"research method phase {field_name} must be non-empty"
                    )
            if type(max_visits) is not int or max_visits < 1:
                raise ValueError("research method phase max_visits must be positive")
            rows.append(
                {
                    "phase_id": phase_id.strip(),
                    "role": role.strip(),
                    "instruction": instruction.strip(),
                    "max_visits": max_visits,
                }
            )
        phase_ids = tuple(str(row["phase_id"]) for row in rows)
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("research method phase ids must be unique")
        if max_cycles is not None and (
            type(max_cycles) is not int or max_cycles < 1
        ):
            raise ValueError("research method max_cycles must be positive or None")

        authoring = {
            "authoring_form": (
                "agent_phase_sequence.v2"
                if max_cycles is None
                else "agent_phase_cycle.v2"
            ),
            "phases": tuple(rows),
        }
        if max_cycles is not None:
            authoring["max_cycles"] = max_cycles
        self.configure(authoring)

        for index, row in enumerate(rows):
            phase_id = str(row["phase_id"])
            role = str(row["role"])
            instruction = str(row["instruction"])
            if index + 1 < len(rows):
                next_id = str(rows[index + 1]["phase_id"])
            else:
                next_id = "return" if max_cycles is None else "cycle_route"

            def view(call: ResearchMethodCall, *, _instruction=instruction):
                return {
                    "instruction": _instruction,
                    "input": call.input_value,
                    "previous": call.previous_value,
                    "state": call.state,
                }

            setattr(
                view,
                "__noetrium_handler_digest__",
                canonical_digest(
                    {
                        "kind": "research.method.phase.view.v1",
                        "phase_id": phase_id,
                        "role": role,
                        "instruction": instruction,
                    }
                ),
            )
            self.agent(
                phase_id,
                f"{self._method_id}.{phase_id}",
                role,
                (next_id,),
                view=view,
                max_visits=(
                    int(row["max_visits"])
                    if max_cycles is None
                    else max(int(row["max_visits"]), max_cycles)
                ),
                evidence=(f"{self._method_id}.{phase_id}",),
            )

        method_id = self._method_id
        if max_cycles is not None:
            first_phase_id = phase_ids[0]

            def cycle_route(call: ResearchMethodCall):
                previous_count = call.state.get("__agent_cycle_count", 0)
                if type(previous_count) is not int or previous_count < 0:
                    raise ValueError(
                        "research method agent cycle count must be non-negative"
                    )
                completed = previous_count + 1
                return {
                    "value": {
                        "completed_cycles": completed,
                        "last_result": call.previous_value,
                    },
                    "state_update": {"__agent_cycle_count": completed},
                    "next_node": (
                        "return" if completed >= max_cycles else first_phase_id
                    ),
                }

            setattr(
                cycle_route,
                "__noetrium_handler_digest__",
                canonical_digest(
                    {
                        "kind": "research.method.phase.cycle-route.v1",
                        "method_id": method_id,
                        "first_phase_id": first_phase_id,
                        "max_cycles": max_cycles,
                    }
                ),
            )
            self.route(
                "cycle_route",
                f"{method_id}.cycle-route",
                cycle_route,
                (first_phase_id, "return"),
                max_visits=max_cycles,
            )

        def return_result(call: ResearchMethodCall):
            return {
                "value": {
                    "method_id": method_id,
                    "phase_ids": phase_ids,
                    "result": call.previous_value,
                }
            }

        setattr(
            return_result,
            "__noetrium_handler_digest__",
            canonical_digest(
                {
                    "kind": "research.method.phase.return.v1",
                    "method_id": method_id,
                    "phase_ids": phase_ids,
                }
            ),
        )
        self.return_node("return", f"{method_id}.return", return_result)
        return self

    def capability(
        self,
        node_id: str,
        operation: str,
        capability: str,
        next_nodes: tuple[str, ...] = (),
        *,
        effect: str = "pure",
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodBuilder":
        try:
            effect_class = EffectClass(effect)
        except ValueError as exc:
            raise ValueError(
                f"unknown research method effect policy: {effect!r}"
            ) from exc
        self._runtime_ports.add(MethodRuntimePort.CAPABILITIES)
        self._capabilities.add(capability)
        self._builder.capability(
            node_id,
            operation,
            capability,
            next_nodes,
            effect_class=effect_class,
            max_visits=max_visits,
            evidence_obligations=evidence,
        )
        return self

    def route(
        self,
        node_id: str,
        operation: str,
        handler: Callable[[ResearchMethodCall], ResearchMethodTransition],
        next_nodes: tuple[str, ...],
        *,
        max_visits: int | None = 1,
    ) -> "ResearchMethodBuilder":
        self._builder.route(
            node_id,
            operation,
            _adapt_handler(handler),
            next_nodes,
            max_visits=max_visits,
        )
        return self

    def checkpoint(
        self,
        node_id: str,
        next_nodes: tuple[str, ...] = (),
        *,
        max_visits: int | None = 1,
    ) -> "ResearchMethodBuilder":
        self._builder.checkpoint(
            node_id,
            next_nodes,
            max_visits=max_visits,
        )
        return self

    def interrupt(
        self,
        node_id: str,
        next_nodes: tuple[str, ...] = (),
        *,
        max_visits: int | None = 1,
    ) -> "ResearchMethodBuilder":
        self._builder.interrupt(
            node_id,
            next_nodes,
            max_visits=max_visits,
        )
        return self

    def return_node(
        self,
        node_id: str,
        operation: str,
        handler: Callable[[ResearchMethodCall], ResearchMethodTransition],
    ) -> "ResearchMethodBuilder":
        self._builder.return_node(
            node_id,
            operation,
            _adapt_handler(handler),
        )
        return self

    def build(self) -> ResearchMethod:
        try:
            execution_class = MethodExecutionClass(self._execution)
        except ValueError as exc:
            raise ValueError(
                f"unknown research method execution policy: {self._execution!r}"
            ) from exc
        program = self._builder.build(
            configuration=self._configuration,
            state_schema=self._state_schema,
            input_schema=self._input_schema,
            output_schema=self._output_schema,
            required_capabilities=tuple(sorted(self._capabilities)),
            required_runtime_ports=tuple(
                sorted(self._runtime_ports, key=lambda row: row.value)
            ),
            execution_class=execution_class,
            evidence_obligations=self._evidence,
            metric_names=self._metrics,
            artifact_kinds=self._artifacts,
        )
        return ResearchMethod(program, tuple(self._components.values()))


class ResearchComponentDSL:
    """Systemized Method-owned component facade over one internal component builder."""

    def __init__(
        self,
        parent: "ResearchMethodDSL",
        builder: ResearchComponentBuilder,
    ) -> None:
        self._parent = parent
        self._builder = builder

    def semantic(
        self,
        node_id: str,
        concern: str,
        operation: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchComponentDSL":
        self._builder.semantic(
            node_id,
            concern,
            operation,
            handler,
            configuration=configuration,
            next_node=next_node,
        )
        return self

    def custom(
        self,
        node_id: str,
        operation: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchComponentDSL":
        self._builder.custom(
            node_id,
            operation,
            handler,
            configuration=configuration,
            next_node=next_node,
        )
        return self

    def end(self) -> "ResearchMethodDSL":
        self._builder.end()
        return self._parent


class ResearchMemoryDSL(ResearchComponentDSL):
    """Complete Method-owned Memory authoring without exposing Machine internals."""

    def _semantic_memory(
        self,
        concern: str,
        node_id: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        operation: str | None = None,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchMemoryDSL":
        self._builder.semantic(
            node_id,
            concern,
            f"memory.{concern}" if operation is None else operation,
            handler,
            configuration=configuration,
            next_node=next_node,
        )
        return self

    def write(
        self,
        node_id: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        operation: str | None = None,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchMemoryDSL":
        return self._semantic_memory(
            "write", node_id, handler,
            operation=operation, configuration=configuration, next_node=next_node,
        )

    def update(
        self,
        node_id: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        operation: str | None = None,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchMemoryDSL":
        return self._semantic_memory(
            "update", node_id, handler,
            operation=operation, configuration=configuration, next_node=next_node,
        )

    def retrieve(
        self,
        node_id: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        operation: str | None = None,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchMemoryDSL":
        return self._semantic_memory(
            "retrieval", node_id, handler,
            operation=operation, configuration=configuration, next_node=next_node,
        )

    def verify(
        self,
        node_id: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        operation: str | None = None,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchMemoryDSL":
        return self._semantic_memory(
            "trust", node_id, handler,
            operation=operation, configuration=configuration, next_node=next_node,
        )

    def forget(
        self,
        node_id: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        operation: str | None = None,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchMemoryDSL":
        return self._semantic_memory(
            "retention", node_id, handler,
            operation=operation, configuration=configuration, next_node=next_node,
        )

    def consolidate(
        self,
        node_id: str,
        handler: Callable[[ResearchComponentCall], ResearchComponentTransition],
        *,
        operation: str | None = None,
        configuration: Mapping[str, JsonValue] | None = None,
        next_node: str | None = None,
    ) -> "ResearchMemoryDSL":
        return self._semantic_memory(
            "consolidation", node_id, handler,
            operation=operation, configuration=configuration, next_node=next_node,
        )


class ResearchMethodContractDSL:
    def __init__(self, parent: "ResearchMethodDSL") -> None:
        self._parent = parent

    def configure(
        self,
        values: Mapping[str, JsonValue],
    ) -> "ResearchMethodContractDSL":
        self._parent._builder.configure(values)
        return self

    def requires(self, *capability_ids: str) -> "ResearchMethodContractDSL":
        self._parent._builder.requires(*capability_ids)
        return self

    def policy(
        self,
        *,
        execution: str | None = None,
        evidence: tuple[str, ...] | None = None,
        metrics: tuple[str, ...] | None = None,
        artifacts: tuple[str, ...] | None = None,
        state_schema: str | None = None,
        input_schema: str | None = None,
        output_schema: str | None = None,
    ) -> "ResearchMethodContractDSL":
        self._parent._builder.policy(
            execution=execution,
            evidence=evidence,
            metrics=metrics,
            artifacts=artifacts,
            state_schema=state_schema,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        return self


class ResearchMethodComponentsDSL:
    def __init__(self, parent: "ResearchMethodDSL") -> None:
        self._parent = parent

    def memory(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchMemoryDSL:
        return ResearchMemoryDSL(
            self._parent,
            self._parent._builder.memory(
                host_id,
                entrypoint=entrypoint,
                version=version,
                state_schema=state_schema,
            ),
        )

    def runtime(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentDSL:
        return ResearchComponentDSL(
            self._parent,
            self._parent._builder.runtime(
                host_id,
                entrypoint=entrypoint,
                version=version,
                state_schema=state_schema,
            ),
        )

    def participant(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentDSL:
        return ResearchComponentDSL(
            self._parent,
            self._parent._builder.participant(
                host_id,
                entrypoint=entrypoint,
                version=version,
                state_schema=state_schema,
            ),
        )

    def environment(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentDSL:
        return ResearchComponentDSL(
            self._parent,
            self._parent._builder.environment(
                host_id,
                entrypoint=entrypoint,
                version=version,
                state_schema=state_schema,
            ),
        )

    def optimization(
        self,
        host_id: str,
        *,
        entrypoint: str,
        version: str = "1",
        state_schema: str = "json",
    ) -> ResearchComponentDSL:
        return ResearchComponentDSL(
            self._parent,
            self._parent._builder.optimization(
                host_id,
                entrypoint=entrypoint,
                version=version,
                state_schema=state_schema,
            ),
        )


class ResearchMethodFlowDSL:
    def __init__(self, parent: "ResearchMethodDSL") -> None:
        self._parent = parent

    @property
    def _builder(self) -> ResearchMethodBuilder:
        return self._parent._builder

    def compute(
        self,
        node_id: str,
        operation: str,
        handler: Callable[[ResearchMethodCall], ResearchMethodTransition],
        next_nodes: tuple[str, ...] = (),
        *,
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodFlowDSL":
        self._builder.compute(
            node_id, operation, handler, next_nodes,
            max_visits=max_visits, evidence=evidence,
        )
        return self

    def capability(
        self,
        node_id: str,
        operation: str,
        capability: str,
        next_nodes: tuple[str, ...] = (),
        *,
        effect: str = "pure",
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodFlowDSL":
        self._builder.capability(
            node_id, operation, capability, next_nodes,
            effect=effect, max_visits=max_visits, evidence=evidence,
        )
        return self

    def dynamic_capability(
        self,
        node_id: str,
        operation: str,
        capability_ids: tuple[str, ...],
        target: Callable[[ResearchMethodCall], str],
        next_nodes: tuple[str, ...] = (),
        *,
        effect: str = "non_idempotent",
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodFlowDSL":
        self._builder.dynamic_capability(
            node_id, operation, capability_ids, target, next_nodes,
            effect=effect, max_visits=max_visits, evidence=evidence,
        )
        return self

    def agent(
        self,
        node_id: str,
        operation: str,
        role: str,
        next_nodes: tuple[str, ...] = (),
        *,
        view: Callable[[ResearchMethodCall], Mapping[str, JsonValue]],
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodFlowDSL":
        self._builder.agent(
            node_id, operation, role, next_nodes,
            view=view, max_visits=max_visits, evidence=evidence,
        )
        return self

    def dynamic_agent(
        self,
        node_id: str,
        operation: str,
        agent_ids: tuple[str, ...],
        target: Callable[[ResearchMethodCall], str],
        next_nodes: tuple[str, ...] = (),
        *,
        view: Callable[[ResearchMethodCall], Mapping[str, JsonValue]],
        max_visits: int | None = 1,
        evidence: tuple[str, ...] = (),
    ) -> "ResearchMethodFlowDSL":
        self._builder.dynamic_agent(
            node_id, operation, agent_ids, target, next_nodes,
            view=view, max_visits=max_visits, evidence=evidence,
        )
        return self

    def phases(
        self,
        phases: tuple[Mapping[str, JsonValue], ...],
        *,
        max_cycles: int | None = None,
    ) -> "ResearchMethodFlowDSL":
        self._builder.phases(phases, max_cycles=max_cycles)
        return self

    def route(
        self,
        node_id: str,
        operation: str,
        handler: Callable[[ResearchMethodCall], ResearchMethodTransition],
        next_nodes: tuple[str, ...],
        *,
        max_visits: int | None = 1,
    ) -> "ResearchMethodFlowDSL":
        self._builder.route(
            node_id, operation, handler, next_nodes, max_visits=max_visits,
        )
        return self

    def checkpoint(
        self,
        node_id: str,
        next_nodes: tuple[str, ...] = (),
        *,
        max_visits: int | None = 1,
    ) -> "ResearchMethodFlowDSL":
        self._builder.checkpoint(
            node_id, next_nodes, max_visits=max_visits,
        )
        return self

    def interrupt(
        self,
        node_id: str,
        next_nodes: tuple[str, ...] = (),
        *,
        max_visits: int | None = 1,
    ) -> "ResearchMethodFlowDSL":
        self._builder.interrupt(
            node_id, next_nodes, max_visits=max_visits,
        )
        return self

    def finish(
        self,
        step_id: str,
        operation: str,
        handler: Callable[[ResearchMethodCall], ResearchMethodTransition],
    ) -> "ResearchMethodFlowDSL":
        self._builder.return_node(step_id, operation, handler)
        return self


class ResearchMethodDSL:
    """Systemized public Method DSL; lower MethodMachine authoring is not exposed."""

    def __init__(self, builder: ResearchMethodBuilder) -> None:
        if type(builder) is not ResearchMethodBuilder:
            raise TypeError("ResearchMethodDSL requires internal ResearchMethodBuilder")
        self._builder = builder
        self._contract = ResearchMethodContractDSL(self)
        self._components = ResearchMethodComponentsDSL(self)
        self._flow = ResearchMethodFlowDSL(self)

    @property
    def contract(self) -> ResearchMethodContractDSL:
        return self._contract

    @property
    def components(self) -> ResearchMethodComponentsDSL:
        return self._components

    @property
    def flow(self) -> ResearchMethodFlowDSL:
        return self._flow



__all__ = [
    "MemoryScope",
    "ResearchComponent",
    "ResearchComponentBuilder",
    "ResearchComponentCall",
    "ResearchComponentResult",
    "ResearchComponentTransition",
    "ResearchEvent",
    "ResearchMethod",
    "ResearchMethodBuilder",
    "ResearchMethodDSL",
    "ResearchMethodContractDSL",
    "ResearchMethodComponentsDSL",
    "ResearchMethodFlowDSL",
    "ResearchComponentDSL",
    "ResearchMemoryDSL",
    "ResearchMethodCall",
    "ResearchMethodTransition",
]
