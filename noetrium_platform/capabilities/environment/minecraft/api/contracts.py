from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType
from enum import StrEnum
import os
from pathlib import Path
import re
from typing import Any, Mapping, TypeAlias

from noetrium_platform.capabilities.environment.api.contracts import ActionReconciliationDisposition
from noetrium_platform.capabilities.environment.api.semantics import (
    environment_unit,
    require_environment_unit,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass, canonical_digest, freeze_json, is_absolute_target_path, thaw_json,
)
from noetrium_platform.substrate.api import ScopeKind, scope_kind
from noetrium_platform.foundation.kernel.record import RecordRole, record_unit
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit


MinecraftJsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | list["MinecraftJsonValue"]
    | dict[str, "MinecraftJsonValue"]
)


class MinecraftActionCategory(StrEnum):
    MOVEMENT = "movement"
    RESOURCE = "resource"
    INVENTORY = "inventory"
    COMBAT = "combat"
    INTERACTION = "interaction"
    OBSERVATION = "observation"


class MinecraftSideEffectDomain(StrEnum):
    """Authority-declared physical domains one action may affect."""

    MOVEMENT = "movement"
    EXCAVATION = "excavation"
    PLACEMENT = "placement"
    INVENTORY = "inventory"
    EQUIPMENT = "equipment"
    COMBAT = "combat"
    WORLD_LOADING = "world_loading"
    INTERACTION = "interaction"
    TIME = "time"
    CHAT = "chat"


class MinecraftActionOutcomeStatus(StrEnum):
    """Provider-neutral disposition of one accepted Minecraft command."""

    APPLIED = "applied"
    SATISFIED = "satisfied"
    PARTIAL = "partial"
    REJECTED = "rejected"


def _split_argument_contract_fields(value: str) -> tuple[str, ...]:
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError("Minecraft argument contract must be an object expression")
    body = text[1:-1].strip()
    if not body:
        return ()
    depth = 0
    start = 0
    rows: list[str] = []
    for index, char in enumerate(body):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("Minecraft argument contract braces are unbalanced")
        elif char == "," and depth == 0:
            row = body[start:index].strip()
            if not row:
                raise ValueError("Minecraft argument contract field is empty")
            rows.append(row)
            start = index + 1
    if depth != 0:
        raise ValueError("Minecraft argument contract braces are unbalanced")
    row = body[start:].strip()
    if not row:
        raise ValueError("Minecraft argument contract field is empty")
    rows.append(row)
    return tuple(rows)


def _numeric_contract_bound(value: str) -> int | float:
    raw = value.strip()
    if re.fullmatch(r"-?[0-9]+", raw):
        return int(raw)
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"Minecraft argument contract numeric bound is invalid: {raw!r}"
        ) from exc
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise ValueError("Minecraft argument contract numeric bound must be finite")
    return parsed


def _argument_value_schema(expression: str) -> dict[str, Any]:
    raw = expression.strip()
    if raw.startswith("{"):
        return dict(_argument_contract_schema(raw))
    if ".." in raw:
        pieces = raw.split("..")
        if len(pieces) != 2:
            raise ValueError("Minecraft argument contract range must have two bounds")
        lower = _numeric_contract_bound(pieces[0])
        upper = _numeric_contract_bound(pieces[1])
        if float(lower) > float(upper):
            raise ValueError("Minecraft argument contract range is inverted")
        integer = type(lower) is int and type(upper) is int
        return {
            "type": "integer" if integer else "number",
            "minimum": lower,
            "maximum": upper,
        }
    if "|" in raw:
        choices = tuple(part.strip() for part in raw.split("|"))
        if any(not choice for choice in choices) or len(set(choices)) != len(choices):
            raise ValueError("Minecraft argument contract enum is invalid")
        return {"type": "string", "enum": list(choices)}
    if raw in {"string", "integer", "number", "boolean"}:
        return {"type": raw}
    raise ValueError(f"unsupported Minecraft argument contract expression: {raw!r}")


