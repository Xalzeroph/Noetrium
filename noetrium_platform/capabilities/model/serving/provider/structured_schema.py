"""Lossless local-vLLM structured decoding: fast wire grammar, exact evidence."""
from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from noetrium_platform.foundation.kernel.kernel import (
    canonical_bytes, freeze_json, thaw_json,
)

# The local vLLM XGrammar backend cannot enforce these bounded keywords; when
# present it can fall back to a substantially slower constrained decoder.
# The complete *original* schema is mandatory for response validation.
_UNSUPPORTED_XGRAMMAR = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minItems", "maxItems", "minLength", "maxLength",
    "minProperties", "maxProperties",
    # The current vLLM V1 XGrammar backend cannot compile these constraints.
    # Remove them from the wire grammar ONLY: the original Draft 2020-12
    # validator (including FormatChecker) still rejects any violating reply.
    "multipleOf", "uniqueItems", "contains", "minContains", "maxContains",
    "format",
})
_NAMED_SUBSCHEMAS = frozenset({
    "properties", "patternProperties", "$defs", "definitions", "dependentSchemas",
})
_DIRECT_SUBSCHEMAS = frozenset({
    "items", "additionalItems", "additionalProperties", "unevaluatedItems",
    "unevaluatedProperties", "propertyNames", "contains", "not", "if",
    "then", "else",
})
_SEQUENCE_SUBSCHEMAS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_XGRAMMAR_BACKEND = "xgrammar"
_XGRAMMAR_DISABLE_ANY_WHITESPACE = "disable-any-whitespace"


def _guarded_xgrammar_backend(body: Mapping) -> str | None:
    """Return the vLLM XGrammar backend with runaway whitespace disabled.

    vLLM 0.8.5/XGrammar explicitly exposes ``disable-any-whitespace`` for
    models that can otherwise greedily emit arbitrary JSON whitespace until
    ``max_tokens``.  This is a wire-decoder constraint only: the durable
    request and exact post-generation JSON Schema validation stay unchanged.
    An explicitly selected non-XGrammar backend remains authoritative.
    """
    raw = body.get("guided_decoding_backend")
    if raw is None:
        return f"{_XGRAMMAR_BACKEND}:{_XGRAMMAR_DISABLE_ANY_WHITESPACE}"
    if type(raw) is not str or not raw.strip():
        return None
    name, separator, raw_options = raw.partition(":")
    if name != _XGRAMMAR_BACKEND:
        return None
    options = {
        option.strip()
        for option in raw_options.split(",")
        if separator and option.strip()
    }
    options.add(_XGRAMMAR_DISABLE_ANY_WHITESPACE)
    return _XGRAMMAR_BACKEND + ":" + ",".join(sorted(options))


def strict_original_schema(body: Mapping) -> Mapping | None:
    fmt = body.get("response_format")
    if not isinstance(fmt, Mapping) or fmt.get("type") != "json_schema":
        return None
    spec = fmt.get("json_schema")
    if not isinstance(spec, Mapping) or spec.get("strict") is not True:
        return None
    schema = spec.get("schema")
    if not isinstance(schema, Mapping):
        raise ValueError("strict JSON schema must contain a schema object")
    # Canonical Noetrium JSON freezes arrays as tuples. JSON Schema validators
    # require actual JSON arrays (lists), including "required" and "anyOf".
    return thaw_json(schema)


