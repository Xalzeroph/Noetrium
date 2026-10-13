"""Registry suggestions must remain declared, separate from world observations."""
from noetrium_platform.capabilities.environment.minecraft.api.agent_context import (
    _compact_world_frontier,
    _lossless_row_table,
    minecraft_agent_context_facets,
)


def _decode_row_table(value):
    if isinstance(value, dict) and {"row_count", "fields", "rows"} <= set(value):
        fields = tuple(value["fields"])
        rows = tuple(dict(zip(fields, row, strict=True)) for row in value["rows"])
        assert len(rows) == value["row_count"]
        return rows
    return tuple(value)


def test_lossless_row_table_round_trips_homogeneous_evidence_and_falls_back_on_drift():
    rows = (
        {"name": "oak_log", "position": {"x": 1, "y": 64, "z": 2}, "distance": 3.0},
        {"name": "birch_log", "position": {"x": 2, "y": 64, "z": 2}, "distance": 4.0},
        {"name": "spruce_log", "position": {"x": 3, "y": 64, "z": 2}, "distance": 5.0},
    )
    packed = _lossless_row_table(rows)
    assert _decode_row_table(packed) == rows
    heterogeneous = rows[:2] + ({"name": "spruce_log", "distance": 5.0},)
    assert _lossless_row_table(heterogeneous) == heterogeneous
    tiny_list = [rows[0]]
    assert _lossless_row_table(tiny_list) is tiny_list
    heterogeneous_list = list(heterogeneous)
    assert _lossless_row_table(heterogeneous_list) is heterogeneous_list


def _decode_compact_frontier(value):
    rows = [dict(row) for row in _decode_row_table(value["candidates"])]
    derived = value.get("derived_candidate_fields", {})
    for row in rows:
        if derived.get("center_x") == "chunk_x*16+8":
            row["center_x"] = row["chunk_x"] * 16 + 8
        if derived.get("center_z") == "chunk_z*16+8":
            row["center_z"] = row["chunk_z"] * 16 + 8
        if "path_reachable" in derived:
            row["path_reachable"] = derived["path_reachable"]
    return tuple(rows)


def test_large_world_frontier_factors_only_provably_derived_columns():
    rows = tuple({
        "adjacent_columns_not_loaded": 1 + (index % 2),
        "center_x": index * 16 + 8,
        "center_z": -24,
        "chunk_x": index,
        "chunk_z": -2,
        "distance_xz": float(index + 1),
        "path_reachable": None,
    } for index in range(12))
    packed = _compact_world_frontier({"candidates": rows, "status": "observed"})
    assert packed["derived_candidate_fields"] == {
        "center_x": "chunk_x*16+8",
        "center_z": "chunk_z*16+8",
        "path_reachable": None,
    }
    assert _decode_compact_frontier(packed) == rows

    drifted = list(rows)
    drifted[5] = {**drifted[5], "center_x": 999, "path_reachable": True}
    fallback = _compact_world_frontier({"candidates": drifted})
    assert "derived_candidate_fields" not in fallback
    assert _decode_row_table(fallback["candidates"]) == tuple(drifted)


def test_frontier_context_is_lossless_and_sensing_reuses_the_execution_copy():
    frontier_candidates = [
        {
            "chunk_x": index, "chunk_z": 0, "center_x": index * 16 + 8,
            "center_z": 8, "distance_xz": float(index + 1),
            "adjacent_columns_not_loaded": 1, "path_reachable": None,
        }
        for index in range(6)
    ]
    facets = minecraft_agent_context_facets({
        "last_action": {"tool": "observe_blocks", "max_distance": 64},
        "last_outcome": {
            "status": "applied", "code": "BLOCKS_OBSERVED",
            "truth_class": "observed", "authoritative_for_current_world": True,
            "loaded_world_only": True, "observed_count": 0, "blocks": [],
            "world_frontier": {
                "truth_class": "observed", "status": "observed_loaded_boundaries",
                "loaded_column_count": 9, "searched_max_distance": 64,
                "candidates": frontier_candidates,
            },
        },
    })
    indexed = {row["label"]: row["value"] for row in facets}
    frontier = indexed["minecraft.last_action_feedback"]["outcome"]["world_frontier"]
    assert _decode_row_table(frontier["candidates"]) == tuple(frontier_candidates)
    sensing = indexed["minecraft.local_sensing"]
    assert "world_frontier" not in sensing
    assert sensing["world_frontier_path"] == "execution.last.outcome.world_frontier"


def test_rejected_wrong_item_name_exposes_declared_candidates_without_claiming_possession():
    facets = minecraft_agent_context_facets({
        "inventory": {"oak_log": 4},
        "last_action": {"tool": "craft_item", "item": "oak_plank"},
        "last_outcome": {
            "status": "rejected", "code": "UNKNOWN_ITEM",
            "target_classification": "unknown",
            "canonical_item_candidates": [{
                "kind": "item", "name": "oak_planks", "edit_distance": 1,
            }],
            "recovery": {
                "action_type": "registry_search",
                "arguments": {"query": "oak_plank", "limit": 12},
            },
        },
    })
    by_label = {row["label"]: row for row in facets}
    holdings = by_label["minecraft.holdings"]
    assert holdings["truth_class"] == "observed"
    assert holdings["value"]["item_counts"] == {"oak_log": 4}
    assert "oak_planks" not in holdings["value"]["item_counts"]
    names = by_label["minecraft.registry_name_candidates"]
    assert names["truth_class"] == "declared"
    assert names["value"]["canonical_item_candidates"][0]["name"] == "oak_planks"
    assert names["value"]["not_physical_world_proof"] is True
    last = by_label["minecraft.last_action_feedback"]
    assert last["truth_class"] == "observed"
    assert last["value"]["outcome"]["code"] == "UNKNOWN_ITEM"
    assert last["value"]["outcome"]["recovery"]["action_type"] == "registry_search"