@lru_cache(maxsize=128)
def _argument_contract_schema(argument_contract: str) -> Mapping[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for row in _split_argument_contract_fields(argument_contract):
        if ":" not in row:
            raise ValueError(f"Minecraft argument contract field lacks type: {row!r}")
        raw_name, expression = row.split(":", 1)
        raw_name = raw_name.strip()
        optional = raw_name.endswith("?")
        name = raw_name[:-1].strip() if optional else raw_name
        if re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
            raise ValueError(f"Minecraft argument contract field is invalid: {name!r}")
        if name in properties:
            raise ValueError(f"duplicate Minecraft argument contract field: {name}")
        properties[name] = _argument_value_schema(expression)
        if not optional:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    frozen = freeze_json(schema)
    if not isinstance(frozen, Mapping):
        raise TypeError("Minecraft argument contract schema must freeze to a mapping")
    return frozen


_MINECRAFT_ACTION_ARGUMENT_SEMANTICS: Mapping[str, Mapping[str, str]] = {
    "observe_blocks": {"query": "minecraft.block_name_query"},
    "registry_search": {"query": "minecraft.registry_name_query"},
    "goto_block": {"block": "minecraft.block_name"},
    "goto_entity": {"entity": "minecraft.entity_type"},
    "move_away": {"entity": "minecraft.entity_type"},
    "follow_player": {"player": "minecraft.player_name"},
    "collect_block": {
        "block": "minecraft.block_or_block_drop_name",
        "position": "minecraft.observed_exact_block_position",
    },
    "excavate_region": {
        "corner_a": "minecraft.observed_exact_block_position",
        "corner_b": "minecraft.observed_exact_block_position",
    },
    "pickup_items": {"item": "minecraft.observed_dropped_item_name"},
    "craft_item": {"item": "minecraft.item_name"},
    "recipe_lookup": {"item": "minecraft.item_name"},
    "recipe_dependencies": {"item": "minecraft.item_name"},
    "smelt_item": {
        "item": "minecraft.item_name",
        "fuel": "minecraft.item_name",
    },
    "enchant_item": {"item": "minecraft.item_name"},
    "place_block": {"item": "minecraft.block_or_item_name"},
    "equip_item": {"item": "minecraft.item_name"},
    "consume_item": {"item": "minecraft.item_name"},
    "discard_item": {"item": "minecraft.item_name"},
    "give_item": {
        "player": "minecraft.player_name",
        "item": "minecraft.item_name",
    },
    "chest_deposit": {"item": "minecraft.item_name"},
    "chest_withdraw": {"item": "minecraft.item_name"},
    "till_and_sow": {"seed": "minecraft.item_name"},
    "attack_nearest": {"entity": "minecraft.entity_type"},
    "attack_entity": {"entity_id": "minecraft.entity_id"},
    "attack_player": {"player": "minecraft.player_name"},
    "ranged_attack": {"entity": "minecraft.entity_type"},
    "fire_projectile": {"weapon": "minecraft.ranged_weapon_name"},
    "mount": {"entity": "minecraft.entity_type"},
    "activate_nearest_block": {"block": "minecraft.block_name"},
    "use_tool_on": {
        "target": "minecraft.block_or_entity_type",
        "target_type": "minecraft.object_kind",
    },
}

# Provider-owned semantic role of action arguments that name the item whose
# successful execution is intended to increase verified inventory.  These are
# planner-control semantics, not physical side-effect authority. Conditional
# exclusions keep alternate modes (for example exact block removal) truthful.
_MINECRAFT_ACTION_ARGUMENT_EFFECTS: Mapping[str, tuple[Mapping[str, Any], ...]] = MappingProxyType({
    "collect_block": ({
        "argument_path": ("block",),
        "role": "inventory_gain_target",
        "unless_arguments": ({"argument_path": ("effect",), "value": "remove"},),
    },),
    "craft_item": ({
        "argument_path": ("item",),
        "role": "inventory_gain_target",
    },),
    "pickup_items": ({
        "argument_path": ("item",),
        "role": "inventory_gain_target",
    },),
    "chest_withdraw": ({
        "argument_path": ("item",),
        "role": "inventory_gain_target",
    },),
})


_MINECRAFT_ACTION_APPLICABILITY: Mapping[str, tuple[str, ...]] = {
    "equip_item": (
        "item must already exist in the latest verified inventory; equipping never creates or crafts the item",
        "destination must match one of the exact enum values in argument_schema; omitting it selects the codec default",
        "use an inventory observation to resolve current equipment after an indeterminate prior effect",
    ),
    "observe_entities": (
        "returns only currently visible entities in bounded observation distance",
        "an empty result does not prove the entity type is absent outside loaded/visible world",
    ),
    "goto_block": (
        "block must denote a Minecraft block type, never an entity or inventory-only item",
        "the provider searches the live world and navigates into block interaction range",
    ),
    "goto_entity": (
        "entity must denote a Minecraft entity type, never a block or item",
        "the target must be currently observable within max_distance",
    ),
    "move_away": (
        "when entity is provided, distance is measured relative to a currently observed entity",
        "when entity is omitted, the provider creates distance from the current position along a navigable direction",
    ),
    "collect_block": (
        "block must denote a Minecraft block type or an item name obtainable as a block drop",
        "without position, the provider finds matching observed blocks and collects up to the requested count",
        "with position, the provider acts only on that exact observed block, requires count=1, and never substitutes another target",
        "effect=remove requires an exact observed block and confirms physical removal without requiring an inventory drop; never silently remove surrounding blocks",
        "the provider verifies reachability and break safety; effect=collect additionally requires harvestability and pickup, stopping on uncertain or absent progress",
    ),
    "excavate_region": (
        "corner_a and corner_b define one explicit loaded-world axis-aligned region selected by the Agent; the provider never expands or redirects it toward a resource",
        "the region is structurally bounded and every non-air block must pass the same physical break-safety oracle before the first removal",
        "each removed block executes as an individually authorized collect_block(effect=remove) child with its own durable effect identity",
        "max_blocks bounds physical removals; reaching the bound with remaining blocks is partial progress, not implicit permission to continue",
    ),
    "pickup_items": (
        "with item, only the exact name confirmed by observed dropped-item metadata may be targeted",
        "unknown drop identities are skipped; a registry entry does not establish a live nearby drop",
        "without item, nearby drops are collected in distance order as before",
        "max_items bounds observed item entities rather than number of items in a stack",
    ),
    "craft_item": (
        "item must denote an inventory item",
        "required ingredients must already exist in the verified inventory; recipe_lookup returns only reference knowledge",
        "the provider may automatically place and try to reclaim a carried crafting table when none is observed nearby, and verifies the exact placed station",
        "recipe/material knowledge is not assumed unless established by execution evidence",
    ),
    "smelt_item": (
        "item and fuel are inventory item types",
        "input, fuel and a reachable furnace are verified before smelting",
    ),
    "place_block": (
        "item must be placeable from inventory as a block",
        "when position is omitted, the provider selects among immediately adjacent replaceable positions with safe solid support using the same Pathfinder placement engine",
    ),
    "attack_nearest": (
        "entity must denote a Minecraft entity type",
    ),
    "ranged_attack": (
        "entity must denote a Minecraft entity type",
    ),
    "fire_projectile": (
        "fires a physically held bow or crossbow along the current facing direction without selecting or requiring a target",
        "weapon optionally constrains the exact bow or crossbow; omitting it allows the local executor to choose an available compatible ranged weapon",
        "successful use is proven by bounded release evidence and physical ammunition consumption, never by an assumed hit",
    ),
    "mount": (
        "entity must identify one currently observed Minecraft entity type",
        "the provider does not infer rideability from a hand-maintained entity list; the physical mount result is authoritative",
    ),
    "use_tool_on": (
        "target_type=entity requires an entity target; target_type=block requires a block target",
        "when target_type is omitted the provider classifies the target from the runtime registry",
    ),
    "observe_blocks": (
        "returns bounded live-world block observations from currently loaded world state",
        "query filters canonical block names but does not turn registry existence into observed presence",
        "position selects one exact loaded block-grid coordinate for O(1) inspection; it is exclusive with query/limit and never loads or navigates to an unseen chunk",
    ),
    "registry_search": (
        "use this observation action to distinguish canonical item, block and entity names",
    ),
    "craft_grid": (
        "inventory station has 4 comma-separated grid entries in row-major order; table has 9 entries",
        "use _ for blank cells and canonical inventory item names for materials",
        "this action tests a proposed grid against the physical server and never reveals an unknown recipe beforehand",
        "only a server output-slot packet and a verified inventory increase may prove production",
    ),
    "recipe_dependencies": (
        "combine only vanilla reference recipes with the latest observed inventory quantities",
        "recursive missing inputs are a reference suggestion, not a verified task plan",
        "unavailable crafting recipes may still have mining, loot, trading, smelting, or hidden datapack acquisition",
        "do not assume any item or block is available until observed and physically acquired",
    ),
    "recipe_lookup": (
        "lookup uses only the version-pinned vanilla Minecraft crafting catalog",
        "server datapacks, hidden rules, current inventory, and executable task plans are not inspected",
        "a missing crafting recipe does not imply that an item cannot be smelted or acquired by other means",
    ),
}


@dataclass(frozen=True, slots=True)
class MinecraftPlannerActionContract:
    """Serializable planner view of one exact MC action capability."""

    action_type: str
    category: str
    description: str
    arguments: str
    argument_schema: Mapping[str, Any]
    mutates_world: bool
    may_move_actor: bool
    argument_semantics: Mapping[str, str] = field(default_factory=dict)
    argument_effects: tuple[Mapping[str, Any], ...] = ()
    applicability: tuple[str, ...] = ()
    syntax_examples: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.argument_schema, Mapping):
            raise TypeError("Minecraft planner argument_schema must be a mapping")
        if not isinstance(self.argument_semantics, Mapping):
            raise TypeError("Minecraft planner argument_semantics must be a mapping")
        if type(self.argument_effects) is not tuple or any(
            not isinstance(row, Mapping) for row in self.argument_effects
        ):
            raise TypeError("Minecraft planner argument_effects must be an object tuple")
        if type(self.applicability) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.applicability
        ):
            raise TypeError("Minecraft planner applicability must be a text tuple")
        if type(self.syntax_examples) is not tuple or any(
            not isinstance(row, Mapping) for row in self.syntax_examples
        ):
            raise TypeError("Minecraft planner syntax_examples must be a tuple of objects")
        object.__setattr__(self, "syntax_examples", tuple(
            freeze_json(dict(row)) for row in self.syntax_examples
        ))
        object.__setattr__(
            self,
            "argument_schema",
            freeze_json(dict(self.argument_schema)),
        )
        object.__setattr__(
            self,
            "argument_semantics",
            freeze_json(dict(self.argument_semantics)),
        )
        object.__setattr__(
            self,
            "argument_effects",
            tuple(freeze_json(dict(row)) for row in self.argument_effects),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "category": self.category,
            "description": self.description,
            "arguments": self.arguments,
            "argument_schema": self.argument_schema,
            "argument_semantics": self.argument_semantics,
            "argument_effects": self.argument_effects,
            "applicability": self.applicability,
            "mutates_world": self.mutates_world,
            # Compact decision truth derived from the same Authority envelope
            # used for runtime enforcement.  It tells the planner that a skill
            # may own actor movement, avoiding redundant pre-navigation without
            # exposing the full physical-domain handbook on every turn.
            "may_move_actor": self.may_move_actor,
            "syntax_examples": self.syntax_examples,
            "examples_are_public_syntax_not_world_evidence": True,
        }


MINECRAFT_ACTION_TRAIT = "environment.minecraft-action"


# Sole authority for per-action physical side-effect domains.  The provider
# receives this compiled envelope from the ActionSpec Unit; it must never infer
# effect permissions from handler/module names.
_MINECRAFT_ACTION_SIDE_EFFECTS: Mapping[str, tuple[MinecraftSideEffectDomain, ...]] = MappingProxyType({
    "goto": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "goto_block": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "goto_entity": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "move_away": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "follow_player": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.TIME),
    "stay": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.TIME),
    "collect_block": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EXCAVATION, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "excavate_region": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EXCAVATION, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING),
    "craft_item": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EXCAVATION, MinecraftSideEffectDomain.PLACEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "craft_grid": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "smelt_item": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.TIME),
    "enchant_item": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "clear_furnace": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "place_block": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.PLACEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "pickup_items": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING),
    "auto_light": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.PLACEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "equip_item": (MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT),
    "consume_item": (MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT),
    "discard_item": (MinecraftSideEffectDomain.INVENTORY,),
    "give_item": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING),
    "chest_inspect": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "chest_deposit": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "chest_withdraw": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "till_and_sow": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EXCAVATION, MinecraftSideEffectDomain.PLACEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.WORLD_LOADING),
    "attack_nearest": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.COMBAT, MinecraftSideEffectDomain.WORLD_LOADING),
    "attack_entity": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.COMBAT, MinecraftSideEffectDomain.WORLD_LOADING),
    "attack_player": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.COMBAT, MinecraftSideEffectDomain.WORLD_LOADING),
    "ranged_attack": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.COMBAT, MinecraftSideEffectDomain.WORLD_LOADING),
    "fire_projectile": (MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.COMBAT, MinecraftSideEffectDomain.TIME),
    "defend_self": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.COMBAT, MinecraftSideEffectDomain.WORLD_LOADING),
    "use_shield": (MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.COMBAT, MinecraftSideEffectDomain.TIME),
    "fish": (MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.TIME),
    "mount": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.INTERACTION),
    "dismount": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INTERACTION),
    "use_door": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.WORLD_LOADING),
    "go_to_bed": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.WORLD_LOADING, MinecraftSideEffectDomain.TIME),
    "activate_nearest_block": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.WORLD_LOADING),
    "show_villager_trades": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.WORLD_LOADING),
    "trade_villager": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.WORLD_LOADING),
    "use_tool_on": (MinecraftSideEffectDomain.MOVEMENT, MinecraftSideEffectDomain.INVENTORY, MinecraftSideEffectDomain.EQUIPMENT, MinecraftSideEffectDomain.INTERACTION, MinecraftSideEffectDomain.WORLD_LOADING),
    "wait": (MinecraftSideEffectDomain.TIME,),
    "chat": (MinecraftSideEffectDomain.CHAT,),
    "observe_blocks": (),
    "observe_entities": (),
    "registry_search": (),
    "recipe_lookup": (),
    "recipe_dependencies": (),
    "describe_action": (),
})


