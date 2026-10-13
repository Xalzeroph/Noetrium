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

from .json_value import JsonInput, JsonMutableValue, JsonObject, JsonValue


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
        "_required_depth",
        "_content_digest",
        "_content_entry_digests",
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
        self._required_depth: int | None = None
        self._content_digest: str | None = None
        self._content_entry_digests: dict[str, str] | None = None

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


def _frozen_json_required_depth(value: JsonValue) -> int:
    """Return exact remaining depth required by an already-frozen JSON value.

    Frozen objects are immutable and acyclic, so this structural fact is stable
    for their lifetime.  Caching it lets the same scientific payload be embedded
    at deeper Machine/Program layers without recursively revalidating the whole
    subtree on every wrapper, while preserving the exact max-depth contract.
    """
    if isinstance(value, _FrozenJsonObject):
        cached = value._required_depth
        if cached is not None:
            return cached
        if not value:
            required = 0
        else:
            required = 1 + max(
                _frozen_json_required_depth(item)
                for item in value.values()
            )
        value._required_depth = required
        return required
    if isinstance(value, tuple):
        if not value:
            return 0
        return 1 + max(_frozen_json_required_depth(item) for item in value)
    return 0



def _enter_recursive(value: object, active: set[int], *, depth: int, max_depth: int) -> int:
    """Enter a value already known to be recursive.

    Hot canonical paths know their exact container type before cycle checking;
    separating detection from entry avoids repeating ABC/dataclass dispatch for
    every dict/tuple in large Unit graphs.
    """
    if depth > max_depth:
        raise CanonicalEncodingError(f"canonical payload exceeds maximum depth {max_depth}")
    identity = id(value)
    if identity in active:
        raise CanonicalEncodingError("cyclic canonical payload is forbidden")
    active.add(identity)
    return identity


def _enter(value: object, active: set[int], *, depth: int, max_depth: int) -> int | None:
    value_type = type(value)
    if value_type in (dict, list, tuple, set, frozenset, MappingProxyType, _FrozenJsonObject):
        return _enter_recursive(value, active, depth=depth, max_depth=max_depth)
    recursive = isinstance(value, (Mapping, list, tuple, set, frozenset)) or (
        is_dataclass(value) and not isinstance(value, type)
    )
    if not recursive:
        return None
    return _enter_recursive(value, active, depth=depth, max_depth=max_depth)