def test_recipe_dependency_reference_and_observed_inventory_have_separate_truth_classes():
    profiles = [{
        "reference_recipe_index": 11,
        "unresolved_acquisition_inputs": {"oak_log": 1},
        "reference_crafting_steps": [
            {"output_item": "oak_planks", "input_items": {"oak_log": 1}},
            {"output_item": "stick", "input_items": {"oak_planks": 2}},
        ],
    }]
    facets = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {"tool": "recipe_dependencies", "item": "stick"},
        "last_outcome": {
            "status": "applied",
            "code": "RECIPE_DEPENDENCIES_REFERENCED",
            "source": "version_pinned_vanilla_minecraft_data",
            "item": "stick",
            "count": 4,
            "item_known": True,
            "root_alternative_dependency_profiles": profiles,
            "alternative_ranking_semantics":
                "declared_shortage_complexity_only_not_physical_availability",
            "authoritative_for_current_world_recipe": False,
            "datapack_rules_included": False,
            "no_physical_effect": True,
            "inventory_before": {},
            "inventory_source": "currently_observed_mineflayer_inventory",
            "observed_local_acquisition_sources": {
                "truth_class": "observed",
                "loaded_world_only": True,
                "observation_status": "bounded_loaded_world_observed",
                "no_global_absence_or_harvestability_claim": True,
                "max_distance": 16,
                "candidates": [{
                    "source_block": "oak_log",
                    "position": {"x": 2, "y": 69, "z": 3},
                    "matched_reference_recipe_indices": [11],
                    "physically_acquired": False,
                    "path_reachable": None,
                }],
            },
        },
    })
    rows = {row["label"]: row for row in facets}
    knowledge = rows["minecraft.crafting_dependency_alternatives"]
    assert knowledge["truth_class"] == "declared"
    selected = knowledge["value"]["selected"]
    assert tuple(step["output_item"] for step in selected["steps"]) == ("oak_planks", "stick")
    assert selected["unresolved_inputs"] == {"oak_log": 1}
    assert knowledge["decision_constraint"] == {
        "kind": "declared_dependency",
        "requirements": {"oak_log": 1},
        "valid_until": "physical_effect",
    }
    assert "alternatives" not in knowledge["value"]
    assert "root_alternative_dependency_profiles" not in knowledge["value"]
    assert "inventory_before" not in knowledge["value"]
    assert "minecraft.crafting_observed_inventory" not in rows
    assert rows["minecraft.holdings"]["truth_class"] == "observed"
    assert rows["minecraft.holdings"]["value"]["item_counts"] == {}
    assert rows["minecraft.holdings"]["value"]["inventory_status"] == "observed_empty"
    sources = rows["minecraft.crafting_local_source_candidates"]
    assert sources["truth_class"] == "observed"
    assert sources["value"]["observed_candidate_count"] == 1
    assert sources["value"]["count_semantics"] == (
        "observed_presence_only_not_required_acquisition_quantity"
    )
    assert sources["value"]["reference_matches"][0]["source_block"] == "oak_log"
    assert sources["value"]["reference_matches"][0]["observed_candidate_blocks"] == 1
    assert sources["value"]["reference_matches"][0]["matching_recipe_requirements"] == (
        {"recipe_index": 11, "unresolved_inputs": {"oak_log": 1}},
    )
    assert "position" not in sources["value"]["reference_matches"][0]


def test_recipe_constraint_marks_only_fully_inventory_satisfied_gain_targets():
    facets = minecraft_agent_context_facets({
        "inventory": {"quartz": 4, "stone": 16, "coal": 32},
        "last_action": {"tool": "recipe_dependencies", "item": "comparator", "count": 1},
        "last_outcome": {
            "status": "applied",
            "code": "RECIPE_DEPENDENCIES_REFERENCED",
            "source": "version_pinned_vanilla_minecraft_data",
            "datapack_rules_included": False,
            "authoritative_for_current_world_recipe": False,
            "no_physical_effect": True,
            "inventory_before": {"quartz": 4, "stone": 16, "coal": 32},
            "inventory_after_reference_allocation": {
                "quartz": 3, "stone": 13, "coal": 32, "redstone_torch": 0,
            },
            "reference_crafting_steps": [{
                "output_item": "comparator",
                "output_count": 1,
                "batches": 1,
                "input_items": {"quartz": 1, "redstone_torch": 3, "stone": 3},
                "requires_crafting_table": True,
                "cyclic_recipe_dependency_unresolved": True,
            }],
            "unresolved_acquisition_inputs": {"redstone_torch": 3},
            "cycles_detected": ["redstone_torch"],
        },
    })
    row = {facet["label"]: facet for facet in facets}[
        "minecraft.crafting_dependency_alternatives"
    ]
    assert row["decision_constraint"] == {
        "kind": "declared_dependency",
        "requirements": {"redstone_torch": 3},
        "satisfied_effect_targets": (
            {"role": "inventory_gain_target", "value": "quartz", "allocated_count": 1},
            {"role": "inventory_gain_target", "value": "stone", "allocated_count": 3},
        ),
        "valid_until": "physical_effect",
    }


def test_recipe_constraint_never_closes_partially_satisfied_input_with_remaining_debt():
    facets = minecraft_agent_context_facets({
        "inventory": {"quartz": 1},
        "last_action": {"tool": "recipe_dependencies", "item": "target", "count": 1},
        "last_outcome": {
            "status": "applied",
            "code": "RECIPE_DEPENDENCIES_REFERENCED",
            "source": "version_pinned_vanilla_minecraft_data",
            "datapack_rules_included": False,
            "authoritative_for_current_world_recipe": False,
            "no_physical_effect": True,
            "inventory_before": {"quartz": 1},
            "inventory_after_reference_allocation": {"quartz": 0},
            "reference_crafting_steps": [{
                "output_item": "target",
                "output_count": 1,
                "batches": 1,
                "input_items": {"quartz": 3},
                "requires_crafting_table": False,
            }],
            "unresolved_acquisition_inputs": {"quartz": 2},
        },
    })
    row = {facet["label"]: facet for facet in facets}[
        "minecraft.crafting_dependency_alternatives"
    ]
    assert row["decision_constraint"] == {
        "kind": "declared_dependency",
        "requirements": {"quartz": 2},
        "valid_until": "physical_effect",
    }