def minecraft_action_unit(
    action_type: str,
    category: MinecraftActionCategory,
    mutates_world: bool,
    description: str,
    argument_contract: str,
    timeout_multiplier: float = 1.0,
    *,
    effect_class: EffectClass | None = None,
    required_actions: tuple[str, ...] = (),
    optional_actions: tuple[str, ...] = (),
    syntax_examples: tuple[Mapping[str, Any], ...] = (),
) -> NoetriumUnit:
    if (
        re.fullmatch(r"[a-z][a-z0-9_]*", action_type) is None
        or not description.strip()
        or not argument_contract.strip()
        or isinstance(timeout_multiplier, bool)
        or not isinstance(timeout_multiplier, (int, float))
        or float(timeout_multiplier) < 1.0
    ):
        raise ValueError("Minecraft action specification is invalid")
    if not isinstance(category, MinecraftActionCategory):
        raise TypeError("Minecraft action category must be typed")
    if type(mutates_world) is not bool:
        raise TypeError("Minecraft action mutates_world must be boolean")
    resolved_effect_class = (
        EffectClass.RECONCILABLE if mutates_world else EffectClass.PURE
    ) if effect_class is None else effect_class
    if not isinstance(resolved_effect_class, EffectClass):
        raise TypeError("Minecraft action effect_class must be EffectClass")
    if mutates_world and resolved_effect_class is EffectClass.PURE:
        raise ValueError("Minecraft mutating action cannot declare PURE effect semantics")
    try:
        side_effects = _MINECRAFT_ACTION_SIDE_EFFECTS[action_type]
    except KeyError as exc:
        raise ValueError(
            "Minecraft action must declare an authoritative side-effect envelope"
        ) from exc
    if any(not isinstance(domain, MinecraftSideEffectDomain) for domain in side_effects):
        raise TypeError("Minecraft side-effect envelope must use typed domains")
    if resolved_effect_class is EffectClass.PURE and side_effects:
        raise ValueError("PURE Minecraft action cannot declare physical side effects")
    if resolved_effect_class is not EffectClass.PURE and not side_effects:
        raise ValueError("Effectful Minecraft action must declare a side-effect envelope")
    if (
        type(required_actions) is not tuple
        or any(type(name) is not str or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
               for name in required_actions)
        or len(set(required_actions)) != len(required_actions)
        or action_type in required_actions
    ):
        raise ValueError("Minecraft required child capabilities must be unique typed actions")
    if (
        type(optional_actions) is not tuple
        or any(type(name) is not str or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
               for name in optional_actions)
        or len(set(optional_actions)) != len(optional_actions)
        or action_type in optional_actions
        or set(optional_actions).intersection(required_actions)
    ):
        raise ValueError("Minecraft optional child capabilities must be disjoint typed actions")
    if type(syntax_examples) is not tuple or any(
        not isinstance(row, Mapping) for row in syntax_examples
    ):
        raise ValueError("Minecraft action syntax examples must be typed objects")
    return structure_unit(
        action_type,
        traits=(MINECRAFT_ACTION_TRAIT,),
        parameters={
            "category": category.value,
            "mutates_world": mutates_world,
            "effect_class": resolved_effect_class.value,
            "side_effect_envelope": tuple(domain.value for domain in side_effects),
            "description": description,
            "argument_contract": argument_contract,
            "timeout_multiplier": float(timeout_multiplier),
            "required_actions": required_actions,
            "optional_actions": optional_actions,
            "syntax_examples": tuple(dict(row) for row in syntax_examples),
        },
    )


def require_minecraft_action(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(MINECRAFT_ACTION_TRAIT)
    ):
        raise TypeError("Minecraft action semantics must be NoetriumUnit")
    return value


def minecraft_action_type(value: NoetriumUnit) -> str:
    return require_minecraft_action(value).unit_id


def minecraft_action_category(value: NoetriumUnit) -> MinecraftActionCategory:
    return MinecraftActionCategory(
        str(require_minecraft_action(value).parameters["category"])
    )


def minecraft_action_mutates_world(value: NoetriumUnit) -> bool:
    return bool(require_minecraft_action(value).parameters["mutates_world"])


def minecraft_action_effect_class(value: NoetriumUnit) -> EffectClass:
    """Return replay/recovery semantics declared by the authoritative action Unit."""
    return EffectClass(str(require_minecraft_action(value).parameters["effect_class"]))


def minecraft_action_side_effect_envelope(
    value: NoetriumUnit,
) -> tuple[MinecraftSideEffectDomain, ...]:
    raw = require_minecraft_action(value).parameters["side_effect_envelope"]
    if type(raw) is not tuple:
        raise TypeError("Minecraft action side-effect envelope must be tuple")
    return tuple(MinecraftSideEffectDomain(str(domain)) for domain in raw)


def minecraft_action_description(value: NoetriumUnit) -> str:
    return str(require_minecraft_action(value).parameters["description"])


def minecraft_action_argument_contract(value: NoetriumUnit) -> str:
    return str(require_minecraft_action(value).parameters["argument_contract"])


def minecraft_action_required_actions(value: NoetriumUnit) -> tuple[str, ...]:
    """The sole Unit-native declaration of a composite action's capability closure."""
    row = require_minecraft_action(value).parameters["required_actions"]
    return tuple(str(name) for name in row)


def minecraft_action_optional_actions(value: NoetriumUnit) -> tuple[str, ...]:
    """Conditionally invoked effects from the same authoritative Unit catalog."""
    row = require_minecraft_action(value).parameters["optional_actions"]
    return tuple(str(name) for name in row)


def minecraft_action_syntax_examples(value: NoetriumUnit) -> tuple[Mapping[str, Any], ...]:
    raw = require_minecraft_action(value).parameters["syntax_examples"]
    return tuple(thaw_json(row) for row in raw)


def minecraft_action_timeout_multiplier(value: NoetriumUnit) -> float:
    return float(require_minecraft_action(value).parameters["timeout_multiplier"])


def _planner_argument_schema(
    action_type: str,
    argument_contract: str,
) -> Mapping[str, Any]:
    raw_schema = _argument_contract_schema(argument_contract)
    semantics = _MINECRAFT_ACTION_ARGUMENT_SEMANTICS.get(action_type, {})
    properties = {
        str(name): dict(value) if isinstance(value, Mapping) else value
        for name, value in dict(raw_schema.get("properties", {})).items()
    }
    for name, semantic_type in semantics.items():
        raw = properties.get(name)
        if isinstance(raw, Mapping):
            annotated = dict(raw)
            annotated["description"] = f"Semantic domain: {semantic_type}"
            properties[name] = annotated
    schema = dict(raw_schema)
    schema["properties"] = properties
    frozen = freeze_json(schema)
    if not isinstance(frozen, Mapping):
        raise TypeError("Minecraft planner argument schema must be a mapping")
    return frozen


def minecraft_action_planner_contract(
    value: NoetriumUnit,
) -> MinecraftPlannerActionContract:
    value = require_minecraft_action(value)
    action_type = minecraft_action_type(value)
    argument_contract = minecraft_action_argument_contract(value)
    return MinecraftPlannerActionContract(
        action_type=action_type,
        category=minecraft_action_category(value).value,
        description=minecraft_action_description(value),
        arguments=argument_contract,
        argument_schema=_planner_argument_schema(
            action_type,
            argument_contract,
        ),
        mutates_world=minecraft_action_mutates_world(value),
        may_move_actor=(
            MinecraftSideEffectDomain.MOVEMENT
            in minecraft_action_side_effect_envelope(value)
        ),
        argument_semantics=_MINECRAFT_ACTION_ARGUMENT_SEMANTICS.get(
            action_type,
            {},
        ),
        argument_effects=_MINECRAFT_ACTION_ARGUMENT_EFFECTS.get(action_type, ()),
        applicability=_MINECRAFT_ACTION_APPLICABILITY.get(action_type, ()),
        syntax_examples=minecraft_action_syntax_examples(value),
    )


