"""Versioned Minecraft recipe data adapters.

This module owns the boundary between external Minecraft data schemas and
Noetrium's typed planner. It intentionally does not import minecraft-data or
copy its files into the runtime: callers provide decoded data, which keeps the
environment contract provider-neutral and makes the data version explicit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .planning import MinecraftRecipe


def _rows(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        return list(value.values())
    return []


class MinecraftRecipeCatalog:
    """Lookup of all known recipe variants for each item."""

    def __init__(
        self,
        recipes: Mapping[str, Sequence[MinecraftRecipe] | MinecraftRecipe],
        *,
        edition: str = "pc",
        version: str = "",
        block_drops: Mapping[str, Sequence[tuple[str, int]]] | None = None,
    ) -> None:
        self.edition = str(edition)
        self.version = str(version)
        normalized: dict[str, tuple[MinecraftRecipe, ...]] = {}
        for item, value in recipes.items():
            candidates = (value,) if isinstance(value, MinecraftRecipe) else tuple(value)
            if not all(isinstance(recipe, MinecraftRecipe) for recipe in candidates):
                raise TypeError(f"recipe catalog entry {item!r} contains a non-recipe value")
            normalized[str(item)] = candidates
        self._recipes = normalized
        self._block_drops = {
            str(item): tuple((str(block), int(count)) for block, count in sources)
            for item, sources in (block_drops or {}).items()
        }

    def recipes_for(self, item: str) -> tuple[MinecraftRecipe, ...]:
        return self._recipes.get(str(item), ())

    def blocks_for(self, item: str) -> tuple[tuple[str, int], ...]:
        return self._block_drops.get(str(item), ())

    def items(self) -> tuple[str, ...]:
        return tuple(sorted(self._recipes))

    @classmethod
    def from_minecraft_data(
        cls,
        recipes_data: Mapping[str, Any],
        items_data: Sequence[Mapping[str, Any]] | Mapping[Any, Mapping[str, Any]],
        blocks_data: Sequence[Mapping[str, Any]] | Mapping[Any, Mapping[str, Any]],
        *,
        edition: str = "pc",
        version: str = "",
    ) -> "MinecraftRecipeCatalog":
        """Normalize minecraft-data Java or Bedrock-style decoded JSON."""

        names_by_id: dict[int, str] = {}
        for row in _rows(items_data):
            if isinstance(row, Mapping) and isinstance(row.get("id"), int) and row.get("name"):
                names_by_id[int(row["id"])] = str(row["name"])

        block_drops: dict[str, list[tuple[str, int]]] = {}
        for raw_block in _rows(blocks_data):
            if not isinstance(raw_block, Mapping) or not raw_block.get("name"):
                continue
            block_name = str(raw_block["name"])
            drops = raw_block.get("drops", ())
            for raw_drop in drops if isinstance(drops, (list, tuple)) else ():
                drop_count = 1
                drop_value = raw_drop
                if isinstance(raw_drop, Mapping):
                    drop_count = raw_drop.get("count", raw_drop.get("amount", 1))
                    drop_value = raw_drop.get("id", raw_drop.get("name"))
                if isinstance(drop_count, bool) or not isinstance(drop_count, int) or drop_count < 1:
                    continue
                item_name = cls._name(drop_value, names_by_id)
                if item_name:
                    block_drops.setdefault(item_name, []).append((block_name, drop_count))

        normalized: dict[str, list[MinecraftRecipe]] = {}
        for raw_item_id, raw_entries in recipes_data.items():
            entries = raw_entries if isinstance(raw_entries, (list, tuple)) else [raw_entries]
            fallback_item = cls._name(raw_item_id, names_by_id)
            for index, raw in enumerate(entries):
                if not isinstance(raw, Mapping):
                    continue
                result_value = raw.get("result", raw.get("output", raw_item_id))
                result_item, result_count = cls._result(result_value, fallback_item, names_by_id)
                if not result_item:
                    continue
                options = cls._ingredient_options(raw, names_by_id)
                ingredients = dict(cls._ingredient_counts(options))
                alternatives = tuple(option for option in options if len(option) > 1)
                recipe_type = str(raw.get("type", ""))
                process = "smelt" if recipe_type in {
                    "furnace", "blast_furnace", "smoker", "campfire", "soul_campfire",
                } else "craft"
                normalized.setdefault(result_item, []).append(
                    MinecraftRecipe(
                        item=result_item,
                        count=result_count,
                        ingredients=ingredients,
                        process=process,
                        ingredient_options=alternatives,
                        station=recipe_type or None,
                        recipe_id=str(raw.get("name") or f"{edition}:{version}:{raw_item_id}:{index}"),
                    )
                )
        return cls(
            normalized,
            edition=edition,
            version=version,
            block_drops=block_drops,
        )

    @staticmethod
    def _name(value: Any, names_by_id: Mapping[int, str]) -> str:
        if isinstance(value, Mapping):
            if value.get("name"):
                return str(value["name"])
            value = value.get("id")
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if isinstance(value, int):
            return names_by_id.get(value, f"id:{value}")
        if value is None:
            return ""
        return str(value)

    @classmethod
    def _result(cls, value: Any, fallback: str, names_by_id: Mapping[int, str]) -> tuple[str, int]:
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], (Mapping, list, tuple)):
            value = value[0]
        count = 1
        if isinstance(value, Mapping):
            count_value = value.get("count", value.get("amount", 1))
            count = int(count_value) if isinstance(count_value, int) and count_value > 0 else 1
        return cls._name(value, names_by_id) or fallback, count

    @classmethod
    def _ingredient_options(cls, raw: Mapping[str, Any], names_by_id: Mapping[int, str]) -> tuple[tuple[str, ...], ...]:
        values: Any = raw.get("inShape")
        if values is not None:
            values = [cell for row in values if isinstance(row, (list, tuple)) for cell in row]
        else:
            values = raw.get("ingredients", raw.get("input", ()))
        options: list[tuple[str, ...]] = []
        for value in values if isinstance(values, (list, tuple)) else ():
            parsed = cls._ingredient_option(value, names_by_id)
            if parsed:
                options.append(parsed)
        return tuple(options)

    @classmethod
    def _ingredient_option(cls, value: Any, names_by_id: Mapping[int, str]) -> tuple[str, ...]:
        if value is None or value == 0:
            return ()
        if isinstance(value, Mapping):
            choices = value.get("options", value.get("choices"))
            if isinstance(choices, (list, tuple)):
                return tuple(name for name in (cls._name(choice, names_by_id) for choice in choices) if name)
        if isinstance(value, (list, tuple)):
            return tuple(
                name
                for name in (cls._name(choice, names_by_id) for choice in value)
                if name and name != "id:0"
            )
        name = cls._name(value, names_by_id)
        return (name,) if name else ()

    @staticmethod
    def _ingredient_counts(options: Sequence[Sequence[str]]) -> tuple[tuple[str, int], ...]:
        counts: dict[str, int] = {}
        for option in options:
            if len(option) == 1:
                counts[option[0]] = counts.get(option[0], 0) + 1
        return tuple(counts.items())


__all__ = ["MinecraftRecipeCatalog"]