def test_recipe_context_bounds_alternative_and_local_source_fanout_without_mutating_evidence():
    profiles = [
        {
            "reference_recipe_index": index,
            "unresolved_acquisition_inputs": {f"log_{index}": 1},
            "reference_crafting_steps": [{
                "output_item": "target", "input_items": {f"log_{index}": 1},
                "output_count": 1, "batches": 1,
                "requires_crafting_table": True,
            }],
            "unresolved_kind_count": 1,
            "unobserved_item_quantity": 1,
            "cycles_detected": [],
        }
        for index in range(12)
    ]
    candidates = [
        {
            "source_block": f"log_{index % 3}",
            "position": {"x": index, "y": 64, "z": 0},
            "matched_reference_recipe_indices": [index % 12],
            "physically_acquired": False, "path_reachable": None,
        }
        for index in range(48)
    ]
    outcome = {
        "status": "applied", "code": "RECIPE_DEPENDENCIES_REFERENCED",
        "source": "version_pinned_vanilla_minecraft_data",
        "item": "target", "count": 1, "item_known": True,
        "minecraft_version": "1.21.1",
        "root_alternative_dependency_profiles": profiles,
        "alternative_ranking_semantics": "ranked",
        "selection_semantics": "provider-selected",
        "authoritative_for_current_world_recipe": False,
        "datapack_rules_included": False, "no_physical_effect": True,
        "inventory_before": {},
        "inventory_source": "currently_observed_mineflayer_inventory",
        "observed_local_acquisition_sources": {
            "truth_class": "observed", "loaded_world_only": True,
            "observation_status": "bounded_loaded_world_observed",
            "max_distance": 16,
            "no_global_absence_or_harvestability_claim": True,
            "candidates": candidates,
        },
    }
    before_profiles = [dict(row) for row in profiles]
    before_candidates = [dict(row) for row in candidates]
    facets = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {"tool": "recipe_dependencies", "item": "target"},
        "last_outcome": outcome,
    })
    rows = {row["label"]: row["value"] for row in facets}
    recipes = rows["minecraft.crafting_dependency_alternatives"]
    assert recipes["alternatives"]["count"] == 12
    assert len(recipes["alternatives"]["sample"]) == 4
    assert recipes["alternatives"]["truncated"] is True
    assert recipes["selected"]["recipe_index"] == 0
    sources = rows["minecraft.crafting_local_source_candidates"]
    assert sources["observed_candidate_count"] == 48
    assert sources["count_semantics"] == (
        "observed_presence_only_not_required_acquisition_quantity"
    )
    assert "candidate_witnesses" not in sources
    assert {row["source_block"] for row in sources["reference_matches"]} == {"log_0", "log_1", "log_2"}
    assert all(row["observed_candidate_blocks"] == 16 for row in sources["reference_matches"])
    assert all(row["matching_recipe_requirements"] for row in sources["reference_matches"])
    assert all("position" not in row for row in sources["reference_matches"])
    assert profiles == before_profiles
    assert candidates == before_candidates


def test_missing_craft_materials_is_not_misreported_as_missing_station():
    facets = minecraft_agent_context_facets({
        "inventory": {"oak_log": 3},
        "last_action": {"tool": "craft_item", "item": "stick"},
        "last_outcome": {
            "status": "rejected",
            "code": "NO_RECIPE_OR_MATERIALS",
            "prerequisites": {"executable_inventory_grid_recipe": False},
            "recovery": {"action_type": "recipe_dependencies",
                         "arguments": {"item": "stick", "count": 4}},
        },
    })
    by_label = {row["label"]: row for row in facets}
    assert "minecraft.physical_blocker" not in by_label
    outcome = by_label["minecraft.last_action_feedback"]["value"]["outcome"]
    assert outcome["code"] == "NO_RECIPE_OR_MATERIALS"
    assert outcome["recovery"]["action_type"] == "recipe_dependencies"



def test_rejected_craft_projects_public_recipes_and_physical_stock_separately():
    reference = {
        "item": "stick", "count": 4,
        "source": "version_pinned_vanilla_minecraft_data",
        "authoritative_for_current_world_recipe": False,
        "datapack_rules_included": False, "no_physical_effect": True,
        "inventory_before": {"oak_log": 1},
        "inventory_source": "currently_observed_mineflayer_inventory",
        "root_alternative_dependency_profiles": [{
            "reference_recipe_index": 0,
            "unresolved_acquisition_inputs": {"oak_planks": 2},
        }],
        "observed_local_acquisition_sources": {
            "truth_class": "observed",
            "loaded_world_only": True,
            "observation_status": "bounded_loaded_world_observed",
            "max_distance": 16, "candidates": [{
                "source_block": "oak_log",
                "position": {"x": 2, "y": 64, "z": 2},
                "physically_acquired": False
            }]
        }
    }
    rows = minecraft_agent_context_facets({
        "inventory": {"oak_log": 1},
        "last_action": {"tool": "craft_item", "item": "stick"},
        "last_outcome": {
            "status": "rejected", "code": "NO_RECIPE_OR_MATERIALS",
            "production_reference": reference,
        }
    })
    values = {row["label"]: row for row in rows}
    declared = values["minecraft.crafting_dependency_alternatives"]
    assert declared["truth_class"] == "declared"
    assert declared["value"]["selected"]["unresolved_inputs"] == {"oak_planks": 2}
    assert "alternatives" not in declared["value"]
    assert "root_alternative_dependency_profiles" not in declared["value"]
    assert "inventory_before" not in declared["value"]
    assert "minecraft.crafting_observed_inventory" not in values
    assert values["minecraft.holdings"]["truth_class"] == "observed"
    assert values["minecraft.holdings"]["value"]["item_counts"] == {"oak_log": 1}
    sources = values["minecraft.crafting_local_source_candidates"]
    assert sources["truth_class"] == "observed"
    assert sources["value"]["observed_candidate_count"] == 1
    assert sources["value"]["count_semantics"] == (
        "observed_presence_only_not_required_acquisition_quantity"
    )
    assert sources["value"]["reference_matches"][0]["source_block"] == "oak_log"