MINECRAFT_ACTION_SPECS: tuple[NoetriumUnit, ...] = (
    minecraft_action_unit("goto", MinecraftActionCategory.MOVEMENT, True, "Navigate to world coordinates.", "{position:{x:number,y:number,z:number}, radius?:0.1..64}", 2.0),
    minecraft_action_unit("goto_block", MinecraftActionCategory.MOVEMENT, True, "Navigate to a loaded exact block type without excavating or placing blocks; buried targets may need separately authorized excavation.", "{block:string, max_distance?:1..128}", 2.0),
    minecraft_action_unit("goto_entity", MinecraftActionCategory.MOVEMENT, True, "Navigate near a visible entity.", "{entity:string, max_distance?:1..128, radius?:1..16}", 2.0),
    minecraft_action_unit("move_away", MinecraftActionCategory.MOVEMENT, True, "Create distance from the current position or an observed entity.", "{distance?:1..64, entity?:string, max_distance?:1..128}", 2.0),
    minecraft_action_unit("follow_player", MinecraftActionCategory.MOVEMENT, True, "Follow a visible player for a bounded interval and verify progress.", "{player:string, duration_s?:1..60, distance?:1..16, max_distance?:1..128}", 3.0),
    minecraft_action_unit("stay", MinecraftActionCategory.MOVEMENT, True, "Remain within a bounded area for a cancellable interval, actively stopping motion at the interval boundaries.", "{duration_s?:1..60}"),
    minecraft_action_unit("collect_block", MinecraftActionCategory.RESOURCE, True, "Use the same safe physical dig engine for resource collection or exact controlled removal. collect (default) obtains up to count additional physically verified items (not a final inventory total); tool optionally constrains the exact already-held harvesting tool instead of letting the local controller choose one; effect=remove requires one observed block position and confirms its removal even without a drop. Never substitute a pinned target, choose a route to excavate, or craft tools on behalf of the Agent.", "{block:string, count?:1..64, max_distance?:4..128, tool?:string, position?:{x:integer,y:integer,z:integer}, effect?:collect|remove}", 4.0),
    minecraft_action_unit("excavate_region", MinecraftActionCategory.RESOURCE, True, "Safely clear one Agent-selected, currently loaded axis-aligned region as a bounded local excavation skill; never select a destination, resource goal, hidden route, or tool-acquisition plan. Every removed block is a separately identified collect_block(effect=remove) child effect.", "{corner_a:{x:integer,y:integer,z:integer}, corner_b:{x:integer,y:integer,z:integer}, max_blocks?:1..32, max_distance?:4..64}", 5.0, required_actions=("collect_block",)),
    minecraft_action_unit("craft_item", MinecraftActionCategory.RESOURCE, True, "Craft one item from verified inventory; use an observed workbench or conditionally place a carried workbench only when the Method authorizes the place_block child effect.", "{item:string, count?:1..64}", 2.0, optional_actions=("place_block",), syntax_examples=({"item":"oak_planks","count":4},)),
    minecraft_action_unit("craft_grid", MinecraftActionCategory.RESOURCE, True, "Experiment with an explicit 2x2 or 3x3 crafting grid. Represent blank slots with _ and entries as comma-separated item names; never predict a hidden recipe. Only server-acknowledged result slots and inventory deltas prove output.", "{grid:string, station:inventory|table, max_distance?:1..128}", 3.0),
    minecraft_action_unit("smelt_item", MinecraftActionCategory.RESOURCE, True, "Smelt inventory input in a nearby furnace with bounded waiting.", "{item:string, count?:1..8, fuel?:string, max_distance?:1..128, max_wait_s?:10..180}", 4.0),
    minecraft_action_unit("enchant_item", MinecraftActionCategory.RESOURCE, True, "Enchant one inventory item at a nearby enchanting table with an available server-provided choice.", "{item:string, choice?:0..2, max_distance?:1..32}", 3.0),
    minecraft_action_unit("clear_furnace", MinecraftActionCategory.RESOURCE, True, "Take all input, fuel and output from a nearby furnace.", "{max_distance?:1..128}", 2.0),
    minecraft_action_unit("place_block", MinecraftActionCategory.RESOURCE, True, "Place an inventory block at an optional exact position.", "{item:string, position?:{x:number,y:number,z:number}}", 2.0),
    minecraft_action_unit("pickup_items", MinecraftActionCategory.RESOURCE, True, "Approach a bounded number of nearby observed dropped-item entities and verify inventory gain. Optionally select an exact observed item name; unknown identities are skipped, not guessed. max_items limits entities, not stack quantity.", "{max_distance?:1..64, max_items?:1..32, item?:string}", 3.0),
    minecraft_action_unit("auto_light", MinecraftActionCategory.RESOURCE, True, "Place one torch when the bounded local area lacks lighting.", "{max_distance?:1..16}"),
    minecraft_action_unit("equip_item", MinecraftActionCategory.INVENTORY, True, "Equip an inventory item to an equipment destination.", "{item:string, destination?:hand|off-hand|head|torso|legs|feet}"),
    minecraft_action_unit("consume_item", MinecraftActionCategory.INVENTORY, True, "Consume one usable food, potion or similar inventory item.", "{item:string}"),
    minecraft_action_unit("discard_item", MinecraftActionCategory.INVENTORY, True, "Drop an exact count from inventory.", "{item:string, count?:1..64}"),
    minecraft_action_unit("give_item", MinecraftActionCategory.INVENTORY, True, "Move near a visible player and drop items to them.", "{player:string, item:string, count?:1..64}", 2.0),
    minecraft_action_unit("chest_inspect", MinecraftActionCategory.INVENTORY, True, "Inspect the nearest chest, trapped chest or barrel; reaching and opening the container is a physical interaction even though the contents are read-only.", "{max_distance?:1..128}", 2.0),
    minecraft_action_unit("chest_deposit", MinecraftActionCategory.INVENTORY, True, "Deposit an exact item count into a nearby container.", "{item:string, count?:1..64, max_distance?:1..128}", 2.0),
    minecraft_action_unit("chest_withdraw", MinecraftActionCategory.INVENTORY, True, "Withdraw an exact item count from a nearby container.", "{item:string, count?:1..64, max_distance?:1..128}", 2.0),
    minecraft_action_unit("till_and_sow", MinecraftActionCategory.INVENTORY, True, "Till a nearby soil block and sow a selected seed.", "{seed:string, max_distance?:1..32}"),
    minecraft_action_unit("attack_nearest", MinecraftActionCategory.COMBAT, True, "Attack the nearest visible entity matching a name.", "{entity:string, max_distance?:1..128, max_hits?:1..20}", 2.0),
    minecraft_action_unit("attack_entity", MinecraftActionCategory.COMBAT, True, "Attack one visible entity by numeric entity ID.", "{entity_id:integer, max_distance?:1..128, max_hits?:1..40}", 2.0),
    minecraft_action_unit("attack_player", MinecraftActionCategory.COMBAT, True, "Attack one visible player by exact username.", "{player:string, max_distance?:1..128, max_hits?:1..40}", 2.0),
    minecraft_action_unit("ranged_attack", MinecraftActionCategory.COMBAT, True, "Fire a bow or crossbow at a visible entity using provider-derived charge timing and trajectory physics.", "{entity:string, max_distance?:1..128, shots?:1..8}", 2.0),
    minecraft_action_unit("fire_projectile", MinecraftActionCategory.COMBAT, True, "Physically fire a held bow or crossbow along the current facing direction without selecting a target; prove use from bounded release and ammunition evidence, not hit inference.", "{weapon?:bow|crossbow, shots?:1..8}", 1.5),
    minecraft_action_unit("defend_self", MinecraftActionCategory.COMBAT, True, "Engage bounded hostile mobs near the bot.", "{radius?:1..32, max_targets?:1..16, max_hits?:1..40}", 3.0),
    minecraft_action_unit("use_shield", MinecraftActionCategory.COMBAT, True, "Equip an available shield in the off hand, raise it for a bounded interval, and verify the local use state before releasing it.", "{duration_ms?:100..10000}"),
    minecraft_action_unit("fish", MinecraftActionCategory.RESOURCE, True, "Fish with a rod for a bounded number of catches.", "{casts?:1..8, max_wait_s?:10..120}", 4.0),
    minecraft_action_unit("mount", MinecraftActionCategory.INTERACTION, True, "Approach one explicitly selected visible entity and request mounting; capability is verified from the resulting vehicle state.", "{entity:string, max_distance?:1..32}"),
    minecraft_action_unit("dismount", MinecraftActionCategory.INTERACTION, True, "Leave the current vehicle and verify the vehicle state.", "{}"),
    minecraft_action_unit("use_door", MinecraftActionCategory.INTERACTION, True, "Open a nearby door and verify its open state.", "{max_distance?:1..32}"),
    minecraft_action_unit("go_to_bed", MinecraftActionCategory.INTERACTION, True, "Navigate to a nearby bed and request sleep.", "{max_distance?:1..64, max_wait_s?:10..60}", 2.0),
    minecraft_action_unit("activate_nearest_block", MinecraftActionCategory.INTERACTION, True, "Activate one nearby button, lever, trapdoor or interactive block.", "{block:string, max_distance?:1..32}"),
    minecraft_action_unit("show_villager_trades", MinecraftActionCategory.INTERACTION, True, "Navigate to a nearby adult employed villager and inspect its trade list; movement and opening the interaction window are physical effects even though the trade data is read-only.", "{max_distance?:1..32}"),
    minecraft_action_unit("trade_villager", MinecraftActionCategory.INTERACTION, True, "Execute a bounded trade with a nearby villager after resource checks.", "{trade_index:integer, max_trades?:1..16, max_distance?:1..32}"),
    minecraft_action_unit("use_tool_on", MinecraftActionCategory.INTERACTION, True, "Use the equipped item on a nearby block or entity and verify the call.", "{target:string, target_type?:block|entity, max_distance?:1..32}"),
    minecraft_action_unit("wait", MinecraftActionCategory.INTERACTION, False, "Wait for a bounded duration.", "{ms?:0..10000}", effect_class=EffectClass.RECONCILABLE),
    minecraft_action_unit("chat", MinecraftActionCategory.INTERACTION, True, "Send one Minecraft chat message.", "{message:string}"),
    minecraft_action_unit("observe_blocks", MinecraftActionCategory.OBSERVATION, False, "Observe bounded live-world blocks by filtered scan or inspect one exact loaded coordinate without navigation or chunk loading.", "{query?:string, position?:{x:integer,y:integer,z:integer}, max_distance?:1..128, limit?:1..100}", syntax_examples=({"query": "oak_log", "max_distance": 16, "limit": 12}, {"position":{"x":2,"y":64,"z":0},"max_distance":16})),
    minecraft_action_unit("observe_entities", MinecraftActionCategory.OBSERVATION, False, "Refresh bounded nearby entity observations.", "{max_distance?:1..128, limit?:1..100}"),
    minecraft_action_unit("registry_search", MinecraftActionCategory.OBSERVATION, False, "Look up declared Minecraft item, block and entity registry names only; this is not a live-world search, does not locate or grant a physical object, and never establishes inventory possession.", "{query:string, limit?:1..100}", syntax_examples=({"query": "plank", "limit": 8},)),
    minecraft_action_unit("recipe_lookup", MinecraftActionCategory.OBSERVATION, False, "Query version-pinned vanilla crafting recipes as public reference knowledge only. Never reveals active datapack or hidden-world changes; does not inspect inventory or generate a task plan.", "{item:string, limit?:1..100}"),
    minecraft_action_unit("recipe_dependencies", MinecraftActionCategory.OBSERVATION, False, "Read a public vanilla crafting dependency tree for an item and its currently observed inventory shortages. Returns reference-only ingredients, batch counts, alternative recipes and uncraftable leaves; no hidden datapack rules or physical goal claims.", "{item:string, count?:1..64}", syntax_examples=({"item":"stick","count":4},)),
    minecraft_action_unit("describe_action", MinecraftActionCategory.OBSERVATION, False, "Inspect one currently authorized action's complete on-demand handbook: exact argument Schema, applicability, prerequisites, physical-success tests, two contextual few-shot examples, two prohibited or mistaken counterexamples, and failure recovery. Reference examples are conditional, not automatically executable and never reveal current hidden-world state.", "{action_type:string}"),
)

