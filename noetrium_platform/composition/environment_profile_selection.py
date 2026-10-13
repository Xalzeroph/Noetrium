from __future__ import annotations

from collections.abc import Mapping
import re

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.product.research_unit import require_research_root
from noetrium_platform.product.research_traits import TRAIT_ENVIRONMENT

_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]*$")


def required_environment_categories(portfolio: NoetriumUnit) -> tuple[str, ...]:
    """Return the exact environment categories declared by a frozen portfolio."""
    require_research_root(portfolio)
    categories: set[str] = set()
    for graph in portfolio.walk():
        for definition in graph.symbols:
            if not definition.has_trait(TRAIT_ENVIRONMENT):
                continue
            config = definition.parameters
            if not isinstance(config, Mapping):
                raise ValueError(
                    f"environment definition {definition.symbol_id!r} requires mapping config"
                )
            category_id = config.get("category_id")
            if type(category_id) is not str or _TOKEN.fullmatch(category_id) is None:
                raise ValueError(
                    f"environment definition {definition.symbol_id!r} has invalid category_id"
                )
            categories.add(category_id)
    return tuple(sorted(categories))


def default_profiles_for_categories(
    catalog: Mapping[str, object],
    categories: tuple[str, ...],
) -> tuple[str, ...]:
    """Map categories to their unique active default profile, failing closed on drift."""
    if type(categories) is not tuple or any(
        type(value) is not str or _TOKEN.fullmatch(value) is None for value in categories
    ):
        raise TypeError("environment categories must be canonical token tuple")
    if tuple(sorted(set(categories))) != categories:
        raise ValueError("environment categories must be unique and canonically ordered")
    raw_profiles = catalog.get("profiles")
    if type(raw_profiles) is not list:
        raise ValueError("environment profile catalog profiles must be a list")

    selected: list[str] = []
    for category_id in categories:
        matches: list[str] = []
        for row in raw_profiles:
            if type(row) is not dict:
                raise ValueError("environment profile catalog entries must be objects")
            if row.get("category_id") != category_id:
                continue
            if row.get("lifecycle") != "active" or row.get("default_for_category") is not True:
                continue
            profile_id = row.get("profile_id")
            if type(profile_id) is not str or _TOKEN.fullmatch(profile_id) is None:
                raise ValueError(
                    f"environment category {category_id!r} has invalid default profile id"
                )
            matches.append(profile_id)
        if len(matches) != 1:
            raise RuntimeError(
                f"environment category {category_id!r} must have exactly one active default profile; "
                f"found {tuple(sorted(matches))!r}"
            )
        selected.append(matches[0])
    return tuple(sorted(set(selected)))


__all__ = [
    "default_profiles_for_categories",
    "required_environment_categories",
]
