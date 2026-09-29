from __future__ import annotations

from collections.abc import Mapping
import re

from noetrium_platform.product.research_os import (
    ResearchDefinitionKind,
    ResearchPortfolio,
)

_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]*$")


def required_environment_categories(portfolio: ResearchPortfolio) -> tuple[str, ...]:
    """Return the exact environment categories declared by a frozen portfolio."""
    if type(portfolio) is not ResearchPortfolio:
        raise TypeError("environment selection requires ResearchPortfolio")
    categories: set[str] = set()
    for program in portfolio.programs:
        for definition in program.definitions:
            if definition.kind is not ResearchDefinitionKind.ENVIRONMENT:
                continue
            config = definition.config
            if not isinstance(config, Mapping):
                raise ValueError(
                    f"environment definition {definition.definition_id!r} requires mapping config"
                )
            category_id = config.get("category_id")
            if type(category_id) is not str or _TOKEN.fullmatch(category_id) is None:
                raise ValueError(
                    f"environment definition {definition.definition_id!r} has invalid category_id"
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
