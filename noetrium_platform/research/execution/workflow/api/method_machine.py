"""Typed Method authoring ABI lowered into the universal NoetriumUnit kernel.

A downstream method supplies bounded scientific semantics and node functions.
Noetrium lowers those semantics into NoetriumUnit and owns Machine commits,
operation envelopes, capabilities, checkpoints, interrupts, and evidence.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import (
    callable_source_digest,
    implementation_digest,
    implementation_field,
    implementation_unit,
    is_implementation,
    resolve_callable,
)
from noetrium_platform.foundation.kernel.structure import (
    endpoint_child_id,
    endpoint_unit,
    relation_id,
    relation_unit,
    structure_unit,
    symbol_implementation,
    symbol_unit,
)


from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
import ast
import importlib
from pathlib import Path
from threading import RLock
import tokenize
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.api import (
    CapabilityPort,
    CapabilityResult,
)
from noetrium_platform.capabilities.api import (
    PARTICIPANT_IMPLEMENTATION_TRAIT,
    participant_implementation_artifact,
    participant_implementation_id,
    participant_implementation_schema,
    participant_implementation_version,
    require_participant_implementation,
)
from noetrium_platform.capabilities.api import (
    ArtifactReference,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort, UNBOUNDED_EXECUTION_CONTROL
from noetrium_platform.foundation.kernel.kernel.unit_driver import UnitActivationRuntimePort
from noetrium_platform.foundation.kernel.kernel import (
    ChildMachineLink,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel.universal import (
    EXECUTABLE_UNIT_TRAIT,
    UNIT_OPERATION_TRAIT,
    UNIT_FLOW_RELATION,
    validate_executable_unit,
)

from .dispatch import OperationDispatchPort
from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnitPort
from noetrium_platform.research.execution.policy.api import (
    ExecutionBudgetAuthorityPort,
)


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


class MethodRuntimePort(StrEnum):
    """Semantic runtime dependencies visible in the immutable MethodProgram ABI."""

    AGENT_LOOP = "agent_loop"
    CAPABILITIES = "capabilities"
    UNIT_ACTIVATION = "unit_activation"
    SCHEMAS = "schemas"


@lru_cache(maxsize=512)
def _method_source_segments(
    source_path: str,
    mtime_ns: int,
    size: int,
) -> dict[str, str]:
    """Index import-resolvable function source once per immutable file identity."""

    path = Path(source_path)
    before = path.stat()
    if before.st_mtime_ns != mtime_ns or before.st_size != size:
        raise RuntimeError("method implementation source changed before indexing")
    with tokenize.open(str(path)) as handle:
        source = handle.read()
    after = path.stat()
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or after.st_mtime_ns != mtime_ns
        or after.st_size != size
    ):
        raise RuntimeError("method implementation source changed while indexing")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines(keepends=True)
    result: dict[str, str] = {}

    def index_body(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                index_body(node.body, prefix + node.name + ".")
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = min(
                [node.lineno, *(item.lineno for item in node.decorator_list)]
            ) - 1
            end = node.end_lineno
            if end is None:
                raise ValueError(
                    "method implementation AST node has no terminal line"
                )
            result[prefix + node.name] = "".join(lines[start:end])

    index_body(tree.body, "")
    return result


METHOD_HANDLER_IMPLEMENTATION_TYPE = "method.handler"


def _method_source_digest(value: Callable[..., object]) -> str:
    return callable_source_digest(value)


def method_handler_implementation(
    module: str,
    qualname: str,
    source_digest: str,
) -> NoetriumUnit:
    if type(module) is not str or not module.strip() or module != module.strip():
        raise ValueError("method implementation module must be canonical text")
    if (
        type(qualname) is not str
        or not qualname.strip()
        or qualname != qualname.strip()
    ):
        raise ValueError("method implementation qualname must be canonical text")
    if "<locals>" in qualname or "<lambda>" in qualname:
        raise ValueError(
            "canonical MethodProgram implementations must be "
            "import-resolvable module-level symbols"
        )
    require_sha256(source_digest, "method implementation source_digest")
    identity = {
        "module": module,
        "qualname": qualname,
        "source_digest": source_digest,
    }
    identity_digest = canonical_digest(identity)
    return implementation_unit(
        f"method.handler:{identity_digest}",
        implementation_type=METHOD_HANDLER_IMPLEMENTATION_TYPE,
        fields=identity,
        identity_fields=identity,
    )


def method_handler_from_callable(
    value: Callable[..., object],
) -> NoetriumUnit:
    if not callable(value):
        raise TypeError("method implementation must be callable")
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if type(module) is not str or type(qualname) is not str:
        raise ValueError("method implementation callable lacks import identity")
    unit = method_handler_implementation(
        module.strip(), qualname.strip(), _method_source_digest(value)
    )
    if resolve_method_handler(unit) is not value:
        raise ValueError(
            "canonical MethodProgram callable must resolve to exact module symbol"
        )
    return unit


def method_handler_from_symbol(symbol: str) -> NoetriumUnit:
    if type(symbol) is not str or ":" not in symbol:
        raise ValueError("method implementation symbol must be 'module:qualname'")
    module, qualname = (part.strip() for part in symbol.split(":", 1))
    if not module or not qualname:
        raise ValueError("method implementation symbol must be 'module:qualname'")
    imported = importlib.import_module(module)
    value: object = imported
    for token in qualname.split("."):
        value = getattr(value, token)
    if not callable(value):
        raise TypeError("method implementation symbol did not resolve to callable")
    return method_handler_from_callable(value)


def resolve_method_handler(
    implementation: NoetriumUnit,
) -> Callable[..., object]:
    if not is_implementation(
        implementation, METHOD_HANDLER_IMPLEMENTATION_TYPE
    ):
        raise TypeError("method handler requires method.handler implementation Unit")
    return resolve_callable(
        implementation, observed_source_digest=_method_source_digest
    )


def method_handler_symbol(implementation: NoetriumUnit) -> str:
    if not is_implementation(implementation, METHOD_HANDLER_IMPLEMENTATION_TYPE):
        raise TypeError("method handler symbol requires implementation Unit")
    return (
        f"{implementation_field(implementation, 'module')}:"
        f"{implementation_field(implementation, 'qualname')}"
    )


def _implementation_ref(
    value: NoetriumUnit | Callable[..., object] | None,
    field_name: str,
) -> NoetriumUnit | None:
    if value is None:
        return None
    if type(value) is NoetriumUnit:
        if not is_implementation(value, METHOD_HANDLER_IMPLEMENTATION_TYPE):
            raise TypeError(
                f"{field_name} Unit is not a method handler implementation"
            )
        return value
    if not callable(value):
        raise TypeError(
            f"{field_name} must be a callable or implementation Unit"
        )
    return method_handler_from_callable(value)


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
    checkpoint_value: JsonValue = None
    binding_plan_digest: str | None = None
    runtime_binding_digest: str | None = None
    schema_digest: str | None = None
    child_links: tuple[ChildMachineLink, ...] = ()

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
        if not isinstance(self.child_links, tuple) or any(
            not isinstance(link, ChildMachineLink) for link in self.child_links
        ):
            raise TypeError("method node child_links must be ChildMachineLink tuple")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "state_update", freeze_json(self.state_update))
        object.__setattr__(self, "checkpoint_value", freeze_json(self.checkpoint_value))


@dataclass(frozen=True, slots=True)
class MethodNodeRequest:
    node_id: str
    visit: int
    state: JsonObject
    input_value: JsonValue
    context: ExecutionContext
    previous_value: JsonValue = None
    effect_receipts: Sequence[EffectReceipt] = ()
    capabilities: CapabilityPort | None = None
    unit_activation: UnitActivationRuntimePort | None = None
    visit_counts: Mapping[str, int] = field(default_factory=dict)
    checkpoint: JsonValue = None
    configuration: JsonObject = field(default_factory=dict)
    parent_machine_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("method node request node_id is required")
        if type(self.visit) is not int or self.visit < 0:
            raise ValueError("method node request visit must be a non-negative integer")
        if not isinstance(self.state, Mapping):
            raise TypeError("method node request state must be a mapping")
        if not isinstance(self.context, ExecutionContext):
            raise TypeError("method node request context must be ExecutionContext")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("method node request configuration must be an object")
        if not isinstance(self.effect_receipts, Sequence):
            raise TypeError(
                "method node request effect_receipts must be an EffectReceipt sequence"
            )
        if self.parent_machine_id is not None and (
            type(self.parent_machine_id) is not str
            or not self.parent_machine_id.strip()
        ):
            raise ValueError(
                "method node request parent_machine_id must be non-empty when provided"
            )
        if self.unit_activation is not None:
            if self.parent_machine_id is None:
                raise ValueError(
                    "method node unit_activation require authoritative parent_machine_id"
                )
            if not isinstance(self.unit_activation, UnitActivationRuntimePort):
                raise TypeError(
                    "method node request unit_activation must satisfy UnitActivationRuntimePort"
                )
            require_sha256(
                self.unit_activation.identity_digest,
                "method unit-activation port identity_digest",
            )
        if not isinstance(self.visit_counts, Mapping) or any(
            type(key) is not str or not key.strip()
            or type(count) is not int or count < 0
            for key, count in self.visit_counts.items()
        ):
            raise TypeError("method node request visit_counts must be a non-negative mapping")
        object.__setattr__(self, "visit_counts", freeze_json(self.visit_counts))
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(self, "input_value", freeze_json(self.input_value))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))
        object.__setattr__(self, "checkpoint", freeze_json(self.checkpoint))
        object.__setattr__(self, "configuration", freeze_json(self.configuration))


MethodNodeHandler = Callable[[MethodNodeRequest], MethodNodeResult]
MethodAgentViewHandler = Callable[[MethodNodeRequest], JsonObject]
MethodAgentTargetHandler = Callable[[MethodNodeRequest], str]
MethodCapabilityTargetHandler = Callable[[MethodNodeRequest], str]


@dataclass(frozen=True, slots=True)
class MethodAgentRequest:
    """Agent-visible request with no authoritative method-state reference."""

    agent_id: str
    goal: JsonValue
    view: JsonObject
    input_value: JsonValue
    previous_value: JsonValue
    context: ExecutionContext
    checkpoint: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise ValueError("method agent request agent_id is required")
        if not isinstance(self.view, Mapping):
            raise TypeError("method agent request view must be a mapping")
        if not isinstance(self.context, ExecutionContext):
            raise TypeError("method agent request context must be ExecutionContext")
        object.__setattr__(self, "goal", freeze_json(self.goal))
        object.__setattr__(self, "view", freeze_json(self.view))
        object.__setattr__(self, "input_value", freeze_json(self.input_value))
        object.__setattr__(self, "previous_value", freeze_json(self.previous_value))
        object.__setattr__(self, "checkpoint", freeze_json(self.checkpoint))


@dataclass(frozen=True, slots=True)
class MethodAgentResult:
    value: JsonValue = None
    state_update: JsonObject = field(default_factory=dict)
    events: tuple[MethodEvent, ...] = ()
    effect_receipts: tuple[EffectReceipt, ...] = ()
    checkpoint: JsonValue = None
    next_node: str | None = None
    interrupt: MethodInterrupt | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state_update, Mapping):
            raise TypeError("method agent state_update must be a mapping")
        if not isinstance(self.events, tuple) or any(not isinstance(event, MethodEvent) for event in self.events):
            raise TypeError("method agent events must be a tuple of MethodEvent")
        if not isinstance(self.effect_receipts, tuple) or any(
            not isinstance(receipt, EffectReceipt) for receipt in self.effect_receipts
        ):
            raise TypeError("method agent effect_receipts must be a tuple of EffectReceipt")
        if self.next_node is not None and (not isinstance(self.next_node, str) or not self.next_node.strip()):
            raise ValueError("method agent next_node must be non-empty when provided")
        if self.interrupt is not None and not isinstance(self.interrupt, MethodInterrupt):
            raise TypeError("method agent interrupt must be MethodInterrupt")
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
class MethodLifetimeResourcePort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def lifetime_resource_ports(
        self,
    ) -> tuple[tuple[object, MethodLifetimeResourcePort], ...]:
        """Flatten to (opaque Authority token, leaf reservation port) pairs."""
        ...

    def reserve_lifetime(
        self,
        lifetime_id: str,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> None: ...

    def release_lifetime(self, lifetime_id: str) -> None: ...


def method_lifetime_resources(
    roots: Iterable[MethodLifetimeResourcePort],
) -> tuple[MethodLifetimeResourcePort, ...]:
    """Canonical, deadlock-free acquisition order over actual Authority domains.

    The token is intentionally opaque: no upper layer can infer or impose
    physical capacity. Its live object identity provides a strict total order
    within the execution process; method digests remain durable scientific IDs.
    """
    domains: dict[int, tuple[object, MethodLifetimeResourcePort]] = {}
    for root in roots:
        if not isinstance(root, MethodLifetimeResourcePort):
            raise TypeError("Method lifetime resource root violates its port")
        for authority, leaf in root.lifetime_resource_ports():
            if authority is None or not isinstance(leaf, MethodLifetimeResourcePort):
                raise TypeError("Method lifetime resource leaf violates its port")
            leaf_digest = require_sha256(
                leaf.identity_digest, "Method lifetime leaf identity"
            )
            key = id(authority)
            previous = domains.get(key)
            if previous is not None and previous[0] is not authority:
                raise RuntimeError("Method lifetime Authority object identity collision")
            if previous is None or leaf_digest < previous[1].identity_digest:
                domains[key] = (authority, leaf)
    return tuple(domains[key][1] for key in sorted(domains))


@runtime_checkable
class MethodSchemaPort(Protocol):
    def validate(self, schema_id: str, value: JsonValue, *, location: str) -> None: ...



METHOD_PROGRAM_TRAIT = "method.program"
METHOD_OPERATION_TRAIT = "method.operation"
METHOD_COMPONENT_TRAIT = "method.component"
METHOD_FLOW_RELATION = UNIT_FLOW_RELATION
METHOD_HANDLER_SYMBOL = "handler"
METHOD_CAPABILITY_TARGET_SYMBOL = "capability-target"
METHOD_AGENT_VIEW_SYMBOL = "agent-view"
METHOD_AGENT_TARGET_SYMBOL = "agent-target"


def _method_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _method_tuple(value: object, field: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(row) is not str or not row.strip() for row in value):
        raise TypeError(f"{field} must be a text tuple")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must be unique")
    return value


def method_program_digest(program: NoetriumUnit) -> str:
    validate_method_program(program)
    return program.unit_digest


def method_program_identity(program: NoetriumUnit) -> NoetriumUnit:
    validate_method_program(program)
    rows = tuple(
        child
        for child in program.members
        if child.has_trait(PARTICIPANT_IMPLEMENTATION_TRAIT)
    )
    if len(rows) != 1:
        raise ValueError("method program requires exactly one implementation Unit")
    implementation = require_participant_implementation(rows[0])
    if str(implementation.parameters["kind"]) != "method":
        raise ValueError("method program implementation kind must be 'method'")
    return implementation


def method_program_configuration_digest(program: NoetriumUnit) -> str:
    return canonical_digest(method_program_configuration(program))


def method_program_configuration(program: NoetriumUnit) -> Mapping[str, JsonValue]:
    validate_method_program(program)
    value = program.parameters.get("configuration", {})
    if not isinstance(value, Mapping):
        raise TypeError("method graph configuration must be an object")
    return value


def method_program_state_schema(program: NoetriumUnit) -> str:
    validate_method_program(program)
    return str(program.parameters["state_schema"])


def method_program_input_schema(program: NoetriumUnit) -> str:
    validate_method_program(program)
    return str(program.parameters["input_schema"])


def method_program_output_schema(program: NoetriumUnit) -> str:
    validate_method_program(program)
    return str(program.parameters["output_schema"])


def method_program_entrypoint(program: NoetriumUnit) -> str:
    validate_method_program(program)
    return str(program.parameters["entrypoint"])


def method_program_required_capabilities(program: NoetriumUnit) -> tuple[str, ...]:
    validate_method_program(program)
    return tuple(program.parameters.get("required_capabilities", ()))


def method_program_required_runtime_ports(program: NoetriumUnit) -> tuple[MethodRuntimePort, ...]:
    validate_method_program(program)
    return tuple(MethodRuntimePort(str(value)) for value in program.parameters.get("required_runtime_ports", ()))


def method_program_execution_class(program: NoetriumUnit) -> MethodExecutionClass:
    validate_method_program(program)
    return MethodExecutionClass(str(program.parameters["execution_class"]))


def method_program_evidence_obligations(program: NoetriumUnit) -> tuple[str, ...]:
    validate_method_program(program)
    return tuple(program.parameters.get("evidence_obligations", ()))


def method_program_metric_names(program: NoetriumUnit) -> tuple[str, ...]:
    validate_method_program(program)
    return tuple(program.parameters.get("metric_names", ()))


def method_program_artifact_kinds(program: NoetriumUnit) -> tuple[str, ...]:
    validate_method_program(program)
    return tuple(program.parameters.get("artifact_kinds", ()))


def method_program_nodes(program: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    validate_method_program(program)
    return tuple(child for child in program.members if child.has_trait(METHOD_OPERATION_TRAIT))


def method_program_components(program: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    validate_method_program(program)
    return tuple(child for child in program.members if child.has_trait(METHOD_COMPONENT_TRAIT))


def method_program_node(program: NoetriumUnit, node_id: str) -> NoetriumUnit:
    validate_method_program(program)
    return program.member(_method_text(node_id, "method node_id"))


def method_node_kind(node: NoetriumUnit) -> MethodNodeKind:
    if type(node) is not NoetriumUnit or not node.has_trait(METHOD_OPERATION_TRAIT):
        raise TypeError("method operation must be a method.operation NoetriumUnit")
    return MethodNodeKind(str(node.parameters["kind"]))


def method_node_operation_type(node: NoetriumUnit) -> str:
    method_node_kind(node)
    return str(node.parameters["operation_type"])


def method_node_configuration(node: NoetriumUnit) -> Mapping[str, JsonValue]:
    method_node_kind(node)
    value = node.parameters.get("configuration", {})
    if not isinstance(value, Mapping):
        raise TypeError("method operation configuration must be an object")
    return value


def method_node_effect_class(node: NoetriumUnit) -> EffectClass:
    method_node_kind(node)
    return EffectClass(str(node.parameters["effect_class"]))


def method_node_max_visits(node: NoetriumUnit) -> int | None:
    method_node_kind(node)
    value = node.parameters.get("max_visits")
    if value is not None and (type(value) is not int or value < 1):
        raise ValueError("method operation max_visits must be positive or null")
    return value


def method_node_input_schema(node: NoetriumUnit) -> str:
    method_node_kind(node)
    return str(node.parameters["input_schema"])


def method_node_output_schema(node: NoetriumUnit) -> str:
    method_node_kind(node)
    return str(node.parameters["output_schema"])


def method_node_evidence_obligations(node: NoetriumUnit) -> tuple[str, ...]:
    method_node_kind(node)
    return tuple(node.parameters.get("evidence_obligations", ()))


def method_node_capability_id(node: NoetriumUnit) -> str | None:
    method_node_kind(node)
    value = node.parameters.get("capability_id")
    return None if value is None else str(value)


def method_node_capability_targets(node: NoetriumUnit) -> tuple[str, ...]:
    method_node_kind(node)
    return tuple(node.parameters.get("capability_targets", ()))


def method_node_agent_id(node: NoetriumUnit) -> str | None:
    method_node_kind(node)
    value = node.parameters.get("agent_id")
    return None if value is None else str(value)


def method_node_agent_targets(node: NoetriumUnit) -> tuple[str, ...]:
    method_node_kind(node)
    return tuple(node.parameters.get("agent_targets", ()))


def method_node_implementation(node: NoetriumUnit, symbol_id: str) -> NoetriumUnit | None:
    try:
        symbol = node.symbol(symbol_id)
    except LookupError:
        return None
    implementation = symbol_implementation(symbol)
    if implementation is None:
        return None
    if not is_implementation(implementation, METHOD_HANDLER_IMPLEMENTATION_TYPE):
        raise TypeError("method implementation symbol must bind method.handler Unit")
    return implementation


def method_node_handler(node: NoetriumUnit) -> NoetriumUnit | None:
    return method_node_implementation(node, METHOD_HANDLER_SYMBOL)


def method_node_capability_target(node: NoetriumUnit) -> NoetriumUnit | None:
    return method_node_implementation(node, METHOD_CAPABILITY_TARGET_SYMBOL)


def method_node_agent_view(node: NoetriumUnit) -> NoetriumUnit | None:
    return method_node_implementation(node, METHOD_AGENT_VIEW_SYMBOL)


def method_node_agent_target(node: NoetriumUnit) -> NoetriumUnit | None:
    return method_node_implementation(node, METHOD_AGENT_TARGET_SYMBOL)


def method_node_implementation_digest(node: NoetriumUnit) -> str:
    method_node_kind(node)
    return canonical_digest(tuple(symbol.semantic_digest for symbol in node.symbols))


def method_node_next_nodes(program: NoetriumUnit, node: NoetriumUnit) -> tuple[str, ...]:
    method_node_kind(node)
    return tuple(
        endpoint_child_id(relation.units('target')[0])
        for relation in program.relations
        if relation_id(relation) == METHOD_FLOW_RELATION
        and endpoint_child_id(relation.units('source')[0]) == node.unit_id
        and endpoint_child_id(relation.units('target')[0]) is not None
    )


_VALIDATED_METHOD_PROGRAMS: dict[str, None] = {}
_VALIDATED_METHOD_PROGRAMS_LOCK = RLock()
_VALIDATED_METHOD_PROGRAM_CACHE_LIMIT = 131072


def _validate_method_program_uncached(program: NoetriumUnit) -> None:
    if type(program) is not NoetriumUnit or not program.has_trait(METHOD_PROGRAM_TRAIT):
        raise TypeError("method program must be a method.program NoetriumUnit")
    if not program.has_trait(EXECUTABLE_UNIT_TRAIT):
        raise TypeError("method program must carry the unit.executable schema")
    params = program.parameters
    for name in ("domain", "version", "state_schema", "input_schema", "output_schema", "entrypoint"):
        _method_text(params.get(name), f"method graph {name}")
    MethodExecutionClass(str(params.get("execution_class")))
    for name in ("required_capabilities", "required_runtime_ports", "evidence_obligations", "metric_names", "artifact_kinds"):
        value = params.get(name, ())
        if type(value) is not tuple:
            raise TypeError(f"method graph {name} must be a tuple")
        if len(value) != len(set(value)) or any(type(row) is not str or not row.strip() for row in value):
            raise ValueError(f"method graph {name} must be unique text")

    operations: list[NoetriumUnit] = []
    universal_operations: list[NoetriumUnit] = []
    components: list[NoetriumUnit] = []
    implementations: list[NoetriumUnit] = []
    for child in program.members:
        is_operation = child.has_trait(METHOD_OPERATION_TRAIT)
        is_universal_operation = child.has_trait(UNIT_OPERATION_TRAIT)
        is_component = child.has_trait(METHOD_COMPONENT_TRAIT)
        is_implementation_child = child.has_trait(PARTICIPANT_IMPLEMENTATION_TRAIT)
        if is_universal_operation:
            universal_operations.append(child)
        if is_operation:
            operations.append(child)
        if is_component:
            components.append(child)
        if is_implementation_child:
            implementations.append(child)
        if sum((is_operation, is_component, is_implementation_child)) != 1:
            raise ValueError(
                "method graph child must be exactly one of method.operation, "
                "method.component, or participant.implementation"
            )
    if not operations:
        raise ValueError("method graph requires at least one operation")
    if not universal_operations:
        raise ValueError("executable unit requires at least one unit.operation member")
    if len(implementations) != 1:
        raise ValueError("method graph requires exactly one participant implementation Unit")
    implementation = require_participant_implementation(implementations[0])
    if str(implementation.parameters["kind"]) != "method":
        raise ValueError("method graph implementation kind must be 'method'")

    operations_by_id = {node.unit_id: node for node in operations}
    universal_operation_ids = {node.unit_id for node in universal_operations}
    entrypoint = str(params["entrypoint"])
    entry = operations_by_id.get(entrypoint)
    if entry is None:
        raise ValueError("method entrypoint must reference method.operation")
    if entrypoint not in universal_operation_ids:
        raise ValueError("executable unit entrypoint must reference unit.operation")

    # Validate universal operation ABI once here instead of traversing the same
    # program again through validate_executable_unit().
    for node in universal_operations:
        node_params = node.parameters
        _method_text(node_params.get("operation"), "unit operation")
        configuration = node_params.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise TypeError("unit operation configuration must be an object")
        max_visits = node_params.get("max_visits")
        if max_visits is not None and (type(max_visits) is not int or max_visits < 1):
            raise ValueError("unit operation max_visits must be positive or None")
        required_capabilities = node_params.get("required_capabilities", ())
        if not isinstance(required_capabilities, tuple):
            tuple(required_capabilities)

    # Build the flow incidence index once. The old return-node check rescanned
    # every relation for every operation, turning validation into O(V*E).
    outgoing: set[str] = set()
    for relation in program.relations:
        if relation_id(relation) != METHOD_FLOW_RELATION:
            continue
        sources = relation.units("source")
        targets = relation.units("target")
        source_id = endpoint_child_id(sources[0])
        target_id = endpoint_child_id(targets[0])
        if source_id is None or target_id is None:
            raise ValueError("method.flow must connect operation graphs")
        if source_id not in operations_by_id or target_id not in operations_by_id:
            raise ValueError("unit.flow may connect only method.operation children")
        outgoing.add(source_id)

    for node in operations:
        # This Unit has already been classified as method.operation. Read its
        # immutable parameter/symbol cuts once instead of re-entering the public
        # accessor validation path for every field.
        node_params = node.parameters
        kind = MethodNodeKind(str(node_params["kind"]))
        str(node_params["operation_type"])
        configuration = node_params.get("configuration", {})
        if not isinstance(configuration, Mapping):
            raise TypeError("method operation configuration must be an object")
        max_visits = node_params.get("max_visits")
        if max_visits is not None and (type(max_visits) is not int or max_visits < 1):
            raise ValueError("method operation max_visits must be positive or null")
        str(node_params["input_schema"])
        str(node_params["output_schema"])
        tuple(node_params.get("evidence_obligations", ()))
        capability_id_raw = node_params.get("capability_id")
        capability_id = None if capability_id_raw is None else str(capability_id_raw)
        capability_targets = tuple(node_params.get("capability_targets", ()))
        agent_id_raw = node_params.get("agent_id")
        agent_id = None if agent_id_raw is None else str(agent_id_raw)
        agent_targets = tuple(node_params.get("agent_targets", ()))

        symbols_by_id = {symbol.unit_id: symbol for symbol in node.symbols}

        def implementation_for(symbol_id: str) -> NoetriumUnit | None:
            symbol = symbols_by_id.get(symbol_id)
            if symbol is None:
                return None
            resolved = symbol_implementation(symbol)
            if resolved is None:
                return None
            if not is_implementation(resolved, METHOD_HANDLER_IMPLEMENTATION_TYPE):
                raise TypeError(
                    "method implementation symbol must bind method.handler Unit"
                )
            return resolved

        handler = implementation_for(METHOD_HANDLER_SYMBOL)
        capability_target = implementation_for(METHOD_CAPABILITY_TARGET_SYMBOL)
        agent_view = implementation_for(METHOD_AGENT_VIEW_SYMBOL)
        agent_target = implementation_for(METHOD_AGENT_TARGET_SYMBOL)
        if kind is MethodNodeKind.CAPABILITY:
            if (capability_id is None) == (capability_target is None):
                raise ValueError("capability operation requires exactly one static or dynamic target")
            if capability_id is not None and capability_targets:
                raise ValueError("static capability cannot declare dynamic target closure")
            if capability_target is not None and not capability_targets:
                raise ValueError("dynamic capability requires capability target closure")
            if handler is not None:
                raise ValueError("capability operation is host-invoked, not handler-invoked")
        elif kind is MethodNodeKind.AGENT:
            if (agent_id is None) == (agent_target is None):
                raise ValueError("agent operation requires exactly one static or dynamic target")
            if agent_view is None:
                raise ValueError("agent operation requires a view projector")
            if agent_id is not None and agent_targets:
                raise ValueError("static agent cannot declare dynamic target closure")
            if agent_target is not None and not agent_targets:
                raise ValueError("dynamic agent requires agent target closure")
            if handler is not None:
                raise ValueError("agent operation is host-invoked, not handler-invoked")
        elif kind in {MethodNodeKind.CHECKPOINT, MethodNodeKind.INTERRUPT}:
            if handler is not None:
                raise ValueError("platform method operation cannot define a handler")
        elif handler is None:
            raise ValueError(f"method operation {node.unit_id!r} requires a handler")
        if kind is MethodNodeKind.RETURN and node.unit_id in outgoing:
            raise ValueError("return operation cannot have outgoing method.flow")

    # Method and universal executable invariants have now been proven over the
    # same immutable member/relation indexes in one Θ(V+E+S) pass.


def validate_method_program(program: NoetriumUnit) -> None:
    """Validate one immutable Method Unit once per exact Unit digest.

    The complete validator remains fail-close for every new digest.  Because a
    NoetriumUnit is immutable, repeating the same graph walk through every
    accessor cannot discover new information and is therefore safely O(1) after
    the first successful validation.
    """
    if type(program) is not NoetriumUnit or not program.has_trait(METHOD_PROGRAM_TRAIT):
        raise TypeError("method program must be a method.program NoetriumUnit")
    digest = program.unit_digest
    with _VALIDATED_METHOD_PROGRAMS_LOCK:
        if digest in _VALIDATED_METHOD_PROGRAMS:
            return

    _validate_method_program_uncached(program)

    with _VALIDATED_METHOD_PROGRAMS_LOCK:
        if digest in _VALIDATED_METHOD_PROGRAMS:
            return
        _VALIDATED_METHOD_PROGRAMS[digest] = None
        if len(_VALIDATED_METHOD_PROGRAMS) > _VALIDATED_METHOD_PROGRAM_CACHE_LIMIT:
            oldest = next(iter(_VALIDATED_METHOD_PROGRAMS))
            if oldest != digest:
                _VALIDATED_METHOD_PROGRAMS.pop(oldest, None)


def method_operation(
    node_id: str,
    operation_type: str,
    *,
    kind: MethodNodeKind,
    handler: NoetriumUnit | MethodNodeHandler | None = None,
    capability_id: str | None = None,
    capability_target: NoetriumUnit | MethodCapabilityTargetHandler | None = None,
    capability_targets: tuple[str, ...] = (),
    effect_class: EffectClass = EffectClass.PURE,
    max_visits: int | None = 1,
    input_schema: str = "json",
    output_schema: str = "json",
    evidence_obligations: tuple[str, ...] = (),
    agent_id: str | None = None,
    agent_view: NoetriumUnit | MethodAgentViewHandler | None = None,
    agent_target: NoetriumUnit | MethodAgentTargetHandler | None = None,
    agent_targets: tuple[str, ...] = (),
    configuration: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    """Construct one canonical method.operation Unit directly."""

    node_id = _method_text(node_id, "method node_id")
    operation_type = _method_text(operation_type, "method operation_type")
    if not isinstance(kind, MethodNodeKind):
        raise TypeError("method operation kind must be MethodNodeKind")
    capability_targets = _method_tuple(capability_targets, "method capability_targets")
    agent_targets = _method_tuple(agent_targets, "method agent_targets")
    evidence_obligations = _method_tuple(
        evidence_obligations, "method evidence_obligations"
    )
    refs = {
        METHOD_HANDLER_SYMBOL: _implementation_ref(handler, "method handler"),
        METHOD_CAPABILITY_TARGET_SYMBOL: _implementation_ref(
            capability_target, "method capability target"
        ),
        METHOD_AGENT_VIEW_SYMBOL: _implementation_ref(agent_view, "method agent view"),
        METHOD_AGENT_TARGET_SYMBOL: _implementation_ref(
            agent_target, "method agent target"
        ),
    }
    symbols = tuple(
        symbol_unit(
            symbol_id,
            traits=("method.implementation",),
            implementation=ref,
        )
        for symbol_id, ref in refs.items()
        if ref is not None
    )
    node = structure_unit(
        node_id,
        traits=(METHOD_OPERATION_TRAIT, UNIT_OPERATION_TRAIT),
        parameters={
            "operation": f"method.node.{node_id}",
            "operation_type": operation_type,
            "kind": kind.value,
            "capability_id": capability_id,
            "capability_targets": capability_targets,
            "effect_class": effect_class.value,
            "max_visits": max_visits,
            "required_capabilities": (
                (capability_id,)
                if kind is MethodNodeKind.CAPABILITY and capability_id is not None
                else ()
            ),
            "input_schema": input_schema,
            "output_schema": output_schema,
            "evidence_obligations": evidence_obligations,
            "agent_id": agent_id,
            "agent_targets": agent_targets,
            "configuration": {} if configuration is None else dict(configuration),
        },
        symbols=symbols,
    )
    # Reuse the canonical node accessors for validation.
    method_node_kind(node)
    method_node_operation_type(node)
    method_node_configuration(node)
    method_node_max_visits(node)
    method_node_input_schema(node)
    method_node_output_schema(node)
    method_node_evidence_obligations(node)
    return node


def method_flow_relation(source_node_id: str, target_node_id: str) -> NoetriumUnit:
    source = _method_text(source_node_id, "method flow source")
    target = _method_text(target_node_id, "method flow target")
    return relation_unit(
        (endpoint_unit(source, None),),
        (endpoint_unit(target, None),),
        METHOD_FLOW_RELATION,
    )


def method_program(
    implementation: NoetriumUnit,
    *,
    entrypoint: str,
    operations: tuple[NoetriumUnit, ...],
    relations: tuple[NoetriumUnit, ...] = (),
    components: tuple[NoetriumUnit, ...] = (),
    configuration: Mapping[str, JsonValue] | None = None,
    state_schema: str = "json",
    input_schema: str = "json",
    output_schema: str = "json",
    required_capabilities: tuple[str, ...] = (),
    required_runtime_ports: tuple[MethodRuntimePort, ...] = (),
    execution_class: MethodExecutionClass = MethodExecutionClass.EFFECT_RECORDED,
    evidence_obligations: tuple[str, ...] = (),
    metric_names: tuple[str, ...] = (),
    artifact_kinds: tuple[str, ...] = (),
) -> NoetriumUnit:
    """Construct the exact method.program Unit; no graph/program builder IR exists."""

    implementation = require_participant_implementation(implementation)
    if str(implementation.parameters["kind"]) != "method":
        raise ValueError("method program implementation kind must be 'method'")
    entrypoint = _method_text(entrypoint, "method entrypoint")
    if type(operations) is not tuple or not operations:
        raise TypeError("method program operations must be a non-empty Unit tuple")
    if any(
        type(node) is not NoetriumUnit or not node.has_trait(METHOD_OPERATION_TRAIT)
        for node in operations
    ):
        raise TypeError("method program operations must be method.operation Units")
    if type(components) is not tuple or any(
        type(component) is not NoetriumUnit
        or not component.has_trait(METHOD_COMPONENT_TRAIT)
        for component in components
    ):
        raise TypeError("method program components must be method.component Units")
    ids = tuple(node.unit_id for node in (*operations, *components))
    if len(ids) != len(set(ids)):
        raise ValueError("method program child identities must be unique")
    if type(relations) is not tuple or any(
        type(relation) is not NoetriumUnit for relation in relations
    ):
        raise TypeError("method program relations must be Unit tuple")
    graph = structure_unit(
        participant_implementation_id(implementation),
        traits=(METHOD_PROGRAM_TRAIT, EXECUTABLE_UNIT_TRAIT),
        parameters={
            "domain": "method",
            "version": participant_implementation_version(implementation),
            "entrypoint": entrypoint,
            "configuration": {} if configuration is None else dict(configuration),
            "state_schema": state_schema,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "required_capabilities": required_capabilities,
            "required_runtime_ports": tuple(port.value for port in required_runtime_ports),
            "execution_class": execution_class.value,
            "evidence_obligations": evidence_obligations,
            "metric_names": metric_names,
            "artifact_kinds": artifact_kinds,
        },
        members=(implementation,) + operations + components,
        relations=relations,
    )
    validate_method_program(graph)
    return graph


@dataclass(frozen=True, slots=True)
class MethodCheckpoint:
    """Non-authoritative receipt for a verified Machine journal cut."""

    run_id: str
    program_digest: str
    sequence: int
    current_node: str
    machine_id: str
    machine_revision: int
    machine_commit_id: str | None
    state_digest: str
    checkpoint_value: JsonValue = None
    checkpoint_id: str = field(init=False)

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.run_id, self.program_digest, self.current_node, self.machine_id, self.state_digest
        )):
            raise ValueError("method checkpoint identity fields are required")
        require_sha256(self.program_digest, "method checkpoint program_digest")
        require_sha256(self.state_digest, "method checkpoint state_digest")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("method checkpoint sequence must be non-negative")
        if type(self.machine_revision) is not int or self.machine_revision < 0:
            raise ValueError("method checkpoint machine_revision must be non-negative")
        if self.machine_revision == 0 and self.machine_commit_id is not None:
            raise ValueError("revision zero checkpoint cannot reference a commit")
        if self.machine_revision > 0:
            if self.machine_commit_id is None:
                raise ValueError("committed checkpoint requires machine_commit_id")
            require_sha256(self.machine_commit_id, "method checkpoint machine_commit_id")
        object.__setattr__(self, "checkpoint_value", freeze_json(self.checkpoint_value))
        object.__setattr__(self, "checkpoint_id", canonical_digest({
            "run_id": self.run_id,
            "program_digest": self.program_digest,
            "sequence": self.sequence,
            "current_node": self.current_node,
            "machine_id": self.machine_id,
            "machine_revision": self.machine_revision,
            "machine_commit_id": self.machine_commit_id,
            "state_digest": self.state_digest,
            "checkpoint_value": self.checkpoint_value,
        }))



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
    evidence_reference: ArtifactReference | None = None
    binding_plan_digest: str | None = None
    runtime_binding_digest: str | None = None
    schema_digest: str | None = None
    failure_code: str | None = None
    failure_phase: str | None = None
    failure_id: str | None = None
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
        if self.evidence_reference is not None and type(
            self.evidence_reference
        ) is not ArtifactReference:
            raise TypeError(
                "method run evidence_reference must be ArtifactReference or null"
            )
        if self.failure_id is not None and (
            not isinstance(self.failure_id, str) or not self.failure_id.strip()
        ):
            raise ValueError("method run failure_id must be non-empty text or null")
        if self.status is MethodRunStatus.SUCCEEDED and self.failure_id is not None:
            raise ValueError("successful method run cannot carry failure_id")
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
            "failure_id": self.failure_id,
            "diagnostics": self.diagnostics,
        }))


@runtime_checkable
class MethodEvidencePort(Protocol):
    """Authoritative evidence sink injected by composition."""

    def record_checkpoint(self, checkpoint: MethodCheckpoint) -> None: ...
    def record_result(
        self,
        result: MethodRunResult,
    ) -> ArtifactReference | None: ...

    def validate_result(self, result: MethodRunResult, obligations: tuple[str, ...]) -> MethodEvidenceStatus: ...


@runtime_checkable
class MethodObservationPort(Protocol):
    """Non-authoritative observation sink; failures must not change method truth."""

    def publish(self, event: MethodEvent, context: ExecutionContext) -> None: ...


@dataclass(frozen=True, slots=True)
class MethodRuntimeContext:
    """Explicit dependency bundle; there is no ambient service registry."""

    execution: ExecutionContext
    execution_control: ExecutionControlPort = UNBOUNDED_EXECUTION_CONTROL
    capabilities: CapabilityPort | None = None
    dispatcher: OperationDispatchPort | None = None
    evidence: MethodEvidencePort | None = None
    observation: MethodObservationPort | None = None
    agent_loop: MethodAgentLoopPort | AsyncMethodAgentLoopPort | None = None
    schemas: MethodSchemaPort | None = None
    program_binding: BoundExecutableUnitPort | None = None
    machine_id: str | None = None
    unit_activation: UnitActivationRuntimePort | None = None
    execution_budget: ExecutionBudgetAuthorityPort | None = None
    binding_plan_digest: str | None = None
    runtime_binding_digest: str | None = None
    schema_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ExecutionContext):
            raise TypeError("method runtime execution must be ExecutionContext")
        if not isinstance(self.execution_control, ExecutionControlPort):
            raise TypeError(
                "method runtime execution_control must satisfy ExecutionControlPort"
            )
        if self.program_binding is not None and not isinstance(
            self.program_binding, BoundExecutableUnitPort
        ):
            raise TypeError(
                "method runtime program_binding must satisfy BoundExecutableUnitPort"
            )
        if self.machine_id is not None and (
            type(self.machine_id) is not str or not self.machine_id.strip()
        ):
            raise ValueError("method runtime machine_id must be non-empty text")
        if (self.program_binding is None) != (self.machine_id is None):
            raise ValueError(
                "method runtime program_binding and machine_id must be bound together"
            )
        if self.execution_budget is not None and not isinstance(
            self.execution_budget,
            ExecutionBudgetAuthorityPort,
        ):
            raise TypeError(
                "method runtime execution_budget must satisfy "
                "ExecutionBudgetAuthorityPort"
            )
        if self.execution.trial_budget and self.execution_budget is None:
            raise RuntimeError(
                "scientific TrialBudget requires the shared execution-budget authority"
            )
        if self.unit_activation is not None:
            if not isinstance(self.unit_activation, UnitActivationRuntimePort):
                raise TypeError(
                    "method runtime unit_activation must satisfy UnitActivationRuntimePort"
                )
            require_sha256(
                self.unit_activation.identity_digest,
                "method runtime unit-activation port identity_digest",
            )
        for name, value in (
            ("binding_plan_digest", self.binding_plan_digest),
            ("runtime_binding_digest", self.runtime_binding_digest),
            ("schema_digest", self.schema_digest),
        ):
            if value is not None:
                require_sha256(value, f"method runtime {name}")

    @property
    def effective_runtime_binding_digest(self) -> str | None:
        if self.unit_activation is None:
            return self.runtime_binding_digest
        return canonical_digest({
            "declared_runtime_binding_digest": self.runtime_binding_digest,
            "child_machine_port_identity_digest": (
                self.unit_activation.identity_digest
            ),
            "execution_budget_identity_digest": (
                None
                if self.execution_budget is None
                else self.execution_budget.identity_digest
            ),
        })


__all__ = [
    "AsyncMethodAgentLoopPort", "MethodAgentLoopPort", "MethodLifetimeResourcePort", "method_lifetime_resources", "MethodAgentRequest", "MethodAgentResult",
    "MethodCheckpoint", "MethodEvidencePort", "MethodEvent", "MethodEvidenceStatus",
    "MethodExecutionClass", "MethodInterrupt", "MethodNodeHandler", "MethodNodeKind", "MethodNodeRequest",
    "MethodNodeResult", "MethodObservationPort", "method_flow_relation", "method_operation", "method_program",
    "METHOD_PROGRAM_TRAIT", "METHOD_OPERATION_TRAIT", "METHOD_COMPONENT_TRAIT", "METHOD_FLOW_RELATION",
    "method_program_digest", "method_program_identity", "method_program_configuration", "method_program_state_schema",
    "method_program_input_schema", "method_program_output_schema", "method_program_entrypoint",
    "method_program_required_capabilities", "method_program_required_runtime_ports",
    "method_program_execution_class", "method_program_evidence_obligations",
    "method_program_metric_names", "method_program_artifact_kinds", "method_program_nodes", "method_program_components",
    "method_program_node", "method_node_kind", "method_node_operation_type",
    "method_node_configuration", "method_node_effect_class", "method_node_max_visits",
    "method_node_input_schema", "method_node_output_schema", "method_node_evidence_obligations",
    "method_node_capability_id", "method_node_capability_targets", "method_node_agent_id",
    "method_node_agent_targets", "method_node_handler", "method_node_capability_target",
    "method_node_agent_view", "method_node_agent_target", "method_node_implementation_digest",
    "method_node_next_nodes", "validate_method_program",
    "MethodRunResult", "MethodRunStatus", "MethodRuntimeContext", "MethodRuntimePort", "MethodSchemaPort",
]
