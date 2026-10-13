"""Universal Unit Machine.

Every executable NoetriumUnit, regardless of scientific domain, is interpreted
by this one machine. Domain labels are semantic metadata only; they never select
an executor, state machine, journal, or lifecycle implementation.

The execution calculus is deliberately small: immutable Unit topology, mutable
journal-backed state, operation invocation, conditional control flow, bounded
or externally-governed repetition, child-Unit recursion, effects, checkpoints,
wait/interrupt, and return. Custom downstream semantics are ordinary operation
implementations carried by Units; the kernel never needs a new domain executor.
"""
from __future__ import annotations

import traceback

from noetrium_platform.foundation.kernel.structure import (
    callable_source_digest,
    endpoint_unit,
    implementation_digest,
    is_implementation,
    relation_unit,
    resolve_callable,
    structure_unit,
    symbol_implementation,
    symbol_unit,
)

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from threading import RLock
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel.canonical import canonical_digest, freeze_json, require_sha256, thaw_json
from noetrium_platform.foundation.kernel.kernel.family import MachineFamilyDescriptor
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.kernel.unit_failure import exception_reference_projection
from noetrium_platform.foundation.kernel.kernel.json_value import JsonObject, JsonValue
from noetrium_platform.foundation.kernel.kernel.contracts import ChildMachineLink
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel.machine import (
    MachineCommand, ExecutableUnitRef, MachineSnapshot,
    MachineStateDelta, MachineStateMutation, MachineStatus, UnitExecutionLock,
    TransitionProposal,
)

UNIT_MACHINE_COMMANDS = ("unit.start", "unit.step", "unit.resume", "unit.limit")
UNIVERSAL_UNIT_MACHINE_VERSION = "4"
UNIVERSAL_UNIT_STATE_SCHEMA_VERSION = "3"
UNIT_STATE_KEY = "_unit"
# Platform-owned livelock detection. These are operational safety thresholds,
# not scientific budgets: they react only to explicit no-progress evidence.
UNIT_SAME_NO_PROGRESS_LIMIT = 3
UNIT_CONSECUTIVE_NO_PROGRESS_LIMIT = 8


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


EXECUTABLE_UNIT_TRAIT = "unit.executable"
UNIT_OPERATION_TRAIT = "unit.operation"
UNIT_FLOW_RELATION = "unit.flow"
UNIT_OPERATION_IMPLEMENTATION_SYMBOL = "implementation"
UNIT_OPERATION_IMPLEMENTATION_TRAIT = "unit.operation.implementation"




def executable_unit_id(unit: NoetriumUnit) -> str:
    return unit.unit_id


def executable_unit_digest(unit: NoetriumUnit) -> str:
    validate_executable_unit(unit)
    return unit.unit_digest


def executable_unit_domain(unit: NoetriumUnit) -> str:
    validate_executable_unit(unit)
    return _text(unit.parameters.get("domain", "unit"), "executable unit domain")



def executable_unit_version(unit: NoetriumUnit) -> str:
    validate_executable_unit(unit)
    return str(unit.parameters["version"])


def executable_unit_state_schema(unit: NoetriumUnit) -> str:
    validate_executable_unit(unit)
    return str(unit.parameters["state_schema"])


def executable_unit_entrypoint(unit: NoetriumUnit) -> str:
    validate_executable_unit(unit)
    return str(unit.parameters["entrypoint"])


def executable_unit_required_capabilities(unit: NoetriumUnit) -> tuple[str, ...]:
    validate_executable_unit(unit)
    value = unit.parameters.get("required_capabilities", ())
    return tuple(value) if isinstance(value, tuple) else tuple(value)


