from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.structure import structure_unit, symbol_unit

from noetrium_platform.composition.environment_profile_selection import (
    default_profiles_for_categories,
    required_environment_categories,
)


def _portfolio(*categories: str):
    definitions = tuple(
        symbol_unit(
            f"environment.{index}",
            traits=("research.environment",),
            parameters={
                "category_id": category,
                "capabilities": ("environment.act",),
            },
        )
        for index, category in enumerate(categories)
    )
    program = structure_unit(
        "paper",
        traits=("research.program",),
        symbols=definitions,
    )
    return structure_unit(
        "selection-test",
        traits=("research.portfolio",),
        members=(program,),
    )


def _catalog(*rows: dict[str, object]) -> dict[str, object]:
    return {"profiles": list(rows)}


def test_required_environment_categories_are_exact_and_canonical():
    assert required_environment_categories(_portfolio("web", "minecraft", "web")) == (
        "minecraft",
        "web",
    )


def test_default_profiles_select_only_required_categories():
    catalog = _catalog(
        {"profile_id": "minecraft", "category_id": "minecraft", "lifecycle": "active", "default_for_category": True},
        {"profile_id": "gui", "category_id": "gui", "lifecycle": "active", "default_for_category": True},
        {"profile_id": "web", "category_id": "web", "lifecycle": "active", "default_for_category": True},
    )
    assert default_profiles_for_categories(catalog, ("minecraft",)) == ("minecraft",)


def test_default_profiles_fail_closed_when_category_has_no_active_default():
    catalog = _catalog(
        {"profile_id": "minecraft-old", "category_id": "minecraft", "lifecycle": "draining", "default_for_category": True},
    )
    with pytest.raises(RuntimeError, match="exactly one active default"):
        default_profiles_for_categories(catalog, ("minecraft",))


def test_default_profiles_fail_closed_on_ambiguous_active_defaults():
    catalog = _catalog(
        {"profile_id": "minecraft-a", "category_id": "minecraft", "lifecycle": "active", "default_for_category": True},
        {"profile_id": "minecraft-b", "category_id": "minecraft", "lifecycle": "active", "default_for_category": True},
    )
    with pytest.raises(RuntimeError, match="exactly one active default"):
        default_profiles_for_categories(catalog, ("minecraft",))