def test_action_help_argument_guide_reaches_agent_as_declared_reference_only():
    """Tool help is useful only if the visibility-cut context actually renders it."""
    contract = {
        "action_type": "equip_item", "category": "inventory",
        "argument_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string"},
                "destination": {"type": "string", "enum": ["hand", "head"]},
            },
            "required": ["item"],
            "additionalProperties": False,
        },
    }
    guide = {
        "source": "authorized_environment_capability",
        "truth_class": "declared",
        "action_type": "equip_item",
        "required_parameter_names": ["item"],
        "optional_parameter_names": ["destination"],
        "registry_name_not_possession": True,
    }
    facets = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {"tool": "describe_action", "action_type": "equip_item"},
        "last_outcome": {
            "status": "applied", "code": "ACTION_DESCRIBED",
            "truth_class": "declared", "physical_world_observed": False,
            "authorized": True,
            "action_contract": contract, "argument_guide": guide,
            "invocation_format": {"executable_example": False},
        },
    })
    indexed = {row["label"]: row for row in facets}
    detail = indexed["minecraft.public_reference_not_physical_possession"]
    assert detail["truth_class"] == "declared"
    assert detail["value"]["argument_guide"] == guide
    assert detail["value"]["action_contract"] == contract
    assert indexed["minecraft.holdings"]["truth_class"] == "observed"
    assert indexed["minecraft.holdings"]["value"]["item_counts"] == {}
    assert detail["value"]["physical_world_observed"] is False


def test_last_action_projection_restores_requested_tool_argument_without_wire_collision():
    facets = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {
            "tool": "collect_block",
            "requested_tool": "iron_pickaxe",
            "block": "iron_ore",
            "count": 1,
            "max_distance": 16,
        },
        "last_outcome": {
            "status": "rejected",
            "code": "REQUESTED_TOOL_NOT_AVAILABLE",
            "requested_tool": "iron_pickaxe",
        },
    })
    row = next(
        row for row in facets if row["label"] == "minecraft.last_action_feedback"
    )
    assert row["value"]["action"] == {
        "action_type": "collect_block",
        "block": "iron_ore",
        "count": 1,
        "max_distance": 16,
        "tool": "iron_pickaxe",
    }


def test_partial_collection_reports_verified_action_progress_not_goal_success():
    facets = minecraft_agent_context_facets({
        "inventory": {"oak_log": 2},
        "last_action": {"tool": "collect_block", "block": "oak_log", "count": 4},
        "last_outcome": {
            "status": "partial", "code": "COLLECTION_SEGMENT_APPLIED",
            "requested_count": 4, "collected_count": 2,
            "inventory_delta": {"oak_log": 2},
            "collection_steps": [
                {"source_block": "oak_log", "cumulative_collected_count": 1},
                {"source_block": "oak_log", "cumulative_collected_count": 2},
            ],
        },
    })
    rows = {row["label"]: row for row in facets}
    feedback_row = rows["minecraft.last_action_feedback"]
    outcome = feedback_row["value"]["outcome"]
    assert "decision_constraint" not in feedback_row
    assert outcome["collected_count"] == 2
    assert outcome["progress"] == {
        "requested": 4,
        "observed_collected": 2,
        "remaining_in_request": 2,
        "scope": "this_action_not_task_goal",
    }
    assert "collection_steps" not in outcome
    assert "minecraft.collection_effect_progress" not in rows
    assert rows["minecraft.holdings"]["value"]["item_counts"] == {"oak_log": 2}


def test_collection_feedback_factors_only_same_source_redundancy():
    facets = minecraft_agent_context_facets({
        "inventory": {"cobblestone": 3},
        "last_action": {
            "tool": "collect_block", "block": "stone", "count": 3,
            "max_distance": 16,
        },
        "last_outcome": {
            "status": "applied", "code": "BLOCKS_COLLECTED",
            "requested_count": 3, "requested_resource": "stone",
            "collected_count": 3,
            "inventory_delta": {"cobblestone": 3},
            "collected_delta": {"cobblestone": 3},
            "source_blocks": ["stone"],
            "expected_items": ["cobblestone"],
            "acceptable_tools": ["wooden_pickaxe", "stone_pickaxe"],
            "unreachable_targets": [],
            "requested_tool": None, "tool_constraint_verified": None,
            "world_frontier": {
                "status": "observed_loaded_boundaries",
                "candidates": [],
                "loaded_column_count": 81,
                "searched_max_distance": 16,
            },
        },
    })
    feedback_row = next(row for row in facets
                        if row["label"] == "minecraft.last_action_feedback")
    outcome = feedback_row["value"]["outcome"]
    assert feedback_row["decision_constraint"] == {
        "kind": "bounded_request_completed",
        "requested_count": 3,
        "observed_count": 3,
        "valid_until": "physical_effect",
    }
    assert outcome["inventory_delta"] == {"cobblestone": 3}
    assert outcome["expected_items"] == ["cobblestone"]
    assert outcome["acceptable_tools"] == ["wooden_pickaxe", "stone_pickaxe"]
    assert outcome["collected_count"] == 3
    for redundant in (
        "requested_count", "requested_resource", "collected_delta",
        "source_blocks", "unreachable_targets", "requested_tool",
        "tool_constraint_verified", "world_frontier", "progress",
    ):
        assert redundant not in outcome


def test_collection_request_cannot_invent_observed_progress_without_provider_evidence():
    for last in (
        {"status": "partial", "code": "BLOCKS_COLLECTED", "requested_count": 4},
        {"status": "partial", "code": "BLOCKS_COLLECTED", "requested_count": 4,
         "collected_count": "4"},
        {"status": "partial", "code": "PATH_INTERRUPTED",
         "requested_count": 4, "collected_count": 2},
    ):
        facets = minecraft_agent_context_facets({
            "inventory": {},
            "last_action": {"tool": "collect_block", "count": 4},
            "last_outcome": last,
        })
        outcome = next(row["value"]["outcome"] for row in facets
                       if row["label"] == "minecraft.last_action_feedback")
        assert "progress" not in outcome

