"""Truth modalities for the universal NoetriumUnit carrier.

The carrier is unified; truth is not. A Unit may state a declaration, an
Authority decision, a provider observation, or evidence. These modalities are
deliberately non-interchangeable.
"""
from __future__ import annotations

from enum import StrEnum

from .unit import NoetriumUnit


class TruthModality(StrEnum):
    DECLARED = "declared"
    AUTHORIZED = "authorized"
    OBSERVED = "observed"
    EVIDENCED = "evidenced"


_MODALITY_ATTRIBUTE = "truth_modality"


def truth_modality(unit: NoetriumUnit) -> TruthModality | None:
    if type(unit) is not NoetriumUnit:
        raise TypeError("truth modality requires NoetriumUnit")
    value = unit.attribute(_MODALITY_ATTRIBUTE)
    return None if value is None else TruthModality(str(value))


def require_truth_modality(
    unit: NoetriumUnit,
    expected: TruthModality,
) -> NoetriumUnit:
    actual = truth_modality(unit)
    expected = TruthModality(expected)
    if actual is not expected:
        raise TypeError(
            f"unit {unit.unit_id!r} truth modality is "
            f"{None if actual is None else actual.value!r}, expected "
            f"{expected.value!r}"
        )
    return unit


def modal_attributes(
    modality: TruthModality,
    attributes: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build attributes with one explicit modality and no shadow declaration."""

    modality = TruthModality(modality)
    result = {} if attributes is None else dict(attributes)
    existing = result.get(_MODALITY_ATTRIBUTE)
    if existing is not None and TruthModality(str(existing)) is not modality:
        raise ValueError("conflicting truth modality")
    result[_MODALITY_ATTRIBUTE] = modality.value
    return result


__all__ = [
    "TruthModality",
    "modal_attributes",
    "require_truth_modality",
    "truth_modality",
]