MINECRAFT_ACTION_SPEC_BY_TYPE = {minecraft_action_type(spec): spec for spec in MINECRAFT_ACTION_SPECS}
if len(MINECRAFT_ACTION_SPEC_BY_TYPE) != len(MINECRAFT_ACTION_SPECS):
    raise RuntimeError("Minecraft action specification contains duplicate action types")
MINECRAFT_ACTION_TYPES: frozenset[str] = frozenset(MINECRAFT_ACTION_SPEC_BY_TYPE)
if frozenset(_MINECRAFT_ACTION_SIDE_EFFECTS) != MINECRAFT_ACTION_TYPES:
    missing = sorted(MINECRAFT_ACTION_TYPES.difference(_MINECRAFT_ACTION_SIDE_EFFECTS))
    extra = sorted(set(_MINECRAFT_ACTION_SIDE_EFFECTS).difference(MINECRAFT_ACTION_TYPES))
    raise RuntimeError(
        f"Minecraft side-effect envelope catalog drift: missing={missing}, extra={extra}"
    )


def _compile_minecraft_required_action_closures() -> Mapping[str, frozenset[str]]:
    """Validate and freeze every transitive required-action closure once.

    The action catalog is immutable for the lifetime of this module. Rewalking
    the same graph on every Agent action adds work without adding authority.
    DFS colors also reject indirect cycles at catalog construction time.
    """
    closures: dict[str, frozenset[str]] = {}
    visiting: set[str] = set()

    def visit(action_type: str) -> frozenset[str]:
        cached = closures.get(action_type)
        if cached is not None:
            return cached
        if action_type in visiting:
            raise RuntimeError("Cyclic Minecraft skill capability graph")
        visiting.add(action_type)
        required: set[str] = set()
        for dependency in minecraft_action_required_actions(
            MINECRAFT_ACTION_SPEC_BY_TYPE[action_type]
        ):
            if dependency not in MINECRAFT_ACTION_SPEC_BY_TYPE:
                raise RuntimeError(f"Unknown nested Minecraft capability: {dependency}")
            required.add(dependency)
            required.update(visit(dependency))
        visiting.remove(action_type)
        frozen = frozenset(required)
        closures[action_type] = frozen
        return frozen

    for action_type in MINECRAFT_ACTION_TYPES:
        visit(action_type)
    return MappingProxyType(closures)


_MINECRAFT_REQUIRED_ACTION_CLOSURES = _compile_minecraft_required_action_closures()


def minecraft_action_required_closure(action_type: str) -> frozenset[str]:
    """Return the precompiled immutable transitive required-capability closure."""
    try:
        return _MINECRAFT_REQUIRED_ACTION_CLOSURES[action_type]
    except KeyError as exc:
        raise ValueError(
            "Minecraft action is not defined by the authoritative catalog"
        ) from exc


def minecraft_action_unavailable_dependencies(
    action_type: str,
    allowed_action_types: frozenset[str],
) -> tuple[str, ...]:
    """Fail closed when a composite would use a capability hidden from a paper."""
    required = minecraft_action_required_closure(action_type)
    return tuple(sorted(required.difference(allowed_action_types)))


for _minecraft_action_name in MINECRAFT_ACTION_TYPES:
    for _minecraft_optional_child in minecraft_action_optional_actions(
        MINECRAFT_ACTION_SPEC_BY_TYPE[_minecraft_action_name]
    ):
        if _minecraft_optional_child not in MINECRAFT_ACTION_TYPES:
            raise RuntimeError("Minecraft optional child capability is not in Unit catalog")


@dataclass(frozen=True, slots=True)
class MinecraftEndpointSpec:
    """Operational network location for one MC environment instance."""

    host: str = "127.0.0.1"
    port: int | None = None

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("Minecraft endpoint host is required")
        if self.port is not None and (
            type(self.port) is not int or not 1 <= self.port <= 65535
        ):
            raise ValueError("Minecraft endpoint port must be between 1 and 65535")

    @property
    def bound_port(self) -> int:
        if self.port is None:
            raise RuntimeError(
                "Minecraft endpoint is not Resource-bound to a physical port"
            )
        return self.port


@dataclass(frozen=True, slots=True)
class MinecraftAgentSpec:
    """Scientific agent conditions independent of the server's network address."""

    username: str = "ResearchBot"
    auth: str = "offline"
    version: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", self.username):
            raise ValueError(
                "Minecraft agent username must match [A-Za-z0-9_]{3,16}"
            )
        if not self.auth.strip():
            raise ValueError("Minecraft agent username and auth are required")


@dataclass(frozen=True, slots=True)
class MinecraftBridgeSpec:
    """Frozen bridge process contract; server lifecycle is owned elsewhere."""

    command: tuple[str, ...]
    cwd: str
    action_recovery_root: str | None = None
    connect_timeout_s: float = 45.0
    command_timeout_s: float = 45.0
    stdout_queue_capacity: int = 4096

    def __post_init__(self) -> None:
        if not self.command or any(not item.strip() for item in self.command):
            raise ValueError("Minecraft bridge command must be non-empty")
        if not self.cwd.strip():
            raise ValueError("Minecraft bridge cwd must be non-empty")
        if self.action_recovery_root is not None and (
            not self.action_recovery_root.strip()
            or not is_absolute_target_path(self.action_recovery_root)
        ):
            raise ValueError("Minecraft bridge action_recovery_root must be absolute when provided")
        if min(self.connect_timeout_s, self.command_timeout_s) <= 0:
            raise ValueError("Minecraft bridge timeouts must be positive")
        if self.stdout_queue_capacity <= 0:
            raise ValueError("Minecraft bridge stdout_queue_capacity must be positive")


MINECRAFT_ENVIRONMENT_TRAIT = "environment.minecraft"