def test_compiled_agent_prompt_contains_typed_action_help_and_physical_progress_without_private_claims():
    from noetrium_platform.research.execution.workflow.composition.agent_context import (
        compile_agent_context,
    )
    facets = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {"tool": "describe_action", "action_type": "craft_item"},
        "last_outcome": {
            "code": "ACTION_DESCRIBED", "status": "applied",
            "truth_class": "declared", "authorized": True,
            "physical_world_observed": False,
            "action_contract": {"action_type": "craft_item", "argument_schema": {
                "type": "object", "properties": {"item": {"type": "string"}},
                "required": ["item"], "additionalProperties": False
            }},
            "argument_guide": {"required_parameter_names": ["item"],
                               "truth_class": "declared",
                               "registry_name_not_possession": True},
        },
    })
    view = compile_agent_context({
        "goal": {"goal": "craft the requested item"},
        "environment": facets,
    }).text
    assert "required_parameter_names" in view
    assert "craft_item" in view
    assert "registry_name_not_possession" in view
    assert "ENVIRONMENT_CONTEXT" in view
    assert '"knowledge":{"reference":' in view
    assert '"actor":{"holdings":' in view
    assert "no_hidden_recipe" not in view


def test_exact_target_rejection_remains_agent_visible_without_retargeting():
    facets = minecraft_agent_context_facets({
        "inventory": {"oak_log": 1},
        "last_action": {
            "tool": "collect_block", "block": "oak_log",
            "position": {"x": 6, "y": 64, "z": 0}, "count": 1,
        },
        "last_outcome": {
            "status": "rejected", "code": "EXACT_TARGET_CHANGED",
            "target": {"x": 6, "y": 64, "z": 0},
            "observed_block": "dirt",
        },
    })
    feedback = next(v for v in facets if v["label"] == "minecraft.last_action_feedback")
    assert feedback["value"]["outcome"]["observed_block"] == "dirt"
    assert feedback["value"]["action"]["position"] == {"x": 6, "y": 64, "z": 0}
    assert "progress" not in feedback["value"]["outcome"]


def test_targeted_pickup_context_distinguishes_target_gain_from_incidental_items():
    facets = minecraft_agent_context_facets({
        "inventory": {"dirt": 1},
        "last_action": {"tool": "pickup_items", "item": "oak_log"},
        "last_outcome": {
            "status": "partial", "code": "PICKUP_EFFECT_INCOMPLETE",
            "matching_gain": 0, "gained": 1, "collected": 0,
            "observed_drop_entities": 2, "candidates": 1,
            "skipped_nonmatching_or_unidentified": 1,
        },
    })
    feedback = next(row for row in facets if row["label"] == "minecraft.last_action_feedback")
    assert feedback["value"]["action"]["item"] == "oak_log"
    assert feedback["value"]["outcome"]["matching_gain"] == 0
    assert feedback["value"]["outcome"]["gained"] == 1
    assert "not_proof_of_current_goal" not in feedback["value"]
    assert next(row for row in facets if row["label"] == "minecraft.action_usage")["value"]["effect_scope"] == "bounded_transition_not_task_goal"


def test_single_json_environment_tree_is_decision_only_and_truth_separated():
    import json
    from noetrium_platform.research.execution.workflow.composition.agent_context import (
        compile_agent_context,
    )
    facets = minecraft_agent_context_facets({
        "position": {"x": 2, "y": 64, "z": 4},
        "health": 17,
        "inventory": {"oak_log": 3},
        "last_action": {"tool": "collect_block", "block": "oak_log", "count": 4},
        "last_outcome": {
            "status": "partial", "code": "COLLECTION_SEGMENT_APPLIED",
            "requested_count": 4, "collected_count": 3,
            "inventory_delta": {"oak_log": 3},
            "collection_steps": [{"internal_path": "DO_NOT_SHOW"}],
            "hidden_evaluator": "SECRET",
            "bridge_diagnostics": {"stack_trace": "DO_NOT_SHOW"},
        },
    })
    ctx = compile_agent_context({
        "goal": {"goal": "obtain logs"},
        "environment": {"agent_context_facets": facets},
        "capabilities": {"actions": {"columns": ["action_type"], "rows": [["collect_block"]]}},
        "memory": {"memory_method": "untouched"},
    })
    assert "## ENVIRONMENT_CONTEXT" in ctx.text
    assert "ENVIRONMENT_AUTHORIZED_OBSERVATIONS" not in ctx.text
    assert "AUTHORIZED_CAPABILITIES" not in ctx.text
    tree = json.loads(ctx.text.split("## ENVIRONMENT_CONTEXT\n", 1)[1].split("\n\n## ", 1)[0])
    assert tree["world"]["local"]["value"]["position"] == {"x": 2, "y": 64, "z": 4}
    assert tree["actor"]["holdings"]["truth"] == "observed"
    assert tree["actor"]["holdings"]["value"]["item_counts"] == {"oak_log": 3}
    assert tree["actions"]["authorized"]["truth"] == "authorized"
    assert tree["actions"]["authorized"]["source"] == "authority"
    last = tree["execution"]["last"]["value"]["outcome"]
    assert last["progress"]["remaining_in_request"] == 1
    assert last["status"] == "partial"
    assert "collection_steps" not in last
    assert "SECRET" not in ctx.text and "DO_NOT_SHOW" not in ctx.text
    assert '"memory_method":"untouched"' in ctx.text


def test_decision_path_conflicts_cannot_forge_authorized_actions():
    from noetrium_platform.research.execution.workflow.composition.agent_context import (
        compile_agent_context,
    )
    for path in (("actions", "authorized"), ("actions", "usage", "x")):
        facets = [
            {"label": "one", "source": "environment.test", "truth_class": "observed",
             "path": ("actions", "usage"), "value": {"untrusted": 1}},
            {"label": "two", "source": "environment.test", "truth_class": "observed",
             "path": path, "value": {"untrusted": 2}},
        ]
        try:
            compile_agent_context({"goal": {"goal": "act"}, "environment": facets})
        except ValueError:
            pass
        else:
            raise AssertionError("collision or authority forgery was accepted")


