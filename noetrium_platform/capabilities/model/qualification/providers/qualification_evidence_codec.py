"""Strict typed codec for durable model-qualification evidence."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
import types
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

from noetrium_platform.foundation.kernel.kernel import JsonDocument, canonical_bytes
from noetrium_platform.capabilities.model.qualification.api import DeploymentQualificationEvidenceRecord


T = TypeVar("T")


class QualificationEvidenceCodecError(ValueError):
    """Persisted qualification evidence does not match the current typed schema."""


def encode_qualification_record(record: DeploymentQualificationEvidenceRecord) -> dict[str, Any]:
    import json

    return json.loads(canonical_bytes(record).decode("utf-8"))


def decode_qualification_record(payload: JsonDocument) -> DeploymentQualificationEvidenceRecord:
    value = _decode_dataclass(DeploymentQualificationEvidenceRecord, payload, "record")
    if not isinstance(value, DeploymentQualificationEvidenceRecord):
        raise QualificationEvidenceCodecError("record decoded to an unexpected type")
    return value


def _decode_dataclass(cls: type[T], payload: JsonDocument, path: str) -> T:
    if type(payload) is not dict:
        raise QualificationEvidenceCodecError(f"{path} must be an object")
    hints = get_type_hints(cls)
    schema_fields = fields(cls)
    expected = {field.name for field in schema_fields}
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise QualificationEvidenceCodecError(
            f"{path} field set mismatch: missing={missing}, extra={extra}"
        )

    decoded = {
        field.name: _decode_value(hints[field.name], payload[field.name], f"{path}.{field.name}")
        for field in schema_fields
    }
    try:
        instance = cls(**{field.name: decoded[field.name] for field in schema_fields if field.init})
    except (TypeError, ValueError) as exc:
        raise QualificationEvidenceCodecError(f"{path} constructor validation failed") from exc

    for field in schema_fields:
        if field.init:
            continue
        if decoded[field.name] != getattr(instance, field.name):
            raise QualificationEvidenceCodecError(f"{path}.{field.name} derived value mismatch")
    return instance


def _decode_value(expected: object, value: object, path: str) -> object:
    origin = get_origin(expected)
    args = get_args(expected)

    if expected is Path:
        if type(value) is not str:
            raise QualificationEvidenceCodecError(f"{path} must be a path string")
        return Path(value)
    if isinstance(expected, type) and issubclass(expected, Enum):
        if type(value) is not str:
            raise QualificationEvidenceCodecError(f"{path} must be an enum string")
        try:
            return expected(value)
        except ValueError as exc:
            raise QualificationEvidenceCodecError(f"{path} has an invalid enum value") from exc
    if isinstance(expected, type) and is_dataclass(expected):
        return _decode_dataclass(expected, value, path)

    if origin is tuple:
        if type(value) is not list:
            raise QualificationEvidenceCodecError(f"{path} must be an array")
        if len(args) != 2 or args[1] is not Ellipsis:
            raise QualificationEvidenceCodecError(f"{path} has unsupported tuple typing")
        return tuple(_decode_value(args[0], item, f"{path}[{index}]") for index, item in enumerate(value))

    if origin in {types.UnionType, Union}:
        none_type = type(None)
        if value is None and none_type in args:
            return None
        choices = tuple(item for item in args if item is not none_type)
        if len(choices) != 1:
            raise QualificationEvidenceCodecError(f"{path} has unsupported union typing")
        return _decode_value(choices[0], value, path)

    if expected is bool:
        if type(value) is not bool:
            raise QualificationEvidenceCodecError(f"{path} must be a boolean")
        return value
    if expected is int:
        if type(value) is not int:
            raise QualificationEvidenceCodecError(f"{path} must be an integer")
        return value
    if expected is float:
        if type(value) is not float:
            raise QualificationEvidenceCodecError(f"{path} must be a float")
        return value
    if expected is str:
        if type(value) is not str:
            raise QualificationEvidenceCodecError(f"{path} must be a string")
        return value
    if expected is type(None):
        if value is not None:
            raise QualificationEvidenceCodecError(f"{path} must be null")
        return None

    raise QualificationEvidenceCodecError(f"{path} has unsupported type {expected!r}")


__all__ = [
    "QualificationEvidenceCodecError",
    "decode_qualification_record",
    "encode_qualification_record",
]