def minecraft_environment_unit(
    environment_id: str,
    revision: str,
    *,
    agent_username: str = "ResearchBot",
    agent_auth: str = "offline",
    agent_version: str = "",
    implementation_version: str = "1",
    abi_version: str = "1",
    schema_version: str = "1",
    provider_id: str = "minecraft.mineflayer.jsonl.v1",
    max_entities: int = 256,
    entity_observation_distance: int = 32,
    allowed_action_types: tuple[str, ...] | None = None,
    visible_state_fields: tuple[str, ...] | None = None,
) -> NoetriumUnit:
    for name, value in (
        ("environment_id", environment_id),
        ("revision", revision),
        ("agent_username", agent_username),
        ("agent_auth", agent_auth),
        ("implementation_version", implementation_version),
        ("abi_version", abi_version),
        ("schema_version", schema_version),
        ("provider_id", provider_id),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"Minecraft environment {name} must be non-empty")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", agent_username):
        raise ValueError("Minecraft agent username must match [A-Za-z0-9_]{3,16}")
    if max_entities < 1:
        raise ValueError("Minecraft environment max_entities must be positive")
    if not 4 <= entity_observation_distance <= 128:
        raise ValueError(
            "Minecraft entity_observation_distance must be in [4, 128]"
        )
    if allowed_action_types is not None:
        if (type(allowed_action_types) is not tuple
            or any(type(name) is not str for name in allowed_action_types)
            or len(allowed_action_types) != len(set(allowed_action_types))
            or not set(allowed_action_types).issubset(MINECRAFT_ACTION_TYPES)):
            raise ValueError("Minecraft allowed_action_types must be a subset of the action catalog")
    if visible_state_fields is not None:
        if (
            type(visible_state_fields) is not tuple
            or any(
                type(name) is not str
                or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
                for name in visible_state_fields
            )
            or len(visible_state_fields) != len(set(visible_state_fields))
        ):
            raise ValueError("Minecraft visible_state_fields must be distinct canonical state names")
    base = environment_unit(
        environment_id,
        category="minecraft",
        revision=revision,
        capabilities=("minecraft.world",),
        parameters={
            "agent_username": agent_username,
            "agent_auth": agent_auth,
            "agent_version": agent_version,
            "implementation_version": implementation_version,
            "abi_version": abi_version,
            "schema_version": schema_version,
            "provider_id": provider_id,
            "max_entities": max_entities,
            "entity_observation_distance": entity_observation_distance,
            **(
                {} if allowed_action_types is None else
                {"allowed_action_types": tuple(sorted(allowed_action_types))}
            ),
            **(
                {} if visible_state_fields is None else
                {"visible_state_fields": tuple(sorted(visible_state_fields))}
            ),
        },
    )
    return structure_unit(
        base.unit_id,
        traits=tuple(sorted(set(base.traits + (MINECRAFT_ENVIRONMENT_TRAIT,)))),
        parameters=base.parameters,
        members=base.members,
    )


def require_minecraft_environment(value: NoetriumUnit) -> NoetriumUnit:
    value = require_environment_unit(value)
    if (
        value.parameters["category"] != "minecraft"
        or not value.has_trait(MINECRAFT_ENVIRONMENT_TRAIT)
    ):
        raise TypeError("Minecraft environment must be environment.minecraft Unit")
    return value


def minecraft_environment_revision(value: NoetriumUnit) -> str:
    return str(require_minecraft_environment(value).parameters["revision"])


def minecraft_environment_implementation_version(value: NoetriumUnit) -> str:
    return str(
        require_minecraft_environment(value).parameters["implementation_version"]
    )


def minecraft_environment_abi_version(value: NoetriumUnit) -> str:
    return str(require_minecraft_environment(value).parameters["abi_version"])


def minecraft_environment_schema_version(value: NoetriumUnit) -> str:
    return str(require_minecraft_environment(value).parameters["schema_version"])


def minecraft_environment_provider_id(value: NoetriumUnit) -> str:
    return str(require_minecraft_environment(value).parameters["provider_id"])


def minecraft_environment_max_entities(value: NoetriumUnit) -> int:
    return int(require_minecraft_environment(value).parameters["max_entities"])


def minecraft_environment_entity_observation_distance(value: NoetriumUnit) -> int:
    return int(
        require_minecraft_environment(value).parameters[
            "entity_observation_distance"
        ]
    )


def minecraft_environment_allowed_action_types(value: NoetriumUnit) -> frozenset[str]:
    environment = require_minecraft_environment(value)
    values = environment.parameters.get("allowed_action_types")
    return (
        MINECRAFT_ACTION_TYPES if values is None
        else frozenset(str(value) for value in values)
    )


def minecraft_environment_visible_state_fields(value: NoetriumUnit) -> frozenset[str] | None:
    environment = require_minecraft_environment(value)
    names = environment.parameters.get("visible_state_fields")
    return None if names is None else frozenset(str(name) for name in names)


def minecraft_environment_agent(value: NoetriumUnit) -> "MinecraftAgentSpec":
    value = require_minecraft_environment(value)
    return MinecraftAgentSpec(
        username=str(value.parameters["agent_username"]),
        auth=str(value.parameters["agent_auth"]),
        version=str(value.parameters["agent_version"]),
    )


def minecraft_environment_scientific_identity_digest(value: NoetriumUnit) -> str:
    return require_minecraft_environment(value).unit_digest


@dataclass(frozen=True, slots=True)
class MinecraftEnvironmentRuntimeBinding:
    """Physical runtime binding derived from Authority-owned endpoint/process facts."""

    endpoint: MinecraftEndpointSpec
    bridge: MinecraftBridgeSpec

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, MinecraftEndpointSpec):
            raise TypeError("Minecraft runtime endpoint must be MinecraftEndpointSpec")
        if not isinstance(self.bridge, MinecraftBridgeSpec):
            raise TypeError("Minecraft runtime bridge must be MinecraftBridgeSpec")

    @property
    def operational_binding_digest(self) -> str:
        return canonical_digest({"endpoint": self.endpoint, "bridge": self.bridge})


@dataclass(frozen=True, slots=True)
class MinecraftSessionRuntimeIdentity:
    """MC-owned session runtime identity exposed before participant binding."""

    runtime_id: str
    runtime_version: str
    abi_version: str
    artifact_digest: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.runtime_id, self.runtime_version, self.abi_version, self.artifact_digest)
        ):
            raise ValueError("Minecraft session runtime identity fields must be non-empty")


@dataclass(frozen=True, slots=True)
class MinecraftServerSpec:
    """Immutable vanilla-server configuration; it owns no process lifecycle."""

    jar_path: str
    workdir: str
    java_executable: str
    libraries_dir: str | None = None
    host: str = "127.0.0.1"
    port: int | None = None
    level_name: str = "research-world"
    level_seed: str = "NOETRIUM_FIXED_WORLD_V1"
    online_mode: bool = False
    xms: str = "512M"
    xmx: str = "2G"
    rcon_endpoint: MinecraftRconEndpoint | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("jar_path", self.jar_path),
            ("workdir", self.workdir),
            ("java_executable", self.java_executable),
        ):
            if not value.strip() or not is_absolute_target_path(value):
                raise ValueError(f"Minecraft server {name} must be an absolute path")
        if self.libraries_dir is not None and (
            not self.libraries_dir.strip() or not is_absolute_target_path(self.libraries_dir)
        ):
            raise ValueError("Minecraft server libraries_dir must be an absolute path when provided")
        if not self.host.strip():
            raise ValueError("Minecraft server host is invalid")
        if self.port is not None and (
            type(self.port) is not int or not 1 <= self.port <= 65535
        ):
            raise ValueError("Minecraft server port is invalid")
        if (
            not self.level_name.strip()
            or "/" in self.level_name
            or "\\" in self.level_name
            or not self.level_seed.strip()
        ):
            raise ValueError("Minecraft server level identity is invalid")
        if not self.xms.strip() or not self.xmx.strip():
            raise ValueError("Minecraft server heap sizes must be non-empty")

    @property
    def bound_port(self) -> int:
        if self.port is None:
            raise RuntimeError(
                "Minecraft server is not Resource-bound to a physical port"
            )
        return self.port

    def command(self) -> tuple[str, ...]:
        if self.libraries_dir is not None:
            library_jars = tuple(
                str(path)
                for path in sorted(Path(self.libraries_dir).rglob("*.jar"))
                if path.is_file()
            )
            if not library_jars:
                raise ValueError(f"Minecraft server libraries_dir contains no jar files: {self.libraries_dir}")
            classpath = os.pathsep.join((str(Path(self.jar_path)), *library_jars))
            return (
                self.java_executable,
                f"-Xms{self.xms}",
                f"-Xmx{self.xmx}",
                "-cp",
                classpath,
                "net.minecraft.server.Main",
                "nogui",
            )
        return (
            self.java_executable,
            f"-Xms{self.xms}",
            f"-Xmx{self.xmx}",
            "-jar",
            str(Path(self.jar_path)),
            "nogui",
        )


@dataclass(frozen=True, slots=True)
class MinecraftServerPreparedFiles:
    """Prepared server configuration facts, not a server process identity."""

    eula_path: str
    properties_path: str
    eula_accepted: bool
    properties_digest: str

    def __post_init__(self) -> None:
        if not self.eula_path or not self.properties_path or not self.properties_digest:
            raise ValueError("Minecraft prepared-file identity is incomplete")