def executable_unit_nodes(unit: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    """Return only executable operation members.

    An executable Unit may recursively own arbitrary semantic child Units.
    Execution is selected by the unit.operation schema, never by directory,
    domain name, or the mere fact that a child exists.
    """

    validate_executable_unit(unit)
    return tuple(
        child for child in unit.members
        if child.has_trait(UNIT_OPERATION_TRAIT)
    )


def executable_unit_node(unit: NoetriumUnit, node_id: str) -> NoetriumUnit:
    validate_executable_unit(unit)
    node = unit.member(_text(node_id, "executable unit node_id"))
    unit_operation_name(node)
    return node


def unit_operation(
    node_id: str,
    operation: str,
    *,
    implementation: NoetriumUnit | None = None,
    configuration: Mapping[str, JsonValue] | None = None,
    max_visits: int | None = None,
    required_capabilities: tuple[str, ...] = (),
) -> NoetriumUnit:
    node_id = _text(node_id, "unit operation id")
    operation = _text(operation, "unit operation")
    if max_visits is not None and (type(max_visits) is not int or max_visits < 1):
        raise ValueError("unit operation max_visits must be positive or None")
    if type(required_capabilities) is not tuple or any(
        type(item) is not str or not item.strip() for item in required_capabilities
    ):
        raise TypeError("unit operation required_capabilities must be text tuple")
    symbols = ()
    if implementation is not None:
        if type(implementation) is not NoetriumUnit or not is_implementation(implementation):
            raise TypeError("unit operation implementation must be implementation Unit")
        symbols = (
            symbol_unit(
                UNIT_OPERATION_IMPLEMENTATION_SYMBOL,
                traits=(UNIT_OPERATION_IMPLEMENTATION_TRAIT,),
                implementation=implementation,
            ),
        )
    return structure_unit(
        node_id,
        traits=(UNIT_OPERATION_TRAIT,),
        parameters={
            "operation": operation,
            "configuration": {} if configuration is None else configuration,
            "max_visits": max_visits,
            "required_capabilities": required_capabilities,
        },
        symbols=symbols,
    )


def unit_operation_name(node: NoetriumUnit) -> str:
    if type(node) is not NoetriumUnit or not node.has_trait(UNIT_OPERATION_TRAIT):
        raise TypeError("operation must carry the unit.operation schema")
    return _text(node.parameters.get("operation"), "unit operation")


def unit_operation_implementation(node: NoetriumUnit) -> NoetriumUnit | None:
    unit_operation_name(node)
    try:
        symbol = node.symbol(UNIT_OPERATION_IMPLEMENTATION_SYMBOL)
    except LookupError:
        return None
    implementation = symbol_implementation(symbol)
    if implementation is None:
        raise ValueError("unit operation implementation symbol has no implementation")
    return implementation


def unit_operation_configuration(node: NoetriumUnit) -> Mapping[str, JsonValue]:
    unit_operation_name(node)
    value = node.parameters.get("configuration", {})
    if not isinstance(value, Mapping):
        raise TypeError("unit operation configuration must be an object")
    return value


def unit_operation_max_visits(node: NoetriumUnit) -> int | None:
    unit_operation_name(node)
    value = node.parameters.get("max_visits")
    if value is not None and (type(value) is not int or value < 1):
        raise ValueError("unit operation max_visits must be positive or None")
    return value


def unit_operation_required_capabilities(node: NoetriumUnit) -> tuple[str, ...]:
    unit_operation_name(node)
    value = node.parameters.get("required_capabilities", ())
    if not isinstance(value, tuple):
        value = tuple(value)
    return tuple(str(item) for item in value)


def unit_operation_allowed_next_nodes(
    unit: NoetriumUnit, node: NoetriumUnit
) -> tuple[str, ...]:
    unit_operation_name(node)
    return tuple(
        sorted(
            relation.targets[0].child_id
            for relation in unit.relations
            if relation.relation_id == UNIT_FLOW_RELATION
            and relation.sources[0].child_id == node.unit_id
            and relation.targets[0].child_id is not None
        )
    )


def unit_operation_next_node(
    unit: NoetriumUnit, node: NoetriumUnit
) -> str | None:
    unit_operation_name(node)
    defaults = tuple(
        relation.targets[0].child_id
        for relation in unit.relations
        if relation.relation_id == UNIT_FLOW_RELATION
        and relation.sources[0].child_id == node.unit_id
        and relation.targets[0].child_id is not None
        and relation.parameters.get("default") is True
    )
    if len(defaults) > 1:
        raise ValueError("unit operation has multiple default transitions")
    return None if not defaults else defaults[0]


def validate_executable_unit(unit: NoetriumUnit) -> None:
    if type(unit) is not NoetriumUnit or not unit.has_trait(EXECUTABLE_UNIT_TRAIT):
        raise TypeError("executable unit must carry the unit.executable schema")
    params = unit.parameters
    for name in ("domain", "version", "state_schema", "entrypoint"):
        _text(params.get(name), f"executable unit {name}")
    operations = tuple(
        child for child in unit.members
        if child.has_trait(UNIT_OPERATION_TRAIT)
    )
    if not operations:
        raise ValueError("executable unit requires at least one unit.operation member")
    operation_ids = {child.unit_id for child in operations}
    entrypoint = str(params["entrypoint"])
    if entrypoint not in operation_ids:
        raise ValueError("executable unit entrypoint must reference unit.operation")
    required = params.get("required_capabilities", ())
    if not isinstance(required, tuple):
        raise TypeError("executable unit required_capabilities must be a tuple")
    if len(required) != len(set(required)) or any(
        type(item) is not str or not item.strip() for item in required
    ):
        raise ValueError("executable unit required_capabilities must be unique text")
    for node in operations:
        unit_operation_name(node)
        unit_operation_configuration(node)
        unit_operation_max_visits(node)
        unit_operation_required_capabilities(node)
    default_counts: dict[str, int] = {}
    for relation in unit.relations:
        if relation.relation_id != UNIT_FLOW_RELATION:
            continue
        if relation.sources[0].child_id is None or relation.targets[0].child_id is None:
            raise ValueError("unit.flow must connect operations")
        source_id = relation.sources[0].child_id
        target_id = relation.targets[0].child_id
        if source_id not in operation_ids or target_id not in operation_ids:
            raise ValueError("unit.flow may connect only unit.operation members")
        if relation.parameters.get("default") is True:
            count = default_counts.get(source_id, 0) + 1
            if count > 1:
                raise ValueError(
                    "unit operation has multiple default transitions: " + source_id
                )
            default_counts[source_id] = count


def executable_unit_ref(unit: NoetriumUnit, lock: UnitExecutionLock) -> ExecutableUnitRef:
    validate_executable_unit(unit)
    if not isinstance(lock, UnitExecutionLock):
        raise TypeError("executable unit lock must be UnitExecutionLock")
    return ExecutableUnitRef(
        unit_digest=unit.unit_digest,
        state_schema=executable_unit_state_schema(unit),
        domain=executable_unit_domain(unit),
        version=executable_unit_version(unit),
        execution_lock=lock,
    )


@lru_cache(maxsize=65536)
def _unit_flow_interned(
    source: str,
    target: str,
    default: bool,
) -> NoetriumUnit:
    """Intern one already-validated immutable flow identity."""

    return relation_unit(
        (endpoint_unit(source, None),),
        (endpoint_unit(target, None),),
        UNIT_FLOW_RELATION,
        {"default": default},
    )


def unit_flow(
    source_node_id: str,
    target_node_id: str,
    *,
    default: bool = False,
) -> NoetriumUnit:
    """Create one exact unit-flow relation Unit."""

    source = _text(source_node_id, "unit flow source")
    target = _text(target_node_id, "unit flow target")
    if type(default) is not bool:
        raise TypeError("unit flow default must be boolean")
    return _unit_flow_interned(source, target, default)


def executable_unit(
    unit_id: str,
    *,
    domain: str = "unit",
    version: str,
    state_schema: str,
    entrypoint: str,
    members: tuple[NoetriumUnit, ...],
    relations: tuple[NoetriumUnit, ...] = (),
    required_capabilities: tuple[str, ...] = (),
) -> NoetriumUnit:
    """Construct the canonical executable semantic Unit directly.

    There is intentionally no Unit/Graph builder IR. Nodes and relations are
    already NoetriumUnits; this function only validates and wraps them in the
    unit.executable schema.
    """

    unit_id = _text(unit_id, "executable unit_id")
    domain = _text(domain, "executable unit domain")
    version = _text(version, "executable unit version")
    state_schema = _text(state_schema, "executable unit state_schema")
    entrypoint = _text(entrypoint, "executable unit entrypoint")
    if type(members) is not tuple or not members or any(
        type(node) is not NoetriumUnit for node in members
    ):
        raise TypeError("executable unit members must be a non-empty NoetriumUnit tuple")
    if type(relations) is not tuple or any(
        type(relation) is not NoetriumUnit for relation in relations
    ):
        raise TypeError("executable unit relations must be a NoetriumUnit tuple")
    if type(required_capabilities) is not tuple or any(
        type(item) is not str or not item.strip() for item in required_capabilities
    ):
        raise TypeError("executable unit required_capabilities must be text tuple")
    if len(required_capabilities) != len(set(required_capabilities)):
        raise ValueError("executable unit required_capabilities must be unique")

    unit = structure_unit(
        unit_id,
        traits=(EXECUTABLE_UNIT_TRAIT,),
        parameters={
            "domain": domain,
            "version": version,
            "state_schema": state_schema,
            "entrypoint": entrypoint,
            "required_capabilities": required_capabilities,
        },
        members=members,
        relations=relations,
    )
    validate_executable_unit(unit)
    return unit


@dataclass(frozen=True, slots=True)
class UnitStateDelta:
    """The one mutable-state channel of STEP.

    data is downstream-owned unit state. semantic is namespaced
    machine/runtime state. They are disjoint namespaces inside one state delta,
    not competing mutation mechanisms.
    """

    data: JsonObject = field(default_factory=dict)
    semantic: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.data, Mapping):
            raise TypeError("UnitStateDelta.data must be an object")
        if not isinstance(self.semantic, Mapping):
            raise TypeError("UnitStateDelta.semantic must be an object")
        object.__setattr__(self, "data", freeze_json(self.data))
        object.__setattr__(self, "semantic", freeze_json(self.semantic))


