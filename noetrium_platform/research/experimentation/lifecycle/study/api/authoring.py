"""Pure Study authoring into the single NoetriumUnit semantic carrier."""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from .unit_semantics import study_unit_from_spec


def materialize_research_study_spec(value: object) -> NoetriumUnit:
    """Compile one author mapping directly to an immutable research.study Unit."""
    if not isinstance(value, Mapping):
        raise TypeError("research Study authoring requires a mapping")
    return study_unit_from_spec(value)


__all__ = ["materialize_research_study_spec"]
