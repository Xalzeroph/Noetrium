from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_digest, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


def _walk_all_roles(root: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    if type(root) is not NoetriumUnit:
        raise TypeError("method schema authority root must be NoetriumUnit")
    rows: list[NoetriumUnit] = []
    seen: set[str] = set()
    stack = [root]
    while stack:
        unit = stack.pop()
        if unit.unit_digest in seen:
            continue
        seen.add(unit.unit_digest)
        rows.append(unit)
        children: list[NoetriumUnit] = []
        for _role_name, values in unit.roles:
            for value in values:
                if type(value) is NoetriumUnit:
                    children.append(value)
        stack.extend(reversed(children))
    return tuple(rows)


def _declared_schema_rows(root: NoetriumUnit) -> tuple[tuple[str, NoetriumUnit], ...]:
    by_id: dict[str, NoetriumUnit] = {}
    for unit in _walk_all_roles(root):
        if unit.attributes.get("kind") != "type":
            continue
        schema_id = unit.parameters.get("schema")
        if type(schema_id) is not str or not schema_id.strip():
            continue
        schema_id = schema_id.strip()
        previous = by_id.get(schema_id)
        if previous is not None and previous.semantic_digest != unit.semantic_digest:
            # Multiple physical type names may deliberately project the same schema.
            # They must agree on the validation contract carried by parameters.
            if dict(previous.parameters) != dict(unit.parameters):
                raise ValueError(
                    "one method schema id has conflicting Unit declarations: "
                    + schema_id
                )
            continue
        by_id[schema_id] = unit
    return tuple(sorted(by_id.items()))


class UnitDeclaredMethodSchemaAuthority:
    """Immutable MethodSchemaPort compiled from Unit Type declarations.

    Static schema truth remains in NoetriumUnit. This runtime object is only the
    compiled validation authority used by Method execution.
    """

    __slots__ = ("_definitions", "identity_digest")

    def __init__(self, root: NoetriumUnit) -> None:
        rows = _declared_schema_rows(root)
        self._definitions = {schema_id: unit for schema_id, unit in rows}
        self.identity_digest = canonical_digest(
            {
                "authority": "unit-declared-method-schema.v1",
                "schemas": tuple(
                    (
                        schema_id,
                        unit.semantic_digest,
                        tuple(sorted(dict(unit.parameters).items())),
                    )
                    for schema_id, unit in rows
                ),
            }
        )

    @property
    def schema_ids(self) -> tuple[str, ...]:
        return tuple(sorted(("json", *self._definitions)))

    def validate(self, schema_id: str, value, *, location: str) -> None:
        if type(schema_id) is not str or not schema_id.strip():
            raise ValueError("method schema_id must be non-empty text")
        if type(location) is not str or not location.strip():
            raise ValueError("method schema validation location must be non-empty text")
        schema_id = schema_id.strip()

        # freeze_json is the canonical JSON-domain validator. It rejects opaque
        # Python objects, NaN/Inf, mutable/non-canonical mappings, and excess depth.
        frozen = freeze_json(value)
        if schema_id == "json":
            return

        definition = self._definitions.get(schema_id)
        if definition is None:
            raise LookupError(f"method schema is not declared by the Unit graph: {schema_id!r}")
        parameters = definition.parameters
        json_type = parameters.get("json_type")
        if json_type is None:
            # The Unit declared an opaque named JSON schema but no narrower
            # structural constraint. JSON-domain validation is therefore exact.
            return
        if type(json_type) is not str:
            raise TypeError(f"method schema {schema_id!r} json_type must be text")

        matches = {
            "object": lambda x: isinstance(x, Mapping),
            "array": lambda x: type(x) is tuple,
            "string": lambda x: type(x) is str,
            "integer": lambda x: type(x) is int,
            "number": lambda x: type(x) in (int, float),
            "boolean": lambda x: type(x) is bool,
            "null": lambda x: x is None,
        }
        predicate = matches.get(json_type)
        if predicate is None:
            raise ValueError(
                f"method schema {schema_id!r} has unsupported json_type {json_type!r}"
            )
        if not predicate(frozen):
            raise TypeError(
                f"{location} does not satisfy method schema {schema_id!r}: "
                f"expected json_type={json_type}"
            )
        required_fields = parameters.get("required_fields", ())
        if type(required_fields) is not tuple or any(
            type(field) is not str or not field for field in required_fields
        ):
            raise TypeError(
                f"method schema {schema_id!r} required_fields must be text tuple"
            )
        if required_fields:
            if not isinstance(frozen, Mapping):
                raise TypeError(
                    f"method schema {schema_id!r} required_fields require object json_type"
                )
            missing = tuple(field for field in required_fields if field not in frozen)
            if missing:
                raise ValueError(
                    f"{location} is missing required fields for {schema_id!r}: {missing!r}"
                )


def compile_method_schema_authority(
    root: NoetriumUnit,
) -> UnitDeclaredMethodSchemaAuthority:
    return UnitDeclaredMethodSchemaAuthority(root)


__all__ = ["UnitDeclaredMethodSchemaAuthority", "compile_method_schema_authority"]