@dataclass(frozen=True, slots=True)
class UnitGoto:
    """Continue through an explicit target or the Unit static flow."""

    target: str | None = None

    def __post_init__(self) -> None:
        if self.target is not None:
            object.__setattr__(
                self,
                "target",
                _text(self.target, "UnitGoto.target"),
            )


@dataclass(frozen=True, slots=True)
class UnitActivate:
    """Durably activate one or more child executable Units, then continue."""

    requests: tuple[JsonObject, ...]
    continuation: str | None = None
    join: str = "all"
    quorum: int | None = None

    def __post_init__(self) -> None:
        if type(self.requests) is not tuple or not self.requests:
            raise ValueError("UnitActivate.requests must be a non-empty tuple")
        frozen = []
        for request in self.requests:
            if not isinstance(request, Mapping):
                raise TypeError("UnitActivate requests must be objects")
            value = freeze_json(request)
            if not isinstance(value, Mapping):
                raise TypeError("UnitActivate request must freeze to object")
            frozen.append(value)
        if self.continuation is not None:
            object.__setattr__(
                self,
                "continuation",
                _text(self.continuation, "UnitActivate.continuation"),
            )
        join = _text(self.join, "UnitActivate.join")
        if join not in {"all", "any", "quorum"}:
            raise ValueError("UnitActivate.join must be all, any, or quorum")
        if join == "quorum":
            if type(self.quorum) is not int or not (1 <= self.quorum <= len(frozen)):
                raise ValueError("UnitActivate.quorum must be within request cardinality")
        elif self.quorum is not None:
            raise ValueError("UnitActivate.quorum is valid only for quorum joins")
        object.__setattr__(self, "requests", tuple(frozen))
        object.__setattr__(self, "join", join)


@dataclass(frozen=True, slots=True)
class UnitSuspend:
    """Suspend without changing the unit continuation target."""

    status: MachineStatus = MachineStatus.WAITING
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            MachineStatus.WAITING,
            MachineStatus.INTERRUPTED,
        }:
            raise ValueError(
                "UnitSuspend status must be WAITING or INTERRUPTED"
            )
        if self.reason is not None:
            object.__setattr__(
                self,
                "reason",
                _text(self.reason, "UnitSuspend.reason"),
            )


@dataclass(frozen=True, slots=True)
class UnitHalt:
    """Terminate the Unit. No continuation exists after this control value."""

    status: MachineStatus = MachineStatus.COMPLETED

    def __post_init__(self) -> None:
        if self.status not in {
            MachineStatus.COMPLETED,
            MachineStatus.FAILED,
        }:
            raise ValueError(
                "UnitHalt status must be COMPLETED or FAILED"
            )


UnitControl = UnitGoto | UnitActivate | UnitSuspend | UnitHalt


@dataclass(frozen=True, slots=True)
class UnitObservation:
    """Non-computational observability attached to one accepted STEP."""

    emitted_commands: tuple[MachineCommand, ...] = ()
    events: tuple[JsonValue, ...] = ()
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    child_links: tuple[ChildMachineLink, ...] = ()
    checkpoint: JsonValue = None
    progress: bool | None = None
    progress_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if type(self.emitted_commands) is not tuple or any(
            not isinstance(item, MachineCommand)
            for item in self.emitted_commands
        ):
            raise TypeError(
                "UnitObservation.emitted_commands must be MachineCommand tuple"
            )
        for field_name in (
            "events",
            "output_refs",
            "evidence_refs",
            "artifact_refs",
        ):
            value = getattr(self, field_name)
            if type(value) is not tuple:
                raise TypeError(
                    f"UnitObservation.{field_name} must be tuple"
                )
        for field_name in (
            "output_refs",
            "evidence_refs",
            "artifact_refs",
        ):
            value = getattr(self, field_name)
            if any(type(item) is not str or not item.strip() for item in value):
                raise TypeError(
                    f"UnitObservation.{field_name} must contain non-empty text"
                )
        if type(self.child_links) is not tuple or any(
            not isinstance(item, ChildMachineLink)
            for item in self.child_links
        ):
            raise TypeError(
                "UnitObservation.child_links must be ChildMachineLink tuple"
            )
        if self.progress is not None and type(self.progress) is not bool:
            raise TypeError(
                "UnitObservation.progress must be boolean or None"
            )
        if self.progress_fingerprint is not None:
            require_sha256(
                self.progress_fingerprint,
                "UnitObservation.progress_fingerprint",
            )
            if self.progress is not False:
                raise ValueError(
                    "progress_fingerprint requires progress=False"
                )
        object.__setattr__(
            self,
            "events",
            tuple(freeze_json(item) for item in self.events),
        )
        object.__setattr__(
            self,
            "checkpoint",
            freeze_json(self.checkpoint),
        )


