"""Minimal recursive semantic carrier for every Noetrium domain.

Noetrium has one persistent semantic object: NoetriumUnit. Domain notions such
as graph, relation, type, boundary, resource, failure, effect and record are
schemas over this carrier, never parallel sources of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from functools import lru_cache
import re
from types import MappingProxyType
from typing import Mapping, Union

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json
from noetrium_platform.foundation.kernel.kernel.canonical import _canonical_digest_update


_TOKEN = re.compile(r"[a-z][a-z0-9_.:-]*")
_EMPTY = freeze_json({})


@lru_cache(maxsize=131072)
def _canonical_token_valid(value: str) -> bool:
    """Validate each immutable token text at most once per process.

    Unit tokens are repeated pervasively across recursive schemas.  The
    canonical-token language is context independent, so re-running the same
    regex for every projection cannot add correctness after one exact text has
    been validated.  The bounded cache keeps memory O(unique hot tokens).
    """
    return _TOKEN.fullmatch(value) is not None


@lru_cache(maxsize=32768)
def _canonical_json_string_bytes(value: str) -> bytes:
    """Cache exact canonical JSON encoding for repeated immutable strings."""
    return json.encoder.encode_basestring(value).encode("utf-8")


def _structure_module():
    # Keep the structure dependency lazy: structure itself projects over
    # NoetriumUnit, so importing it at module load would create a runtime cycle.
    # One lazy import site is sufficient for every compatibility projection.
    from . import structure as structure_module

    return structure_module


def _universal_module():
    # Universal execution projects over NoetriumUnit as well, so keep this lazy.
    from .kernel import universal as universal_module

    return universal_module


def unit_merkle_digest(tag: str, *parts: object) -> str:
    """Fast unambiguous digest for already-canonical Unit identity parts."""

    out = bytearray()
    extend = out.extend
    stack = list(reversed(parts))
    stack.append(tag)
    while stack:
        value = stack.pop()
        if value is None:
            extend(b"N")
            continue
        value_type = type(value)
        if value_type is str:
            data = value.encode("utf-8")
            extend(b"S")
            extend(len(data).to_bytes(4, "big"))
            extend(data)
            continue
        if value_type is int:
            data = str(value).encode("ascii")
            extend(b"I")
            extend(len(data).to_bytes(4, "big"))
            extend(data)
            continue
        if value_type is tuple:
            extend(b"T")
            extend(len(value).to_bytes(4, "big"))
            stack.extend(reversed(value))
            continue
        raise TypeError(
            f"unsupported unit identity component: {value_type.__name__}"
        )
    return sha256(out).hexdigest()


def unit_token(value: str, field: str = "unit token") -> str:
    if type(value) is not str or not _canonical_token_valid(value):
        raise ValueError(f"{field} must be a canonical token")
    return value


@dataclass(frozen=True, slots=True)
class UnitRef:
    """Identity reference inside a recursive unit universe.

    The empty path denotes the current unit. Non-empty paths are resolved from
    the current schema scope. References, rather than object pointers, permit
    sharing and cycles without recursive Python-object cycles.
    """

    path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.path) is not tuple:
            raise TypeError("unit reference path must be a tuple")
        object.__setattr__(
            self,
            "path",
            tuple(unit_token(row, "unit reference path") for row in self.path),
        )

    @property
    def local_id(self) -> str | None:
        return None if not self.path else self.path[-1]


UnitRoleValue = Union[JsonValue, UnitRef, "NoetriumUnit"]


def _freeze_role_value(value: object) -> UnitRoleValue:
    if type(value) is UnitRef or type(value) is NoetriumUnit:
        return value
    return freeze_json(value)


def _structural_value(value: UnitRoleValue) -> object:
    """Exact structural contribution of one role value.

    Nested Units contribute their exact unit identity, not only their semantic
    projection. This prevents intentionally-equivalent semantic projections
    from collapsing distinct immutable structures.
    """

    if type(value) is UnitRef:
        return ("ref", value.path)
    if type(value) is NoetriumUnit:
        return ("unit", value.unit_digest)
    return ("atom", value)


def _unit_structural_digest(
    schemas: tuple[str, ...],
    attributes: JsonValue,
    roles: tuple[tuple[str, tuple[UnitRoleValue, ...]], ...],
) -> str:
    """Hash the exact legacy structural JSON without materializing it.

    ``NoetriumUnit`` identity is SHA-256 over the canonical document
    ``{attributes, roles, schemas}``.  The generic path previously allocated a
    second recursive tuple tree for every role value and then redispatched over
    each wrapper.  Unit/ref contributions are already canonical immutable
    identities, so stream those exact JSON tokens directly and invoke the
    generic encoder only for finite-JSON attributes/atom payloads.

    The local ``max_depth`` values preserve the old global depth=64 contract:
    attributes enter the structural root at depth 1; atom values enter through
    roles -> role pair -> values -> ("atom", value) at depth 5.
    """

    digest = sha256()
    update = digest.update
    encode_text = _canonical_json_string_bytes

    update(b'{"attributes":')
    _canonical_digest_update(
        digest,
        attributes,
        active=set(),
        depth=1,
        max_depth=64,
    )
    update(b',"roles":[')
    first_role = True
    for role_name, values in roles:
        if first_role:
            first_role = False
        else:
            update(b',')
        update(b'[')
        update(encode_text(role_name))
        update(b',[')
        first_value = True
        for value in values:
            if first_value:
                first_value = False
            else:
                update(b',')
            if type(value) is UnitRef:
                update(b'["ref",[')
                for index, part in enumerate(value.path):
                    if index:
                        update(b',')
                    update(encode_text(part))
                update(b']]')
            elif type(value) is NoetriumUnit:
                update(b'["unit",')
                update(encode_text(value.unit_digest))
                update(b']')
            else:
                update(b'["atom",')
                _canonical_digest_update(
                    digest,
                    value,
                    active=set(),
                    depth=5,
                    max_depth=64,
                )
                update(b']')
        update(b']]')
    update(b'],"schemas":[')
    for index, schema in enumerate(schemas):
        if index:
            update(b',')
        update(encode_text(schema))
    update(b']}')
    return digest.hexdigest()


def _member_walk_cardinality(values: tuple[UnitRoleValue, ...]) -> int | None:
    # The cached projection must preserve walk("member")'s type failures.
    # A malformed reference or atom must not silently disappear from cost.
    count = 1
    for child in values:
        if type(child) is not NoetriumUnit:
            return None
        subtree = child._member_walk_count
        if subtree is None:
            return None
        count += subtree
    return count


@dataclass(frozen=True, slots=True, eq=False)
class NoetriumUnit:
    """One recursive, self-contained semantic unit.

    roles is the only structural relation mechanism. A role value is either a
    literal, a reference, or another Unit definition. All higher-level
    structures are schema projections over these roles.
    """

    unit_id: str
    schemas: tuple[str, ...] = ()
    attributes: JsonValue = None
    roles: tuple[tuple[str, tuple[UnitRoleValue, ...]], ...] = ()
    semantic_projection_digest: str | None = field(
        default=None, repr=False, compare=False
    )
    structural_digest: str = field(init=False)
    semantic_digest: str = field(init=False)
    unit_digest: str = field(init=False)
    _roles_by_name: Mapping[str, tuple[UnitRoleValue, ...]] = field(
        init=False, repr=False, compare=False
    )
    _schema_set: frozenset[str] = field(init=False, repr=False, compare=False)
    _parameters_cache: Mapping[str, object] | None = field(
        init=False, repr=False, compare=False
    )
    _member_walk_count: int | None = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        unit_id = unit_token(self.unit_id, "unit_id")
        if type(self.schemas) is not tuple:
            raise TypeError("unit schemas must be a tuple")
        schemas = tuple(
            sorted(unit_token(row, "unit schema") for row in self.schemas)
        )
        schema_set = frozenset(schemas)
        if len(schemas) != len(schema_set):
            raise ValueError("unit schemas must be unique")
        attributes = _EMPTY if self.attributes is None else freeze_json(self.attributes)
        if not isinstance(attributes, Mapping):
            raise TypeError("unit attributes must be an object")

        if type(self.roles) is not tuple:
            raise TypeError("unit roles must be a tuple")
        normalized: list[tuple[str, tuple[UnitRoleValue, ...]]] = []
        seen: set[str] = set()
        for entry in self.roles:
            if type(entry) is not tuple or len(entry) != 2:
                raise TypeError("unit role entry must be a (name, values) tuple")
            role_name, values = entry
            role_name = unit_token(role_name, "unit role")
            if role_name in seen:
                raise ValueError(f"duplicate unit role: {role_name}")
            seen.add(role_name)
            if type(values) is not tuple:
                raise TypeError("unit role values must be a tuple")
            normalized.append(
                (role_name, tuple(_freeze_role_value(value) for value in values))
            )
        normalized.sort(key=lambda row: row[0])
        roles = tuple(normalized)
        roles_by_name = MappingProxyType(dict(roles))
        member_count = _member_walk_cardinality(
            roles_by_name.get("member", ())
        )
        parameters_value = attributes.get("parameters", _EMPTY)
        parameters_cache = (
            parameters_value if isinstance(parameters_value, Mapping) else None
        )

        structural = _unit_structural_digest(schemas, attributes, roles)
        projected = self.semantic_projection_digest
        if projected is not None:
            if (
                type(projected) is not str
                or len(projected) != 64
                or any(char not in "0123456789abcdef" for char in projected)
            ):
                raise ValueError(
                    "unit semantic_projection_digest must be lowercase SHA-256"
                )
        semantic = structural if projected is None else projected
        instance = sha256(
            b"noetrium.unit.instance.v2\0"
            + unit_id.encode("utf-8")
            + b"\0"
            + structural.encode("ascii")
            + b"\0"
            + semantic.encode("ascii")
        ).hexdigest()

        object.__setattr__(self, "unit_id", unit_id)
        object.__setattr__(self, "schemas", schemas)
        object.__setattr__(self, "attributes", attributes)
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "_roles_by_name", roles_by_name)
        object.__setattr__(self, "_schema_set", schema_set)
        object.__setattr__(self, "_parameters_cache", parameters_cache)
        object.__setattr__(self, "_member_walk_count", member_count)
        object.__setattr__(self, "structural_digest", structural)
        object.__setattr__(self, "semantic_digest", semantic)
        object.__setattr__(self, "unit_digest", instance)

    @classmethod
    def _from_normalized(
        cls,
        unit_id: str,
        *,
        schemas: tuple[str, ...],
        attributes: JsonValue,
        roles: tuple[tuple[str, tuple[UnitRoleValue, ...]], ...],
        semantic_projection_digest: str | None = None,
        structural_digest: str | None = None,
    ) -> "NoetriumUnit":
        """Construct from a kernel-proven canonical cut without re-normalizing.

        This is intentionally private. Callers must already have proven the
        exact invariants enforced by ``__post_init__``: canonical tokenized id
        and schemas, frozen object attributes, sorted unique role names, and
        frozen role values. The identity algorithm remains byte-for-byte the
        public constructor's algorithm; only duplicate validation/freezing work
        is removed.
        """

        projected = semantic_projection_digest
        if projected is not None and (
            type(projected) is not str
            or len(projected) != 64
            or any(char not in "0123456789abcdef" for char in projected)
        ):
            raise ValueError(
                "unit semantic_projection_digest must be lowercase SHA-256"
            )
        structural = structural_digest
        if structural is None:
            structural = _unit_structural_digest(schemas, attributes, roles)
        elif (
            type(structural) is not str
            or len(structural) != 64
            or any(char not in "0123456789abcdef" for char in structural)
        ):
            raise ValueError("unit structural_digest must be lowercase SHA-256")
        semantic = structural if projected is None else projected
        instance = sha256(
            b"noetrium.unit.instance.v2\0"
            + unit_id.encode("utf-8")
            + b"\0"
            + structural.encode("ascii")
            + b"\0"
            + semantic.encode("ascii")
        ).hexdigest()
        value = object.__new__(cls)
        parameters_value = attributes.get("parameters", _EMPTY)
        parameters_cache = (
            parameters_value if isinstance(parameters_value, Mapping) else None
        )
        object.__setattr__(value, "unit_id", unit_id)
        object.__setattr__(value, "schemas", schemas)
        object.__setattr__(value, "attributes", attributes)
        object.__setattr__(value, "roles", roles)
        object.__setattr__(value, "_roles_by_name", MappingProxyType(dict(roles)))
        object.__setattr__(value, "_schema_set", frozenset(schemas))
        object.__setattr__(value, "_parameters_cache", parameters_cache)
        object.__setattr__(
            value, "_member_walk_count",
            _member_walk_cardinality(dict(roles).get("member", ())),
        )
        object.__setattr__(value, "semantic_projection_digest", projected)
        object.__setattr__(value, "structural_digest", structural)
        object.__setattr__(value, "semantic_digest", semantic)
        object.__setattr__(value, "unit_digest", instance)
        return value

    @classmethod
    def make_structure(cls, unit_id: str, **kwargs) -> "NoetriumUnit":
        return _structure_module().structure_unit(unit_id, **kwargs)

    @classmethod
    def make_symbol(cls, symbol_id: str, **kwargs) -> "NoetriumUnit":
        return _structure_module().symbol_unit(symbol_id, **kwargs)

    @classmethod
    def make_type(
        cls,
        type_id: str,
        *,
        storage_kind="data",
        parameters=None,
        supertypes: tuple[str, ...] = (),
    ) -> "NoetriumUnit":
        structure = _structure_module()
        if isinstance(storage_kind, str):
            storage_kind = structure.GraphStorageKind(storage_kind)
        return structure.type_unit(
            type_id,
            storage_kind=storage_kind,
            parameters=parameters,
            supertypes=supertypes,
        )

    @classmethod
    def make_port(
        cls,
        name: str,
        type_ref: "NoetriumUnit" | None = None,
        *,
        mode="one",
    ) -> "NoetriumUnit":
        structure = _structure_module()
        if type_ref is None:
            type_ref = structure.ANY_TYPE
        if isinstance(mode, str):
            mode = structure.GraphPortMode(mode)
        return structure.port_unit(name, type_ref, mode)

    @classmethod
    def make_state(
        cls,
        state_id: str,
        type_ref: "NoetriumUnit",
        *,
        access="read_write",
        scope_id: str | None = None,
        configuration=None,
    ) -> "NoetriumUnit":
        structure = _structure_module()
        if isinstance(access, str):
            access = structure.GraphStateAccess(access)
        return structure.state_unit(
            state_id,
            type_ref,
            access=access,
            scope_id=scope_id,
            configuration=configuration,
        )

    @classmethod
    def make_effect(
        cls,
        effect_id: str,
        *,
        configuration=None,
    ) -> "NoetriumUnit":
        return _structure_module().effect_unit(
            effect_id,
            configuration=configuration,
        )

    @classmethod
    def make_evidence(
        cls,
        evidence_id: str,
        type_ref: "NoetriumUnit",
        *,
        required: bool = True,
        configuration=None,
    ) -> "NoetriumUnit":
        return _structure_module().evidence_unit(
            evidence_id,
            type_ref,
            required=required,
            configuration=configuration,
        )

    @classmethod
    def make_boundary(cls, **kwargs) -> "NoetriumUnit":
        return _structure_module().boundary_unit(**kwargs)

    @classmethod
    def make_endpoint(
        cls,
        child_id: str | None,
        port_name: str | None,
        **kwargs,
    ) -> "NoetriumUnit":
        return _structure_module().endpoint_unit(child_id, port_name, **kwargs)

    @classmethod
    def make_relation(
        cls,
        sources: tuple["NoetriumUnit", ...],
        targets: tuple["NoetriumUnit", ...],
        relation_id: str,
        **kwargs,
    ) -> "NoetriumUnit":
        return _structure_module().relation_unit(sources, targets, relation_id, **kwargs)








    @classmethod
    def make_operation(
        cls,
        node_id: str,
        implementation=None,
        *,
        operation: str | None = None,
        configuration=None,
        max_visits: int | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "NoetriumUnit":
        """Construct one universally executable operation Unit.

        A downstream callable is frozen into an implementation Unit and is
        resolved once by the Universal Unit Machine. No platform registration
        or domain-specific executor is required.
        """

        implementation_unit = implementation
        if implementation is not None and type(implementation) is not cls:
            if not callable(implementation):
                raise TypeError(
                    "operation implementation must be callable or NoetriumUnit"
                )
            implementation_unit = cls.from_python_callable(
                f"unit.operation:{unit_token(node_id, 'unit operation id')}",
                implementation,
                implementation_type="unit.operation",
            )
        resolved_operation = (
            f"inline:{unit_token(node_id, 'unit operation id')}"
            if operation is None
            else operation
        )
        return _universal_module().unit_operation(
            node_id,
            resolved_operation,
            implementation=implementation_unit,
            configuration=configuration,
            max_visits=max_visits,
            required_capabilities=required_capabilities,
        )

    @classmethod
    def make_flow(
        cls,
        source_node_id: str,
        target_node_id: str,
        *,
        default: bool = False,
    ) -> "NoetriumUnit":
        """Construct one universal control-flow relation Unit."""

        return _universal_module().unit_flow(
            source_node_id,
            target_node_id,
            default=default,
        )

    @classmethod
    def make_executable(
        cls,
        unit_id: str,
        *,
        entrypoint: str,
        members: tuple["NoetriumUnit", ...],
        domain: str = "unit",
        version: str = "1",
        state_schema: str = "json",
        relations: tuple["NoetriumUnit", ...] = (),
        required_capabilities: tuple[str, ...] = (),
    ) -> "NoetriumUnit":
        """Construct an executable Unit for any current or future domain."""

        return _universal_module().executable_unit(
            unit_id,
            domain=domain,
            version=version,
            state_schema=state_schema,
            entrypoint=entrypoint,
            members=members,
            relations=relations,
            required_capabilities=required_capabilities,
        )


    @classmethod
    def from_python_callable(
        cls,
        implementation_id: str,
        implementation,
        *,
        implementation_type: str = "python.callable",
        fields=None,
    ) -> "NoetriumUnit":
        """Freeze any importable Python callable as one implementation Unit."""

        return _structure_module().callable_implementation_unit(
            implementation_id,
            implementation,
            implementation_type=implementation_type,
            fields=fields,
        )


    def role(self, name: str) -> tuple[UnitRoleValue, ...]:
        return self._roles_by_name.get(unit_token(name, "unit role"), ())

    def units(self, role_name: str) -> tuple["NoetriumUnit", ...]:
        values = self.role(role_name)
        if any(type(value) is not NoetriumUnit for value in values):
            raise TypeError(f"unit role {role_name!r} is not unit-valued")
        return tuple(values)  # type: ignore[return-value]

    def refs(self, role_name: str) -> tuple[UnitRef, ...]:
        values = self.role(role_name)
        if any(type(value) is not UnitRef for value in values):
            raise TypeError(f"unit role {role_name!r} is not reference-valued")
        return tuple(values)  # type: ignore[return-value]

    def one_unit(self, role_name: str) -> "NoetriumUnit":
        values = self.units(role_name)
        if len(values) != 1:
            raise ValueError(f"unit role {role_name!r} requires exactly one unit")
        return values[0]

    def has_schema(self, schema_id: str) -> bool:
        return unit_token(schema_id, "unit schema") in self._schema_set

    @property
    def traits(self) -> tuple[str, ...]:
        """Semantic traits; a universal Unit view, not a second carrier."""

        return self.schemas

    @property
    def trait_ids(self) -> frozenset[str]:
        return self._schema_set

    def has_trait(self, trait_id: str) -> bool:
        return self.has_schema(trait_id)

    @property
    def parameters(self) -> Mapping[str, object]:
        value = self._parameters_cache
        if value is None:
            raise TypeError("unit parameters projection must be an object")
        return value

    def _require_kind(self, expected: str) -> None:
        kind = self.attributes.get("kind")
        if kind != expected:
            raise TypeError(
                f"unit {self.unit_id!r} is {kind!r}, expected {expected!r}"
            )

    @property
    def graph_id(self) -> str:
        self._require_kind("structure")
        return self.unit_id

    @property
    def name(self) -> str:
        self._require_kind("port")
        return self.unit_id

    @property
    def type_ref(self) -> "NoetriumUnit":
        kind = self.attributes.get("kind")
        if kind not in {"port", "state", "evidence"}:
            raise TypeError(f"unit {self.unit_id!r} has no type_ref projection")
        return self.one_unit("type")

    @property
    def type_id(self) -> str:
        kind = self.attributes.get("kind")
        if kind == "type":
            return self.unit_id
        if kind == "atom":
            value = self.attributes.get("type_id")
            if type(value) is not str:
                raise TypeError("atom type_id projection is invalid")
            return value
        raise TypeError(f"unit {self.unit_id!r} has no type_id projection")

    @property
    def type_digest(self) -> str:
        self._require_kind("type")
        return self.semantic_digest

    @property
    def storage_kind(self):
        self._require_kind("type")
        return _structure_module().GraphStorageKind(
            str(self.attributes.get("storage_kind"))
        )

    @property
    def supertypes(self) -> tuple[str, ...]:
        self._require_kind("type")
        values = self.attributes.get("supertypes", ())
        if type(values) is not tuple or any(type(value) is not str for value in values):
            raise TypeError("type supertypes projection is invalid")
        return values

    def is_assignable_to(self, target: "NoetriumUnit") -> bool:
        self._require_kind("type")
        if type(target) is not NoetriumUnit:
            raise TypeError("type target must be NoetriumUnit")
        target._require_kind("type")
        if target.unit_id == "research.any":
            return True
        if self.unit_id == target.unit_id:
            return self.parameters == target.parameters
        return target.unit_id in self.supertypes

    @property
    def mode(self):
        self._require_kind("port")
        return _structure_module().GraphPortMode(
            str(self.attributes.get("mode"))
        )

    @property
    def inputs(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("boundary")
        return self.units("input")

    @property
    def outputs(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("boundary")
        return self.units("output")

    @property
    def state(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("boundary")
        return self.units("state")

    @property
    def effects(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("boundary")
        return self.units("effect")

    @property
    def scopes(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("boundary")
        return self.units("scope")

    @property
    def evidence(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("boundary")
        return self.units("evidence")

    @property
    def boundary_digest(self) -> str:
        self._require_kind("boundary")
        return self.semantic_digest

    def input(self, name: str) -> "NoetriumUnit":
        self._require_kind("boundary")
        name = unit_token(name, "boundary input name")
        for value in self.units("input"):
            if value.unit_id == name:
                return value
        raise LookupError(f"boundary has no input {name!r}")

    def output(self, name: str) -> "NoetriumUnit":
        self._require_kind("boundary")
        name = unit_token(name, "boundary output name")
        for value in self.units("output"):
            if value.unit_id == name:
                return value
        raise LookupError(f"boundary has no output {name!r}")

    @property
    def child_id(self) -> str | None:
        self._require_kind("endpoint")
        value = self.attributes.get("child_id")
        return None if value is None else str(value)

    @property
    def port_name(self) -> str | None:
        self._require_kind("endpoint")
        value = self.attributes.get("port_name")
        return None if value is None else str(value)

    @property
    def sources(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("relation")
        return self.units("source")

    @property
    def targets(self) -> tuple["NoetriumUnit", ...]:
        self._require_kind("relation")
        return self.units("target")

    @property
    def relation_id(self) -> str:
        self._require_kind("relation")
        value = self.attributes.get("relation_id")
        if type(value) is not str:
            raise TypeError("relation_id projection is invalid")
        return value

    @property
    def relation_digest(self) -> str:
        self._require_kind("relation")
        return self.semantic_digest

    @property
    def trigger(self):
        self._require_kind("relation")
        structure = _structure_module()
        return structure.GraphTrigger(
            structure.GraphTriggerKind(str(self.attributes.get("trigger_kind"))),
            self.attributes.get("trigger_quorum"),
        )

    @property
    def progress(self):
        self._require_kind("relation")
        value = self.attributes.get("progress")
        if value is None:
            return None
        return _structure_module().GraphProgressKind(str(value))

    @property
    def atom_id(self) -> str:
        self._require_kind("atom")
        return self.unit_id

    @property
    def atom_digest(self) -> str:
        self._require_kind("atom")
        return self.semantic_digest

    @property
    def value(self):
        self._require_kind("atom")
        return self.attributes.get("value")

    @property
    def symbol_id(self) -> str:
        self._require_kind("symbol")
        return self.unit_id

    @property
    def symbol_digest(self) -> str:
        self._require_kind("symbol")
        return self.semantic_digest

    @property
    def platform_resolved(self) -> bool:
        self._require_kind("symbol")
        return not self.units("implementation")

    @property
    def implementation(self) -> "NoetriumUnit | None":
        self._require_kind("symbol")
        values = self.units("implementation")
        if len(values) > 1:
            raise ValueError("symbol has multiple implementations")
        return None if not values else values[0]

    @property
    def implementation_id(self) -> str | None:
        kind = self.attributes.get("kind")
        if kind == "symbol":
            implementation = self.implementation
            return None if implementation is None else implementation.implementation_id
        if kind == "implementation":
            return self.unit_id
        raise TypeError(f"unit {self.unit_id!r} has no implementation_id projection")

    @property
    def implementation_digest(self) -> str | None:
        kind = self.attributes.get("kind")
        if kind == "symbol":
            implementation = self.implementation
            return None if implementation is None else implementation.implementation_digest
        if kind == "implementation":
            value = self.attributes.get("implementation_digest")
            return None if value is None else str(value)
        raise TypeError(
            f"unit {self.unit_id!r} has no implementation_digest projection"
        )

    @property
    def scope_id(self) -> str | None:
        kind = self.attributes.get("kind")
        if kind in {"scope", "state"}:
            value = self.attributes.get("scope_id")
            return None if value is None else str(value)
        raise TypeError(f"unit {self.unit_id!r} has no scope_id projection")

    @property
    def state_id(self) -> str:
        self._require_kind("state")
        return self.unit_id

    @property
    def access(self):
        self._require_kind("state")
        return _structure_module().GraphStateAccess(
            str(self.attributes.get("access"))
        )

    @property
    def effect_id(self) -> str:
        self._require_kind("effect")
        return self.unit_id

    @property
    def evidence_id(self) -> str:
        self._require_kind("evidence")
        return self.unit_id

    @property
    def required(self) -> bool:
        self._require_kind("evidence")
        value = self.attributes.get("required")
        if type(value) is not bool:
            raise TypeError("evidence required projection is invalid")
        return value

    @property
    def configuration(self):
        kind = self.attributes.get("kind")
        if kind not in {"scope", "state", "effect", "evidence"}:
            raise TypeError(f"unit {self.unit_id!r} has no configuration projection")
        value = self.attributes.get("configuration", _EMPTY)
        if not isinstance(value, Mapping):
            raise TypeError("configuration projection must be an object")
        return value

    @property
    def members(self) -> tuple["NoetriumUnit", ...]:
        return self.units("member")

    @property
    def relations(self) -> tuple["NoetriumUnit", ...]:
        return self.units("relation")

    @property
    def atoms(self) -> tuple["NoetriumUnit", ...]:
        return self.units("atom")

    @property
    def symbols(self) -> tuple["NoetriumUnit", ...]:
        return self.units("symbol")

    @property
    def symbol_ids(self) -> tuple[str, ...]:
        values = self.attributes.get("symbol_ids", ())
        if type(values) is not tuple or any(type(value) is not str for value in values):
            raise TypeError("unit symbol_ids projection must be a text tuple")
        return values

    @property
    def boundary(self) -> "NoetriumUnit":
        return self.one_unit("boundary")

    @property
    def leaf(self) -> bool:
        return not self.members

    def member(self, unit_id: str) -> "NoetriumUnit":
        unit_token(unit_id, "member unit_id")
        for unit in self.members:
            if unit.unit_id == unit_id:
                return unit
        raise LookupError(f"unit has no member {unit_id!r}")

    def unit_at_path(self, path: tuple[str, ...]) -> "NoetriumUnit":
        """Resolve one recursive member path from this Unit root."""

        ref = UnitRef(path)
        if not ref.path or ref.path[0] != self.unit_id:
            raise LookupError(f"unit root has no path {path!r}")
        current = self
        for child_id in ref.path[1:]:
            current = current.member(child_id)
        return current

    def owning_unit_with_schema(
        self,
        path: tuple[str, ...],
        schema_id: str,
    ) -> tuple[tuple[str, ...], "NoetriumUnit"]:
        """Return the nearest ancestor carrying the requested schema."""

        ref = UnitRef(path)
        if not ref.path or ref.path[0] != self.unit_id:
            raise LookupError(f"unit root has no path {path!r}")
        current = self
        matched = ((self.unit_id,), self) if self.has_schema(schema_id) else None
        for offset, child_id in enumerate(ref.path[1:], start=2):
            current = current.member(child_id)
            if current.has_schema(schema_id):
                matched = (ref.path[:offset], current)
        if matched is None:
            raise LookupError(
                f"unit path {path!r} has no ancestor with schema {schema_id!r}"
            )
        return matched

    def symbol(self, unit_id: str) -> "NoetriumUnit":
        unit_token(unit_id, "symbol unit_id")
        for unit in self.symbols:
            if unit.unit_id == unit_id:
                return unit
        raise LookupError(f"unit has no symbol {unit_id!r}")

    def attribute(self, name: str, default: object = None) -> object:
        unit_token(name, "unit attribute")
        return self.attributes.get(name, default)

    @property
    def member_walk_count(self) -> int:
        """The exact size of walk("member"), computed once by induction."""

        result = self._member_walk_count
        if result is None:
            raise TypeError("unit role 'member' is not unit-valued")
        return result

    def walk(self, role_name: str = "member") -> tuple["NoetriumUnit", ...]:
        rows: list[NoetriumUnit] = []
        stack: list[NoetriumUnit] = [self]
        while stack:
            unit = stack.pop()
            rows.append(unit)
            children = unit.units(role_name)
            stack.extend(reversed(children))
        return tuple(rows)

    def paths_with_schema(
        self,
        schema_id: str,
        role_name: str = "member",
    ) -> tuple[tuple[tuple[str, ...], "NoetriumUnit"], ...]:
        """Enumerate recursive Unit paths carrying one schema in canonical order."""

        schema = unit_token(schema_id, "unit schema")
        role_name = unit_token(role_name, "unit role")
        rows: list[tuple[tuple[str, ...], NoetriumUnit]] = []
        stack: list[tuple[NoetriumUnit, tuple[str, ...]]] = [
            (self, (self.unit_id,))
        ]
        while stack:
            unit, path = stack.pop()
            if unit.has_schema(schema):
                rows.append((path, unit))
            children = unit.units(role_name)
            stack.extend(
                reversed(
                    tuple(
                        (child, path + (child.unit_id,))
                        for child in children
                    )
                )
            )
        return tuple(rows)

    def units_with_schema(
        self,
        schema_id: str,
        role_name: str = "member",
    ) -> tuple["NoetriumUnit", ...]:
        """Project the recursive role tree onto Units carrying one schema."""

        schema = unit_token(schema_id, "unit schema")
        return tuple(
            unit
            for unit in self.walk(role_name)
            if unit.has_schema(schema)
        )

    def __eq__(self, other: object) -> bool:
        return type(other) is NoetriumUnit and self.unit_digest == other.unit_digest

    def __hash__(self) -> int:
        return hash(self.unit_digest)


def role(name: str, *values: UnitRoleValue) -> tuple[str, tuple[UnitRoleValue, ...]]:
    """Canonical role constructor used by every schema factory."""

    return (unit_token(name, "unit role"), tuple(values))


__all__ = ["NoetriumUnit", "UnitRef", "UnitRoleValue", "role", "unit_merkle_digest", "unit_token"]