@lru_cache(maxsize=128)
def _compiled_xgrammar_projection(schema_bytes: bytes) -> Mapping | None:
    """Reuse a deterministic schema compilation, never a model decision.

    Keys are exact canonical schema bytes (not hashes with collision risk);
    values are recursively frozen, safe for concurrent readers. The bounded
    cache cannot retain an unbounded number of distinct downstream schemas.
    """
    original = json.loads(schema_bytes)
    changed = False

    def project(node):
        nonlocal changed
        if not isinstance(node, Mapping):
            return node
        output = {}
        for key, value in node.items():
            if key in _UNSUPPORTED_XGRAMMAR:
                changed = True
                continue
            if key in _NAMED_SUBSCHEMAS and isinstance(value, Mapping):
                output[key] = {name: project(child) for name, child in value.items()}
            elif key in _DIRECT_SUBSCHEMAS and isinstance(value, Mapping):
                output[key] = project(value)
            elif key in _SEQUENCE_SUBSCHEMAS and isinstance(value, (tuple, list)):
                output[key] = [project(child) for child in value]
            else:
                output[key] = value
        return output

    projected = project(original)
    if not changed:
        return None
    Draft202012Validator.check_schema(original)
    return freeze_json(projected)


def xgrammar_wire_projection(body: Mapping) -> dict | None:
    """Return a wire-only XGrammar projection without changing semantics.

    Exact original schema and request identity remain immutable.  The wire
    grammar strips only engine-unsupported constraints (which are revalidated
    exactly after generation) and disables XGrammar's arbitrary JSON
    whitespace, preventing valid prefixes from consuming the whole token budget
    without ever closing the JSON value.
    """
    original = strict_original_schema(body)
    if original is None:
        return None
    guarded_backend = _guarded_xgrammar_backend(body)
    if guarded_backend is None:
        # A caller explicitly selected another guided-decoding backend.  Do not
        # silently force XGrammar or apply its compatibility projection.
        return None
    fast_schema = _compiled_xgrammar_projection(canonical_bytes(original))
    wire = dict(body)
    changed = False
    if wire.get("guided_decoding_backend") != guarded_backend:
        wire["guided_decoding_backend"] = guarded_backend
        changed = True
    if fast_schema is not None:
        fmt = dict(wire["response_format"])
        spec = dict(fmt["json_schema"])
        spec["schema"] = fast_schema
        fmt["json_schema"] = spec
        wire["response_format"] = fmt
        changed = True
    return wire if changed else None


@lru_cache(maxsize=128)
def _compiled_exact_validator(schema_bytes: bytes) -> Draft202012Validator:
    schema = json.loads(schema_bytes)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _specific_validation_error(error: ValidationError) -> ValidationError:
    """Choose the most actionable leaf from combinator validation failures.

    ``jsonschema`` reports an ``anyOf``/``oneOf`` miss at the union root even
    when one discriminator branch nearly matched and only a nested numeric or
    property constraint failed. Planner repair needs that leaf constraint, not
    the opaque union boundary. Discriminator enum misses are deliberately
    deprioritized because every non-selected branch produces one.
    """
    leaves: list[ValidationError] = []

    def visit(node: ValidationError) -> None:
        if node.context:
            for child in node.context:
                visit(child)
        else:
            leaves.append(node)

    visit(error)
    if not leaves:
        return error

    def rank(node: ValidationError) -> tuple[int, int, int]:
        path = tuple(node.absolute_path)
        discriminator_miss = (
            node.validator == "enum"
            and bool(path)
            and path[-1] in {"action_type", "type", "kind"}
        )
        semantic_leaf = node.validator not in {"anyOf", "oneOf", "allOf"}
        return (
            0 if discriminator_miss else 1,
            1 if semantic_leaf else 0,
            len(path),
        )

    return max(leaves, key=rank)


def validate_original_structured_response(text: str, original_body: Mapping) -> None:
    """Reject a relaxed-wire response unless the full original schema accepts it."""
    schema = strict_original_schema(original_body)
    if schema is None:
        return
    if type(text) is not str:
        raise ValueError("strict model response must be text")
    try:
        candidate = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("strict model response is not JSON") from exc
    try:
        _compiled_exact_validator(canonical_bytes(schema)).validate(candidate)
    except ValidationError as exc:
        specific = _specific_validation_error(exc)
        path = "/".join(str(part) for part in specific.absolute_path)
        raise ValueError(
            "strict model response violates original JSON schema "
            f"({specific.validator} at {path or '$'}: {specific.message})"
        ) from exc