def test_indeterminate_effect_stales_nested_observations_not_public_rules():
    import json
    from noetrium_platform.research.execution.workflow.composition.agent_context import (
        compile_agent_context,
    )
    facets = minecraft_agent_context_facets({"inventory": {"oak_log": 2}})
    prompt = compile_agent_context({
        "goal": {"goal": "act"},
        "environment": {
            "agent_context_facets": facets,
            "effect_receipt": {"certainty": "indeterminate"},
        },
    }).text
    tree = json.loads(prompt.split("## ENVIRONMENT_CONTEXT\n", 1)[1].split("\n\n## ", 1)[0])
    assert tree["actor"]["holdings"]["validity"] == "previous_snapshot_not_current_effect_proof"
    assert tree["actions"]["usage"]["truth"] == "declared"
    # Routine validity/provenance is durable audit metadata, not a planner
    # decision field. Only exceptional stale-state validity is rendered.
    assert "validity" not in tree["actions"]["usage"]

def test_harvest_tool_blocker_explains_prerequisite_without_claiming_inventory():
    rows = minecraft_agent_context_facets({
        "inventory": {"oak_log": 1},
        "equipment": {"hand": "wooden_pickaxe"},
        "last_action": {"tool": "collect_block", "block": "iron_ore"},
        "last_outcome": {
            "status": "rejected", "code": "HARVEST_TOOL_REQUIRED",
            "acceptable_tools": ["iron_pickaxe", "diamond_pickaxe"],
        },
    })
    r = {item["label"]: item for item in rows}
    assert "minecraft.physical_blocker" not in r
    assert "iron_pickaxe" not in r["minecraft.holdings"]["value"]["item_counts"]
    feedback = r["minecraft.last_action_feedback"]["value"]["outcome"]
    assert feedback["status"] == "rejected"
    assert feedback["code"] == "HARVEST_TOOL_REQUIRED"
    assert feedback["acceptable_tools"] == ["iron_pickaxe", "diamond_pickaxe"]


def test_partial_navigation_failure_exposes_observed_displacement_not_global_no_path():
    rows = minecraft_agent_context_facets({
        "position": {"x": 13, "y": 64, "z": -9},
        "last_action": {"tool": "goto_block", "block": "oak_log"},
        "last_outcome": {
            "status": "partial", "code": "PATH_INTERRUPTED",
            "moved": 4.75,
            "navigation_error": {"name": "NoPath", "code": "NoPath",
                                 "stack": "PRIVATE_STACK", "message": "private map"}
        },
    })
    indexed = {item["label"]: item for item in rows}
    progress = indexed["minecraft.navigation_effect_progress"]
    assert progress["truth_class"] == "observed"
    assert progress["value"]["displacement_blocks"] == 4.75
    assert progress["value"]["physical_displacement_observed"] is True
    assert progress["value"]["destination_confirmed"] is False
    assert progress["value"]["navigation_error"] == {"name": "NoPath", "code": "NoPath"}
    assert "minecraft.physical_blocker" not in indexed
    feedback = indexed["minecraft.last_action_feedback"]["value"]["outcome"]
    assert feedback["status"] == "partial"
    assert feedback["code"] == "PATH_INTERRUPTED"
    assert "PRIVATE_STACK" not in str(rows)
    assert "private map" not in str(rows)


def test_combat_evidence_projects_own_attack_and_weapon_reference_without_forging_victory():
    from noetrium_platform.research.execution.workflow.composition.agent_context import (
        compile_agent_context,
    )
    rows = minecraft_agent_context_facets({
        "inventory": {"wooden_sword": 1, "diamond_sword": 1},
        "last_action": {"tool": "attack_nearest"},
        "last_outcome": {
            "code": "TARGET_HIT_CONFIRMED", "status": "applied",
            "weapon": "diamond_sword", "attack_signals": 2,
            "hurt_signals": 1, "own_hurt_signals": 1,
            "target_valid_after": True,
            "weapon_selection": {
                "selected_weapon": "diamond_sword",
                "selection_basis": "versioned_registry_damage_then_weapon_category_and_remaining_durability",
                "selected_durability_remaining": 1561,
                "registry_damage_available": False,
                "equipped": True,
            },
        },
    })
    indexed = {row["label"]: row for row in rows}
    effects = indexed["minecraft.combat_effect_evidence"]
    assert effects["truth_class"] == "observed"
    assert effects["value"]["own_hurt_signals"] == 1
    assert effects["value"]["target_valid_after"] is True
    assert effects["value"]["not_a_benchmark_goal_judgment"] is True
    reference = indexed["minecraft.combat_equipment_selection_reference"]
    assert reference["truth_class"] == "declared"
    assert reference["value"]["selected_weapon"] == "diamond_sword"
    text = compile_agent_context({
        "goal": {"goal": "fight a visible enemy"},
        "environment": rows,
    }).text
    assert '"combat_evidence"' in text
    assert '"weapon_reference"' in text
    assert "not_an_optimal_strategy_or_dps_proof" in text


def test_third_party_ranged_damage_does_not_enter_context_as_attributed_hit():
    rows = minecraft_agent_context_facets({
        "inventory": {"bow": 1, "arrow": 2},
        "last_action": {"tool": "ranged_attack"},
        "last_outcome": {
            "code": "SHOTS_RELEASED_HIT_UNCONFIRMED", "status": "partial",
            "shots_released": 1, "ammo_consumed": 1,
            "hurt_signals": 1, "own_hurt_signals": 0,
            "damage_attribution": "other_or_unknown_source",
            "navigation_error": {
                "name": "NoPath", "stack": "private_navigation_trace",
            },
        },
    })
    indexed = {row["label"]: row for row in rows}
    progress = indexed["minecraft.combat_effect_evidence"]
    assert progress["truth_class"] == "observed"
    assert progress["value"]["own_hurt_signals"] == 0
    assert progress["value"]["unattributed_damage_not_credited"] is True
    assert progress["value"]["outcome_code"] == "SHOTS_RELEASED_HIT_UNCONFIRMED"
    assert "private_navigation_trace" not in str(rows)
    assert "TARGET_HIT_ATTRIBUTED_TO_OWN_SHOT" not in str(rows)


def test_action_usage_invariants_preserve_method_owned_goal_decomposition_without_leaking_actions():
    facets = minecraft_agent_context_facets({"inventory": {"oak_log": 1}})
    by_label = {facet["label"]: facet for facet in facets}
    usage = by_label["minecraft.action_usage"]
    assert usage["truth_class"] == "declared"
    value = usage["value"]
    assert value["action_scope"] == "authorized_catalog_only"
    assert value["count_scope"] == "bounded_action_effect_only"
    assert value["strategy_owner"] == "method"
    rendered = str(value)
    for action_name in (
        "collect_block", "craft_item", "pickup_items", "describe_action",
        "registry_search", "recipe_dependencies", "obtain_item",
    ):
        assert action_name not in rendered
    assert by_label["minecraft.holdings"]["value"]["item_counts"] == {"oak_log": 1}