@dataclass(frozen=True, slots=True)
class UnitTransition:
    """The sole semantic result of one Universal Unit Machine STEP."""

    state: UnitStateDelta = field(default_factory=UnitStateDelta)
    control: UnitControl = field(default_factory=UnitGoto)
    intents: tuple[str, ...] = ()
    value: JsonValue = None
    observation: UnitObservation = field(default_factory=UnitObservation)

    def __post_init__(self) -> None:
        if not isinstance(self.state, UnitStateDelta):
            raise TypeError("UnitTransition.state must be UnitStateDelta")
        if not isinstance(
            self.control,
            (UnitGoto, UnitActivate, UnitSuspend, UnitHalt),
        ):
            raise TypeError(
                "UnitTransition.control must be Goto, Activate, Suspend, or Halt"
            )
        if type(self.intents) is not tuple or any(
            type(item) is not str or not item.strip()
            for item in self.intents
        ):
            raise TypeError(
                "UnitTransition.intents must be non-empty text tuple"
            )
        if len(self.intents) != len(set(self.intents)):
            raise ValueError("UnitTransition.intents must be unique")
        if not isinstance(self.observation, UnitObservation):
            raise TypeError(
                "UnitTransition.observation must be UnitObservation"
            )
        object.__setattr__(self, "value", freeze_json(self.value))

    @classmethod
    def goto(
        cls,
        target: str | None = None,
        *,
        value: JsonValue = None,
        state_delta: Mapping[str, JsonValue] | None = None,
        semantic_delta: Mapping[str, JsonValue] | None = None,
        intents: tuple[str, ...] = (),
        emitted_commands: tuple[MachineCommand, ...] = (),
        events: tuple[JsonValue, ...] = (),
        output_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
        child_links: tuple[ChildMachineLink, ...] = (),
        checkpoint: JsonValue = None,
        progress: bool | None = None,
        progress_fingerprint: str | None = None,
    ) -> "UnitTransition":
        return cls(
            state=UnitStateDelta(
                {} if state_delta is None else state_delta,
                {} if semantic_delta is None else semantic_delta,
            ),
            control=UnitGoto(target),
            intents=intents,
            value=value,
            observation=UnitObservation(
                emitted_commands=emitted_commands,
                events=events,
                output_refs=output_refs,
                evidence_refs=evidence_refs,
                artifact_refs=artifact_refs,
                child_links=child_links,
                checkpoint=checkpoint,
                progress=progress,
                progress_fingerprint=progress_fingerprint,
            ),
        )

    @classmethod
    def activate(
        cls,
        requests: tuple[Mapping[str, JsonValue], ...],
        *,
        continuation: str | None = None,
        join: str = "all",
        quorum: int | None = None,
        value: JsonValue = None,
        state_delta: Mapping[str, JsonValue] | None = None,
        semantic_delta: Mapping[str, JsonValue] | None = None,
        intents: tuple[str, ...] = (),
        emitted_commands: tuple[MachineCommand, ...] = (),
        events: tuple[JsonValue, ...] = (),
        output_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
        child_links: tuple[ChildMachineLink, ...] = (),
        checkpoint: JsonValue = None,
        progress: bool | None = None,
        progress_fingerprint: str | None = None,
    ) -> "UnitTransition":
        return cls(
            state=UnitStateDelta(
                {} if state_delta is None else state_delta,
                {} if semantic_delta is None else semantic_delta,
            ),
            control=UnitActivate(
                tuple(dict(request) for request in requests),
                continuation=continuation,
                join=join,
                quorum=quorum,
            ),
            intents=intents,
            value=value,
            observation=UnitObservation(
                emitted_commands=emitted_commands,
                events=events,
                output_refs=output_refs,
                evidence_refs=evidence_refs,
                artifact_refs=artifact_refs,
                child_links=child_links,
                checkpoint=checkpoint,
                progress=progress,
                progress_fingerprint=progress_fingerprint,
            ),
        )

    @classmethod
    def suspend(
        cls,
        reason: str | None = None,
        *,
        interrupted: bool = False,
        value: JsonValue = None,
        state_delta: Mapping[str, JsonValue] | None = None,
        semantic_delta: Mapping[str, JsonValue] | None = None,
        intents: tuple[str, ...] = (),
        emitted_commands: tuple[MachineCommand, ...] = (),
        events: tuple[JsonValue, ...] = (),
        output_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
        child_links: tuple[ChildMachineLink, ...] = (),
        checkpoint: JsonValue = None,
        progress: bool | None = None,
        progress_fingerprint: str | None = None,
    ) -> "UnitTransition":
        return cls(
            state=UnitStateDelta(
                {} if state_delta is None else state_delta,
                {} if semantic_delta is None else semantic_delta,
            ),
            control=UnitSuspend(
                MachineStatus.INTERRUPTED
                if interrupted
                else MachineStatus.WAITING,
                reason,
            ),
            intents=intents,
            value=value,
            observation=UnitObservation(
                emitted_commands=emitted_commands,
                events=events,
                output_refs=output_refs,
                evidence_refs=evidence_refs,
                artifact_refs=artifact_refs,
                child_links=child_links,
                checkpoint=checkpoint,
                progress=progress,
                progress_fingerprint=progress_fingerprint,
            ),
        )

    @classmethod
    def halt(
        cls,
        *,
        failed: bool = False,
        value: JsonValue = None,
        state_delta: Mapping[str, JsonValue] | None = None,
        semantic_delta: Mapping[str, JsonValue] | None = None,
        intents: tuple[str, ...] = (),
        emitted_commands: tuple[MachineCommand, ...] = (),
        events: tuple[JsonValue, ...] = (),
        output_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
        child_links: tuple[ChildMachineLink, ...] = (),
        checkpoint: JsonValue = None,
        progress: bool | None = None,
        progress_fingerprint: str | None = None,
    ) -> "UnitTransition":
        return cls(
            state=UnitStateDelta(
                {} if state_delta is None else state_delta,
                {} if semantic_delta is None else semantic_delta,
            ),
            control=UnitHalt(
                MachineStatus.FAILED
                if failed
                else MachineStatus.COMPLETED
            ),
            intents=intents,
            value=value,
            observation=UnitObservation(
                emitted_commands=emitted_commands,
                events=events,
                output_refs=output_refs,
                evidence_refs=evidence_refs,
                artifact_refs=artifact_refs,
                child_links=child_links,
                checkpoint=checkpoint,
                progress=progress,
                progress_fingerprint=progress_fingerprint,
            ),
        )


