from __future__ import annotations

from research.reproductions.voyager_minecraft.curriculum import (
    VOYAGER_CURRICULUM_DEFAULT_WARMUP,
    VOYAGER_CURRICULUM_OBSERVATION_ORDER,
    voyager_curriculum_compose_message,
    voyager_curriculum_context,
    voyager_curriculum_fixed_biome_questions,
    voyager_curriculum_randomizable_sections,
    voyager_curriculum_render_observation,
    voyager_parse_curriculum_questions,
)


def _observation():
    return {
        "status": {
            "biome": "forest",
            "timeOfDay": "day",
            "entities": {"cow": 3.0, "zombie": 8.0},
            "health": 19,
            "food": 17,
            "position": {"x": 1, "y": 64, "z": -2},
            "equipment": ["wooden_pickaxe"],
            "inventoryUsed": 4,
        },
        "voxels": ["oak_log", "grass_block"],
        "blockRecords": ["oak_log", "grass_block", "stone", "coal_ore"],
        "inventory": {
            "oak_log": 2,
            "stick": 4,
            "diamond": 1,
        },
    }


def test_voyager_curriculum_freezes_paper_warmup_and_observation_order() -> None:
    assert VOYAGER_CURRICULUM_DEFAULT_WARMUP["context"] == 15
    assert VOYAGER_CURRICULUM_DEFAULT_WARMUP["biome"] == 10
    assert VOYAGER_CURRICULUM_DEFAULT_WARMUP["nearby_entities"] == 5
    assert VOYAGER_CURRICULUM_DEFAULT_WARMUP["optional_inventory_items"] == 7
    assert VOYAGER_CURRICULUM_OBSERVATION_ORDER[:4] == (
        "context",
        "biome",
        "time",
        "nearby_blocks",
    )
    assert voyager_curriculum_randomizable_sections(progress=4) == ()
    assert voyager_curriculum_randomizable_sections(progress=10) == (
        "biome",
        "other_blocks",
        "nearby_entities",
    )
    assert "context" in voyager_curriculum_randomizable_sections(progress=15)


def test_voyager_curriculum_renders_source_observation_and_filters_optional_inventory() -> None:
    sections = voyager_curriculum_render_observation(
        world_observation=_observation(),
        chest_observation="Chests: None\n\n",
        completed_tasks=("task-1",),
        failed_tasks=("task-x",),
    )
    assert sections["biome"] == "Biome: forest\n\n"
    assert sections["nearby_entities"] == "Nearby entities: cow, zombie\n\n"
    assert "stone" in sections["other_blocks"]
    assert "coal_ore" in sections["other_blocks"]
    assert "diamond" not in sections["inventory"]
    assert "oak_log" in sections["inventory"]
    assert "stick" in sections["inventory"]

    underground = dict(_observation())
    underground["voxels"] = ["stone", "deepslate"]
    underground_sections = voyager_curriculum_render_observation(
        world_observation=underground,
        chest_observation="",
        completed_tasks=(),
        failed_tasks=(),
    )
    assert underground_sections["biome"] == "Biome: underground\n\n"


def test_voyager_curriculum_qa_parsing_context_filter_and_random_mask_are_explicit() -> None:
    text = (
        "Reasoning: inspect the world\n"
        "Question 1: How to make a torch?\nConcept 1: torch\n"
        "Question 2: How to smelt iron?\nConcept 2: furnace\n"
    )
    generated = voyager_parse_curriculum_questions(text)
    assert generated == (
        "How to make a torch?",
        "How to smelt iron?",
    )

    fixed = voyager_curriculum_fixed_biome_questions(_observation())
    assert len(fixed) == 3
    assert all("forest" in question for question in fixed)

    questions = (
        "q1",
        "q2",
        "q3",
        "q4",
        "q5",
        "q6",
        "q7",
    )
    answers = (
        "Answer: a1",
        "Answer: Unknown",
        "This language model cannot answer",
        "Answer: a4",
        "Answer: a5",
        "Answer: a6",
        "Answer: a7",
    )
    context = voyager_curriculum_context(questions, answers)
    assert "Question 1: q1" in context
    assert "q2" not in context
    assert "q3" not in context
    assert "Question 5: q7" in context

    sections = voyager_curriculum_render_observation(
        world_observation=_observation(),
        chest_observation="Chests: None\n\n",
        completed_tasks=tuple(f"task-{index}" for index in range(15)),
        failed_tasks=(),
    )
    sections = dict(sections)
    sections["context"] = context
    message = voyager_curriculum_compose_message(
        sections=sections,
        included_random_sections=("context", "biome", "health"),
    )
    assert context in message
    assert "Biome: forest" in message
    assert "Health: 19.0/20" in message
    # zero-warmup sections are always present regardless of the random mask
    assert "Nearby blocks:" in message
    assert "Position:" in message
    assert "Inventory (" in message
