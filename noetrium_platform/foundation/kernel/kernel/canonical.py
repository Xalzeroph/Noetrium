from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import cast

from .json_value import JsonInput, JsonMutableValue, JsonValue


class CanonicalEncodingError(TypeError):
    """Value cannot be represented by the platform canonical JSON contract."""


class CanonicalDecodingFailureKind(StrEnum):
    BOM = "bom"
    DUPLICATE_KEY = "duplicate_key"
    NON_FINITE = "non_finite"
    SYNTAX = "syntax"
    DOMAIN = "domain"


_DECODING_MESSAGES = {
    CanonicalDecodingFailureKind.BOM: "canonical JSON contains forbidden UTF-8 BOM",
    CanonicalDecodingFailureKind.DUPLICATE_KEY: "canonical JSON contains duplicate object key",
    CanonicalDecodingFailureKind.NON_FINITE: "canonical JSON contains forbidden non-finite value",
    CanonicalDecodingFailureKind.SYNTAX: "canonical JSON cannot be decoded",
    CanonicalDecodingFailureKind.DOMAIN: "canonical JSON violates strict finite JSON domain",
}


class CanonicalDecodingError(ValueError):
    """Stable typed projection of strict platform JSON decode failures."""

    def __init__(self, kind: CanonicalDecodingFailureKind) -> None:
        self.kind = kind
        super().__init__(_DECODING_MESSAGES[kind])


_DEFAULT_MAX_DEPTH = 128
_CONTAINER_TYPES = (Mapping, list, tuple, set, frozenset)
_FROZEN_JSON_TOKEN = object()


class _FrozenJsonObject(Mapping[str, JsonValue]):
    """Trusted deeply-frozen JSON object produced only by freeze_json()."""

    __slots__ = (
        "_data",
        "_validated_depth_limit",
        "_canonical_bytes",
        "_canonical_digest",
        "_canonical_validated_max_depth",
        "_canonical_normalized",
        "_canonical_normalized_remaining_depth",
    )

    def __init__(
        self,
        data: dict[str, JsonValue],
        *,
        validated_depth_limit: int,
        _token: object,
    ) -> None:
        if _token is not _FROZEN_JSON_TOKEN:
            raise TypeError("frozen JSON objects are created only by freeze_json")
        self._data = MappingProxyType(data)
        self._validated_depth_limit = validated_depth_limit
        self._canonical_bytes: bytes | None = None
        self._canonical_digest: str | None = None
        self._canonical_validated_max_depth: int | None = None
        self._canonical_normalized: dict[str, object] | None = None
        self._canonical_normalized_remaining_depth: int | None = None

    def __getitem__(self, key: str) -> JsonValue:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def _cache_canonical(
        self,
        payload: bytes,
        *,
        validated_max_depth: int,
    ) -> None:
        self._canonical_bytes = payload
        self._canonical_digest = hashlib.sha256(payload).hexdigest()
        current = self._canonical_validated_max_depth
        if current is None or validated_max_depth < current:
            self._canonical_validated_max_depth = validated_max_depth


    def _cache_normalized(
        self,
        normalized: dict[str, object],
        *,
        validated_remaining_depth: int,
    ) -> None:
        self._canonical_normalized = normalized
        current = self._canonical_normalized_remaining_depth
        if current is None or validated_remaining_depth < current:
            self._canonical_normalized_remaining_depth = validated_remaining_depth


def _enter(value: object, active: set[int], *, depth: int, max_depth: int) -> int | None:
    if depth > max_depth:
        raise CanonicalEncodingError(f"canonical payload exceeds maximum depth {max_depth}")
    recursive = isinstance(value, _CONTAINER_TYPES) or (is_dataclass(value) and not isinstance(value, type))
    if not recursive:
        return None
    identity = id(value)
    if identity in active:
        raise CanonicalEncodingError("cyclic canonical payload is forbidden")
    active.add(identity)
    return identity