@dataclass(frozen=True, slots=True)
class UnitStepContext:
    unit: NoetriumUnit
    node: NoetriumUnit
    snapshot: MachineSnapshot
    configuration: JsonObject
    payload: JsonValue
    data: JsonObject
    previous_value: JsonValue
    visit: int
    visit_counts: Mapping[str, int] = field(default_factory=dict)
    checkpoint_value: JsonValue = None
    semantic_state: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Static Unit/node validity and JSON freezing are compile/command/snapshot
        # responsibilities. STEP is the hot path: do not re-walk the immutable
        # Unit graph or re-freeze already canonical Machine state on every call.
        if type(self.unit) is not NoetriumUnit:
            raise TypeError("UnitStepContext.unit must be NoetriumUnit")
        if type(self.node) is not NoetriumUnit:
            raise TypeError("UnitStepContext.node must be NoetriumUnit")
        if not isinstance(self.snapshot, MachineSnapshot):
            raise TypeError("UnitStepContext requires MachineSnapshot")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("UnitStepContext.configuration must be object")
        if not isinstance(self.data, Mapping):
            raise TypeError("UnitStepContext.data must be object")
        if not isinstance(self.visit_counts, Mapping):
            raise TypeError("UnitStepContext.visit_counts must be object")
        if not isinstance(self.semantic_state, Mapping):
            raise TypeError("UnitStepContext.semantic_state must be object")
        if type(self.visit) is not int or self.visit <= 0:
            raise ValueError("UnitStepContext.visit must be positive")

    def goto(self, target: str | None = None, **kwargs) -> UnitTransition:
        return UnitTransition.goto(target, **kwargs)

    def activate(
        self,
        requests: tuple[Mapping[str, JsonValue], ...],
        **kwargs,
    ) -> UnitTransition:
        return UnitTransition.activate(requests, **kwargs)

    def suspend(self, reason: str | None = None, **kwargs) -> UnitTransition:
        return UnitTransition.suspend(reason, **kwargs)

    def halt(self, **kwargs) -> UnitTransition:
        return UnitTransition.halt(**kwargs)


UnitStepImplementation = Callable[[UnitStepContext], UnitTransition]


@runtime_checkable
class UnitOperationRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, operation: str) -> UnitStepImplementation: ...

    def implementation_digest(self, operation: str) -> str: ...


class UnitOperationRegistry(UnitOperationRegistryPort):
    @classmethod
    def empty(cls) -> "UnitOperationRegistry":
        return cls()

    def __init__(self) -> None:
        self._handlers: Mapping[str, tuple[UnitStepImplementation, str]] = {}
        self._lock = RLock()
        self._sealed = False
        self._operations: tuple[str, ...] | None = None
        self._identity_digest: str | None = None

    @property
    def sealed(self) -> bool:
        return self._sealed

    def seal(self) -> "UnitOperationRegistry":
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
        handler: UnitStepImplementation,
        *,
        implementation_digest: str,
    ) -> None:
        operation = _text(operation, "unit operation")
        if not callable(handler):
            raise TypeError("unit operation handler must be callable")
        digest = require_sha256(
            implementation_digest,
            "unit operation implementation_digest",
        )
        value = (handler, digest)
        with self._lock:
            if self._sealed:
                raise RuntimeError("unit handler registry is sealed")
            current = self._handlers.get(operation)
            if current is not None and current != value:
                raise ValueError(f"unit operation already registered: {operation}")
            self._handlers[operation] = value

    def resolve(self, operation: str) -> UnitStepImplementation:
        operation = _text(operation, "unit operation")
        if self._sealed:
            try:
                return self._handlers[operation][0]
            except KeyError as exc:
                raise KeyError(f"unbound machine-unit operation: {operation}") from exc
        with self._lock:
            try:
                return self._handlers[operation][0]
            except KeyError as exc:
                raise KeyError(f"unbound machine-unit operation: {operation}") from exc

    def implementation_digest(self, operation: str) -> str:
        operation = _text(operation, "unit operation")
        if self._sealed:
            try:
                return self._handlers[operation][1]
            except KeyError as exc:
                raise KeyError(f"unbound machine-unit operation: {operation}") from exc
        with self._lock:
            try:
                return self._handlers[operation][1]
            except KeyError as exc:
                raise KeyError(f"unbound machine-unit operation: {operation}") from exc

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


def unit_operation_binding_digest(
    unit: NoetriumUnit,
    handlers: UnitOperationRegistryPort,
) -> str:
    """Freeze the exact implementation behind every executable operation."""

    validate_executable_unit(unit)
    if not isinstance(handlers, UnitOperationRegistryPort):
        raise TypeError("Unit execution requires UnitOperationRegistryPort")
    require_sha256(handlers.identity_digest, "unit operation registry identity_digest")
    implementations = []
    for node in executable_unit_nodes(unit):
        operation = unit_operation_name(node)
        inline = unit_operation_implementation(node)
        digest = (
            implementation_digest(inline)
            if inline is not None
            else handlers.implementation_digest(operation)
        )
        implementations.append(
            (
                node.unit_id,
                operation,
                require_sha256(digest, "unit operation implementation_digest"),
            )
        )
    return canonical_digest({
        "executable_unit_digest": unit.unit_digest,
        "operation_implementations": tuple(sorted(implementations)),
    })



@dataclass(frozen=True, slots=True)
class _CompiledUnitStep:
    index: int
    node: NoetriumUnit
    operation: str
    inline_implementation: UnitStepImplementation | None
    configuration: JsonObject
    max_visits: int | None
    allowed_next: frozenset[str]
    default_next: str | None
    runtime_module: str | None


@dataclass(frozen=True, slots=True)
class _UnitExecutionPlan:
    unit_digest: str
    domain: str
    entrypoint: str
    steps: tuple[_CompiledUnitStep, ...]
    step_index: Mapping[str, int]
    external_operations: tuple[str, ...]


def _compile_unit_execution_plan(unit: NoetriumUnit) -> _UnitExecutionPlan:
    """Compile immutable Unit topology exactly once per bound host."""

    validate_executable_unit(unit)
    compiled_steps: list[_CompiledUnitStep] = []
    index_by_id: dict[str, int] = {}
    external_operations: set[str] = set()
    for index, node in enumerate(executable_unit_nodes(unit)):
        operation = unit_operation_name(node)
        implementation_unit = unit_operation_implementation(node)
        inline_implementation = (
            resolve_callable(
                implementation_unit,
                observed_source_digest=callable_source_digest,
            )
            if implementation_unit is not None
            else None
        )
        if inline_implementation is None:
            external_operations.add(operation)
        raw_configuration = unit_operation_configuration(node)
        frozen_configuration = freeze_json(raw_configuration)
        if not isinstance(frozen_configuration, Mapping):
            raise TypeError("unit operation configuration must freeze to object")
        runtime_module = frozen_configuration.get("runtime_module")
        if runtime_module is not None:
            runtime_module = _text(
                runtime_module,
                "unit operation runtime_module",
            )
        compiled_steps.append(
            _CompiledUnitStep(
                index=index,
                node=node,
                operation=operation,
                inline_implementation=inline_implementation,
                configuration=frozen_configuration,
                max_visits=unit_operation_max_visits(node),
                allowed_next=frozenset(
                    unit_operation_allowed_next_nodes(unit, node)
                ),
                default_next=unit_operation_next_node(unit, node),
                runtime_module=runtime_module,
            )
        )
        index_by_id[node.unit_id] = index
    return _UnitExecutionPlan(
        unit_digest=unit.unit_digest,
        domain=executable_unit_domain(unit),
        entrypoint=executable_unit_entrypoint(unit),
        steps=tuple(compiled_steps),
        step_index=MappingProxyType(index_by_id),
        external_operations=tuple(sorted(external_operations)),
    )


