from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest, freeze_json


VOYAGER_CURRICULUM_OBSERVATION_ORDER = (
    "context",
    "biome",
    "time",
    "nearby_blocks",
    "other_blocks",
    "nearby_entities",
    "health",
    "hunger",
    "position",
    "equipment",
    "inventory",
    "chests",
    "completed_tasks",
    "failed_tasks",
)

VOYAGER_CURRICULUM_DEFAULT_WARMUP = {
    "context": 15,
    "biome": 10,
    "time": 15,
    "nearby_blocks": 0,
    "other_blocks": 10,
    "nearby_entities": 5,
    "health": 15,
    "hunger": 15,
    "position": 0,
    "equipment": 0,
    "inventory": 0,
    "optional_inventory_items": 7,
    "chests": 0,
    "completed_tasks": 0,
    "failed_tasks": 0,
}

VOYAGER_CORE_INVENTORY_PATTERN = (
    r".*_log|.*_planks|stick|crafting_table|furnace"
    r"|cobblestone|dirt|coal|.*_pickaxe|.*_sword|.*_axe"
)


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return dict(value)


def _sequence(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    return ()


def _names(value: object) -> tuple[str, ...]:
    rows = []
    for item in _sequence(value):
        if isinstance(item, Mapping):
            name = item.get("name", item.get("displayName", item.get("username")))
            if name is not None:
                rows.append(str(name))
        elif item is not None:
            rows.append(str(item))
    return tuple(rows)


def _status(observation: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    value = observation.get("status")
    return _mapping(value, "Voyager curriculum status") if isinstance(value, Mapping) else dict(observation)


def _inventory(observation: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    value = observation.get("inventory", {})
    return _mapping(value, "Voyager curriculum inventory") if isinstance(value, Mapping) else {}


def _voxels(observation: Mapping[str, JsonValue]) -> tuple[str, ...]:
    value = observation.get("voxels")
    if value is None:
        value = observation.get("nearby_blocks", ())
    return tuple(str(row) for row in _sequence(value))


def _block_records(observation: Mapping[str, JsonValue]) -> tuple[str, ...]:
    value = observation.get("blockRecords")
    if value is None:
        value = observation.get("block_records", ())
    return tuple(str(row) for row in _sequence(value))


def _entity_names(status: Mapping[str, JsonValue]) -> tuple[str, ...]:
    value = status.get("entities", ())
    if isinstance(value, Mapping):
        sortable = []
        for key, distance in value.items():
            try:
                numeric = float(distance)
            except (TypeError, ValueError):
                numeric = float("inf")
            sortable.append((numeric, str(key)))
        return tuple(name for _, name in sorted(sortable))
    return _names(value)


def voyager_curriculum_render_observation(
    *,
    world_observation: Mapping[str, JsonValue],
    chest_observation: str,
    completed_tasks: tuple[str, ...],
    failed_tasks: tuple[str, ...],
) -> JsonObject:
    """Render the paper-release CurriculumAgent observation sections."""

    observation = dict(world_observation)
    status = _status(observation)
    inventory = _inventory(observation)
    voxels = _voxels(observation)
    block_records = _block_records(observation)

    biome = str(status.get("biome", observation.get("biome", "unknown")))
    if not any(
        marker in block
        for block in voxels
        for marker in ("dirt", "log", "grass", "sand", "snow")
    ):
        biome = "underground"

    inventory_keys = set(str(key) for key in inventory)
    other_blocks = sorted(
        set(block_records).difference(set(voxels).union(inventory_keys))
    )
    nearby_entities = _entity_names(status)

    progress = len(completed_tasks)
    visible_inventory = dict(inventory)
    if progress < VOYAGER_CURRICULUM_DEFAULT_WARMUP["optional_inventory_items"]:
        matcher = re.compile(VOYAGER_CORE_INVENTORY_PATTERN)
        visible_inventory = {
            key: value
            for key, value in visible_inventory.items()
            if matcher.search(str(key)) is not None
        }

    position_value = status.get("position", {})
    position = dict(position_value) if isinstance(position_value, Mapping) else {}
    x = float(position.get("x", 0.0))
    y = float(position.get("y", 0.0))
    z = float(position.get("z", 0.0))
    health = float(status.get("health", 0.0))
    hunger = float(status.get("food", status.get("hunger", 0.0)))
    inventory_used = status.get(
        "inventoryUsed",
        status.get("inventory_used", len(visible_inventory)),
    )
    try:
        inventory_used = int(inventory_used)
    except (TypeError, ValueError):
        inventory_used = len(visible_inventory)

    sections = {
        "context": "",
        "biome": f"Biome: {biome}\n\n",
        "time": f"Time: {status.get('timeOfDay', status.get('time_of_day', 'unknown'))}\n\n",
        "nearby_blocks": (
            f"Nearby blocks: {', '.join(voxels) if voxels else 'None'}\n\n"
        ),
        "other_blocks": (
            "Other blocks that are recently seen: "
            f"{', '.join(other_blocks) if other_blocks else 'None'}\n\n"
        ),
        "nearby_entities": (
            f"Nearby entities: {', '.join(nearby_entities) if nearby_entities else 'None'}\n\n"
        ),
        "health": f"Health: {health:.1f}/20\n\n",
        "hunger": f"Hunger: {hunger:.1f}/20\n\n",
        "position": f"Position: x={x:.1f}, y={y:.1f}, z={z:.1f}\n\n",
        "equipment": f"Equipment: {status.get('equipment', ())}\n\n",
        "inventory": (
            f"Inventory ({inventory_used}/36): "
            f"{visible_inventory if visible_inventory else 'Empty'}\n\n"
        ),
        "chests": str(chest_observation),
        "completed_tasks": (
            "Completed tasks so far: "
            f"{', '.join(completed_tasks) if completed_tasks else 'None'}\n\n"
        ),
        "failed_tasks": (
            "Failed tasks that are too hard: "
            f"{', '.join(failed_tasks) if failed_tasks else 'None'}\n\n"
        ),
    }
    return freeze_json(sections)


def voyager_curriculum_fixed_biome_questions(
    world_observation: Mapping[str, JsonValue],
) -> tuple[str, ...]:
    sections = voyager_curriculum_render_observation(
        world_observation=world_observation,
        chest_observation="",
        completed_tasks=(),
        failed_tasks=(),
    )
    biome_line = str(sections["biome"]).split(":", 1)[-1].strip()
    return (
        f"What are the blocks that I can find in the {biome_line} in Minecraft?",
        f"What are the items that I can find in the {biome_line} in Minecraft?",
        f"What are the mobs that I can find in the {biome_line} in Minecraft?",
    )


def voyager_parse_curriculum_questions(text: str) -> tuple[str, ...]:
    if type(text) is not str:
        raise TypeError("Voyager curriculum QA question response must be text")
    pairs = re.findall(
        r"Question \d+: (.+)\nConcept \d+: (.+)",
        text,
    )
    return tuple(question for question, _ in pairs)


def voyager_curriculum_context(
    questions: tuple[str, ...],
    answers: tuple[str, ...],
) -> str:
    if len(questions) != len(answers):
        raise ValueError("Voyager curriculum QA cardinality mismatch")
    rows: list[str] = []
    index = 1
    for question, answer in zip(questions, answers):
        if "Answer: Unknown" in answer or "language model" in answer:
            continue
        rows.append(f"Question {index}: {question}\n{answer}\n\n")
        index += 1
        if index > 5:
            break
    return "".join(rows)


def voyager_curriculum_randomizable_sections(
    *,
    progress: int,
) -> tuple[str, ...]:
    if type(progress) is not int or progress < 0:
        raise ValueError("Voyager curriculum progress must be non-negative")
    return tuple(
        key
        for key in VOYAGER_CURRICULUM_OBSERVATION_ORDER
        if VOYAGER_CURRICULUM_DEFAULT_WARMUP[key] != 0
        and progress >= VOYAGER_CURRICULUM_DEFAULT_WARMUP[key]
    )


def voyager_curriculum_always_sections(*, progress: int) -> tuple[str, ...]:
    if type(progress) is not int or progress < 0:
        raise ValueError("Voyager curriculum progress must be non-negative")
    return tuple(
        key
        for key in VOYAGER_CURRICULUM_OBSERVATION_ORDER
        if VOYAGER_CURRICULUM_DEFAULT_WARMUP[key] == 0
        and progress >= VOYAGER_CURRICULUM_DEFAULT_WARMUP[key]
    )


def voyager_curriculum_compose_message(
    *,
    sections: Mapping[str, JsonValue],
    included_random_sections: tuple[str, ...],
) -> str:
    allowed = set(voyager_curriculum_always_sections(progress=10**9))
    allowed.update(included_random_sections)
    return "".join(
        str(sections[key])
        for key in VOYAGER_CURRICULUM_OBSERVATION_ORDER
        if key in allowed and key in sections
    )


def voyager_curriculum_semantics_digest() -> str:
    return canonical_digest({
        "observation_order": VOYAGER_CURRICULUM_OBSERVATION_ORDER,
        "warmup": VOYAGER_CURRICULUM_DEFAULT_WARMUP,
        "core_inventory_pattern": VOYAGER_CORE_INVENTORY_PATTERN,
        "random_inclusion_probability": 0.8,
        "context_answer_limit": 5,
        "qa_semantic_reuse_distance_threshold": 0.05,
    })


__all__ = [
    "VOYAGER_CORE_INVENTORY_PATTERN",
    "VOYAGER_CURRICULUM_DEFAULT_WARMUP",
    "VOYAGER_CURRICULUM_OBSERVATION_ORDER",
    "voyager_curriculum_always_sections",
    "voyager_curriculum_compose_message",
    "voyager_curriculum_context",
    "voyager_curriculum_fixed_biome_questions",
    "voyager_curriculum_randomizable_sections",
    "voyager_curriculum_render_observation",
    "voyager_curriculum_semantics_digest",
    "voyager_parse_curriculum_questions",
]
