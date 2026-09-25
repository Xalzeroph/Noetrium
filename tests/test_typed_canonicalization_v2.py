from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum, StrEnum
from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel.canonical import (
    CanonicalEncodingError,
    canonical_digest,
    canonical_text,
)


class Kind(Enum):
    A = "a"


@dataclass
class Payload:
    name: str
    hidden: str = field(default="ignored", metadata={"transient": True})


def test_canonicalization_is_deterministic_for_supported_values() -> None:
    left = {"set": {3, 1, 2}, "tuple": (Kind.A, b"abc"), "record": Payload("x")}
    right = {"record": Payload("x"), "tuple": (Kind.A, b"abc"), "set": {2, 3, 1}}
    assert canonical_text(left) == canonical_text(right)
    assert canonical_digest(left) == canonical_digest(right)


def test_canonicalization_rejects_non_finite_float_and_non_string_keys() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(CanonicalEncodingError):
            canonical_text(value)
    with pytest.raises(CanonicalEncodingError, match="string keys"):
        canonical_text({1: "x"})


def test_canonicalization_rejects_cycles_with_typed_error() -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    with pytest.raises(CanonicalEncodingError, match="cyclic"):
        canonical_text(cycle)


def test_canonicalization_enforces_explicit_depth_bound() -> None:
    value: object = "leaf"
    for _ in range(8):
        value = [value]
    with pytest.raises(CanonicalEncodingError, match="maximum depth"):
        canonical_text(value, max_depth=4)


def test_canonicalization_rejects_custom_objects() -> None:
    class Custom:
        pass

    with pytest.raises(CanonicalEncodingError, match="unsupported"):
        canonical_text(Custom())


def test_native_path_contract_is_not_claimed_portable() -> None:
    path = Path("root") / "child"
    assert canonical_text(path) == canonical_text(str(path))

def test_strict_json_decode_rejects_duplicates_nonfinite_and_bom() -> None:
    from noetrium_platform.foundation.kernel.kernel import (
        CanonicalDecodingError, CanonicalDecodingFailureKind, strict_json_loads,
    )

    assert strict_json_loads('{"a":[1,true,null]}') == {"a": [1, True, None]}
    with pytest.raises(CanonicalDecodingError) as duplicate:
        strict_json_loads('{"secret-key":1,"secret-key":2}')
    assert duplicate.value.kind is CanonicalDecodingFailureKind.DUPLICATE_KEY
    assert str(duplicate.value) == "canonical JSON contains duplicate object key"
    assert "secret-key" not in str(duplicate.value)
    for token in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(CanonicalDecodingError) as nonfinite:
            strict_json_loads('{"value":' + token + '}')
        assert nonfinite.value.kind is CanonicalDecodingFailureKind.NON_FINITE
        assert token not in str(nonfinite.value)
    with pytest.raises(CanonicalDecodingError) as bom:
        strict_json_loads(b"\xef\xbb\xbf{}")
    assert bom.value.kind is CanonicalDecodingFailureKind.BOM
    with pytest.raises(CanonicalDecodingError) as syntax:
        strict_json_loads('{"broken":')
    assert syntax.value.kind is CanonicalDecodingFailureKind.SYNTAX


def test_frozen_json_is_deeply_immutable_and_alias_free() -> None:
    from collections.abc import Mapping
    from noetrium_platform.foundation.kernel.kernel import freeze_json, thaw_json

    source = {"nested": {"items": [1, {"value": 2}]}}
    frozen = freeze_json(source)
    assert isinstance(frozen, Mapping)
    source["nested"]["items"][1]["value"] = 99
    assert thaw_json(frozen) == {"nested": {"items": [1, {"value": 2}]}}
    with pytest.raises(TypeError):
        frozen["new"] = 1  # type: ignore[index]
    nested = frozen["nested"]
    assert isinstance(nested, Mapping)
    items = nested["items"]
    assert isinstance(items, tuple)
    with pytest.raises(TypeError):
        items[0] = 3  # type: ignore[index]


def test_frozen_json_rejects_cycles_nonfinite_and_non_string_keys() -> None:
    from noetrium_platform.foundation.kernel.kernel import CanonicalEncodingError, freeze_json

    cycle: list[object] = []
    cycle.append(cycle)
    with pytest.raises(CanonicalEncodingError, match="cyclic"):
        freeze_json(cycle)  # type: ignore[arg-type]
    with pytest.raises(CanonicalEncodingError, match="non-finite"):
        freeze_json({"x": float("nan")})
    with pytest.raises(CanonicalEncodingError, match="string keys"):
        freeze_json({1: "x"})  # type: ignore[dict-item]