def _normalize_frozen(
    value: _FrozenJsonObject,
    *,
    active: set[int],
    depth: int,
    max_depth: int,
) -> object:
    entered = _enter_recursive(value, active, depth=depth, max_depth=max_depth)
    try:
        remaining_depth = max_depth - depth
        cached_normalized = value._canonical_normalized
        validated_remaining = value._canonical_normalized_remaining_depth
        if (
            cached_normalized is not None
            and validated_remaining is not None
            and remaining_depth >= validated_remaining
        ):
            return cached_normalized
        required_depth = value._required_depth
        if required_depth is None and cached_normalized is not None:
            required_depth = _frozen_json_required_depth(value)
        if required_depth is not None:
            if remaining_depth < required_depth:
                raise CanonicalEncodingError(
                    f"canonical payload exceeds maximum depth {max_depth}"
                )
            if cached_normalized is not None:
                return cached_normalized
        rows = {
            key: _normalize(
                item,
                active=active,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for key, item in value.items()
        }
        value._cache_normalized(
            rows,
            validated_remaining_depth=remaining_depth,
        )
        return rows
    finally:
        active.remove(entered)


def _normalize(value: object, *, active: set[int], depth: int, max_depth: int) -> object:
    value_type = type(value)

    # Exact finite-JSON primitives dominate Unit canonicalization.  Dispatch on
    # exact type first; subclass/Enum compatibility stays in the cold fallback.
    if value is None or value_type is str or value_type is int or value_type is bool:
        return value
    if value_type is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalEncodingError("non-finite floats are forbidden in canonical payloads")
        return value
    if value_type is _FrozenJsonObject:
        return _normalize_frozen(
            value,
            active=active,
            depth=depth,
            max_depth=max_depth,
        )
    if value_type is bytes:
        return {"$bytes_sha256": hashlib.sha256(value).hexdigest(), "$bytes_size": len(value)}

    if value_type is dict or value_type is MappingProxyType:
        entered = _enter_recursive(value, active, depth=depth, max_depth=max_depth)
        try:
            rows: dict[str, object] = {}
            for key, item in value.items():
                if type(key) is not str and not isinstance(key, str):
                    raise CanonicalEncodingError("canonical mappings require string keys")
                rows[key] = _normalize(
                    item,
                    active=active,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            return rows
        finally:
            active.remove(entered)

    if value_type is tuple or value_type is list:
        entered = _enter_recursive(value, active, depth=depth, max_depth=max_depth)
        try:
            return [
                _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
                for item in value
            ]
        finally:
            active.remove(entered)

    if value_type is set or value_type is frozenset:
        entered = _enter_recursive(value, active, depth=depth, max_depth=max_depth)
        try:
            normalized = [
                _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
                for item in value
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
        finally:
            active.remove(entered)

    # Preserve historical subclass semantics on the cold path.
    if isinstance(value, (str, int, bool)):
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
        return str(value)

    entered = _enter(value, active, depth=depth, max_depth=max_depth)
    try:
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
            rows: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise CanonicalEncodingError("canonical mappings require string keys")
                rows[key] = _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
            return rows
        if isinstance(value, (set, frozenset)):
            normalized = [
                _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
                for item in tuple(value)
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
            return [
                _normalize(item, active=active, depth=depth + 1, max_depth=max_depth)
                for item in tuple(value)
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


def json_content_digest(value: object) -> str:
    """Deterministic Merkle root for finite JSON content.

    The digest is content-equivalent across processes and independent of
    execution history. Frozen objects cache per-field child roots so copy-on-
    write state updates rehash only changed values plus shallow parent maps.
    """

    if isinstance(value, _FrozenJsonObject):
        cached = value._content_digest
        if cached is not None:
            return cached
        entry_cache = (
            {}
            if value._content_entry_digests is None
            else dict(value._content_entry_digests)
        )
        digest = hashlib.sha256()
        digest.update(b"noetrium-json-merkle-v1\0object\0")
        digest.update(len(value).to_bytes(8, "big"))
        for key in sorted(value):
            key_bytes = key.encode("utf-8")
            digest.update(len(key_bytes).to_bytes(8, "big"))
            digest.update(key_bytes)
            child_digest = entry_cache.get(key)
            if child_digest is None:
                child_digest = json_content_digest(value[key])
                entry_cache[key] = child_digest
            digest.update(bytes.fromhex(child_digest))
        result = digest.hexdigest()
        value._content_entry_digests = entry_cache
        value._content_digest = result
        return result

    if isinstance(value, Mapping):
        digest = hashlib.sha256()
        digest.update(b"noetrium-json-merkle-v1\0object\0")
        digest.update(len(value).to_bytes(8, "big"))
        for key in sorted(value):
            if type(key) is not str:
                raise CanonicalEncodingError(
                    "JSON content digest requires string mapping keys"
                )
            key_bytes = key.encode("utf-8")
            digest.update(len(key_bytes).to_bytes(8, "big"))
            digest.update(key_bytes)
            digest.update(bytes.fromhex(json_content_digest(value[key])))
        return digest.hexdigest()

    if isinstance(value, (tuple, list)):
        digest = hashlib.sha256()
        digest.update(b"noetrium-json-merkle-v1\0array\0")
        digest.update(len(value).to_bytes(8, "big"))
        for item in value:
            digest.update(bytes.fromhex(json_content_digest(item)))
        return digest.hexdigest()

    payload = canonical_bytes(value)
    digest = hashlib.sha256()
    digest.update(b"noetrium-json-merkle-v1\0scalar\0")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
    return digest.hexdigest()


def freeze_json_object_reusing(
    base: Mapping[str, JsonValue],
    data: Mapping[str, JsonInput],
    *,
    changed_keys: frozenset[str],
) -> JsonObject:
    """Freeze one COW mapping while inheriting unchanged Merkle child roots."""

    if not isinstance(base, Mapping) or not isinstance(data, Mapping):
        raise TypeError("COW frozen object reuse requires mappings")
    if type(changed_keys) is not frozenset or any(
        type(key) is not str for key in changed_keys
    ):
        raise TypeError("changed_keys must be frozenset[str]")
    frozen = freeze_json(data)
    if not isinstance(frozen, _FrozenJsonObject):
        raise CanonicalEncodingError("frozen COW object must be JSON object")
    if isinstance(base, _FrozenJsonObject):
        cached = base._content_entry_digests
        if cached is not None:
            frozen._content_entry_digests = {
                key: digest
                for key, digest in cached.items()
                if key in frozen and key not in changed_keys
            }
    return frozen


def canonical_text(value: object, *, indent: int | None = None, max_depth: int = _DEFAULT_MAX_DEPTH) -> str:
    return canonical_bytes(value, indent=indent, max_depth=max_depth).decode("utf-8")


class _CanonicalDigestFastPathUnsupported(Exception):
    """Internal control flow for values outside the exact JSON hot path."""


def _canonical_digest_update(
    digest,
    value: object,
    *,
    active: set[int],
    depth: int,
    max_depth: int,
) -> None:
    """Stream canonical JSON bytes directly into SHA-256.

    For the exact finite-JSON domain dominating Unit construction this emits
    exactly the bytes produced by ``canonical_bytes`` while retaining only the
    recursion stack. Cold Python/container subclasses deliberately fall back to
    the existing encoder, preserving the public canonical domain.
    """

    value_type = type(value)
    if value is None:
        digest.update(b"null")
        return
    if value_type is bool:
        digest.update(b"true" if value else b"false")
        return
    if value_type is int:
        digest.update(str(value).encode("ascii"))
        return
    if value_type is str:
        digest.update(json.encoder.encode_basestring(value).encode("utf-8"))
        return
    if value_type is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalEncodingError(
                "non-finite floats are forbidden in canonical payloads"
            )
        digest.update(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        return
    if value_type is bytes:
        _canonical_digest_update(
            digest,
            {
                "$bytes_sha256": hashlib.sha256(value).hexdigest(),
                "$bytes_size": len(value),
            },
            active=active,
            depth=depth,
            max_depth=max_depth,
        )
        return

    if value_type is _FrozenJsonObject:
        remaining = max_depth - depth
        if remaining < _frozen_json_required_depth(value):
            raise CanonicalEncodingError(
                f"canonical payload exceeds maximum depth {max_depth}"
            )
        cached_bytes = value._canonical_bytes
        if cached_bytes is not None:
            digest.update(cached_bytes)
            return
        container = value
        is_mapping = True
    elif value_type is dict or value_type is MappingProxyType:
        if depth > max_depth:
            raise CanonicalEncodingError(
                f"canonical payload exceeds maximum depth {max_depth}"
            )
        container = value
        is_mapping = True
    elif value_type is tuple or value_type is list:
        if depth > max_depth:
            raise CanonicalEncodingError(
                f"canonical payload exceeds maximum depth {max_depth}"
            )
        container = value
        is_mapping = False
    else:
        raise _CanonicalDigestFastPathUnsupported

    entered: int | None = None
    if value_type is not _FrozenJsonObject:
        entered = id(container)
        if entered in active:
            raise CanonicalEncodingError("cyclic canonical payload is forbidden")
        active.add(entered)
    try:
        next_depth = depth + 1
        if is_mapping:
            digest.update(b"{")
            first = True
            for key in sorted(container):
                if type(key) is not str and not isinstance(key, str):
                    raise CanonicalEncodingError(
                        "canonical mappings require string keys"
                    )
                if first:
                    first = False
                else:
                    digest.update(b",")
                digest.update(json.encoder.encode_basestring(key).encode("utf-8"))
                digest.update(b":")
                item = container[key]
                item_type = type(item)
                if item is None:
                    digest.update(b"null")
                elif item_type is bool:
                    digest.update(b"true" if item else b"false")
                elif item_type is int:
                    digest.update(str(item).encode("ascii"))
                elif item_type is str:
                    digest.update(
                        json.encoder.encode_basestring(item).encode("utf-8")
                    )
                elif item_type is float:
                    if item != item or item in (float("inf"), float("-inf")):
                        raise CanonicalEncodingError(
                            "non-finite floats are forbidden in canonical payloads"
                        )
                    digest.update(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                else:
                    _canonical_digest_update(
                        digest,
                        item,
                        active=active,
                        depth=next_depth,
                        max_depth=max_depth,
                    )
            digest.update(b"}")
        else:
            digest.update(b"[")
            first = True
            for item in container:
                if first:
                    first = False
                else:
                    digest.update(b",")
                item_type = type(item)
                if item is None:
                    digest.update(b"null")
                elif item_type is bool:
                    digest.update(b"true" if item else b"false")
                elif item_type is int:
                    digest.update(str(item).encode("ascii"))
                elif item_type is str:
                    digest.update(
                        json.encoder.encode_basestring(item).encode("utf-8")
                    )
                elif item_type is float:
                    if item != item or item in (float("inf"), float("-inf")):
                        raise CanonicalEncodingError(
                            "non-finite floats are forbidden in canonical payloads"
                        )
                    digest.update(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                else:
                    _canonical_digest_update(
                        digest,
                        item,
                        active=active,
                        depth=next_depth,
                        max_depth=max_depth,
                    )
            digest.update(b"]")
    finally:
        if entered is not None:
            active.remove(entered)


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
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    digest = hashlib.sha256()
    try:
        _canonical_digest_update(
            digest, value, active=set(), depth=0, max_depth=max_depth
        )
    except _CanonicalDigestFastPathUnsupported:
        return hashlib.sha256(
            canonical_bytes(value, max_depth=max_depth)
        ).hexdigest()
    result = digest.hexdigest()
    if isinstance(value, _FrozenJsonObject):
        value._canonical_digest = result
        current = value._canonical_validated_max_depth
        if current is None or max_depth < current:
            value._canonical_validated_max_depth = max_depth
    return result


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

    value_type = type(value)
    if value is None or value_type is str or value_type is int or value_type is bool:
        return value
    if value_type is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalEncodingError("frozen JSON forbids non-finite floats")
        return value
    if value_type is _FrozenJsonObject:
        remaining = max_depth - depth
        if remaining >= value._validated_depth_limit:
            return value
        required_depth = _frozen_json_required_depth(value)
        if remaining < required_depth:
            raise CanonicalEncodingError(
                f"frozen JSON exceeds maximum depth {max_depth}"
            )
        value._validated_depth_limit = remaining
        return value

    if value_type is dict:
        container = value
        container_kind = "mapping"
    elif value_type is tuple:
        container = value
        container_kind = "tuple"
    elif value_type is list:
        container = value
        container_kind = "list"
    else:
        if isinstance(value, Enum):
            raise CanonicalEncodingError("strict finite JSON forbids Enum values")
        if isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise CanonicalEncodingError("frozen JSON forbids non-finite floats")
            return value
        if isinstance(value, _FrozenJsonObject):
            remaining = max_depth - depth
            if remaining >= value._validated_depth_limit:
                return value
            required_depth = _frozen_json_required_depth(value)
            if remaining < required_depth:
                raise CanonicalEncodingError(
                    f"frozen JSON exceeds maximum depth {max_depth}"
                )
            value._validated_depth_limit = remaining
            return value
        if isinstance(value, Mapping):
            container = value
            container_kind = "mapping"
        elif isinstance(value, tuple):
            container = value
            container_kind = "tuple-subclass"
        elif isinstance(value, list):
            container = value
            container_kind = "list"
        else:
            raise CanonicalEncodingError(
                f"unsupported {value_type.__name__} in frozen JSON"
            )

    identity = id(container)
    if identity in active:
        raise CanonicalEncodingError("cyclic frozen JSON is forbidden")
    active.add(identity)
    try:
        child_depth = depth + 1

        if container_kind == "mapping":
            frozen: dict[str, JsonValue] = {}
            for key, item in tuple(container.items()):
                if type(key) is not str and not isinstance(key, str):
                    raise CanonicalEncodingError(
                        "frozen JSON mappings require string keys"
                    )
                if child_depth > max_depth:
                    raise CanonicalEncodingError(
                        f"frozen JSON exceeds maximum depth {max_depth}"
                    )
                item_type = type(item)
                if (
                    item is None
                    or item_type is str
                    or item_type is int
                    or item_type is bool
                ):
                    frozen_item = item
                elif item_type is float:
                    if item != item or item in (float("inf"), float("-inf")):
                        raise CanonicalEncodingError(
                            "frozen JSON forbids non-finite floats"
                        )
                    frozen_item = item
                elif (
                    item_type is _FrozenJsonObject
                    and max_depth - child_depth >= item._validated_depth_limit
                ):
                    frozen_item = item
                else:
                    frozen_item = _freeze_json(
                        item,
                        active=active,
                        depth=child_depth,
                        max_depth=max_depth,
                    )
                frozen[key] = frozen_item
            return _FrozenJsonObject(
                frozen,
                validated_depth_limit=max_depth - depth,
                _token=_FROZEN_JSON_TOKEN,
            )

        if container_kind == "tuple":
            if container and child_depth > max_depth:
                raise CanonicalEncodingError(
                    f"frozen JSON exceeds maximum depth {max_depth}"
                )
            changed: list[JsonValue] | None = None
            for index, item in enumerate(container):
                item_type = type(item)
                if (
                    item is None
                    or item_type is str
                    or item_type is int
                    or item_type is bool
                ):
                    frozen_item = item
                elif item_type is float:
                    if item != item or item in (float("inf"), float("-inf")):
                        raise CanonicalEncodingError(
                            "frozen JSON forbids non-finite floats"
                        )
                    frozen_item = item
                elif (
                    item_type is _FrozenJsonObject
                    and max_depth - child_depth >= item._validated_depth_limit
                ):
                    frozen_item = item
                else:
                    frozen_item = _freeze_json(
                        item,
                        active=active,
                        depth=child_depth,
                        max_depth=max_depth,
                    )
                if changed is None:
                    if frozen_item is item:
                        continue
                    changed = list(container[:index])
                changed.append(frozen_item)
            return container if changed is None else tuple(changed)

        source = tuple(container)
        if source and child_depth > max_depth:
            raise CanonicalEncodingError(
                f"frozen JSON exceeds maximum depth {max_depth}"
            )
        frozen_items: list[JsonValue] = []
        all_same = container_kind == "tuple-subclass"
        for item in source:
            item_type = type(item)
            if (
                item is None
                or item_type is str
                or item_type is int
                or item_type is bool
            ):
                frozen_item = item
            elif item_type is float:
                if item != item or item in (float("inf"), float("-inf")):
                    raise CanonicalEncodingError(
                        "frozen JSON forbids non-finite floats"
                    )
                frozen_item = item
            elif (
                item_type is _FrozenJsonObject
                and max_depth - child_depth >= item._validated_depth_limit
            ):
                frozen_item = item
            else:
                frozen_item = _freeze_json(
                    item,
                    active=active,
                    depth=child_depth,
                    max_depth=max_depth,
                )
            frozen_items.append(frozen_item)
            if frozen_item is not item:
                all_same = False
        if all_same:
            return container
        return tuple(frozen_items)
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


def _native_strict_finite_json_impl(
    value: object,
    active: set[int],
    depth: int,
    max_depth: int,
) -> bool:
    """Positional recursive core for strict finite-JSON validation."""
    if depth > max_depth:
        raise CanonicalEncodingError(f"frozen JSON exceeds maximum depth {max_depth}")
    value_type = type(value)
    if value is None or value_type is bool or value_type is str or value_type is int:
        return True
    if value_type is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalEncodingError("frozen JSON forbids non-finite floats")
        return True
    if value_type is not dict and value_type is not list and value_type is not tuple:
        if isinstance(value, Enum):
            raise CanonicalEncodingError("strict finite JSON forbids Enum values")
        return False

    identity = id(value)
    if identity in active:
        raise CanonicalEncodingError("cyclic frozen JSON is forbidden")
    active.add(identity)
    try:
        native = True
        next_depth = depth + 1
        if value_type is dict:
            for key, item in value.items():
                if type(key) is not str:
                    if not isinstance(key, str):
                        raise CanonicalEncodingError(
                            "frozen JSON mappings require string keys"
                        )
                    native = False
                if next_depth > max_depth:
                    raise CanonicalEncodingError(
                        f"frozen JSON exceeds maximum depth {max_depth}"
                    )
                item_type = type(item)
                if (
                    item is None
                    or item_type is bool
                    or item_type is str
                    or item_type is int
                ):
                    continue
                if item_type is float:
                    if item != item or item in (float("inf"), float("-inf")):
                        raise CanonicalEncodingError(
                            "frozen JSON forbids non-finite floats"
                        )
                    continue
                if not _native_strict_finite_json_impl(
                    item, active, next_depth, max_depth
                ):
                    native = False
            return native

        if value and next_depth > max_depth:
            raise CanonicalEncodingError(
                f"frozen JSON exceeds maximum depth {max_depth}"
            )
        for item in value:
            item_type = type(item)
            if (
                item is None
                or item_type is bool
                or item_type is str
                or item_type is int
            ):
                continue
            if item_type is float:
                if item != item or item in (float("inf"), float("-inf")):
                    raise CanonicalEncodingError(
                        "frozen JSON forbids non-finite floats"
                    )
                continue
            if not _native_strict_finite_json_impl(
                item, active, next_depth, max_depth
            ):
                native = False
        return native
    finally:
        active.remove(identity)


def _native_strict_finite_json(
    value: object,
    *,
    active: set[int],
    depth: int,
    max_depth: int,
) -> bool:
    """Validate strict JSON and report whether CPython can encode it directly."""
    return _native_strict_finite_json_impl(
        value, active, depth, max_depth
    )


def strict_finite_json_bytes(value: object, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> bytes:
    """Encode only the narrow finite JSON domain used at scientific/public seams."""
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    if _native_strict_finite_json(
        value,
        active=set(),
        depth=0,
        max_depth=max_depth,
    ):
        mutable = value
    else:
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
    return hashlib.sha256(
        strict_finite_json_bytes(value, max_depth=max_depth)
    ).hexdigest()


__all__ = [
    "CanonicalDecodingError", "CanonicalDecodingFailureKind", "CanonicalEncodingError", "DigestValidationError",
    "Sha256Digest", "canonical_bytes", "canonical_digest", "canonical_text",
    "freeze_json", "freeze_json_object_reusing", "json_content_digest",
    "require_sha256", "strict_finite_json_bytes",
    "strict_finite_json_digest", "strict_finite_json_text", "strict_json_loads", "thaw_json",
]