def test_unfiltered_block_scan_is_summary_only_but_explicit_query_keeps_witnesses():
    blocks = [
        {"name": "oak_log", "position": {"x": 2, "y": 64, "z": 2}, "distance": 2.8},
        {"name": "stone", "position": {"x": 3, "y": 63, "z": 1}, "distance": 3.1},
    ]
    base_outcome = {
        "status": "applied", "code": "BLOCKS_OBSERVED",
        "truth_class": "observed", "authoritative_for_current_world": True,
        "loaded_world_only": True, "observed_count": 2,
        "searched_max_distance": 16, "counts": {"oak_log": 1, "stone": 1},
        "blocks": blocks,
    }
    summary = minecraft_agent_context_facets({
        "last_action": {"tool": "observe_blocks", "max_distance": 16},
        "last_outcome": base_outcome,
    })
    summary_value = next(
        row["value"] for row in summary if row["label"] == "minecraft.local_sensing"
    )
    assert "blocks" not in summary_value
    assert summary_value["counts"] == {"oak_log": 1, "stone": 1}
    assert summary_value["detail_scope"] == "summary_until_explicit_query"

    detailed = minecraft_agent_context_facets({
        "last_action": {
            "tool": "observe_blocks", "query": "oak_log", "max_distance": 16,
        },
        "last_outcome": {**base_outcome, "query": "oak_log"},
    })
    detailed_value = next(
        row["value"] for row in detailed if row["label"] == "minecraft.local_sensing"
    )
    assert detailed_value["query"] == "oak_log"
    decoded = _decode_row_table(detailed_value["blocks"])
    assert tuple(decoded) == tuple(blocks)
    assert "detail_scope" not in detailed_value


def test_exact_block_observation_reaches_agent_context_without_route_oracle():
    rows = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {
            "tool": "observe_blocks",
            "position": {"x": 3, "y": 61, "z": -2},
            "max_distance": 16,
        },
        "last_outcome": {
            "status": "applied",
            "code": "BLOCK_POSITION_OBSERVED",
            "truth_class": "observed",
            "authoritative_for_current_world": True,
            "loaded_world_only": True,
            "exact_position": {"x": 3, "y": 61, "z": -2},
            "searched_max_distance": 16,
            "distance": 5.0,
            "observed": True,
            "block": {
                "name": "stone",
                "position": {"x": 3, "y": 61, "z": -2},
                "distance": 5.0,
                "metadata": 0,
                "waterlogged": False,
            },
        },
    })
    indexed = {row["label"]: row for row in rows}
    sensing = indexed["minecraft.local_sensing"]
    assert sensing["truth_class"] == "observed"
    assert sensing["value"]["exact_position"] == {"x": 3, "y": 61, "z": -2}
    assert sensing["value"]["block"]["name"] == "stone"
    assert "route" not in str(sensing["value"]).lower()


def test_excavation_partial_feedback_preserves_completed_prefix_and_non_strategic_blocker():
    rows = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {
            "tool": "excavate_region",
            "corner_a": {"x": 1, "y": 64, "z": 0},
            "corner_b": {"x": 4, "y": 65, "z": 0},
        },
        "last_outcome": {
            "status": "partial",
            "code": "EXCAVATION_BOUND_REACHED",
            "region": {
                "min": {"x": 1, "y": 64, "z": 0},
                "max": {"x": 4, "y": 65, "z": 0},
                "volume": 8,
            },
            "removed": ({"x": 1, "y": 64, "z": 0},),
            "removed_count": 1,
            "remaining_count": 7,
            "remaining": ({"name": "stone", "position": {"x": 2, "y": 64, "z": 0}},),
            "max_blocks": 1,
            "child_results": (),
        },
    })
    indexed = {row["label"]: row for row in rows}
    feedback = indexed["minecraft.last_action_feedback"]["value"]["outcome"]
    assert feedback["removed_count"] == 1
    assert feedback["remaining_count"] == 7
    assert "minecraft.physical_blocker" not in indexed
    assert feedback["code"] == "EXCAVATION_BOUND_REACHED"
    assert feedback["status"] == "partial"


def test_exact_tool_and_ammunition_failures_are_agent_visible_without_auto_strategy():
    cases = (
        (
            "collect_block",
            {"status": "rejected", "code": "REQUESTED_TOOL_NOT_AVAILABLE"},
        ),
        (
            "fire_projectile",
            {
                "status": "rejected", "code": "AMMUNITION_NOT_AVAILABLE",
                "weapon": "bow", "ammo": "arrow", "available": 0,
                "requested_shots": 1,
            },
        ),
    )
    for action_type, outcome in cases:
        rows = minecraft_agent_context_facets({
            "inventory": {},
            "last_action": {"tool": action_type},
            "last_outcome": outcome,
        })
        indexed = {row["label"]: row for row in rows}
        assert "minecraft.physical_blocker" not in indexed
        feedback = indexed["minecraft.last_action_feedback"]["value"]["outcome"]
        assert feedback["code"] == outcome["code"]
        assert feedback["status"] == "rejected"


def test_excavation_agent_projection_is_bounded_while_evidence_can_remain_complete():
    removed = tuple({"x": i, "y": 64, "z": 0} for i in range(20))
    remaining = tuple(
        {"name": "stone", "position": {"x": i, "y": 65, "z": 0}}
        for i in range(16)
    )
    children = tuple(
        {"index": i, "status": "applied", "code": "BLOCK_REMOVED"}
        for i in range(20)
    )
    rows = minecraft_agent_context_facets({
        "last_action": {
            "tool": "excavate_region",
            "corner_a": {"x": 0, "y": 64, "z": 0},
            "corner_b": {"x": 15, "y": 65, "z": 0},
            "max_blocks": 20,
        },
        "last_outcome": {
            "status": "partial", "code": "EXCAVATION_BOUND_REACHED",
            "removed": removed, "removed_count": 20,
            "remaining": remaining, "remaining_count": 16,
            "child_results": children, "max_blocks": 20,
        },
    })
    indexed = {row["label"]: row for row in rows}
    value = indexed["minecraft.last_action_feedback"]["value"]
    outcome = value["outcome"]
    assert len(outcome["removed"]) == 8
    assert outcome["removed_truncated"] is True
    assert len(outcome["remaining"]) == 8
    assert outcome["remaining_truncated"] is True
    assert outcome["child_effect_summary"] == {
        "count": 20,
        "status_counts": {"applied": 20},
        "full_rows_retained_in_evidence_only": True,
    }
    assert "child_results" not in outcome
    assert value["action"]["max_blocks"] == 20