def test_sha256_digest_requires_canonical_lowercase_text() -> None:
    from noetrium_platform.foundation.kernel.kernel import DigestValidationError, Sha256Digest, require_sha256

    value = "a" * 64
    assert require_sha256(value, "content_sha256") == value
    assert str(Sha256Digest(value)) == value
    for invalid in ("A" * 64, " a" * 32, "a" * 63, "g" * 64):
        with pytest.raises(DigestValidationError, match="canonical lowercase"):
            require_sha256(invalid, "content_sha256")


def test_strict_finite_json_bytes_and_digest_form_kernel_authority_contract() -> None:
    import hashlib

    from noetrium_platform.foundation.kernel.kernel import strict_finite_json_bytes, strict_finite_json_digest

    values = (
        None,
        True,
        7,
        1.25,
        "text",
        {"b": [3, 2, 1], "a": {"nested": False}},
        ("tuple", {"x": 1}),
    )
    for value in values:
        encoded = strict_finite_json_bytes(value)
        assert strict_finite_json_digest(value) == hashlib.sha256(encoded).hexdigest()


def test_strict_finite_json_bytes_and_digest_match_data_overlap() -> None:
    from noetrium_platform.evidence.data._canonical import canonical_bytes as data_bytes, canonical_digest as data_digest
    from noetrium_platform.foundation.kernel.kernel import strict_finite_json_bytes, strict_finite_json_digest

    values = (
        None,
        True,
        7,
        1.25,
        "text",
        {"b": [3, 2, 1], "a": {"nested": False}},
        ("tuple", {"x": 1}),
    )
    for value in values:
        expected = strict_finite_json_bytes(value)
        digest = strict_finite_json_digest(value)
        assert data_bytes(value) == expected
        assert data_digest(value) == digest


def test_strict_finite_json_encoder_rejects_wider_canonical_domain() -> None:
    from noetrium_platform.foundation.kernel.kernel import (
        CanonicalEncodingError, strict_finite_json_bytes, strict_finite_json_digest,
    )

    class StringKind(StrEnum):
        A = "a"

    class NumberKind(IntEnum):
        A = 1

    invalid = (
        b"bytes", Path("root/child"), {1, 2}, frozenset({1}), Payload("x"),
        Kind.A, StringKind.A, NumberKind.A, {1: "x"}, float("nan"), float("inf"),
    )
    for encoder in (strict_finite_json_bytes, strict_finite_json_digest):
        for value in invalid:
            with pytest.raises(CanonicalEncodingError):
                encoder(value)

        cycle: list[object] = []
        cycle.append(cycle)
        with pytest.raises(CanonicalEncodingError, match="cyclic"):
            encoder(cycle)

        deep: object = "leaf"
        for _ in range(8):
            deep = [deep]
        with pytest.raises(CanonicalEncodingError, match="maximum depth"):
            encoder(deep, max_depth=4)


def test_freeze_json_rejects_enum_subclasses_even_when_they_are_json_scalars() -> None:
    from noetrium_platform.foundation.kernel.kernel import CanonicalEncodingError, freeze_json

    class StringKind(StrEnum):
        A = "a"

    class NumberKind(IntEnum):
        A = 1

    for value in (Kind.A, StringKind.A, NumberKind.A):
        with pytest.raises(CanonicalEncodingError, match="Enum"):
            freeze_json(value)  # type: ignore[arg-type]

def test_strict_json_decode_rejects_values_outside_canonical_domain() -> None:
    from noetrium_platform.foundation.kernel.kernel import (
        CanonicalDecodingError, CanonicalDecodingFailureKind, strict_json_loads,
    )

    deep = '"leaf"'
    for _ in range(140):
        deep = '[' + deep + ']'
    with pytest.raises(CanonicalDecodingError) as depth:
        strict_json_loads(deep)
    assert depth.value.kind is CanonicalDecodingFailureKind.DOMAIN
    assert str(depth.value) == "canonical JSON violates strict finite JSON domain"
    with pytest.raises(CanonicalDecodingError) as unicode_error:
        strict_json_loads('"\\ud800"')
    assert unicode_error.value.kind is CanonicalDecodingFailureKind.DOMAIN


def test_role01_consumers_do_not_reimplement_kernel_json_or_sha_primitives() -> None:
    portfolio = Path(__file__).resolve().parents[1] / "noetrium_platform/foundation/portfolio/api/contracts.py"
    leaf = Path(__file__).resolve().parents[1] / "noetrium_platform/foundation/kernel/kernel/leaf_contract.py"
    portfolio_source = portfolio.read_text(encoding="utf-8")
    leaf_source = leaf.read_text(encoding="utf-8")
    assert "_SHA256 =" not in portfolio_source
    assert "_reject_json_constant" not in portfolio_source
    assert "_unique_json_object" not in portfolio_source
    assert "json.loads(" not in portfolio_source
    assert "strict_finite_json_bytes" in portfolio_source
    assert "strict_finite_json_digest" in portfolio_source
    assert "strict_json_loads" in portfolio_source
    assert "hashlib.sha256" not in leaf_source
    assert "json.dumps(" not in leaf_source
