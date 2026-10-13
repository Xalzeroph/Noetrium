"""Schema compiler and projections for recursive NoetriumUnit structures.

This module contains no persistent structural classes. Type, boundary, relation,
symbol and graph are schemas over NoetriumUnit. The sole truth carrier lives in
foundation.kernel.unit.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, deque
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from hashlib import sha256
import importlib
import inspect
import json
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Callable, Mapping
from weakref import WeakKeyDictionary

import canonaut

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, require_sha256, strict_finite_json_bytes
from .dag import deterministic_hypergraph_topological_order, strongly_connected_components
from .unit import NoetriumUnit, UnitRef, role, unit_token


class GraphStorageKind(StrEnum):
    ARTIFACT = "artifact"
    EVIDENCE = "evidence"
    CHECKPOINT = "checkpoint"
    SELECTION = "selection"
    METRIC = "metric"
    DATA = "data"


class GraphPortMode(StrEnum):
    ONE = "one"
    OPTIONAL = "optional"
    MANY = "many"
    STREAM = "stream"


class GraphStateAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read-write"


class GraphTriggerKind(StrEnum):
    ALL = "all"
    ANY = "any"
    QUORUM = "quorum"


class GraphProgressKind(StrEnum):
    INITIAL = "initial"
    EVENT = "event"
    STATE = "state"
    GUARD = "guard"
    TIMER = "timer"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class GraphTrigger:
    """Ephemeral trigger value; persisted truth lives on a relation Unit."""

    kind: GraphTriggerKind = GraphTriggerKind.ALL
    quorum: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, GraphTriggerKind):
            raise TypeError("graph trigger kind must be typed")
        if self.kind is GraphTriggerKind.QUORUM:
            if type(self.quorum) is not int or self.quorum < 1:
                raise ValueError("quorum trigger requires positive quorum")
        elif self.quorum is not None:
            raise ValueError("only quorum trigger accepts quorum")

    def satisfied(self, *, satisfied_sources: int, source_count: int) -> bool:
        if (
            type(satisfied_sources) is not int
            or type(source_count) is not int
            or satisfied_sources < 0
            or source_count < 0
            or satisfied_sources > source_count
        ):
            raise ValueError("invalid trigger source count")
        if self.kind is GraphTriggerKind.ALL:
            return satisfied_sources == source_count
        if self.kind is GraphTriggerKind.ANY:
            return satisfied_sources >= 1
        return satisfied_sources >= int(self.quorum)


_EMPTY_OBJECT = freeze_json({})


def _object(value: JsonValue | None, field: str) -> Mapping[str, object]:
    frozen = freeze_json({} if value is None else value)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{field} must be an object")
    return frozen


def _shallow_string_mapping_key(
    value: object,
) -> tuple[tuple[str, str], ...] | None:
    """Exact zero-serialization key for the common shallow string-map shape."""
    if not isinstance(value, Mapping):
        return None
    rows: list[tuple[str, str]] = []
    for key, item in value.items():
        if type(key) is not str or type(item) is not str:
            return None
        rows.append((key, item))
    rows.sort()
    return tuple(rows)


def _texts(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    rows = tuple(unit_token(row, field) for row in values)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return tuple(sorted(rows))


def _kind(unit: NoetriumUnit, expected: str) -> None:
    if type(unit) is not NoetriumUnit:
        raise TypeError(f"{expected} projection requires NoetriumUnit")
    if unit.attribute("kind") != expected:
        raise TypeError(
            f"unit {unit.unit_id!r} is {unit.attribute('kind')!r}, expected {expected!r}"
        )


@lru_cache(maxsize=16384)
def _shallow_type_shape(
    storage_kind: str,
    parameter_items: tuple[tuple[str, str], ...],
    supertypes: tuple[str, ...],
) -> tuple[Mapping[str, object], str]:
    parameters = freeze_json(dict(parameter_items))
    attributes = freeze_json(
        {
            "kind": "type",
            "storage_kind": storage_kind,
            "parameters": parameters,
            "supertypes": supertypes,
        }
    )
    if not isinstance(attributes, Mapping):
        raise RuntimeError("type shape attributes must be an object")
    prototype = NoetriumUnit._from_normalized(
        "research.type-shape",
        schemas=(),
        attributes=attributes,
        roles=(),
        semantic_projection_digest="0" * 64,
    )
    return attributes, prototype.structural_digest


def type_unit(
    type_id: str,
    storage_kind: GraphStorageKind = GraphStorageKind.DATA,
    parameters: JsonValue = None,
    supertypes: tuple[str, ...] = (),
) -> NoetriumUnit:
    type_id = unit_token(type_id, "research type_id")
    if not isinstance(storage_kind, GraphStorageKind):
        raise TypeError("research type storage_kind must be typed")
    supertypes = _texts(supertypes, "research supertype")
    raw_parameters: object = {} if parameters is None else parameters
    shallow_key = _shallow_string_mapping_key(raw_parameters)
    if shallow_key is not None:
        attributes, structural = _shallow_type_shape(
            storage_kind.value,
            shallow_key,
            supertypes,
        )
        frozen_parameters = attributes["parameters"]
        semantic = canonical_digest(
            {
                "type_id": type_id,
                "storage_kind": storage_kind.value,
                "parameters": frozen_parameters,
                "supertypes": supertypes,
            }
        )
        return NoetriumUnit._from_normalized(
            type_id,
            schemas=(),
            attributes=attributes,
            roles=(),
            semantic_projection_digest=semantic,
            structural_digest=structural,
        )

    parameters = _object(parameters, "research type parameters")
    semantic = canonical_digest(
        {
            "type_id": type_id,
            "storage_kind": storage_kind.value,
            "parameters": parameters,
            "supertypes": supertypes,
        }
    )
    return NoetriumUnit(
        type_id,
        attributes={
            "kind": "type",
            "storage_kind": storage_kind.value,
            "parameters": parameters,
            "supertypes": supertypes,
        },
        semantic_projection_digest=semantic,
    )


ANY_TYPE = type_unit("research.any")
CONTROL_TYPE = type_unit("research.control")


def type_id(unit: NoetriumUnit) -> str:
    _kind(unit, "type")
    return unit.unit_id


def type_storage_kind(unit: NoetriumUnit) -> GraphStorageKind:
    _kind(unit, "type")
    return GraphStorageKind(str(unit.attribute("storage_kind")))


def type_supertypes(unit: NoetriumUnit) -> tuple[str, ...]:
    _kind(unit, "type")
    values = unit.attribute("supertypes", ())
    if type(values) is not tuple or any(type(value) is not str for value in values):
        raise TypeError("type supertypes projection is invalid")
    return values


def type_assignable_to(source: NoetriumUnit, target: NoetriumUnit) -> bool:
    _kind(source, "type")
    _kind(target, "type")
    if target.unit_id == "research.any":
        return True
    if source.unit_id == target.unit_id:
        return source.parameters == target.parameters
    return target.unit_id in type_supertypes(source)


def port_unit(
    name: str,
    type_ref: NoetriumUnit = ANY_TYPE,
    mode: GraphPortMode = GraphPortMode.ONE,
) -> NoetriumUnit:
    name = unit_token(name, "research port name")
    _kind(type_ref, "type")
    if not isinstance(mode, GraphPortMode):
        raise TypeError("research port mode must be typed")
    return NoetriumUnit(
        name,
        attributes={"kind": "port", "mode": mode.value},
        roles=(role("type", type_ref),),
    )


def port_type(unit: NoetriumUnit) -> NoetriumUnit:
    _kind(unit, "port")
    return unit.one_unit("type")


def port_mode(unit: NoetriumUnit) -> GraphPortMode:
    _kind(unit, "port")
    return GraphPortMode(str(unit.attribute("mode")))


def state_unit(
    state_id: str,
    type_ref: NoetriumUnit,
    access: GraphStateAccess = GraphStateAccess.READ_WRITE,
    scope_id: str | None = None,
    configuration: JsonValue = None,
) -> NoetriumUnit:
    state_id = unit_token(state_id, "research state_id")
    _kind(type_ref, "type")
    if not isinstance(access, GraphStateAccess):
        raise TypeError("research state access must be typed")
    if scope_id is not None:
        scope_id = unit_token(scope_id, "research state scope_id")
    return NoetriumUnit(
        state_id,
        attributes={
            "kind": "state",
            "access": access.value,
            "scope_id": scope_id,
            "configuration": _object(configuration, "research state configuration"),
        },
        roles=(role("type", type_ref),),
    )


@lru_cache(maxsize=16384)
def _shallow_effect_unit(
    effect_id: str,
    configuration_items: tuple[tuple[str, str], ...],
) -> NoetriumUnit:
    return NoetriumUnit(
        effect_id,
        attributes={
            "kind": "effect",
            "configuration": freeze_json(dict(configuration_items)),
        },
    )


def effect_unit(effect_id: str, configuration: JsonValue = None) -> NoetriumUnit:
    effect_id = unit_token(effect_id, "research effect_id")
    raw_configuration: object = {} if configuration is None else configuration
    shallow_key = _shallow_string_mapping_key(raw_configuration)
    if shallow_key is not None:
        return _shallow_effect_unit(effect_id, shallow_key)
    return NoetriumUnit(
        effect_id,
        attributes={
            "kind": "effect",
            "configuration": _object(configuration, "research effect configuration"),
        },
    )


def evidence_unit(
    evidence_id: str,
    type_ref: NoetriumUnit,
    required: bool = True,
    configuration: JsonValue = None,
) -> NoetriumUnit:
    evidence_id = unit_token(evidence_id, "research evidence_id")
    _kind(type_ref, "type")
    if type(required) is not bool:
        raise TypeError("research evidence required must be bool")
    return NoetriumUnit(
        evidence_id,
        attributes={
            "kind": "evidence",
            "required": required,
            "configuration": _object(
                configuration, "research evidence configuration"
            ),
        },
        roles=(role("type", type_ref),),
    )


def _type_document(unit: NoetriumUnit) -> dict[str, object]:
    return {
        "type_id": type_id(unit),
        "storage_kind": type_storage_kind(unit).value,
        "parameters": unit.parameters,
        "supertypes": type_supertypes(unit),
    }


def _port_document(unit: NoetriumUnit) -> dict[str, object]:
    _kind(unit, "port")
    return {
        "name": unit.unit_id,
        "type": _type_document(port_type(unit)),
        "mode": port_mode(unit).value,
    }


def _scope_document(unit: NoetriumUnit) -> dict[str, object]:
    _kind(unit, "scope")
    return {
        "scope_id": unit.attribute("scope_id"),
        "scope_kind": unit.attribute("scope_kind"),
    }


def _state_document(unit: NoetriumUnit) -> dict[str, object]:
    _kind(unit, "state")
    return {
        "state_id": unit.unit_id,
        "type": _type_document(unit.one_unit("type")),
        "access": str(unit.attribute("access")),
        "scope_id": unit.attribute("scope_id"),
        "configuration": unit.attribute("configuration", _EMPTY_OBJECT),
    }


def _effect_document(unit: NoetriumUnit) -> dict[str, object]:
    _kind(unit, "effect")
    return {
        "effect_id": unit.unit_id,
        "configuration": unit.attribute("configuration", _EMPTY_OBJECT),
    }


def _evidence_document(unit: NoetriumUnit) -> dict[str, object]:
    _kind(unit, "evidence")
    return {
        "evidence_id": unit.unit_id,
        "type": _type_document(unit.one_unit("type")),
        "required": bool(unit.attribute("required")),
        "configuration": unit.attribute("configuration", _EMPTY_OBJECT),
    }


def boundary_unit(
    *,
    inputs: tuple[NoetriumUnit, ...] = (),
    outputs: tuple[NoetriumUnit, ...] = (),
    state: tuple[NoetriumUnit, ...] = (),
    effects: tuple[NoetriumUnit, ...] = (),
    scopes: tuple[NoetriumUnit, ...] = (),
    evidence: tuple[NoetriumUnit, ...] = (),
) -> NoetriumUnit:
    groups = (
        ("input", inputs, "port"),
        ("output", outputs, "port"),
        ("state", state, "state"),
        ("effect", effects, "effect"),
        ("scope", scopes, "scope"),
        ("evidence", evidence, "evidence"),
    )
    normalized: dict[str, tuple[NoetriumUnit, ...]] = {}
    for role_name, rows, expected in groups:
        if type(rows) is not tuple:
            raise TypeError(f"boundary {role_name} must be a tuple")
        for row in rows:
            _kind(row, expected)
        ordered = tuple(sorted(rows, key=lambda row: row.unit_id))
        if len({row.unit_id for row in ordered}) != len(ordered):
            raise ValueError(f"boundary {role_name} identities must be unique")
        normalized[role_name] = ordered
    scope_ids = {str(row.attribute("scope_id")) for row in normalized["scope"]}
    for row in normalized["state"]:
        scope_id = row.attribute("scope_id")
        if scope_id is not None and scope_id not in scope_ids:
            raise ValueError(
                f"state {row.unit_id!r} references unknown scope {scope_id!r}"
            )
    semantic = canonical_digest(
        {
            "inputs": tuple(_port_document(row) for row in normalized["input"]),
            "outputs": tuple(_port_document(row) for row in normalized["output"]),
            "state": tuple(_state_document(row) for row in normalized["state"]),
            "effects": tuple(_effect_document(row) for row in normalized["effect"]),
            "scopes": tuple(_scope_document(row) for row in normalized["scope"]),
            "evidence": tuple(
                _evidence_document(row) for row in normalized["evidence"]
            ),
        }
    )
    return NoetriumUnit(
        "boundary",
        attributes={"kind": "boundary"},
        roles=tuple(
            role(role_name, *normalized[role_name])
            for role_name, _rows, _expected in groups
        ),
        semantic_projection_digest=semantic,
    )


EMPTY_BOUNDARY = boundary_unit()


def boundary_input(boundary: NoetriumUnit, name: str) -> NoetriumUnit:
    _kind(boundary, "boundary")
    name = unit_token(name, "boundary input name")
    for row in boundary.units("input"):
        if row.unit_id == name:
            return row
    raise LookupError(f"boundary has no input {name!r}")


def boundary_output(boundary: NoetriumUnit, name: str) -> NoetriumUnit:
    _kind(boundary, "boundary")
    name = unit_token(name, "boundary output name")
    for row in boundary.units("output"):
        if row.unit_id == name:
            return row
    raise LookupError(f"boundary has no output {name!r}")


def atom_unit(atom_id: str, type_id_value: str, value: JsonValue = None) -> NoetriumUnit:
    atom_id = unit_token(atom_id, "graph atom_id")
    type_id_value = unit_token(type_id_value, "graph atom type_id")
    frozen = freeze_json(value)
    semantic = canonical_digest(
        {"atom_id": atom_id, "type_id": type_id_value, "value": frozen}
    )
    return NoetriumUnit(
        atom_id,
        attributes={"kind": "atom", "type_id": type_id_value, "value": frozen},
        semantic_projection_digest=semantic,
    )


IMPLEMENTATION_SCHEMA = "noetrium.implementation"


_CALLABLE_SOURCE_DIGEST_CACHE: WeakKeyDictionary[
    object, tuple[object, str | None, int | None, int | None, str]
] = WeakKeyDictionary()
_CALLABLE_IMPLEMENTATION_UNIT_CACHE: WeakKeyDictionary[
    object,
    OrderedDict[
        tuple[str, str, str, str, str],
        tuple[tuple[object, str | None, int | None, int | None], NoetriumUnit],
    ],
] = WeakKeyDictionary()
_CALLABLE_SOURCE_DIGEST_LOCK = RLock()
_CALLABLE_IMPLEMENTATION_CACHE_PER_CALLABLE = 256

# Universal operation Units are frequently repeated verbatim across Method
# instances.  Cache only the exact ``unit.operation`` structural cut; scientific
# structures outside that schema pay no additional digest/cache overhead.
_OPERATION_STRUCTURE_CACHE: OrderedDict[tuple[object, ...], NoetriumUnit] = OrderedDict()
_OPERATION_STRUCTURE_CACHE_LOCK = RLock()
_OPERATION_STRUCTURE_CACHE_MAXSIZE = 65536

# Structure semantic identity excludes the root unit_id. Large research plans
# therefore rebuild many exact semantic cuts under distinct instance names.
# Cache by the complete immutable inputs that determine the semantic projection;
# the bounded LRU never becomes an authority and can be dropped at any time.
_STRUCTURE_SEMANTIC_CACHE: OrderedDict[tuple[object, ...], str] = OrderedDict()
_STRUCTURE_SEMANTIC_CACHE_LOCK = RLock()
_STRUCTURE_SEMANTIC_CACHE_MAXSIZE = 65536
_EMPTY_TOPOLOGY_DIGEST = canonical_digest(("noetrium.unit.topology.empty.v1",))


def _callable_source_generation(
    value: Callable[..., object],
) -> tuple[object, str | None, int | None, int | None]:
    code = getattr(value, "__code__", None)
    source_path = inspect.getsourcefile(value)
    if source_path is None:
        return code, None, None, None
    try:
        stat = Path(source_path).stat()
    except OSError:
        return code, source_path, None, None
    return code, source_path, int(stat.st_mtime_ns), int(stat.st_size)


def _callable_source_identity(
    value: Callable[..., object],
) -> tuple[tuple[object, str | None, int | None, int | None], str]:
    """Return the exact loaded-source generation and canonical source digest."""

    generation = _callable_source_generation(value)
    try:
        with _CALLABLE_SOURCE_DIGEST_LOCK:
            cached = _CALLABLE_SOURCE_DIGEST_CACHE.get(value)
    except TypeError:
        cached = None
    if cached is not None and cached[:4] == generation:
        return generation, cached[4]

    try:
        source = inspect.getsource(value)
    except (OSError, TypeError) as exc:
        raise ValueError("implementation callable source cannot be resolved") from exc
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    try:
        with _CALLABLE_SOURCE_DIGEST_LOCK:
            _CALLABLE_SOURCE_DIGEST_CACHE[value] = (*generation, digest)
    except TypeError:
        # Some exotic callable objects are neither weak-referenceable nor
        # hashable. They retain exact semantics via the uncached path.
        pass
    return generation, digest


def _callable_source_digest(value: Callable[..., object]) -> str:
    return _callable_source_identity(value)[1]


def callable_source_digest(value: Callable[..., object]) -> str:
    """Canonical source digest for every Python callable implementation Unit."""
    return _callable_source_digest(value)


def callable_implementation_unit(
    implementation_id: str,
    implementation: Callable[..., object],
    *,
    implementation_type: str = "python.callable",
    fields: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    """Freeze one importable Python callable as a content-addressed implementation Unit."""

    if not callable(implementation):
        raise TypeError("implementation must be callable")
    module = getattr(implementation, "__module__", None)
    qualname = getattr(implementation, "__qualname__", None)
    if type(module) is not str or type(qualname) is not str:
        raise ValueError("implementation callable lacks import identity")
    if module == "__main__" or "<locals>" in qualname or "<lambda>" in qualname:
        raise ValueError("implementation must be a module-resolvable named symbol")

    implementation_id = unit_token(implementation_id, "implementation_id")
    implementation_type = unit_token(implementation_type, "implementation_type")
    generation, source_digest = _callable_source_identity(implementation)
    frozen_fields = freeze_json({} if fields is None else dict(fields))
    if not isinstance(frozen_fields, Mapping):
        raise TypeError("implementation fields must be objects")
    fields_digest = canonical_digest(frozen_fields)
    cache_key = (
        implementation_id,
        implementation_type,
        module,
        qualname,
        fields_digest,
    )
    try:
        with _CALLABLE_SOURCE_DIGEST_LOCK:
            per_callable = _CALLABLE_IMPLEMENTATION_UNIT_CACHE.get(implementation)
            if per_callable is not None:
                cached = per_callable.get(cache_key)
                if cached is not None and cached[0] == generation:
                    per_callable.move_to_end(cache_key)
                    return cached[1]
    except TypeError:
        per_callable = None

    payload = {
        "module": module,
        "qualname": qualname,
        "source_digest": source_digest,
        **dict(frozen_fields),
    }
    unit = implementation_unit(
        implementation_id,
        implementation_type=implementation_type,
        fields=payload,
        identity_fields=payload,
    )
    try:
        with _CALLABLE_SOURCE_DIGEST_LOCK:
            per_callable = _CALLABLE_IMPLEMENTATION_UNIT_CACHE.get(implementation)
            if per_callable is None:
                per_callable = OrderedDict()
                _CALLABLE_IMPLEMENTATION_UNIT_CACHE[implementation] = per_callable
            existing = per_callable.get(cache_key)
            if existing is not None and existing[0] == generation:
                if existing[1].unit_digest != unit.unit_digest:
                    raise RuntimeError(
                        "callable implementation generation resolved to multiple Unit identities"
                    )
                per_callable.move_to_end(cache_key)
                return existing[1]
            per_callable[cache_key] = (generation, unit)
            per_callable.move_to_end(cache_key)
            while len(per_callable) > _CALLABLE_IMPLEMENTATION_CACHE_PER_CALLABLE:
                per_callable.popitem(last=False)
    except TypeError:
        # Non-weak-referenceable/hashable exotic callables remain exact via the
        # uncached path.
        pass
    return unit


def implementation_unit(
    implementation_id: str,
    *,
    implementation_type: str,
    fields: Mapping[str, JsonValue] | None = None,
    identity_fields: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    """Canonical implementation schema over the universal NoetriumUnit."""

    implementation_id = unit_token(implementation_id, "implementation_id")
    implementation_type = unit_token(
        implementation_type, "implementation_type"
    )
    payload = freeze_json({} if fields is None else dict(fields))
    identity_payload = freeze_json(
        dict(payload) if identity_fields is None else dict(identity_fields)
    )
    if not isinstance(payload, Mapping) or not isinstance(
        identity_payload, Mapping
    ):
        raise TypeError("implementation fields must be objects")
    digest = canonical_digest(
        {
            "implementation_type": implementation_type,
            "implementation_id": implementation_id,
            "identity": identity_payload,
        }
    )
    return NoetriumUnit(
        implementation_id,
        schemas=(IMPLEMENTATION_SCHEMA,),
        attributes={
            "kind": "implementation",
            "implementation_type": implementation_type,
            "implementation_digest": digest,
            **dict(payload),
        },
        semantic_projection_digest=digest,
    )


def is_implementation(
    unit: object,
    implementation_type: str | None = None,
) -> bool:
    if type(unit) is not NoetriumUnit or unit.attribute("kind") != "implementation":
        return False
    return (
        True
        if implementation_type is None
        else unit.attribute("implementation_type") == implementation_type
    )


def require_implementation(
    unit: NoetriumUnit,
    implementation_type: str | None = None,
) -> NoetriumUnit:
    if not is_implementation(unit, implementation_type):
        suffix = (
            ""
            if implementation_type is None
            else f" of type {implementation_type!r}"
        )
        raise TypeError(f"expected implementation Unit{suffix}")
    return unit


def implementation_type(unit: NoetriumUnit) -> str:
    require_implementation(unit)
    return str(unit.attribute("implementation_type"))


def implementation_digest(unit: NoetriumUnit) -> str:
    require_implementation(unit)
    digest = unit.attribute("implementation_digest")
    require_sha256(digest, "implementation_digest")
    return digest


def implementation_field(
    unit: NoetriumUnit,
    name: str,
    default: object = None,
) -> object:
    require_implementation(unit)
    return unit.attribute(name, default)


def import_symbol(module: str, qualname: str) -> object:
    if type(module) is not str or not module.strip():
        raise ValueError("implementation module must be non-empty")
    if type(qualname) is not str or not qualname.strip():
        raise ValueError("implementation qualname must be non-empty")
    value: object = importlib.import_module(module.strip())
    for part in qualname.strip().split("."):
        value = getattr(value, part)
    return value


def resolve_callable(
    unit: NoetriumUnit,
    *,
    observed_source_digest: Callable[[Callable[..., object]], str],
) -> Callable[..., object]:
    require_implementation(unit)
    module = implementation_field(unit, "module")
    qualname = implementation_field(unit, "qualname")
    source_digest = implementation_field(unit, "source_digest")
    if type(module) is not str or type(qualname) is not str:
        raise TypeError("callable implementation lacks import coordinates")
    require_sha256(source_digest, "implementation source_digest")
    value = import_symbol(module, qualname)
    if not callable(value):
        raise TypeError(
            "implementation coordinates no longer resolve to callable"
        )
    observed = observed_source_digest(value)
    require_sha256(observed, "observed implementation source_digest")
    if observed != source_digest:
        raise RuntimeError(
            "implementation source drifted: "
            f"{module}:{qualname}; "
            f"expected_source_digest={source_digest}; "
            f"observed_source_digest={observed}"
        )
    return value


@lru_cache(maxsize=65536)
def _empty_parameter_symbol_unit(
    symbol_id: str,
    traits: tuple[str, ...],
    implementation: NoetriumUnit | None,
) -> NoetriumUnit:
    """Intern the dominant immutable symbol shape after validation.

    Empty-parameter symbols are pervasive operation/handler declarations. Their
    exact identity is determined only by the canonical symbol id, trait tuple,
    and implementation Unit.  Caching only this zero-payload case avoids adding
    an extra parameter digest to unique, parameterized scientific symbols.
    """

    implementation_digest = (
        None
        if implementation is None
        else str(implementation.attribute("implementation_digest"))
    )
    parameters = freeze_json({})
    semantic = canonical_digest(
        {
            "symbol_id": symbol_id,
            "traits": traits,
            "implementation_digest": implementation_digest,
            "parameters": parameters,
        }
    )
    roles = (
        ()
        if implementation is None
        else (("implementation", (implementation,)),)
    )
    return NoetriumUnit._from_normalized(
        symbol_id,
        schemas=traits,
        attributes=MappingProxyType({
            "kind": "symbol",
            "parameters": parameters,
        }),
        roles=roles,
        semantic_projection_digest=semantic,
    )


_PARAMETERIZED_SYMBOL_CACHE_LIMIT = 65536
_ParameterizedSymbolPrefix = tuple[str, tuple[str, ...], str | None]
_PARAMETERIZED_SYMBOL_CACHE: OrderedDict[
    str, tuple[_ParameterizedSymbolPrefix, NoetriumUnit]
] = OrderedDict()
# A prefix can own arbitrarily many unique parameter sets. Scanning all of
# them makes constructing N distinct paper configurations Θ(N²). Keep one
# temporal-locality candidate per prefix; otherwise perform the authoritative
# canonical parameter digest and O(1) semantic dictionary lookup. No aliases.
_PARAMETERIZED_SYMBOL_PREFIX_INDEX: dict[
    _ParameterizedSymbolPrefix, str
] = {}
_PARAMETERIZED_SYMBOL_CACHE_LOCK = RLock()


def _same_canonical_json_fast(raw: object, frozen: object) -> bool:
    """Prove canonical equality for the built-in strict-JSON hot domain.

    False means only "not proven" and falls back to the authoritative digest.
    Exact scalar type checks avoid Python equality aliases such as bool/int;
    float.hex preserves signed zero.
    """
    if raw is frozen:
        return True
    raw_type = type(raw)
    if raw is None:
        return frozen is None
    if raw_type is bool:
        return type(frozen) is bool and raw is frozen
    if raw_type is int:
        return type(frozen) is int and raw == frozen
    if raw_type is str:
        return type(frozen) is str and raw == frozen
    if raw_type is float:
        return type(frozen) is float and raw.hex() == frozen.hex()
    if raw_type is dict:
        if not isinstance(frozen, Mapping) or len(raw) != len(frozen):
            return False
        for key, value in raw.items():
            if type(key) is not str or key not in frozen:
                return False
            if not _same_canonical_json_fast(value, frozen[key]):
                return False
        return True
    if raw_type is list or raw_type is tuple:
        if type(frozen) is not tuple or len(raw) != len(frozen):
            return False
        return all(
            _same_canonical_json_fast(left, right)
            for left, right in zip(raw, frozen, strict=True)
        )
    return False


def _parameterized_symbol_fast_lookup(
    prefix: _ParameterizedSymbolPrefix,
    raw_parameters: object,
) -> NoetriumUnit | None:
    with _PARAMETERIZED_SYMBOL_CACHE_LOCK:
        semantic = _PARAMETERIZED_SYMBOL_PREFIX_INDEX.get(prefix)
        if semantic is None:
            return None
        cached = _PARAMETERIZED_SYMBOL_CACHE.get(semantic)
        if cached is None:
            _PARAMETERIZED_SYMBOL_PREFIX_INDEX.pop(prefix, None)
            return None
        unit = cached[1]
        if not _same_canonical_json_fast(raw_parameters, unit.parameters):
            return None
        _PARAMETERIZED_SYMBOL_CACHE.move_to_end(semantic)
        return unit


def _parameterized_symbol_semantic_lookup(
    semantic: str,
) -> NoetriumUnit | None:
    with _PARAMETERIZED_SYMBOL_CACHE_LOCK:
        cached = _PARAMETERIZED_SYMBOL_CACHE.get(semantic)
        if cached is None:
            return None
        _PARAMETERIZED_SYMBOL_CACHE.move_to_end(semantic)
        _PARAMETERIZED_SYMBOL_PREFIX_INDEX[cached[0]] = semantic
        return cached[1]


def _publish_parameterized_symbol(
    semantic: str,
    prefix: _ParameterizedSymbolPrefix,
    unit: NoetriumUnit,
) -> NoetriumUnit:
    with _PARAMETERIZED_SYMBOL_CACHE_LOCK:
        cached = _PARAMETERIZED_SYMBOL_CACHE.get(semantic)
        if cached is not None:
            _PARAMETERIZED_SYMBOL_CACHE.move_to_end(semantic)
            _PARAMETERIZED_SYMBOL_PREFIX_INDEX[prefix] = semantic
            existing = cached[1]
            if existing.unit_digest != unit.unit_digest:
                raise RuntimeError(
                    "one semantic symbol digest produced multiple structural identities"
                )
            return existing

        _PARAMETERIZED_SYMBOL_CACHE[semantic] = (prefix, unit)
        _PARAMETERIZED_SYMBOL_PREFIX_INDEX[prefix] = semantic

        while len(_PARAMETERIZED_SYMBOL_CACHE) > _PARAMETERIZED_SYMBOL_CACHE_LIMIT:
            stale_semantic, (stale_prefix, _stale_unit) = (
                _PARAMETERIZED_SYMBOL_CACHE.popitem(last=False)
            )
            if _PARAMETERIZED_SYMBOL_PREFIX_INDEX.get(stale_prefix) == stale_semantic:
                _PARAMETERIZED_SYMBOL_PREFIX_INDEX.pop(stale_prefix, None)
        return unit


def _canonical_string_bytes(value: str) -> bytes:
    return json.encoder.encode_basestring(value).encode("utf-8")


def _symbol_semantic_digest(
    symbol_id: str,
    traits: tuple[str, ...],
    implementation_digest: str | None,
    parameter_bytes: bytes,
) -> str:
    digest = sha256()
    update = digest.update
    update(b'{"implementation_digest":')
    update(
        b"null"
        if implementation_digest is None
        else _canonical_string_bytes(implementation_digest)
    )
    update(b',"parameters":')
    update(parameter_bytes)
    update(b',"symbol_id":')
    update(_canonical_string_bytes(symbol_id))
    update(b',"traits":[')
    for index, trait in enumerate(traits):
        if index:
            update(b",")
        update(_canonical_string_bytes(trait))
    update(b"]}")
    return digest.hexdigest()


def _symbol_structural_digest(
    traits: tuple[str, ...],
    implementation: NoetriumUnit | None,
    parameter_bytes: bytes,
) -> str:
    digest = sha256()
    update = digest.update
    update(b'{"attributes":{"kind":"symbol","parameters":')
    update(parameter_bytes)
    update(b'},"roles":')
    if implementation is None:
        update(b"[]")
    else:
        update(b'[["implementation",[["unit",')
        update(_canonical_string_bytes(implementation.unit_digest))
        update(b"]]]]")
    update(b',"schemas":[')
    for index, trait in enumerate(traits):
        if index:
            update(b",")
        update(_canonical_string_bytes(trait))
    update(b"]}")
    return digest.hexdigest()


def symbol_unit(
    symbol_id: str,
    traits: tuple[str, ...] = (),
    implementation: NoetriumUnit | None = None,
    parameters: JsonValue = None,
) -> NoetriumUnit:
    symbol_id = unit_token(symbol_id, "research symbol_id")
    traits = _texts(traits, "research symbol trait")
    raw_parameters: object = {} if parameters is None else parameters
    if not isinstance(raw_parameters, Mapping):
        _object(parameters, "research symbol parameters")
        raise RuntimeError("symbol parameter validation returned a non-object")
    if (
        implementation is not None
        and implementation.attribute("kind") != "implementation"
    ):
        raise TypeError("symbol implementation must be an implementation Unit")
    if not raw_parameters:
        return _empty_parameter_symbol_unit(symbol_id, traits, implementation)

    implementation_digest = (
        None
        if implementation is None
        else str(implementation.attribute("implementation_digest"))
    )
    prefix = (symbol_id, traits, implementation_digest)
    cached = _parameterized_symbol_fast_lookup(prefix, raw_parameters)
    if cached is not None:
        return cached

    parameter_bytes = strict_finite_json_bytes(raw_parameters)
    semantic = _symbol_semantic_digest(
        symbol_id,
        traits,
        implementation_digest,
        parameter_bytes,
    )
    cached = _parameterized_symbol_semantic_lookup(semantic)
    if cached is not None:
        return cached

    frozen_parameters = _object(parameters, "research symbol parameters")
    roles = (
        ()
        if implementation is None
        else (("implementation", (implementation,)),)
    )
    structural = _symbol_structural_digest(
        traits,
        implementation,
        parameter_bytes,
    )
    unit = NoetriumUnit._from_normalized(
        symbol_id,
        schemas=traits,
        attributes=MappingProxyType({
            "kind": "symbol",
            "parameters": frozen_parameters,
        }),
        roles=roles,
        semantic_projection_digest=semantic,
        structural_digest=structural,
    )
    return _publish_parameterized_symbol(semantic, prefix, unit)


def symbol_implementation(symbol: NoetriumUnit) -> NoetriumUnit | None:
    _kind(symbol, "symbol")
    values = symbol.units("implementation")
    if len(values) > 1:
        raise ValueError("symbol has multiple implementations")
    return None if not values else values[0]


def endpoint_unit(
    child_id: str | None,
    port_name: str | None,
    *,
    ordinal: int = 0,
    side: str = "endpoint",
) -> NoetriumUnit:
    if child_id is not None:
        child_id = unit_token(child_id, "relation child_id")
    if port_name is not None:
        port_name = unit_token(port_name, "relation port_name")
    if child_id is None and port_name is None:
        raise ValueError("relation endpoint cannot be completely empty")
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("relation endpoint ordinal must be non-negative")
    semantic = canonical_digest((child_id, port_name, ordinal, side))
    return NoetriumUnit._from_normalized(
        f"endpoint:{semantic[:24]}",
        schemas=(),
        attributes=MappingProxyType({
            "kind": "endpoint",
            "child_id": child_id,
            "port_name": port_name,
            "ordinal": ordinal,
            "side": side,
        }),
        roles=(),
    )


def endpoint_child_id(endpoint: NoetriumUnit) -> str | None:
    _kind(endpoint, "endpoint")
    value = endpoint.attribute("child_id")
    return None if value is None else str(value)


def endpoint_port_name(endpoint: NoetriumUnit) -> str | None:
    _kind(endpoint, "endpoint")
    value = endpoint.attribute("port_name")
    return None if value is None else str(value)


def relation_trigger(relation: NoetriumUnit) -> GraphTrigger:
    _kind(relation, "relation")
    return GraphTrigger(
        GraphTriggerKind(str(relation.attribute("trigger_kind"))),
        relation.attribute("trigger_quorum"),
    )


def relation_progress(relation: NoetriumUnit) -> GraphProgressKind | None:
    _kind(relation, "relation")
    value = relation.attribute("progress")
    return None if value is None else GraphProgressKind(str(value))


def relation_id(relation: NoetriumUnit) -> str:
    _kind(relation, "relation")
    return str(relation.attribute("relation_id"))


def _relation_instance_digest(
    sources: tuple[NoetriumUnit, ...],
    targets: tuple[NoetriumUnit, ...],
    relation_id_value: str,
    parameters: Mapping[str, object],
    trigger: GraphTrigger,
    progress: GraphProgressKind | None,
) -> str:
    hasher = sha256()
    hasher.update(b"noetrium.unit.relation.instance.v1\0")
    for marker, endpoints in ((b"S", sources), (b"T", targets)):
        hasher.update(marker)
        for endpoint in endpoints:
            hasher.update((endpoint_child_id(endpoint) or "").encode("utf-8"))
            hasher.update(b"\0")
            hasher.update((endpoint_port_name(endpoint) or "").encode("utf-8"))
            hasher.update(b"\0")
    for value in (
        relation_id_value,
        canonical_digest(parameters),
        trigger.kind.value,
        "" if trigger.quorum is None else str(trigger.quorum),
        "" if progress is None else progress.value,
    ):
        hasher.update(value.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def relation_unit(
    sources: tuple[NoetriumUnit, ...],
    targets: tuple[NoetriumUnit, ...],
    relation_id: str,
    parameters: JsonValue = None,
    trigger: GraphTrigger = GraphTrigger(),
    progress: GraphProgressKind | None = None,
) -> NoetriumUnit:
    relation_id = unit_token(relation_id, "relation_id")
    if not isinstance(trigger, GraphTrigger):
        raise TypeError("relation trigger must be GraphTrigger")
    if progress is not None and not isinstance(progress, GraphProgressKind):
        raise TypeError("relation progress must be typed")
    for label, rows in (("sources", sources), ("targets", targets)):
        if type(rows) is not tuple or not rows:
            raise TypeError(f"relation {label} must be a non-empty endpoint tuple")
        for row in rows:
            _kind(row, "endpoint")
        if len(rows) > 1:
            identities = tuple(
                (endpoint_child_id(row), endpoint_port_name(row)) for row in rows
            )
            if len(identities) != len(set(identities)):
                raise ValueError(f"relation {label} must be unique")
    if len(sources) > 1:
        sources = tuple(
            sorted(
                sources,
                key=lambda row: (
                    endpoint_child_id(row) or "",
                    endpoint_port_name(row) or "",
                ),
            )
        )
    if len(targets) > 1:
        targets = tuple(
            sorted(
                targets,
                key=lambda row: (
                    endpoint_child_id(row) or "",
                    endpoint_port_name(row) or "",
                ),
            )
        )
    if trigger.kind is GraphTriggerKind.QUORUM and int(trigger.quorum) > len(sources):
        raise ValueError("relation quorum exceeds source count")
    parameters = _object(parameters, "relation parameters")
    semantic = _relation_instance_digest(
        sources, targets, relation_id, parameters, trigger, progress
    )
    return NoetriumUnit._from_normalized(
        f"relation:{semantic}",
        schemas=(),
        attributes=MappingProxyType({
            "kind": "relation",
            "relation_id": relation_id,
            "parameters": parameters,
            "trigger_kind": trigger.kind.value,
            "trigger_quorum": trigger.quorum,
            "progress": None if progress is None else progress.value,
        }),
        roles=(("source", sources), ("target", targets)),
        semantic_projection_digest=semantic,
    )


@lru_cache(maxsize=16384)
def _relation_body_digest_cached(
    parameters_digest: str,
    trigger_kind: str,
    trigger_quorum: int | None,
    progress: str | None,
) -> str:
    return canonical_digest(
        (
            "noetrium.unit.relation.body.v1",
            parameters_digest,
            trigger_kind,
            trigger_quorum,
            progress,
        )
    )


def _relation_body_digest(relation: NoetriumUnit) -> str:
    return _relation_body_digest_cached(
        canonical_digest(relation.parameters),
        relation_trigger(relation).kind.value,
        relation_trigger(relation).quorum,
        None if relation_progress(relation) is None else relation_progress(relation).value,
    )


def _endpoint_semantic(
    endpoint: NoetriumUnit,
    member_semantics: Mapping[str, str],
) -> tuple[str, str]:
    child_id = endpoint_child_id(endpoint)
    owner = "boundary" if child_id is None else member_semantics[child_id]
    return owner, endpoint_port_name(endpoint) or ""


def _relation_semantic(
    relation: NoetriumUnit,
    member_semantics: Mapping[str, str],
) -> str:
    return canonical_digest(
        (
            "noetrium.unit.relation.semantic.v1",
            _relation_body_digest(relation),
            tuple(
                sorted(
                    _endpoint_semantic(row, member_semantics)
                    for row in relation.units("source")
                )
            ),
            tuple(
                sorted(
                    _endpoint_semantic(row, member_semantics)
                    for row in relation.units("target")
                )
            ),
        )
    )


def _dag_refined_member_colors(
    members: tuple[NoetriumUnit, ...],
    relations: tuple[NoetriumUnit, ...],
    member_semantics: Mapping[str, str],
):
    """Refine duplicate member semantics without hyperedge expansion."""
    ids = tuple(member_semantics)
    known = set(ids)
    relation_rows = []
    incoming = {value: [] for value in ids}
    outgoing = {value: [] for value in ids}

    for relation in relations:
        relation_digest = _relation_body_digest(relation)
        sources = tuple(
            (child_id, endpoint_port_name(endpoint) or "")
            for endpoint in relation.units("source")
            for child_id in (endpoint_child_id(endpoint),)
            if child_id is not None
        )
        targets = tuple(
            (child_id, endpoint_port_name(endpoint) or "")
            for endpoint in relation.units("target")
            for child_id in (endpoint_child_id(endpoint),)
            if child_id is not None
        )
        if any(child_id not in known for child_id, _port in sources + targets):
            return None
        if not sources or not targets:
            continue
        index = len(relation_rows)
        relation_rows.append((relation_digest, sources, targets))
        for source_id, source_port in sources:
            outgoing[source_id].append((index, source_port))
        for target_id, target_port in targets:
            incoming[target_id].append((index, target_port))

    def directional_levels(reverse_direction: bool):
        source_index = 2 if reverse_direction else 1
        target_index = 1 if reverse_direction else 2
        incoming_count = {value: 0 for value in ids}
        outgoing_relations = {value: [] for value in ids}
        unresolved = []
        source_max = []
        target_rows = []
        for relation_index, row in enumerate(relation_rows):
            sources = row[source_index]
            targets = row[target_index]
            unresolved.append(len(sources))
            source_max.append(0)
            target_rows.append(targets)
            for source_id, _port in sources:
                outgoing_relations[source_id].append(relation_index)
            for target_id, _port in targets:
                incoming_count[target_id] += 1

        ready = deque(value for value in ids if incoming_count[value] == 0)
        order = []
        levels = {value: 0 for value in ids}
        while ready:
            value = ready.popleft()
            order.append(value)
            for relation_index in outgoing_relations[value]:
                if levels[value] > source_max[relation_index]:
                    source_max[relation_index] = levels[value]
                remaining = unresolved[relation_index] - 1
                unresolved[relation_index] = remaining
                if remaining:
                    continue
                next_level = source_max[relation_index] + 1
                for target_id, _port in target_rows[relation_index]:
                    if next_level > levels[target_id]:
                        levels[target_id] = next_level
                    incoming_count[target_id] -= 1
                    if incoming_count[target_id] == 0:
                        ready.append(target_id)
        if len(order) != len(ids):
            return None
        return levels

    forward_level = directional_levels(False)
    if forward_level is None:
        return None
    backward_level = directional_levels(True)
    if backward_level is None:
        return None

    def ranks(levels, reverse_direction: bool):
        grouped = {}
        for value in ids:
            grouped.setdefault(levels[value], []).append(value)
        result = {}
        incidence = outgoing if reverse_direction else incoming
        opposite_index = 2 if reverse_direction else 1
        opposite_signatures: dict[int, tuple[tuple[str, tuple[int, int]], ...]] = {}
        for level in sorted(grouped):
            signatures = {}
            for value in grouped[level]:
                contexts = []
                for relation_index, local_port in incidence[value]:
                    relation_digest, sources, targets = relation_rows[relation_index]
                    opposite_signature = opposite_signatures.get(relation_index)
                    if opposite_signature is None:
                        opposite = (relation_digest, sources, targets)[opposite_index]
                        opposite_signature = tuple(
                            sorted(
                                (remote_port, result[remote_id])
                                for remote_id, remote_port in opposite
                            )
                        )
                        opposite_signatures[relation_index] = opposite_signature
                    contexts.append(
                        (
                            relation_digest,
                            local_port,
                            opposite_signature,
                        )
                    )
                signatures[value] = (
                    member_semantics[value],
                    tuple(sorted(contexts)),
                )
            unique = tuple(sorted(set(signatures.values())))
            rank_by_signature = {
                signature: index for index, signature in enumerate(unique)
            }
            for value in grouped[level]:
                result[value] = (
                    level,
                    rank_by_signature[signatures[value]],
                )
        return result

    forward = ranks(forward_level, False)
    backward = ranks(backward_level, True)
    return {
        value: (
            f"{member_semantics[value]}:"
            f"{forward[value][0]}:{forward[value][1]}:"
            f"{backward[value][0]}:{backward[value][1]}"
        )
        for value in ids
    }



def _canonical_colored_tree_digest(
    component: frozenset[str],
    directed_edges: tuple[tuple[str, str], ...],
    colors: Mapping[str, str],
) -> str | None:
    """Exact canonical digest for one connected directed colored tree."""
    if not component:
        raise ValueError("canonical tree component cannot be empty")
    undirected = {node: set() for node in component}
    induced = []
    for source, target in directed_edges:
        if source not in component or target not in component:
            raise ValueError("tree digest received an edge outside its component")
        induced.append((source, target))
        undirected[source].add(target)
        undirected[target].add(source)
    undirected_edge_count = sum(len(rows) for rows in undirected.values()) // 2
    if undirected_edge_count != len(component) - 1:
        return None

    if len(component) <= 2:
        centers = tuple(component)
    else:
        degree = {node: len(rows) for node, rows in undirected.items()}
        leaves = [node for node, value in degree.items() if value <= 1]
        remaining = len(component)
        while remaining > 2:
            next_leaves = []
            remaining -= len(leaves)
            for leaf in leaves:
                for neighbor in undirected[leaf]:
                    degree[neighbor] -= 1
                    if degree[neighbor] == 1:
                        next_leaves.append(neighbor)
                degree[leaf] = 0
            leaves = next_leaves
        centers = tuple(node for node, value in degree.items() if value > 0)
        if not centers:
            centers = tuple(leaves)

    edge_set = frozenset(induced)

    def rooted_digest(root: str) -> str:
        parent = {root: None}
        order = []
        stack = [root]
        while stack:
            node = stack.pop()
            order.append(node)
            for neighbor in undirected[node]:
                if neighbor == parent[node]:
                    continue
                if neighbor in parent:
                    raise RuntimeError("tree traversal discovered a cycle")
                parent[neighbor] = node
                stack.append(neighbor)

        digests = {}
        for node in reversed(order):
            children = []
            for neighbor in undirected[node]:
                if parent.get(neighbor) != node:
                    continue
                forward = (node, neighbor) in edge_set
                backward = (neighbor, node) in edge_set
                direction = (
                    "both" if forward and backward
                    else "out" if forward
                    else "in" if backward
                    else None
                )
                if direction is None:
                    raise RuntimeError("tree edge lost directed incidence")
                children.append((direction, digests[neighbor]))
            digests[node] = canonical_digest(
                (
                    "noetrium.unit.colored-directed-tree.node.v1",
                    colors[node],
                    tuple(sorted(children)),
                )
            )
        return digests[root]

    return min(rooted_digest(center) for center in centers)


def _canonical_colored_incidence_digest(
    edges: tuple[tuple[str, str], ...],
    colors: Mapping[str, str],
) -> str:
    """Exact component-wise canonicalization with linear component partitioning."""
    nodes = tuple(colors)
    undirected = {node: set() for node in nodes}
    for source, target in edges:
        undirected[source].add(target)
        undirected[target].add(source)

    # Discover components once, then partition directed edges with one additional
    # pass. The former implementation rescanned every edge for every component,
    # which degenerates to O(C*E) for many disconnected structures.
    component_by_node: dict[str, int] = {}
    components: list[frozenset[str]] = []
    seen: set[str] = set()
    for root in nodes:
        if root in seen:
            continue
        component: set[str] = set()
        pending = [root]
        seen.add(root)
        while pending:
            node = pending.pop()
            component.add(node)
            for neighbor in undirected[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        component_index = len(components)
        frozen = frozenset(component)
        components.append(frozen)
        for node in frozen:
            component_by_node[node] = component_index

    edges_by_component: list[list[tuple[str, str]]] = [
        [] for _ in components
    ]
    for edge in edges:
        source_component = component_by_node[edge[0]]
        target_component = component_by_node[edge[1]]
        if source_component != target_component:
            raise RuntimeError("connected-component partition split a directed edge")
        edges_by_component[source_component].append(edge)

    component_digests = []
    for component_index, frozen in enumerate(components):
        component_edges = tuple(edges_by_component[component_index])
        tree_digest = _canonical_colored_tree_digest(
            frozen,
            component_edges,
            colors,
        )
        if tree_digest is not None:
            component_digests.append(
                canonical_digest(
                    (
                        "noetrium.unit.topology.tree-component.v1",
                        len(frozen),
                        tree_digest,
                    )
                )
            )
            continue

        component_colors = {node: colors[node] for node in frozen}
        canonical = canonaut.canonize(
            component_edges,
            colors=component_colors,
        )
        component_digests.append(
            canonical_digest(
                (
                    "noetrium.unit.topology.general-component.v1",
                    tuple(canonical.canonical_edges),
                    tuple(
                        component_colors[node]
                        for node in canonical.labeling
                    ),
                )
            )
        )

    return canonical_digest(
        (
            "noetrium.unit.topology.components.v2",
            tuple(sorted(component_digests)),
        )
    )

def _structure_semantic_digest(
    traits: tuple[str, ...],
    parameters: Mapping[str, object],
    boundary: NoetriumUnit,
    atoms: tuple[NoetriumUnit, ...],
    symbols: tuple[NoetriumUnit, ...],
    symbol_ids: tuple[str, ...],
    members: tuple[NoetriumUnit, ...],
    relations: tuple[NoetriumUnit, ...],
    *,
    parameters_digest: str | None = None,
) -> str:
    resolved_parameters_digest = (
        canonical_digest(parameters)
        if parameters_digest is None
        else parameters_digest
    )
    cache_key = (
        traits,
        resolved_parameters_digest,
        boundary.semantic_digest,
        tuple(row.semantic_digest for row in atoms),
        tuple(row.semantic_digest for row in symbols),
        symbol_ids,
        tuple((row.unit_id, row.semantic_digest) for row in members),
        tuple(row.unit_digest for row in relations),
    )
    with _STRUCTURE_SEMANTIC_CACHE_LOCK:
        cached = _STRUCTURE_SEMANTIC_CACHE.get(cache_key)
        if cached is not None:
            _STRUCTURE_SEMANTIC_CACHE.move_to_end(cache_key)
            return cached

    member_semantics = {row.unit_id: row.semantic_digest for row in members}
    child_multiset = tuple(sorted(Counter(member_semantics.values()).items()))

    if not relations:
        topology_digest = _EMPTY_TOPOLOGY_DIGEST
    elif len(set(member_semantics.values())) == len(member_semantics):
        topology_digest = canonical_digest(
            (
                "noetrium.unit.topology.discrete.v1",
                tuple(
                    sorted(
                        _relation_semantic(row, member_semantics)
                        for row in relations
                    )
                ),
            )
        )
    else:
        refined = _dag_refined_member_colors(
            members, relations, member_semantics
        )
        stable = member_semantics if refined is None else refined
        if refined is not None and len(set(refined.values())) == len(refined):
            topology_digest = canonical_digest(
                (
                    "noetrium.unit.topology.refined.v2",
                    tuple(
                        sorted(
                            _relation_semantic(row, stable)
                            for row in relations
                        )
                    ),
                )
            )
        else:
            colors: dict[str, str] = {}
            edges: list[tuple[str, str]] = []
            for member in members:
                node = f"member:{member.unit_id}"
                colors[node] = "member:" + stable[member.unit_id]
            for index, relation in enumerate(relations):
                relation_node = f"relation:{index}"
                colors[relation_node] = "relation:" + _relation_body_digest(relation)
                for side, endpoints in (
                    ("source", relation.units("source")),
                    ("target", relation.units("target")),
                ):
                    for ordinal, endpoint in enumerate(endpoints):
                        incidence = f"incidence:{index}:{side}:{ordinal}"
                        colors[incidence] = (
                            f"incidence:{side}:{endpoint_port_name(endpoint) or '@self'}"
                        )
                        edges.append((relation_node, incidence))
                        child_id = endpoint_child_id(endpoint)
                        if child_id is None:
                            boundary_node = (
                                f"boundary:{side}:{endpoint_port_name(endpoint)}"
                            )
                            colors[boundary_node] = (
                                f"boundary:{side}:{endpoint_port_name(endpoint)}"
                            )
                            edges.append((incidence, boundary_node))
                        else:
                            edges.append((incidence, f"member:{child_id}"))
            topology_digest = _canonical_colored_incidence_digest(
                tuple(edges),
                colors,
            )

    result = canonical_digest(
        (
            "noetrium.unit.structure.semantic.v1",
            traits,
            resolved_parameters_digest,
            boundary.semantic_digest,
            tuple(row.semantic_digest for row in atoms),
            tuple(row.semantic_digest for row in symbols),
            symbol_ids,
            child_multiset,
            topology_digest,
        )
    )
    with _STRUCTURE_SEMANTIC_CACHE_LOCK:
        existing = _STRUCTURE_SEMANTIC_CACHE.get(cache_key)
        if existing is not None:
            if existing != result:
                raise RuntimeError(
                    "structure semantic cache key produced conflicting digest"
                )
            _STRUCTURE_SEMANTIC_CACHE.move_to_end(cache_key)
            return existing
        _STRUCTURE_SEMANTIC_CACHE[cache_key] = result
        _STRUCTURE_SEMANTIC_CACHE.move_to_end(cache_key)
        while len(_STRUCTURE_SEMANTIC_CACHE) > _STRUCTURE_SEMANTIC_CACHE_MAXSIZE:
            _STRUCTURE_SEMANTIC_CACHE.popitem(last=False)
    return result


def structure_unit(
    unit_id: str,
    *,
    traits: tuple[str, ...] = (),
    parameters: JsonValue = None,
    boundary: NoetriumUnit = EMPTY_BOUNDARY,
    atoms: tuple[NoetriumUnit, ...] = (),
    symbols: tuple[NoetriumUnit, ...] = (),
    symbol_ids: tuple[str, ...] = (),
    members: tuple[NoetriumUnit, ...] = (),
    relations: tuple[NoetriumUnit, ...] = (),
    semantic_projection_digest: str | None = None,
) -> NoetriumUnit:
    unit_id = unit_token(unit_id, "structure unit_id")
    traits = _texts(traits, "structure trait")
    parameters = _object(parameters, "structure parameters")
    _kind(boundary, "boundary")
    for label, rows, expected in (
        ("atoms", atoms, "atom"),
        ("symbols", symbols, "symbol"),
        ("relations", relations, "relation"),
    ):
        if type(rows) is not tuple:
            raise TypeError(f"structure {label} must be a tuple")
        for row in rows:
            _kind(row, expected)
    if type(members) is not tuple or any(
        type(row) is not NoetriumUnit for row in members
    ):
        raise TypeError("structure members must be a NoetriumUnit tuple")
    symbol_ids = _texts(symbol_ids, "structure symbol")
    atoms = tuple(sorted(atoms, key=lambda row: row.unit_id))
    symbols = tuple(sorted(symbols, key=lambda row: row.unit_id))
    members = tuple(sorted(members, key=lambda row: row.unit_id))
    relations = tuple(sorted(relations, key=lambda row: row.semantic_digest))
    for label, rows in (("atom", atoms), ("symbol", symbols), ("member", members)):
        ids = tuple(row.unit_id for row in rows)
        if len(ids) != len(set(ids)):
            raise ValueError(f"structure {label} identities must be unique")
    owned_symbol_ids = {row.unit_id for row in symbols}
    overlap = tuple(sorted(owned_symbol_ids & set(symbol_ids)))
    if overlap:
        raise ValueError(f"structure cannot shadow parent-bound symbols: {overlap}")
    available = owned_symbol_ids | set(symbol_ids)
    for member in members:
        unknown = tuple(value for value in member.symbol_ids if value not in available)
        if unknown:
            raise ValueError(
                f"structure {member.unit_id!r} binds unknown parent symbols: {unknown}"
            )

    operation_cache_key: tuple[object, ...] | None = None
    operation_parameters_digest: str | None = None
    if "unit.operation" in traits:
        operation_parameters_digest = canonical_digest(parameters)
        operation_cache_key = (
            unit_id,
            traits,
            operation_parameters_digest,
            boundary.unit_digest,
            tuple(row.unit_digest for row in atoms),
            tuple(row.unit_digest for row in symbols),
            symbol_ids,
            tuple(row.unit_digest for row in members),
            tuple(row.unit_digest for row in relations),
            semantic_projection_digest,
        )
        with _OPERATION_STRUCTURE_CACHE_LOCK:
            cached_operation = _OPERATION_STRUCTURE_CACHE.get(operation_cache_key)
            if cached_operation is not None:
                _OPERATION_STRUCTURE_CACHE.move_to_end(operation_cache_key)
                return cached_operation

    members_by_id = {row.unit_id: row for row in members}
    member_ids = set(members_by_id)
    port_indexes: dict[
        str | None,
        tuple[dict[str, NoetriumUnit], dict[str, NoetriumUnit]],
    ] = {}

    def endpoint_type(
        endpoint: NoetriumUnit,
        source: bool,
    ) -> NoetriumUnit | None:
        port_name = endpoint_port_name(endpoint)
        if port_name is None:
            return None
        child_id = endpoint_child_id(endpoint)
        indexes = port_indexes.get(child_id)
        if indexes is None:
            if child_id is None:
                owner_boundary = boundary
            else:
                try:
                    owner_boundary = members_by_id[child_id].boundary
                except KeyError as exc:
                    raise ValueError(
                        f"relation references unknown member {child_id!r}"
                    ) from exc
            indexes = (
                {row.unit_id: row for row in owner_boundary.units("input")},
                {row.unit_id: row for row in owner_boundary.units("output")},
            )
            port_indexes[child_id] = indexes

        # Graph relations read from the root input / child output side and
        # write to the root output / child input side.
        want_input = source if child_id is None else not source
        ports = indexes[0] if want_input else indexes[1]
        try:
            return port_type(ports[port_name])
        except KeyError as exc:
            direction = "input" if want_input else "output"
            raise LookupError(
                f"boundary has no {direction} {port_name!r}"
            ) from exc

    for relation in relations:
        for endpoint in relation.units("source") + relation.units("target"):
            child_id = endpoint_child_id(endpoint)
            if child_id is not None and child_id not in member_ids:
                raise ValueError(
                    f"relation references unknown member {child_id!r}"
                )
        source_types = tuple(
            endpoint_type(endpoint, True)
            for endpoint in relation.units("source")
        )
        target_types = tuple(
            endpoint_type(endpoint, False)
            for endpoint in relation.units("target")
        )
        typed_sources = tuple(
            {value.unit_digest: value for value in source_types if value is not None}.values()
        )
        typed_targets = tuple(
            {value.unit_digest: value for value in target_types if value is not None}.values()
        )
        if typed_sources and typed_targets:
            # type_assignable_to() has a finite indexable predicate:
            #   target=research.any
            #   OR exact (type_id, parameters)
            #   OR target type_id declared as a source supertype.
            # Index the source side once instead of evaluating the S×T product.
            exact_targets = {
                (source.unit_id, canonical_digest(source.parameters))
                for source in typed_sources
            }
            supertype_targets = {
                supertype
                for source in typed_sources
                for supertype in type_supertypes(source)
                if supertype != source.unit_id
            }
            for target in typed_targets:
                target_id = target.unit_id
                if target_id == "research.any" or target_id in supertype_targets:
                    continue
                if (
                    target_id,
                    canonical_digest(target.parameters),
                ) in exact_targets:
                    continue
                raise ValueError("relation has an unsatisfied target type")

    semantic = (
        _structure_semantic_digest(
            traits,
            parameters,
            boundary,
            atoms,
            symbols,
            symbol_ids,
            members,
            relations,
            parameters_digest=operation_parameters_digest,
        )
        if semantic_projection_digest is None
        else semantic_projection_digest
    )
    # All public-constructor invariants have been proven above. Preserve the
    # exact post-init canonical role order while avoiding a second token,
    # freeze and sort traversal over this immutable graph cut.
    unit = NoetriumUnit._from_normalized(
        unit_id,
        schemas=traits,
        attributes=MappingProxyType({
            "kind": "structure",
            "parameters": parameters,
            "symbol_ids": symbol_ids,
        }),
        roles=(
            ("atom", atoms),
            ("boundary", (boundary,)),
            ("member", members),
            ("relation", relations),
            ("symbol", symbols),
        ),
        semantic_projection_digest=semantic,
    )
    if operation_cache_key is not None:
        with _OPERATION_STRUCTURE_CACHE_LOCK:
            existing_operation = _OPERATION_STRUCTURE_CACHE.get(operation_cache_key)
            if existing_operation is not None:
                if existing_operation.unit_digest != unit.unit_digest:
                    raise RuntimeError(
                        "exact unit.operation structure resolved to multiple Unit identities"
                    )
                _OPERATION_STRUCTURE_CACHE.move_to_end(operation_cache_key)
                return existing_operation
            _OPERATION_STRUCTURE_CACHE[operation_cache_key] = unit
            _OPERATION_STRUCTURE_CACHE.move_to_end(operation_cache_key)
            while len(_OPERATION_STRUCTURE_CACHE) > _OPERATION_STRUCTURE_CACHE_MAXSIZE:
                _OPERATION_STRUCTURE_CACHE.popitem(last=False)
    return unit


def structure_topological_order(
    unit: NoetriumUnit,
    relation_ids: frozenset[str] | tuple[str, ...],
) -> tuple[str, ...]:
    selected = frozenset(relation_ids)
    ids = tuple(member.unit_id for member in unit.members)
    known = set(ids)
    hyperrelations: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for relation in unit.relations:
        if relation_id(relation) not in selected:
            continue
        sources: list[str] = []
        targets: list[str] = []
        for endpoint in relation.units("source"):
            child_id = endpoint_child_id(endpoint)
            if child_id is None:
                raise ValueError("topological relation must connect members")
            if child_id not in known:
                raise ValueError(
                    "topological relation references unknown member"
                )
            sources.append(child_id)
        for endpoint in relation.units("target"):
            child_id = endpoint_child_id(endpoint)
            if child_id is None:
                raise ValueError("topological relation must connect members")
            if child_id not in known:
                raise ValueError(
                    "topological relation references unknown member"
                )
            targets.append(child_id)
        hyperrelations.append((tuple(sources), tuple(targets)))
    return deterministic_hypergraph_topological_order(
        ids,
        tuple(hyperrelations),
    )


def structure_ready_targets(
    unit: NoetriumUnit,
    *,
    satisfied_members: frozenset[str],
    relation_ids: frozenset[str] | None = None,
) -> tuple[str, ...]:
    known = {member.unit_id for member in unit.members}
    if not satisfied_members <= known:
        raise ValueError("satisfied members contain unknown ids")
    blocked: set[str] = set()
    for relation in unit.relations:
        if relation_ids is not None and relation_id(relation) not in relation_ids:
            continue
        endpoints = relation.units("source")
        satisfied_sources = sum(
            endpoint_child_id(source) in satisfied_members for source in endpoints
        )
        if relation_trigger(relation).satisfied(
            satisfied_sources=satisfied_sources,
            source_count=len(endpoints),
        ):
            continue
        blocked.update(
            target_id
            for target in relation.units("target")
            if (target_id := endpoint_child_id(target)) is not None
        )
    return tuple(sorted(known - satisfied_members - blocked))


def validate_execution_progress(
    unit: NoetriumUnit,
    relation_ids: frozenset[str] | None = None,
) -> None:
    """Reject progress-free cycles in linear hypergraph-incidence work."""
    selected = None if relation_ids is None else frozenset(relation_ids)
    member_ids = tuple(member.unit_id for member in unit.members)
    known = set(member_ids)
    adjacency = {("member", member_id): [] for member_id in member_ids}
    progress_members: set[str] = set()
    relation_ordinal = 0

    for relation in unit.relations:
        if selected is not None and relation_id(relation) not in selected:
            continue
        relation_node = ("relation", relation_ordinal)
        relation_ordinal += 1
        adjacency[relation_node] = []
        sources = set()
        targets = set()
        for endpoint in relation.units("source"):
            child_id = endpoint_child_id(endpoint)
            if child_id is None:
                continue
            if child_id not in known:
                raise ValueError("execution relation references unknown source member")
            sources.add(child_id)
        for endpoint in relation.units("target"):
            child_id = endpoint_child_id(endpoint)
            if child_id is None:
                continue
            if child_id not in known:
                raise ValueError("execution relation references unknown target member")
            targets.add(child_id)
        if relation_progress(relation) is not None:
            progress_members.update(sources)
            progress_members.update(targets)
        for source_id in sources:
            adjacency[("member", source_id)].append(relation_node)
        for target_id in targets:
            adjacency[relation_node].append(("member", target_id))

    nodes = tuple(adjacency)
    for component in strongly_connected_components(nodes, adjacency):
        cyclic = len(component) > 1 or any(
            node in adjacency[node] for node in component
        )
        if not cyclic:
            continue
        component_members = {
            str(payload)
            for kind, payload in component
            if kind == "member"
        }
        if component_members and component_members.isdisjoint(progress_members):
            raise ValueError(
                "execution cycle has no progress source: "
                f"{tuple(sorted(component_members))}"
            )


__all__ = [
    "NoetriumUnit",
    "UnitRef",
    "ANY_TYPE",
    "CONTROL_TYPE",
    "EMPTY_BOUNDARY",
    "GraphPortMode",
    "GraphProgressKind",
    "GraphStateAccess",
    "GraphStorageKind",
    "GraphTrigger",
    "GraphTriggerKind",
    "atom_unit",
    "boundary_input",
    "boundary_output",
    "boundary_unit",
    "effect_unit",
    "endpoint_child_id",
    "endpoint_port_name",
    "endpoint_unit",
    "evidence_unit",
    "IMPLEMENTATION_SCHEMA",
    "implementation_digest",
    "implementation_field",
    "implementation_type",
    "import_symbol",
    "is_implementation",
    "require_implementation",
    "resolve_callable",
    "implementation_unit",
    "port_mode",
    "port_type",
    "port_unit",
    "relation_id",
    "relation_progress",
    "relation_trigger",
    "relation_unit",
    "state_unit",
    "structure_ready_targets",
    "structure_topological_order",
    "structure_unit",
    "symbol_implementation",
    "symbol_unit",
    "type_assignable_to",
    "type_id",
    "type_storage_kind",
    "type_supertypes",
    "type_unit",
    "validate_execution_progress",
]