def test_action_usage_physical_truth_explicitly_separates_registry_names_from_possession():
    facets = minecraft_agent_context_facets({"inventory": {}})
    usage = next(
        row["value"] for row in facets
        if row["label"] == "minecraft.action_usage"
    )
    assert usage["reference_truth"] == "declared_not_physical"
    assert usage["observation_scope"] == "loaded_world_not_global"


def test_generic_blocker_preserves_distinct_source_facts_across_v112_style_rejection_cycle():
    states = (
        {
            "inventory": {},
            "equipment": {"hand": None},
            "last_action": {"tool": "collect_block", "block": "iron_ore"},
            "last_outcome": {
                "status": "rejected",
                "code": "HARVEST_TOOL_REQUIRED",
                "semantic_domain": "minecraft.block_or_block_drop_name",
                "acceptable_tools": ["stone_pickaxe", "iron_pickaxe"],
                "prerequisites": {
                    "acceptable_tools": ["stone_pickaxe", "iron_pickaxe"],
                    "held_tool": None,
                },
            },
        },
        {
            "inventory": {},
            "equipment": {"hand": None},
            "last_action": {"tool": "equip_item", "item": "stone_pickaxe"},
            "last_outcome": {
                "status": "rejected",
                "code": "ITEM_NOT_AVAILABLE",
                "semantic_domain": "minecraft.item_name",
                "target_classification": "item",
                "prerequisites": {
                    "inventory_contains_requested_item": False,
                    "exact_registry_item": True,
                    "available_concrete_items": [],
                },
            },
        },
    )
    projected = []
    for state in states:
        indexed = {row["label"]: row for row in minecraft_agent_context_facets(state)}
        assert "minecraft.physical_blocker" not in indexed
        feedback = indexed["minecraft.last_action_feedback"]["value"]["outcome"]
        protocol = indexed["minecraft.action_usage"]["value"]
        projected.append((feedback, protocol))

    harvest_feedback, harvest_protocol = projected[0]
    equip_feedback, equip_protocol = projected[1]
    assert harvest_feedback["code"] == "HARVEST_TOOL_REQUIRED"
    assert harvest_feedback["acceptable_tools"] == ["stone_pickaxe", "iron_pickaxe"]
    assert harvest_feedback["prerequisites"]["held_tool"] is None
    assert equip_feedback["code"] == "ITEM_NOT_AVAILABLE"
    assert equip_feedback["target_classification"] == "item"
    assert equip_feedback["prerequisites"]["inventory_contains_requested_item"] is False
    assert harvest_protocol["rejected_retry"] == equip_protocol["rejected_retry"] == "change_evidence_or_arguments"
    assert harvest_protocol["partial_progress"] == equip_protocol["partial_progress"] == "preserve"
    assert "direction" not in harvest_feedback
    assert "direction" not in equip_feedback


def test_version_pinned_public_reference_declares_history_retention_without_changing_truth():
    facets = minecraft_agent_context_facets({
        "inventory": {},
        "last_action": {"tool": "recipe_lookup", "item": "wooden_hoe"},
        "last_outcome": {
            "status": "applied",
            "code": "VANILLA_RECIPES_REFERENCED",
            "truth_class": "declared",
            "source": "version_pinned_vanilla_minecraft_data",
            "authoritative_for_current_world": False,
            "datapack_rules_included": False,
            "minecraft_version": "1.21.1",
            "item": "wooden_hoe",
            "item_known": True,
            "recipe_kind": "crafting_only",
            "recipes": (),
            "recipes_recorded": 0,
            "recipes_truncated": False,
        },
    })
    reference = next(
        row for row in facets
        if row["label"] == "minecraft.public_reference_not_physical_possession"
    )
    assert reference["truth_class"] == "declared"
    assert reference["history_retention"] == "source_declared_reference"
    assert reference["value"]["authoritative_for_current_world"] is False


def test_recipe_lookup_marks_input_relation_unquantified_until_dependency_resolver():
    facets = minecraft_agent_context_facets({
        "inventory": {"oak_log": 8},
        "last_action": {"tool": "recipe_lookup", "item": "oak_planks", "limit": 20},
        "last_outcome": {
            "status": "applied",
            "code": "VANILLA_RECIPES_REFERENCED",
            "truth_class": "declared",
            "item": "oak_planks",
            "item_known": True,
            "minecraft_version": "1.20.1",
            "source": "version_pinned_vanilla_minecraft_data",
            "authoritative_for_current_world": False,
            "datapack_rules_included": False,
            "recipe_kind": "crafting_only",
            "recipes_recorded": 1,
            "recipes_truncated": False,
            "recipes": [{
                "type": "shaped",
                "shape": [["oak_log"]],
                "result_count": 4,
                "requires_crafting_table": False,
            }],
        },
    })
    row = next(
        row for row in facets
        if row["label"] == "minecraft.public_reference_not_physical_possession"
    )
    assert row["decision_constraint"] == {
        "kind": "unquantified_dependency_reference",
        "unquantified_effect_targets": (
            {"role": "inventory_gain_target", "value": "oak_log"},
        ),
        "resolver": {
            "action_type": "recipe_dependencies",
            "arguments": {"item": "oak_planks"},
            "required_arguments": ("count",),
        },
        "valid_until": "physical_effect",
    }
    # Control metadata is not copied into the model-visible reference value.
    assert "resolver" not in row["value"]
    assert "unquantified_effect_targets" not in row["value"]
