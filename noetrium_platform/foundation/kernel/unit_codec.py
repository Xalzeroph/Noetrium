"""Canonical codec for the one universal NoetriumUnit carrier.

This module intentionally knows nothing about research graphs, resources,
failures, or effects. Every domain persists the same carrier through this codec.
"""
from __future__ import annotations

from collections import defaultdict
import heapq
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes,
    strict_json_loads,
)

from .unit import NoetriumUnit, UnitRef


UNIT_DOCUMENT_SCHEMA = "noetrium.unit.document.v2"


def _collect(root: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    if type(root) is not NoetriumUnit:
        raise TypeError("unit codec requires NoetriumUnit")
    found: dict[str, NoetriumUnit] = {}
    stack = [root]
    while stack:
        unit = stack.pop()
        previous = found.get(unit.unit_digest)
        if previous is not None:
            if previous != unit:
                raise ValueError("unit digest collision")
            continue
        found[unit.unit_digest] = unit
        for _name, values in unit.roles:
            for value in values:
                if type(value) is NoetriumUnit:
                    stack.append(value)
    return tuple(found[digest] for digest in sorted(found))


def unit_document(root: NoetriumUnit) -> dict[str, object]:
    units = _collect(root)
    index = {unit.unit_digest: offset for offset, unit in enumerate(units)}

    def value_document(value: object) -> dict[str, object]:
        if type(value) is NoetriumUnit:
            return {"kind": "unit", "index": index[value.unit_digest]}
        if type(value) is UnitRef:
            return {"kind": "ref", "path": value.path}
        return {"kind": "literal", "value": value}

    return {
        "schema": UNIT_DOCUMENT_SCHEMA,
        "root": index[root.unit_digest],
        "units": tuple(
            {
                "index": offset,
                "unit_id": unit.unit_id,
                "schemas": unit.schemas,
                "attributes": unit.attributes,
                "roles": tuple(
                    {
                        "name": name,
                        "values": tuple(value_document(value) for value in values),
                    }
                    for name, values in unit.roles
                ),
                "semantic_projection_digest": unit.semantic_projection_digest,
                "structural_digest": unit.structural_digest,
                "semantic_digest": unit.semantic_digest,
                "unit_digest": unit.unit_digest,
            }
            for offset, unit in enumerate(units)
        ),
    }


def encode_unit(root: NoetriumUnit) -> bytes:
    return canonical_bytes(unit_document(root))


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{field} must be an array")
    return tuple(value)


def decode_unit(raw: bytes) -> NoetriumUnit:
    if type(raw) is not bytes:
        raise TypeError("unit payload must be bytes")
    document = _mapping(strict_json_loads(raw), "unit document")
    if document.get("schema") != UNIT_DOCUMENT_SCHEMA:
        raise ValueError("unsupported unit document schema")
    raw_records = _sequence(document.get("units"), "unit document.units")
    if not raw_records:
        raise ValueError("unit document is empty")

    # Parse every document field exactly once. The second phase only resolves
    # already-validated Unit indices as dependencies become materializable.
    prepared: list[
        tuple[
            str,
            tuple[str, ...],
            Mapping[str, object],
            str | None,
            object,
            object,
            object,
            tuple[tuple[str, tuple[tuple[str, object], ...]], ...],
        ]
    ] = []
    dependencies: list[set[int]] = []
    parents: dict[int, set[int]] = defaultdict(set)
    record_count = len(raw_records)

    for expected, raw_record in enumerate(raw_records):
        record = _mapping(raw_record, f"units[{expected}]")
        if record.get("index") != expected:
            raise ValueError("unit table must use dense canonical indices")

        unit_id = record.get("unit_id")
        raw_schemas = _sequence(record.get("schemas"), "unit schemas")
        attributes = _mapping(record.get("attributes"), "unit attributes")
        projection = record.get("semantic_projection_digest")
        if type(unit_id) is not str or any(
            type(row) is not str for row in raw_schemas
        ):
            raise ValueError("unit identity/schema document is invalid")
        if projection is not None and type(projection) is not str:
            raise ValueError("semantic projection digest must be text/null")

        deps: set[int] = set()
        parsed_roles: list[
            tuple[str, tuple[tuple[str, object], ...]]
        ] = []
        for raw_role in _sequence(
            record.get("roles"),
            f"units[{expected}].roles",
        ):
            role = _mapping(raw_role, "unit role")
            name = role.get("name")
            if type(name) is not str:
                raise ValueError("unit role name must be text")
            parsed_values: list[tuple[str, object]] = []
            for raw_value in _sequence(
                role.get("values"),
                "unit role values",
            ):
                value = _mapping(raw_value, "unit role value")
                kind = value.get("kind")
                if kind == "unit":
                    child = value.get("index")
                    if (
                        type(child) is not int
                        or child < 0
                        or child >= record_count
                    ):
                        raise ValueError("unit child index out of range")
                    if child == expected:
                        raise ValueError(
                            "recursive object cycle must use UnitRef"
                        )
                    deps.add(child)
                    parents[child].add(expected)
                    parsed_values.append(("unit", child))
                elif kind == "ref":
                    path = _sequence(value.get("path"), "unit ref path")
                    if any(type(token) is not str for token in path):
                        raise ValueError(
                            "unit ref path must contain text"
                        )
                    parsed_values.append(("ref", tuple(path)))
                elif kind == "literal":
                    if "value" not in value:
                        raise ValueError(
                            "literal unit role value is missing value"
                        )
                    parsed_values.append(("literal", value["value"]))
                else:
                    raise ValueError("unknown unit role value kind")
            parsed_roles.append((name, tuple(parsed_values)))

        prepared.append(
            (
                unit_id,
                tuple(raw_schemas),
                attributes,
                projection,
                record.get("structural_digest"),
                record.get("semantic_digest"),
                record.get("unit_digest"),
                tuple(parsed_roles),
            )
        )
        dependencies.append(deps)

    ready = [index for index, deps in enumerate(dependencies) if not deps]
    heapq.heapify(ready)
    built: dict[int, NoetriumUnit] = {}

    while ready:
        index = heapq.heappop(ready)
        (
            unit_id,
            schemas,
            attributes,
            projection,
            expected_structural_digest,
            expected_semantic_digest,
            expected_unit_digest,
            parsed_roles,
        ) = prepared[index]
        roles: list[tuple[str, tuple[object, ...]]] = []
        for name, parsed_values in parsed_roles:
            values: list[object] = []
            for kind, payload in parsed_values:
                if kind == "unit":
                    child = int(payload)
                    try:
                        values.append(built[child])
                    except KeyError as exc:
                        raise ValueError(
                            "unit dependency materialized out of order"
                        ) from exc
                elif kind == "ref":
                    values.append(UnitRef(payload))
                else:
                    values.append(payload)
            roles.append((name, tuple(values)))

        unit = NoetriumUnit(
            unit_id,
            schemas=schemas,
            attributes=attributes,
            roles=tuple(roles),
            semantic_projection_digest=projection,
        )
        if unit.structural_digest != expected_structural_digest:
            raise ValueError("unit structural digest mismatch")
        if unit.semantic_digest != expected_semantic_digest:
            raise ValueError("unit semantic digest mismatch")
        if unit.unit_digest != expected_unit_digest:
            raise ValueError("unit digest mismatch")
        built[index] = unit
        for parent in parents.get(index, ()):
            dependencies[parent].discard(index)
            if not dependencies[parent]:
                heapq.heappush(ready, parent)

    if len(built) != len(prepared):
        raise ValueError("nested Unit object dependency cycle; use UnitRef")

    root = document.get("root")
    if type(root) is not int or root not in built:
        raise ValueError("unit document root is invalid")
    result = built[root]
    if encode_unit(result) != raw:
        raise ValueError("unit payload is not canonical")
    return result


__all__ = [
    "UNIT_DOCUMENT_SCHEMA",
    "decode_unit",
    "encode_unit",
    "unit_document",
]
