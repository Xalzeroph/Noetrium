from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


MINECRAFT_TASK_SUCCESS_KINDS = frozenset({
    "inventory_delta_min",
    "inventory_delta_match_min",
    "inventory_min",
    "inventory_goal_token_match",
    "away_then_return",
    "target_defeated",
    "verified_item_use",
    "verified_action",
    "inventory_all_min",
    "combat_survived",
    "blueprint_complete",
})


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _verified_rows(action_results: Sequence[object]) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for raw in action_results:
        row = _mapping(raw)
        outcome = _mapping(row.get("outcome"))
        if outcome.get("verified") is True:
            rows.append(row)
    return tuple(rows)


def _state(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_mapping(row.get("outcome")).get("state"))


def _provider_outcome(row: Mapping[str, Any]) -> Mapping[str, Any]:
    outcome = _mapping(row.get("outcome"))
    state = _mapping(outcome.get("state"))
    last = state.get("last_outcome")
    if isinstance(last, Mapping):
        return last
    for event in outcome.get("events", ()) if isinstance(outcome.get("events"), Sequence) else ():
        event_row = _mapping(event)
        if event_row.get("kind") != "action_result":
            continue
        payload = _mapping(event_row.get("payload"))
        candidate = payload.get("outcome")
        if isinstance(candidate, Mapping):
            return candidate
    return {}


def _inventory(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_state(row).get("inventory"))


