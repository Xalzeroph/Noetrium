"""Universal Agent action authoring from authorized capability Unit contracts.

No Minecraft/GUI/robotics action lists, world ontologies or model-specific
templates live here. Methods borrow the exact schema of the environment
already authorized by its Capability Authority.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from noetrium_platform.foundation.kernel.kernel import thaw_json


def _obj(raw: object, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(name + " must be an object")
    return raw


def _sequence(raw: object, name: str) -> Sequence[Any]:
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise TypeError(name + " must be a sequence")
    return raw


def capability_authorized_action_contracts(
    metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Read only explicitly exported action contracts; never query task internals."""
    documents = _sequence(
        _obj(metadata, "capability descriptor").get("environment_capabilities", ()),
        "environment capability list",
    )
    names: dict[str, dict[str, Any]] = {}
    for document in documents:
        descriptor = _obj(document, "environment descriptor")
        owner = _obj(descriptor.get("metadata", {}), "environment metadata")
        contracts = _sequence(owner.get("action_contracts", ()), "action contracts")
        # Capability authorization MUST already have filtered these records.
        permitted = set(_sequence(descriptor.get("action_types", ()), "authorized action names"))
        for row in contracts:
            action = _obj(row, "action contract")
            name = action.get("action_type")
            if not isinstance(name, str) or not name:
                raise TypeError("action contract action_type must be nonempty text")
            if name not in permitted:
                raise ValueError("action contract leaked a non-authorized action: " + name)
            schema = _obj(action.get("argument_schema"), "action arguments schema")
            if schema.get("type") != "object":
                raise TypeError("authorized action argument_schema must be an object schema")
            candidate = thaw_json(action)
            if name in names and candidate != names[name]:
                raise ValueError("incompatible authorized action definitions: " + name)
            names[name] = candidate
    if not names:
        raise ValueError("No authorized action contracts exported by provider")
    return tuple(names[name] for name in sorted(names))


def compact_authorized_action_catalog(
    contracts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bounded decision index; full detail and typed schema remain authorized."""
    if not contracts:
        raise ValueError("authorized action catalog must be non-empty")
    all_columns = tuple(key for key in contracts[0] if key != "argument_schema")
    if "action_type" not in all_columns:
        raise ValueError("action contract requires action_type")
    if any(
        set(row) - {"argument_schema"} != set(all_columns) or "argument_schema" not in row
        for row in contracts
    ):
        raise ValueError("action catalog must have one uniform authorized schema")
    # Preserve *all* authorized actions and their compact signatures in the
    # default decision view. If exact detail inspection is itself authorized,
    # long prose/examples belong behind that provider-backed action rather than
    # being repeated on every model turn. Never guess action relevance from a
    # goal, method, benchmark, or environment name: this only changes the
    # representation of the complete authorized index, not its membership.
    can_expand = any(row["action_type"] == "describe_action" for row in contracts)
    deferred_detail_columns = frozenset({
        "description",
        "argument_semantics",
        "argument_effects",
        "applicability",
        "syntax_examples",
        "examples_are_public_syntax_not_world_evidence",
        "usage_guide",
    })
    columns = (
        tuple(key for key in all_columns if key not in deferred_detail_columns)
        if can_expand else all_columns
    )
    result = {
        "columns": columns,
        "rows": tuple(tuple(thaw_json(row[key]) for key in columns) for row in contracts),
    }
    if can_expand:
        result["details_via"] = "describe_action"
    return result


def compile_authorized_action_generation(
    contracts: Sequence[Mapping[str, Any]],
    *,
    name: str = "one_authorized_capability_action_v1",
    max_tokens: int = 384,
    optional_fields: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a disjoint, strict action/arguments JSON schema from Unit truth."""
    if not contracts:
        raise ValueError("authorized action generation requires capability contracts")
    if type(max_tokens) is not int or max_tokens <= 0:
        raise ValueError("model output token bound must be positive")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("structured generation schema name must be nonempty")
    seen = set()
    branches = []
    for row in contracts:
        name_value = _obj(row, "authorized action").get("action_type")
        if not isinstance(name_value, str) or not name_value or name_value in seen:
            raise ValueError("action names must be unique and nonempty")
        seen.add(name_value)
        schema = _obj(row.get("argument_schema"), "authorized action schema")
        if schema.get("type") != "object":
            raise TypeError("action argument schema must be an object")
        branches.append({
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "enum": [name_value]},
                "arguments": thaw_json(schema),
            },
            "required": ["action_type", "arguments"],
            "additionalProperties": False,
        })
    extras = dict(optional_fields or {})
    if "action" in extras:
        raise ValueError("method cannot override the authorized action schema")
    return {
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {**{key: thaw_json(value) for key, value in extras.items()},
                                   "action": {"anyOf": branches}},
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        },
    }