class UniversalUnitMachine:
    def __init__(
        self,
        unit: NoetriumUnit,
        handlers: UnitOperationRegistryPort,
        *,
        handler_binding_digest: str | None = None,
        execution_plan: _UnitExecutionPlan | None = None,
    ) -> None:
        if not isinstance(handlers, UnitOperationRegistryPort):
            raise TypeError(
                "Universal Unit Machine requires UnitOperationRegistryPort"
            )
        self.unit = unit
        if isinstance(handlers, UnitOperationRegistry):
            handlers.seal()
        self.handlers = handlers
        plan = (
            _compile_unit_execution_plan(unit)
            if execution_plan is None
            else execution_plan
        )
        if (
            not isinstance(plan, _UnitExecutionPlan)
            or plan.unit_digest != unit.unit_digest
        ):
            raise ValueError(
                "Universal Unit Machine execution plan belongs to another Unit"
            )
        self._plan = plan
        self._execution_plan = plan.steps
        self._step_index = plan.step_index
        self._bound_external_handlers = MappingProxyType({
            operation: handlers.resolve(operation)
            for operation in plan.external_operations
        })

        if handler_binding_digest is None:
            handler_binding_digest = unit_operation_binding_digest(
                unit,
                handlers,
            )
        else:
            handler_binding_digest = require_sha256(
                handler_binding_digest,
                "unit handler_binding_digest",
            )
        self.handler_binding_digest = handler_binding_digest

    def _state(self, snapshot: MachineSnapshot) -> Mapping[str, JsonValue]:
        value = snapshot.state.get(UNIT_STATE_KEY)
        if value is None:
            raise ValueError("executable unit has not been started")
        state = _mapping(value, "executable unit state")
        if state.get("unit_digest") != self.unit.unit_digest:
            raise ValueError("machine state belongs to a different executable Unit")
        return state

    def _compiled_step(self, node_id: str) -> _CompiledUnitStep:
        node_id = _text(node_id, "executable unit cursor")
        try:
            return self._execution_plan[self._step_index[node_id]]
        except KeyError as exc:
            raise KeyError(node_id) from exc

    def _resolve_dynamic_next_node(
        self,
        step: _CompiledUnitStep,
        requested: str,
    ) -> str:
        requested = _text(requested, "UnitGoto.target")
        if requested in self._step_index:
            return requested
        if step.runtime_module is not None:
            qualified = f"{step.runtime_module}.{requested}"
            if qualified in self._step_index:
                return qualified
        raise KeyError(requested)


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
        traceback_tail: tuple[str, ...] = (),
        extra_events: tuple[JsonValue, ...] = (),
        request_refs: tuple[str, ...] = (),
        effect_intent_refs: tuple[str, ...] = (),
        state_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
        correlation_refs: tuple[str, ...] = (),
        child_links: tuple[ChildMachineLink, ...] = (),
    ) -> TransitionProposal:
        failure = {
            "code": code,
            "message": message,
            "error_digest": error_digest,
            "traceback_tail": traceback_tail,
            "cursor": cursor,
            "visit": visit,
            "request_refs": tuple(request_refs),
            "effect_refs": tuple(effect_intent_refs),
            "state_refs": tuple(state_refs),
            "evidence_refs": tuple(evidence_refs),
            "artifact_refs": tuple(artifact_refs),
            "correlation_refs": tuple(correlation_refs),
            "child_link_refs": tuple(link.link_digest for link in child_links),
        }
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta=MachineStateDelta((
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "cursor"),
                    None,
                ),
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "semantic", "unit_failure"),
                    failure,
                ),
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "status"),
                    MachineStatus.FAILED.value,
                ),
            )),
            event_payloads=({
                "type": "executable_unit_failed",
                "unit_id": self.unit.unit_id,
                **failure,
            }, *extra_events),
            effect_intent_refs=effect_intent_refs,
            accepted_status=MachineStatus.FAILED,
            evidence_refs=evidence_refs,
            artifact_refs=artifact_refs,
            child_links=child_links,
        )

    def propose(self, command: MachineCommand, state: MachineSnapshot) -> TransitionProposal:
        if state.unit.unit_digest != self.unit.unit_digest:
            raise ValueError("ExecutableUnitRef does not match executable Unit")

        if command.kind == "unit.start":
            root = state.state
            if UNIT_STATE_KEY in root:
                raise ValueError("executable unit is already started")
            payload = _mapping(command.payload, "unit.start payload")
            initial_data = _mapping(payload.get("initial_data", {}), "unit initial_data")
            unit_state: JsonObject = {
                "unit_digest": self.unit.unit_digest,
                "initial_data_digest": canonical_digest(initial_data),
                "cursor": self._plan.entrypoint,
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
                    (UNIT_STATE_KEY,),
                    unit_state,
                ),
                event_payloads=({"type": "executable_unit_started", "unit_id": self.unit.unit_id,
                                 "domain": self._plan.domain, "entrypoint": self._plan.entrypoint},),
                accepted_status=MachineStatus.RUNNABLE,
            )

        current = self._state(state)
        if command.kind == "unit.limit":
            if current.get("status") != MachineStatus.RUNNABLE.value:
                raise ValueError("unit.limit requires a runnable unit")
            return self._failure_proposal(
                command,
                state,
                current,
                code="unit.step_limit",
                message="executable unit exceeded its bounded step limit",
                cursor=(
                    str(current.get("cursor"))
                    if current.get("cursor") is not None
                    else None
                ),
            )
        if command.kind == "unit.resume":
            if current.get("status") not in {
                MachineStatus.WAITING.value,
                MachineStatus.INTERRUPTED.value,
            }:
                raise ValueError("only waiting/interrupted unit can resume")
            pending_activation = current.get("activation")
            if pending_activation is None:
                return TransitionProposal(
                    machine_id=state.machine_id,
                    command_id=command.command_id,
                    base_revision=state.revision,
                    state_delta=MachineStateDelta.set(
                        (UNIT_STATE_KEY, "status"),
                        MachineStatus.RUNNABLE.value,
                    ),
                    event_payloads=({"type": "executable_unit_resumed"},),
                    accepted_status=MachineStatus.RUNNABLE,
                )
            pending = _mapping(
                pending_activation,
                "unit pending activation",
            )
            resume_payload = _mapping(
                command.payload,
                "unit activation resume payload",
            )
            link_rows = resume_payload.get("child_links", ())
            if not isinstance(link_rows, tuple):
                link_rows = tuple(link_rows)
            child_links = []
            for row in link_rows:
                mapping = _mapping(row, "unit activation child link")
                expected_digest = mapping.get("link_digest")
                link = ChildMachineLink(
                    parent_machine_id=str(mapping["parent_machine_id"]),
                    child_machine_id=str(mapping["child_machine_id"]),
                    child_unit_digest=str(mapping["child_unit_digest"]),
                    child_execution_lock_digest=str(
                        mapping["child_execution_lock_digest"]
                    ),
                    child_snapshot_ref=str(mapping["child_snapshot_ref"]),
                    child_transition_start=int(mapping["child_transition_start"]),
                    child_transition_end=int(mapping["child_transition_end"]),
                    child_result_ref=(
                        None
                        if mapping.get("child_result_ref") is None
                        else str(mapping["child_result_ref"])
                    ),
                    failure_policy=str(mapping["failure_policy"]),
                )
                if (
                    expected_digest is not None
                    and str(expected_digest) != link.link_digest
                ):
                    raise ValueError(
                        "unit activation child link identity drifted"
                    )
                child_links.append(link)
            continuation = pending.get("continuation")
            if continuation is not None:
                continuation = _text(
                    continuation,
                    "unit activation continuation",
                )
                self._compiled_step(continuation)
            accepted = (
                MachineStatus.COMPLETED
                if continuation is None
                else MachineStatus.RUNNABLE
            )
            mutations = [
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "status"),
                    accepted.value,
                ),
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "cursor"),
                    continuation,
                ),
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "previous_value"),
                    resume_payload.get("value"),
                ),
                MachineStateMutation.delete_path(
                    (UNIT_STATE_KEY, "activation"),
                ),
            ]
            return TransitionProposal(
                machine_id=state.machine_id,
                command_id=command.command_id,
                base_revision=state.revision,
                state_delta=MachineStateDelta(tuple(mutations)),
                event_payloads=({
                    "type": "executable_unit_activation_resumed",
                    "child_count": len(child_links),
                    "continuation": continuation,
                    "status": accepted.value,
                },),
                child_links=tuple(child_links),
                accepted_status=accepted,
            )

        if command.kind != "unit.step":
            raise ValueError(f"unsupported Universal Unit Machine command: {command.kind}")
        if current.get("status") != MachineStatus.RUNNABLE.value:
            raise ValueError("executable unit must be runnable before stepping")

        cursor = _text(current.get("cursor"), "executable unit cursor")
        step = self._compiled_step(cursor)
        node = step.node
        visits = _mapping(current.get("visits", {}), "unit visits")
        visit = visits.get(cursor, 0)
        if type(visit) is not int or visit < 0:
            raise ValueError("unit visit count is invalid")
        visit += 1
        if step.max_visits is not None and visit > step.max_visits:
            return self._failure_proposal(
                command,
                state,
                current,
                code="unit.node_visit_limit",
                message=(
                    f"unit node visit limit reached: {node.unit_id} "
                    f"({visit}>{step.max_visits})"
                ),
                cursor=node.unit_id,
                visit=visit,
            )
        data = _mapping(current.get("data", {}), "unit data")
        request = UnitStepContext(
            unit=self.unit,
            node=node,
            snapshot=state,
            configuration=step.configuration,
            payload=command.payload,
            data=data,
            previous_value=current.get("previous_value"),
            visit=visit,
            visit_counts=visits,
            checkpoint_value=current.get("checkpoint_value"),
            semantic_state=_mapping(
                current.get("semantic", {}),
                "unit semantic state",
            ),
        )
        try:
            implementation = (
                step.inline_implementation
                if step.inline_implementation is not None
                else self._bound_external_handlers[step.operation]
            )
            result = implementation(request)
            if not isinstance(result, UnitTransition):
                raise TypeError(
                    "STEP implementation must return UnitTransition"
                )
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
            refs = exception_reference_projection(exc)
            return self._failure_proposal(
                command,
                state,
                current,
                code="unit.node_exception",
                message=message,
                cursor=node.unit_id,
                visit=visit,
                error_digest=description.error_digest,
                traceback_tail=tuple(
                    line.rstrip()
                    for line in traceback.format_exception(exc)[-24:]
                ),
                request_refs=refs.request_refs,
                effect_intent_refs=refs.effect_refs,
                state_refs=refs.state_refs,
                evidence_refs=refs.evidence_refs,
                artifact_refs=refs.artifact_refs,
                correlation_refs=refs.correlation_refs,
            )

        raw_watchdog = _mapping(
            current.get("progress_watchdog", {}),
            "unit progress watchdog",
        )
        consecutive_no_progress = int(
            raw_watchdog.get("consecutive_no_progress", 0)
        )
        same_fingerprint = int(raw_watchdog.get("same_fingerprint", 0))
        last_fingerprint = raw_watchdog.get("last_fingerprint")
        if last_fingerprint is not None and type(last_fingerprint) is not str:
            raise TypeError("unit progress watchdog fingerprint is invalid")
        if result.observation.progress is True:
            progress_watchdog = {
                "consecutive_no_progress": 0,
                "same_fingerprint": 0,
                "last_fingerprint": None,
            }
        elif result.observation.progress is False:
            fingerprint = result.observation.progress_fingerprint or canonical_digest({
                "unit_digest": self.unit.unit_digest,
                "node_id": cursor,
                "operation": step.operation,
                "effect_intent_refs": result.intents,
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
                same_fingerprint >= UNIT_SAME_NO_PROGRESS_LIMIT
                or consecutive_no_progress >= UNIT_CONSECUTIVE_NO_PROGRESS_LIMIT
            ):
                return self._failure_proposal(
                    command,
                    state,
                    current,
                    code="unit.no_progress_livelock",
                    message=(
                        "executable unit repeated mechanically rejected/no-effect "
                        "attempts"
                    ),
                    cursor=node.unit_id,
                    visit=visit,
                    extra_events=result.observation.events,
                    effect_intent_refs=result.intents,
                    evidence_refs=result.observation.evidence_refs,
                    artifact_refs=result.observation.artifact_refs,
                    child_links=result.observation.child_links,
                )
        else:
            progress_watchdog = dict(raw_watchdog)

        state_update = _mapping(
            result.state.data,
            "UnitTransition.state.data",
        )
        semantic_update = _mapping(
            result.state.semantic,
            "UnitTransition.state.semantic",
        )
        control = result.control
        wait_reason = None
        activation_payload = None
        if isinstance(control, UnitGoto):
            next_node = (
                self._resolve_dynamic_next_node(step, control.target)
                if control.target is not None
                else step.default_next
            )
            if next_node is None:
                accepted = MachineStatus.COMPLETED
            else:
                accepted = MachineStatus.RUNNABLE
        elif isinstance(control, UnitActivate):
            continuation = (
                self._resolve_dynamic_next_node(step, control.continuation)
                if control.continuation is not None
                else step.default_next
            )
            activation_payload = freeze_json({
                "requests": control.requests,
                "join": control.join,
                "quorum": control.quorum,
                "continuation": continuation,
                "source_node": cursor,
            })
            next_node = cursor
            accepted = MachineStatus.WAITING
            wait_reason = "unit.activate"
        elif isinstance(control, UnitSuspend):
            next_node = cursor
            accepted = control.status
            wait_reason = control.reason
        elif isinstance(control, UnitHalt):
            next_node = None
            accepted = control.status
        else:
            raise TypeError("unsupported Unit control value")
        transition_target = (
            activation_payload.get("continuation")
            if activation_payload is not None
            else next_node
        )
        if transition_target is not None:
            self._compiled_step(str(transition_target))
            if step.allowed_next and str(transition_target) not in step.allowed_next:
                return self._failure_proposal(
                    command,
                    state,
                    current,
                    code="unit.invalid_transition",
                    message=(
                        "unit node selected non-adjacent next node: "
                        + str(transition_target)
                    ),
                    cursor=node.unit_id,
                    visit=visit,
                )

        granular_delta = [
            MachineStateMutation.set(
                (UNIT_STATE_KEY, "cursor"),
                next_node,
            ),
            MachineStateMutation.set(
                (UNIT_STATE_KEY, "previous_value"),
                result.value,
            ),
            MachineStateMutation.set(
                (UNIT_STATE_KEY, "status"),
                accepted.value,
            ),
            MachineStateMutation.set(
                (UNIT_STATE_KEY, "visits", cursor),
                visit,
            ),
        ]
        granular_delta.extend(
            MachineStateMutation.set(
                (UNIT_STATE_KEY, "data", key),
                value,
            )
            for key, value in state_update.items()
        )
        granular_delta.extend(
            MachineStateMutation.set(
                (UNIT_STATE_KEY, "semantic", key),
                value,
            )
            for key, value in semantic_update.items()
        )
        granular_delta.append(
            MachineStateMutation.set(
                (UNIT_STATE_KEY, "progress_watchdog"),
                progress_watchdog,
            )
        )
        if activation_payload is not None:
            granular_delta.append(
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "activation"),
                    activation_payload,
                )
            )
        elif current.get("activation") is not None:
            granular_delta.append(
                MachineStateMutation.delete_path(
                    (UNIT_STATE_KEY, "activation"),
                )
            )
        if result.observation.checkpoint is not None:
            granular_delta.append(
                MachineStateMutation.set(
                    (UNIT_STATE_KEY, "checkpoint_value"),
                    result.observation.checkpoint,
                )
            )
        state_delta = MachineStateDelta(tuple(granular_delta))
        return TransitionProposal(
            machine_id=state.machine_id, command_id=command.command_id,
            base_revision=state.revision,
            state_delta=state_delta,
            emitted_commands=result.observation.emitted_commands, output_refs=result.observation.output_refs,
            event_payloads=({
                "type": "executable_unit_node_executed", "unit_id": self.unit.unit_id,
                "node_id": cursor, "operation": step.operation, "visit": visit,
                "next_node": next_node, "status": accepted.value,
                "checkpoint_observed": result.observation.checkpoint is not None,
                "activation_pending": activation_payload is not None,
            }, *result.observation.events),
            effect_intent_refs=result.intents, wait_reason=wait_reason,
            accepted_status=accepted, evidence_refs=result.observation.evidence_refs,
            artifact_refs=result.observation.artifact_refs,
            child_links=result.observation.child_links,
        )