def _normalize(value: object, *, active: set[int], depth: int, max_depth: int) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalEncodingError("non-finite floats are forbidden in canonical payloads")
        return value
    if isinstance(value, Enum):
        return _normalize(value.value, active=active, depth=depth + 1, max_depth=max_depth)
    if isinstance(value, bytes):
        return {"$bytes_sha256": hashlib.sha256(value).hexdigest(), "$bytes_size": len(value)}
    if isinstance(value, Path):
        # Path stringification is deterministic only when callers already agree on
        # host/path flavor. Cross-machine scientific identities should pass an
        # explicitly normalized portable string rather than a native Path.
        return str(value)

    entered = _enter(value, active, depth=depth, max_depth=max_depth)
    try:
        if isinstance(value, _FrozenJsonObject):
            remaining_depth = max_depth - depth
            cached_normalized = value._canonical_normalized
            validated_remaining = value._canonical_normalized_remaining_depth
            if (
                cached_normalized is not None
                and validated_remaining is not None
                and remaining_depth >= validated_remaining
            ):
                return cached_normalized
            rows: dict[str, object] = {}
            for key, item in value.items():
                rows[key] = _normalize(
                    item,
                    active=active,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            value._cache_normalized(
                rows,
                validated_remaining_depth=remaining_depth,
            )
            return rows
        if is_dataclass(value) and not isinstance(value, type):
            snapshot = tuple(
                (field.name, getattr(value, field.name))
                for field in fields(value)
                if not field.metadata.get("transient", False)
            )
            return {
                name: _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
                for name, item in snapshot
            }
        if isinstance(value, Mapping):
            snapshot = tuple(value.items())
            rows: dict[str, object] = {}
            for key, item in snapshot:
                if not isinstance(key, str):
                    raise CanonicalEncodingError("canonical mappings require string keys")
                rows[key] = _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
            return rows
        if isinstance(value, (set, frozenset)):
            snapshot = tuple(value)
            normalized = [
                _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
                for item in snapshot
            ]
            return sorted(
                normalized,
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            )
        if isinstance(value, (tuple, list)):
            snapshot = tuple(value)
            return [
                _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
                for item in snapshot
            ]
        raise CanonicalEncodingError(f"unsupported canonical payload type: {type(value).__name__}")
    finally:
        if entered is not None:
            active.remove(entered)



def _reject_constant(_token: str) -> object:
    raise CanonicalDecodingError(CanonicalDecodingFailureKind.NON_FINITE)


def _object_from_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalDecodingError(CanonicalDecodingFailureKind.DUPLICATE_KEY)
        result[key] = value
    return result


def strict_json_loads(raw: str | bytes) -> JsonMutableValue:
    if isinstance(raw, bytes) and raw.startswith(b"\xef\xbb\xbf"):
        raise CanonicalDecodingError(CanonicalDecodingFailureKind.BOM)
    try:
        value = cast(
            JsonMutableValue,
            json.loads(
                raw,
                parse_constant=_reject_constant,
                object_pairs_hook=_object_from_pairs,
            ),
        )
    except CanonicalDecodingError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise CanonicalDecodingError(CanonicalDecodingFailureKind.SYNTAX) from exc
    try:
        strict_finite_json_bytes(value)
    except (CanonicalEncodingError, UnicodeEncodeError) as exc:
        raise CanonicalDecodingError(CanonicalDecodingFailureKind.DOMAIN) from exc
    return value

def canonical_bytes(
    value: object,
    *,
    indent: int | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> bytes:
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    kwargs: dict[str, object] = {
        "sort_keys": True,
        "ensure_ascii": False,
        "allow_nan": False,
    }
    if indent is None:
        kwargs["separators"] = (",", ":")
    else:
        kwargs["indent"] = indent
    if isinstance(value, _FrozenJsonObject) and indent is None:
        cached = value._canonical_bytes
        validated = value._canonical_validated_max_depth
        if (
            cached is not None
            and validated is not None
            and max_depth >= validated
        ):
            return cached
        normalized = _normalize(
            value,
            active=set(),
            depth=0,
            max_depth=max_depth,
        )
        payload = json.dumps(normalized, **kwargs).encode("utf-8")
        value._cache_canonical(
            payload,
            validated_max_depth=max_depth,
        )
        return payload
    normalized = _normalize(value, active=set(), depth=0, max_depth=max_depth)
    return json.dumps(normalized, **kwargs).encode("utf-8")


def canonical_text(value: object, *, indent: int | None = None, max_depth: int = _DEFAULT_MAX_DEPTH) -> str:
    return canonical_bytes(value, indent=indent, max_depth=max_depth).decode("utf-8")


def canonical_digest(value: object, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> str:
    if isinstance(value, _FrozenJsonObject):
        cached = value._canonical_digest
        validated = value._canonical_validated_max_depth
        if (
            cached is not None
            and validated is not None
            and max_depth >= validated
        ):
            return cached
        payload = canonical_bytes(value, max_depth=max_depth)
        digest = hashlib.sha256(payload).hexdigest()
        value._canonical_digest = digest
        return digest
    return hashlib.sha256(canonical_bytes(value, max_depth=max_depth)).hexdigest()


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class DigestValidationError(ValueError):
    """Digest text is not in the canonical representation required by Platform."""


def require_sha256(value: str, field: str = "sha256") -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise DigestValidationError(f"{field} must be canonical lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True, order=True)
class Sha256Digest:
    value: str

    def __post_init__(self) -> None:
        require_sha256(self.value, "digest")

    def __str__(self) -> str:
        return self.value


def _freeze_json(value: JsonInput, *, active: set[int], depth: int, max_depth: int) -> JsonValue:
    if depth > max_depth:
        raise CanonicalEncodingError(f"frozen JSON exceeds maximum depth {max_depth}")
    if isinstance(value, Enum):
        raise CanonicalEncodingError("strict finite JSON forbids Enum values")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalEncodingError("frozen JSON forbids non-finite floats")
        return value
    if isinstance(value, _FrozenJsonObject):
        remaining = max_depth - depth
        if remaining >= value._validated_depth_limit:
            return value
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEncodingError(
                    "frozen JSON mappings require string keys"
                )
            validated = _freeze_json(
                item,
                active=active,
                depth=depth + 1,
                max_depth=max_depth,
            )
            if validated is not item:
                raise CanonicalEncodingError(
                    "trusted frozen JSON contained a mutable descendant"
                )
        value._validated_depth_limit = remaining
        return value
    if not isinstance(value, (Mapping, list, tuple)):
        raise CanonicalEncodingError(f"unsupported {type(value).__name__} in frozen JSON")
    identity = id(value)
    if identity in active:
        raise CanonicalEncodingError("cyclic frozen JSON is forbidden")
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            frozen: dict[str, JsonValue] = {}
            for key, item in tuple(value.items()):
                if not isinstance(key, str):
                    raise CanonicalEncodingError("frozen JSON mappings require string keys")
                frozen[key] = _freeze_json(item, active=active, depth=depth + 1, max_depth=max_depth)
            return _FrozenJsonObject(
                frozen,
                validated_depth_limit=max_depth - depth,
                _token=_FROZEN_JSON_TOKEN,
            )
        source = tuple(value)
        frozen_items = tuple(
            _freeze_json(
                item,
                active=active,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for item in source
        )
        if isinstance(value, tuple) and all(
            frozen is original
            for frozen, original in zip(frozen_items, source, strict=True)
        ):
            return value
        return frozen_items
    finally:
        active.remove(identity)


def freeze_json(value: JsonInput, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> JsonValue:
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    return _freeze_json(value, active=set(), depth=0, max_depth=max_depth)


def thaw_json(value: JsonValue) -> JsonMutableValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def strict_finite_json_bytes(value: object, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> bytes:
    """Encode only the narrow finite JSON domain used at scientific/public seams."""
    frozen = freeze_json(cast(JsonInput, value), max_depth=max_depth)
    mutable = thaw_json(frozen)
    return json.dumps(
        mutable,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def strict_finite_json_text(value: object, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> str:
    return strict_finite_json_bytes(value, max_depth=max_depth).decode("utf-8")


def strict_finite_json_digest(value: object, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> str:
    return hashlib.sha256(strict_finite_json_bytes(value, max_depth=max_depth)).hexdigest()


__all__ = [
    "CanonicalDecodingError", "CanonicalDecodingFailureKind", "CanonicalEncodingError", "DigestValidationError",
    "Sha256Digest", "canonical_bytes", "canonical_digest", "canonical_text",
    "freeze_json", "require_sha256", "strict_finite_json_bytes",
    "strict_finite_json_digest", "strict_finite_json_text", "strict_json_loads", "thaw_json",
]