def _action(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(row.get("action"))


def _action_arguments(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_action(row).get("arguments"))


def _action_type(row: Mapping[str, Any]) -> str:
    action = _action(row)
    return str(action.get("action_type", action.get("tool", ""))).strip()


def _provider_applied(row: Mapping[str, Any]) -> bool:
    provider = _provider_outcome(row)
    return str(provider.get("status", "")).strip() == "applied"


def _rows_proving_required_collection_tool(
    rows: Sequence[Mapping[str, Any]],
    required_tool: str,
) -> tuple[Mapping[str, Any], ...]:
    """Keep only collect effects that physically prove the requested tool constraint."""
    result: list[Mapping[str, Any]] = []
    for row in rows:
        if _action_type(row) != "collect_block":
            continue
        arguments = _action_arguments(row)
        provider = _provider_outcome(row)
        held_after = _mapping(provider.get("held_after"))
        if (
            str(arguments.get("tool", "")).strip() == required_tool
            and str(provider.get("code", "")) == "BLOCKS_COLLECTED"
            and provider.get("tool_constraint_verified") is True
            and str(provider.get("requested_tool", "")).strip() == required_tool
            and str(held_after.get("name", "")).strip() == required_tool
        ):
            result.append(row)
    return tuple(result)


def _name_matches(name: str, success: Mapping[str, Any]) -> bool:
    exact = success.get("items")
    if isinstance(exact, Sequence) and not isinstance(exact, (str, bytes, bytearray)):
        if name in {str(value) for value in exact}:
            return True
    item = str(success.get("item", "")).strip()
    if item and name == item:
        return True
    suffixes = success.get("item_suffixes")
    if isinstance(suffixes, Sequence) and not isinstance(suffixes, (str, bytes, bytearray)):
        if any(name.endswith(str(value)) for value in suffixes):
            return True
    return False


def _provider_delta_matching(
    rows: Sequence[Mapping[str, Any]],
    success: Mapping[str, Any],
) -> int:
    total = 0
    for row in rows:
        delta = _mapping(_provider_outcome(row).get("inventory_delta"))
        total += sum(
            int(value or 0)
            for name, value in delta.items()
            if _name_matches(str(name), success) and int(value or 0) > 0
        )
    return total


def _inventory_delta_matching(
    rows: Sequence[Mapping[str, Any]],
    success: Mapping[str, Any],
) -> int:
    total = 0
    for row in rows:
        delta = _mapping(_provider_outcome(row).get("inventory_delta"))
        total += sum(
            int(value or 0)
            for name, value in delta.items()
            if _name_matches(str(name), success)
        )
    if total:
        return total
    if not rows:
        return 0
    current = _inventory(rows[-1])
    current_total = sum(
        int(value or 0)
        for name, value in current.items()
        if _name_matches(str(name), success)
    )
    for row in rows:
        before = _provider_outcome(row).get("inventory_before")
        if isinstance(before, Mapping):
            before_total = sum(
                int(value or 0)
                for name, value in before.items()
                if _name_matches(str(name), success)
            )
            return current_total - before_total
    return 0


def _inventory_matching(
    row: Mapping[str, Any],
    success: Mapping[str, Any],
) -> int:
    return sum(
        int(value or 0)
        for name, value in _inventory(row).items()
        if _name_matches(str(name), success)
    )


def _inventory_delta_total(
    rows: Sequence[Mapping[str, Any]],
    item: str,
) -> int:
    if not rows:
        return 0
    current = _inventory(rows[-1])
    current_count = int(current.get(item, 0) or 0)
    for row in rows:
        provider = _provider_outcome(row)
        before = provider.get("inventory_before")
        if isinstance(before, Mapping):
            return current_count - int(before.get(item, 0) or 0)
    total = 0
    for row in rows:
        delta = _mapping(_provider_outcome(row).get("inventory_delta"))
        total += int(delta.get(item, 0) or 0)
    return total


def _position(value: object) -> tuple[float, float, float] | None:
    row = _mapping(value)
    try:
        return (float(row["x"]), float(row["y"]), float(row["z"]))
    except (KeyError, TypeError, ValueError):
        return None


def _distance(left: object, right: object) -> float | None:
    a = _position(left)
    b = _position(right)
    if a is None or b is None:
        return None
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def minecraft_task_success_satisfied(
    task: Mapping[str, Any],
    action_results: Sequence[object],
) -> bool:
    """Evaluate one benchmark success contract from grounded verified trajectory.

    The environment owns action truth; the benchmark owns task truth.  Only
    verified environment outcomes may satisfy a task contract, and no model
    self-report is consulted.
    """

    success = _mapping(task.get("success"))
    kind = str(success.get("kind", "")).strip()
    rows = _verified_rows(action_results)
    if not rows or not kind:
        return False

    if kind in {"inventory_delta_min", "inventory_delta_match_min"}:
        count = int(success.get("count", 0) or 0)
        if count <= 0:
            return False
        required_tool = str(success.get("required_tool", "")).strip()
        if required_tool:
            tool_rows = _rows_proving_required_collection_tool(rows, required_tool)
            if not tool_rows:
                return False
            return _provider_delta_matching(tool_rows, success) >= count
        if kind == "inventory_delta_min":
            item = str(success.get("item", "")).strip()
            return bool(item) and _inventory_delta_total(rows, item) >= count
        return _inventory_delta_matching(rows, success) >= count

    if kind == "inventory_min":
        item = str(success.get("item", "")).strip()
        count = int(success.get("count", 0) or 0)
        if not item or count <= 0:
            return False
        return int(_inventory(rows[-1]).get(item, 0) or 0) >= count

    if kind == "inventory_goal_token_match":
        goal = str(success.get("goal", "")).strip().lower()
        if not goal:
            return False
        inventory = _inventory(rows[-1])
        aliases = success.get("wood_aliases", ("log", "oak_log", "wood"))
        if not isinstance(aliases, Sequence) or isinstance(aliases, (str, bytes, bytearray)):
            return False
        normalized_aliases = {str(value).strip().lower() for value in aliases}
        if any(word in goal for word in ("log", "wood", "tree")):
            for item, count in inventory.items():
                name = str(item).strip().lower().removeprefix("minecraft:")
                if int(count or 0) > 0 and (
                    name in normalized_aliases or name.endswith("_log")
                ):
                    return True
        for item, count in inventory.items():
            if int(count or 0) <= 0:
                continue
            token = str(item).strip().lower().removeprefix("minecraft:").replace("_", " ")
            if token and token in goal:
                return True
        return False

    if kind == "away_then_return":
        anchor_name = str(success.get("anchor", "")).strip()
        departure = float(success.get("min_departure_distance", 0) or 0)
        radius = float(success.get("return_radius", 0) or 0)
        if not anchor_name or departure <= 0 or radius < 0:
            return False
        seen_departure = False
        final_distance: float | None = None
        for row in rows:
            state = _state(row)
            anchors = _mapping(state.get("anchors"))
            distance = _distance(state.get("position"), anchors.get(anchor_name))
            if distance is None:
                continue
            if distance >= departure:
                seen_departure = True
            final_distance = distance
        return seen_departure and final_distance is not None and final_distance <= radius

    if kind == "target_defeated":
        entity = str(success.get("entity", "")).strip().lower()
        count = int(success.get("count", 1) or 1)
        if not entity or count <= 0:
            return False
        defeated = 0
        for row in rows:
            provider = _provider_outcome(row)
            code = str(provider.get("code", ""))
            target = str(provider.get("target_name", "")).strip().lower()
            arguments = _action_arguments(row)
            requested = str(
                arguments.get(
                    "entity",
                    arguments.get("target", arguments.get("mob", "")),
                )
            ).strip().lower()
            if code != "TARGET_DEFEATED":
                continue
            if entity in {target, requested} or entity in target or entity in requested:
                defeated += 1
        return defeated >= count

    if kind == "verified_item_use":
        item = str(success.get("item", "")).strip()
        if not item:
            return False
        placeable = {
            "redstone_block", "dispenser", "dropper", "observer", "piston",
            "redstone_lamp", "redstone_torch", "repeater", "detector_rail",
            "comparator", "activator_rail", "tnt",
        }
        armor_suffixes = ("_boots", "_leggings", "_chestplate", "_helmet")
        for row in rows:
            provider = _provider_outcome(row)
            if not _provider_applied(row):
                continue
            code = str(provider.get("code", "")).strip()
            action_type = _action_type(row)
            arguments = _action_arguments(row)
            argument_item = str(arguments.get("item", "")).strip()

            # Equipping is itself semantic use only for wearable armor.  For
            # tools/weapons the benchmark says "use", so a later physical
            # interaction must be proven instead of merely holding the item.
            if (
                item.endswith(armor_suffixes)
                and action_type == "equip_item"
                and code == "ITEM_EQUIPPED"
            ):
                equipped = _mapping(provider.get("equipped"))
                if argument_item == item and str(equipped.get("name", "")).strip() == item:
                    return True

            # Already-present blocks are not a use of the newly crafted item.
            if item in placeable and action_type == "place_block":
                if (
                    argument_item == item
                    and code in {"BLOCK_PLACED", "BLOCK_PLACED_DESPITE_PROVIDER_ERROR"}
                    and str(provider.get("placed", "")).strip() == item
                ):
                    return True

            if item == "bow" and action_type in {"ranged_attack", "fire_projectile"}:
                if (
                    str(provider.get("weapon", "")).strip() == item
                    and int(provider.get("shots_released", 0) or 0) > 0
                    and int(provider.get("ammo_consumed", 0) or 0) > 0
                    and code in {
                        "TARGET_DEFEATED_AFTER_VERIFIED_SHOT",
                        "TARGET_HIT_ATTRIBUTED_TO_OWN_SHOT",
                        "SHOTS_RELEASED_HIT_UNCONFIRMED",
                        "PROJECTILES_RELEASED",
                    }
                ):
                    return True

            if item.endswith("_sword") and action_type in {
                "attack_nearest", "attack_entity", "attack_player",
            }:
                if (
                    str(provider.get("weapon", "")).strip() == item
                    and code in {"TARGET_HIT_CONFIRMED", "TARGET_DEFEATED"}
                ):
                    return True

            if item.endswith(("_pickaxe", "_axe", "_shovel")) and action_type == "collect_block":
                held_after = _mapping(provider.get("held_after"))
                if (
                    code in {"BLOCKS_COLLECTED", "BLOCK_REMOVED"}
                    and str(held_after.get("name", "")).strip() == item
                ):
                    return True

            if item.endswith("_hoe") and action_type == "till_and_sow":
                if code == "SEED_PLANTED" and str(provider.get("hoe_used", "")).strip() == item:
                    return True

            if action_type == "use_tool_on" and code in {
                "TOOL_USED_ON_ENTITY", "TOOL_USED_ON_BLOCK",
            }:
                if str(provider.get("held_item", "")).strip() == item:
                    return True
        return False

    if kind == "verified_action":
        action_type = str(success.get("action_type", "")).strip()
        code = str(success.get("provider_code", "")).strip()
        for row in rows:
            provider = _provider_outcome(row)
            if action_type and _action_type(row) != action_type:
                continue
            if code and str(provider.get("code", "")) != code:
                continue
            return True
        return False

    if kind == "inventory_all_min":
        required = success.get("items")
        if not isinstance(required, Mapping) or not required:
            return False
        inventory = _inventory(rows[-1])
        return all(
            int(inventory.get(str(item), 0) or 0) >= int(count)
            for item, count in required.items()
        )

    if kind == "combat_survived":
        required = int(success.get("min_verified_combat_actions", 0) or 0)
        if required <= 0:
            return False
        plan = task.get("action_plan", ())
        planned_types = {
            str(_mapping(row).get("action_type", "")).strip()
            for row in plan
            if isinstance(row, Mapping)
        }
        verified_actions = sum(
            1
            for row in rows
            if str(_mapping(row.get("action")).get("action_type", "")).strip()
            in planned_types
        )
        health = _state(rows[-1]).get("health")
        return verified_actions >= required and isinstance(health, (int, float)) and health > 0

    if kind == "blueprint_complete":
        required = {
            str(value).strip()
            for value in success.get("blocks", ())
            if isinstance(value, str) and value.strip()
        }
        if not required:
            return False
        placed: set[str] = set()
        for row in rows:
            action = _mapping(row.get("action"))
            if action.get("action_type") != "place_block":
                continue
            arguments = _mapping(action.get("arguments"))
            item = arguments.get("item", arguments.get("block"))
            if isinstance(item, str) and item.strip():
                placed.add(item.strip())
        return required.issubset(placed)

    raise ValueError(f"unsupported Minecraft task-success contract kind: {kind}")


__all__ = ["MINECRAFT_TASK_SUCCESS_KINDS", "minecraft_task_success_satisfied"]