def universal_machine_family() -> MachineFamilyDescriptor:
    """The single Machine family for every executable NoetriumUnit."""

    return MachineFamilyDescriptor(
        family_id=f"unit.machine.v{UNIVERSAL_UNIT_MACHINE_VERSION}",
        implementation_version=UNIVERSAL_UNIT_MACHINE_VERSION,
        state_schema=f"unit.machine-state.v{UNIVERSAL_UNIT_STATE_SCHEMA_VERSION}",
        command_kinds=UNIT_MACHINE_COMMANDS,
    )


__all__ = [
    "unit_operation_binding_digest",
    "UNIT_STATE_KEY",
    "EXECUTABLE_UNIT_TRAIT", "UNIT_OPERATION_TRAIT", "UNIT_FLOW_RELATION",
    "UNIT_OPERATION_IMPLEMENTATION_SYMBOL", "UNIT_OPERATION_IMPLEMENTATION_TRAIT",
    "UNIT_MACHINE_COMMANDS", "UnitOperationRegistry",
    "UnitOperationRegistryPort", "UnitStepContext",
    "UnitStateDelta", "UnitGoto", "UnitActivate", "UnitSuspend", "UnitHalt",
    "UnitObservation", "UnitTransition", "UnitStepImplementation", "UniversalUnitMachine",
    "unit_flow", "unit_operation", "executable_unit",
    "unit_operation_name", "unit_operation_implementation", "unit_operation_configuration",
    "unit_operation_max_visits", "unit_operation_required_capabilities",
    "unit_operation_allowed_next_nodes", "unit_operation_next_node",
    "executable_unit_id", "executable_unit_digest", "executable_unit_domain",
    "executable_unit_version", "executable_unit_state_schema",
    "executable_unit_entrypoint", "executable_unit_required_capabilities",
    "executable_unit_nodes", "executable_unit_node", "executable_unit_ref",
    "validate_executable_unit", "universal_machine_family",
]