@dataclass(frozen=True, slots=True)
class MinecraftRconEndpoint:
    """MC-native control endpoint; the secret is resolved outside this value."""

    host: str = "127.0.0.1"
    port: int | None = None
    command_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("Minecraft RCON endpoint host is invalid")
        if self.port is not None and (
            type(self.port) is not int or not 1 <= self.port <= 65535
        ):
            raise ValueError("Minecraft RCON endpoint port is invalid")
        if self.command_timeout_s <= 0:
            raise ValueError("Minecraft RCON command timeout must be positive")

    @property
    def bound_port(self) -> int:
        if self.port is None:
            raise RuntimeError(
                "Minecraft RCON endpoint is not Resource-bound to a physical port"
            )
        return self.port


@dataclass(frozen=True, slots=True)
class MinecraftConsoleCommandResult:
    """A server-console command response without any credential material."""

    command: str
    response: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.command.strip() or "\x00" in self.command:
            raise ValueError("Minecraft console command is invalid")
        if not self.evidence_ref.strip():
            raise ValueError("Minecraft console evidence_ref is required")


@dataclass(frozen=True, slots=True)
class MinecraftWorldQuiescence:
    """Evidence that a live MC world reached a save/quiescent cut."""

    source_workdir: str
    level_name: str
    server_contract_digest: str
    process_identity_digest: str
    save_evidence_ref: str

    def __post_init__(self) -> None:
        if not self.source_workdir.strip() or not is_absolute_target_path(self.source_workdir):
            raise ValueError("Minecraft world quiescence source_workdir must be absolute")
        if (
            not self.level_name.strip()
            or "/" in self.level_name
            or "\\" in self.level_name
            or self.level_name in {".", ".."}
        ):
            raise ValueError("Minecraft world quiescence level_name is invalid")
        for name, value in (
            ("server_contract_digest", self.server_contract_digest),
            ("process_identity_digest", self.process_identity_digest),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
                raise ValueError(f"Minecraft quiescence {name} must be a SHA-256 digest")
        if not self.save_evidence_ref.strip():
            raise ValueError("Minecraft world quiescence requires save evidence")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MinecraftWorldCut:
    """Immutable identity of a verified, reusable Minecraft world cut."""

    cut_id: str
    snapshot_ref: str
    manifest_ref: str
    level_name: str
    server_contract_digest: str
    process_identity_digest: str
    manifest_digest: str
    save_evidence_ref: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.cut_id,
                self.snapshot_ref,
                self.manifest_ref,
                self.level_name,
                self.server_contract_digest,
                self.process_identity_digest,
                self.manifest_digest,
                self.save_evidence_ref,
            )
        ):
            raise ValueError("Minecraft world cut identity is incomplete")
        for name, value in (
            ("server_contract_digest", self.server_contract_digest),
            ("process_identity_digest", self.process_identity_digest),
            ("manifest_digest", self.manifest_digest),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
                raise ValueError(f"Minecraft world cut {name} must be a SHA-256 digest")
        if "/" in self.level_name or "\\" in self.level_name:
            raise ValueError("Minecraft world cut level_name must be a single path component")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MinecraftWorldBranch:
    """Identity and cleanup authority for one isolated branch materialization."""

    branch_id: str
    cut_id: str
    workdir: str
    level_name: str
    manifest_digest: str
    cleanup_ref: str

    def __post_init__(self) -> None:
        if not self.branch_id.strip() or not self.cut_id.strip() or not self.workdir.strip():
            raise ValueError("Minecraft world branch identity is incomplete")
        if not is_absolute_target_path(self.workdir):
            raise ValueError("Minecraft world branch workdir must be absolute")
        if not self.level_name.strip() or "/" in self.level_name or "\\" in self.level_name:
            raise ValueError("Minecraft world branch level_name is invalid")
        if len(self.manifest_digest) != 64 or any(char not in "0123456789abcdef" for char in self.manifest_digest.lower()):
            raise ValueError("Minecraft world branch manifest_digest must be a SHA-256 digest")
        if not self.cleanup_ref.strip():
            raise ValueError("Minecraft world branch cleanup_ref is required")


@dataclass(frozen=True, slots=True)
class MinecraftBranchRuntimeRequest:
    """Frozen input for realizing one isolated branch runtime.

    Callers declare branch identity and scope only. Physical host ports are
    selected, fenced, renewed and released exclusively by Resource authority.
    """

    branch: MinecraftWorldBranch
    environment: NoetriumUnit
    environment_runtime_template: MinecraftEnvironmentRuntimeBinding
    server_template: MinecraftServerSpec
    session_id: str
    scope: NoetriumUnit
    endpoint_host: str = "127.0.0.1"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("Minecraft branch runtime session_id is required")
        if type(self.scope) is not NoetriumUnit or scope_kind(self.scope) is not ScopeKind.BRANCH:
            raise ValueError(
                "Minecraft branch runtime scope must be a branch scope; "
                f"actual_type={type(self.scope).__module__}.{type(self.scope).__qualname__}, "
                f"actual_kind={getattr(self.scope, 'kind', None)!r}, "
                f"actual_scope={getattr(self.scope, 'key', None)!r}"
            )
        require_minecraft_environment(self.environment)
        if not isinstance(
            self.environment_runtime_template,
            MinecraftEnvironmentRuntimeBinding,
        ):
            raise TypeError(
                "Minecraft branch environment runtime template must be typed"
            )
        if self.environment_runtime_template.endpoint.port is not None:
            raise ValueError(
                "Minecraft branch environment runtime template must not preselect a port"
            )
        if self.server_template.port is not None:
            raise ValueError(
                "Minecraft branch server template must not preselect a port"
            )
        if (
            self.server_template.rcon_endpoint is not None
            and self.server_template.rcon_endpoint.port is not None
        ):
            raise ValueError(
                "Minecraft branch RCON template must not preselect a port"
            )
        if not self.endpoint_host.strip():
            raise ValueError("Minecraft branch endpoint_host is required")

    @property
    def endpoint_allocation_id(self) -> str:
        return f"minecraft:{self.branch.branch_id}:{self.session_id}:game"

    @property
    def rcon_endpoint_allocation_id(self) -> str | None:
        if self.server_template.rcon_endpoint is None:
            return None
        return f"minecraft:{self.branch.branch_id}:{self.session_id}:rcon"


@dataclass(frozen=True, slots=True)
class MinecraftObservationEvent:
    """Architecture-neutral event decoded from one bridge envelope."""

    kind: str
    payload: Mapping[str, MinecraftJsonValue]
    sequence: int = 0
    timestamp_ms: int = 0
    source: str = "mineflayer"
    request_id: str | None = None
    stream_id: str | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip() or self.sequence < 0 or self.timestamp_ms < 0:
            raise ValueError("Minecraft observation event identity is invalid")
        if not self.source.strip():
            raise ValueError("Minecraft observation event source is required")
        if self.request_id is not None and not self.request_id.strip():
            raise ValueError("Minecraft observation event request_id must be non-empty")
        if self.stream_id is not None and not self.stream_id.strip():
            raise ValueError("Minecraft observation event stream_id must be non-empty")


def minecraft_child_effect_rows(
    payload: Mapping[str, MinecraftJsonValue],
    *,
    expected_action_id: str,
    expected_request_digest: str,
    expected_invocation_unit_digest: str,
    expected_authorization_unit_digest: str,
) -> tuple[dict[str, MinecraftJsonValue], ...]:
    raw = payload.get("child_effects", ())
    if raw is None:
        raw = ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("Minecraft action_result child_effects must be an array")
    rows: list[dict[str, MinecraftJsonValue]] = []
    by_action_id: dict[str, dict[str, MinecraftJsonValue]] = {}
    for raw_row in raw:
        if not isinstance(raw_row, Mapping):
            raise ValueError("Minecraft child effect evidence must be an object")
        action_id = raw_row.get("action_id")
        request_digest = raw_row.get("request_digest")
        action_type = raw_row.get("action_type")
        parent_action_id = raw_row.get("parent_action_id")
        parent_request_digest = raw_row.get("parent_request_digest")
        step_index = raw_row.get("step_index")
        depth = raw_row.get("depth")
        if not isinstance(action_id, str) or not action_id.strip() or action_id in by_action_id:
            raise ValueError("Minecraft child effect action identity is invalid")
        if (
            not isinstance(request_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", request_digest) is None
        ):
            raise ValueError("Minecraft child effect request digest is invalid")
        if not isinstance(action_type, str) or action_type not in MINECRAFT_ACTION_SPEC_BY_TYPE:
            raise ValueError("Minecraft child effect action type is invalid")
        if not isinstance(parent_action_id, str) or not parent_action_id.strip():
            raise ValueError("Minecraft child effect parent identity is invalid")
        if type(step_index) is not int or step_index < 0:
            raise ValueError("Minecraft child effect step index is invalid")
        if type(depth) is not int or depth < 1:
            raise ValueError("Minecraft child effect depth is invalid")
        if raw_row.get("root_invocation_unit_digest") != expected_invocation_unit_digest:
            raise ValueError("Minecraft child effect root invocation Unit drifted")
        if raw_row.get("authorization_unit_digest") != expected_authorization_unit_digest:
            raise ValueError("Minecraft child effect authorization Unit drifted")
        if raw_row.get("action_spec_unit_digest") != MINECRAFT_ACTION_SPEC_BY_TYPE[action_type].unit_digest:
            raise ValueError("Minecraft child effect action-spec Unit drifted")
        if parent_action_id == expected_action_id:
            expected_parent_digest = expected_request_digest
            expected_depth = 1
        else:
            parent = by_action_id.get(parent_action_id)
            if parent is None:
                raise ValueError("Minecraft child effect parent must precede its child")
            expected_parent_digest = str(parent["request_digest"])
            expected_depth = int(parent["depth"])
            expected_depth += 1
        if parent_request_digest != expected_parent_digest or depth != expected_depth:
            raise ValueError("Minecraft child effect causal lineage is inconsistent")
        state = raw_row.get("state")
        disposition = raw_row.get("disposition")
        if state not in {"intent", "terminal"}:
            raise ValueError("Minecraft child effect state is invalid")
        if disposition not in {"applied", "rejected", "not_applied", "unknown"}:
            raise ValueError("Minecraft child effect disposition is invalid")
        row: dict[str, MinecraftJsonValue] = {
            "action_id": action_id,
            "request_digest": request_digest,
            "action_type": action_type,
            "parent_action_id": parent_action_id,
            "parent_request_digest": parent_request_digest,
            "step_index": step_index,
            "depth": depth,
            "root_invocation_unit_digest": expected_invocation_unit_digest,
            "authorization_unit_digest": expected_authorization_unit_digest,
            "action_spec_unit_digest": str(raw_row["action_spec_unit_digest"]),
            "state": str(state),
            "disposition": str(disposition),
            "outcome_status": raw_row.get("outcome_status"),
            "outcome_code": raw_row.get("outcome_code"),
        }
        rows.append(row)
        by_action_id[action_id] = row
    return tuple(rows)


def minecraft_action_result_record(
    event: MinecraftObservationEvent,
    *,
    expected_action_id: str,
    expected_action_type: str,
    expected_request_digest: str,
    expected_invocation_unit_digest: str,
    expected_authorization_unit_digest: str,
) -> NoetriumUnit:
    if event.kind != "action_result":
        raise ValueError("Minecraft action evidence must be an action_result event")
    payload = event.payload
    action_id = payload.get("action_id")
    if not isinstance(action_id, str) or action_id != expected_action_id:
        raise ValueError(
            "Minecraft action_result action_id does not match the request"
        )
    lineage = {
        "request_digest": (payload.get("request_digest"), expected_request_digest),
        "action_invocation_unit_digest": (
            payload.get("action_invocation_unit_digest"), expected_invocation_unit_digest
        ),
        "action_authorization_unit_digest": (
            payload.get("action_authorization_unit_digest"), expected_authorization_unit_digest
        ),
    }
    for field_name, (actual, expected) in lineage.items():
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(ch not in "0123456789abcdef" for ch in expected)
        ):
            raise ValueError(f"Minecraft expected {field_name} is not canonical SHA-256")
        if actual != expected:
            raise ValueError(f"Minecraft action_result {field_name} does not match the request")
    action = payload.get("action")
    if not isinstance(action, Mapping) or action.get("tool") != expected_action_type:
        raise ValueError(
            "Minecraft action_result tool does not match the request action_type"
        )
    outcome = payload.get("outcome")
    if not isinstance(outcome, Mapping):
        raise ValueError("Minecraft action_result outcome must be a mapping")
    verified = payload.get("verified")
    if not isinstance(verified, bool):
        raise ValueError("Minecraft action_result verified must be boolean")
    raw_disposition = payload.get("effect_disposition")
    if raw_disposition is None:
        raise ValueError("Minecraft action_result effect_disposition is required")
    try:
        effect_disposition = ActionReconciliationDisposition(str(raw_disposition))
    except ValueError as exc:
        raise ValueError("Minecraft action_result effect_disposition is invalid") from exc
    control = payload.get("execution_control")
    if control is not None:
        if not isinstance(control, Mapping):
            raise ValueError("Minecraft action_result execution control must be a mapping")
        if (
            control.get("state") != "settled"
            or control.get("effect_disposition") != effect_disposition.value
        ):
            raise ValueError(
                "Minecraft action_result execution control contradicts effect evidence"
            )
        transitions = control.get("transitions")
        if type(transitions) is not int or transitions < 2:
            raise ValueError("Minecraft action_result execution transition count is invalid")
        reason = control.get("reason")
        if reason is not None and (not isinstance(reason, str) or not reason):
            raise ValueError("Minecraft action_result interruption reason is invalid")
    raw_status = outcome.get("status")
    if raw_status is None:
        raise ValueError("Minecraft action_result outcome.status is required")
    try:
        status = MinecraftActionOutcomeStatus(str(raw_status))
    except ValueError as exc:
        raise ValueError("Minecraft action_result status is invalid") from exc
    if status is MinecraftActionOutcomeStatus.REJECTED and verified:
        raise ValueError("Rejected Minecraft action_result cannot be verified")
    if status is MinecraftActionOutcomeStatus.SATISFIED:
        if verified:
            raise ValueError("Satisfied-no-effect Minecraft action_result cannot be effect-verified")
        if effect_disposition is not ActionReconciliationDisposition.NOT_APPLIED:
            raise ValueError("Satisfied Minecraft action_result must prove no physical effect")
        if outcome.get("goal_satisfied") is not True:
            raise ValueError("Satisfied Minecraft action_result must prove goal_satisfied")
    if status is MinecraftActionOutcomeStatus.APPLIED:
        if not verified:
            raise ValueError("Applied Minecraft action_result must be verified")
        if effect_disposition is not ActionReconciliationDisposition.APPLIED:
            raise ValueError("Applied Minecraft action_result must prove an applied effect")
    if status is MinecraftActionOutcomeStatus.REJECTED and effect_disposition not in {
        ActionReconciliationDisposition.REJECTED,
        ActionReconciliationDisposition.NOT_APPLIED,
    }:
        raise ValueError("Rejected Minecraft action_result must prove rejection or no effect")
    if status is MinecraftActionOutcomeStatus.PARTIAL and effect_disposition not in {
        ActionReconciliationDisposition.APPLIED,
        ActionReconciliationDisposition.UNKNOWN,
    }:
        raise ValueError("Partial Minecraft action_result effect disposition is invalid")
    child_effects = minecraft_child_effect_rows(
        payload,
        expected_action_id=expected_action_id,
        expected_request_digest=expected_request_digest,
        expected_invocation_unit_digest=expected_invocation_unit_digest,
        expected_authorization_unit_digest=expected_authorization_unit_digest,
    )
    return record_unit(
        "environment.minecraft.action-result",
        frozenset({RecordRole.JOURNAL, RecordRole.EVIDENCE}),
        payload={
            "action_id": action_id,
            "action_type": expected_action_type,
            "request_digest": expected_request_digest,
            "action_invocation_unit_digest": expected_invocation_unit_digest,
            "action_authorization_unit_digest": expected_authorization_unit_digest,
            "status": status.value,
            "effect_disposition": effect_disposition.value,
            "child_effects": child_effects,
            "outcome": dict(outcome),
        },
        provenance={
            "source": event.source,
            "request_id": event.request_id,
            "sequence": event.sequence,
            "timestamp_ms": event.timestamp_ms,
        },
    )

@dataclass(frozen=True, slots=True)
class MinecraftBridgeEnvelope:
    """Validated wire envelope emitted by a Minecraft bridge.

    This is the direct, architecture-neutral extraction of v034's
    ``BridgeEnvelope``. It deliberately contains no task, memory, benchmark or
    evolution fields; those remain payload data owned by the composing project.
    """

    kind: str
    timestamp_ms: int
    payload: Mapping[str, MinecraftJsonValue]
    source: str = "mineflayer"
    sequence: int = 0
    request_id: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MinecraftBridgeEnvelope":
        if value.get("type") != "event":
            raise ValueError("Minecraft bridge envelope must have type=event")
        kind = str(value.get("kind", ""))
        if not kind.strip():
            raise ValueError("Minecraft bridge event kind is required")
        payload = value.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("Minecraft bridge event payload must be a mapping")
        timestamp_ms = int(value.get("ts_ms", 0))
        sequence = int(value.get("seq", 0))
        source = str(value.get("source", "mineflayer"))
        request_id_value = value.get("request_id")
        request_id = None if request_id_value is None else str(request_id_value)
        return cls(
            kind=kind,
            timestamp_ms=timestamp_ms,
            payload=dict(payload),
            source=source,
            sequence=sequence,
            request_id=request_id,
        )

    def as_observation(self, *, stream_id: str | None = None) -> MinecraftObservationEvent:
        return MinecraftObservationEvent(
            kind=self.kind,
            payload=dict(self.payload),
            sequence=self.sequence,
            timestamp_ms=self.timestamp_ms,
            source=self.source,
            request_id=self.request_id,
            stream_id=stream_id,
        )
