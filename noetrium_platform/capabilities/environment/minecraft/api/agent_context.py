"""Minecraft-owned public context projection into environment-neutral facets.

The universal context compiler never knows about blocks, health, inventory,
equipment or recipes. This provider projects ONLY the observation already
passed through the single Minecraft visibility cut.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _fields(row: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: row[name] for name in names if name in row}


def _present_fields(row: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """Decision projection of present non-null source fields only."""
    return {
        name: row[name]
        for name in names
        if name in row and row[name] is not None
    }


def _decision_last_action(raw: object) -> object:
    """Present bridge action evidence in planner vocabulary, not wire ABI.

    The bridge reserves ``action.tool`` for the command identity. Actions whose
    public arguments also include ``tool`` preserve that argument as
    ``requested_tool`` in durable evidence. Reconstruct the planner-facing
    shape so the model never sees the command name masquerading as a tool
    argument.
    """
    if not isinstance(raw, Mapping):
        return raw
    action_type = raw.get("tool") or raw.get("action_type")
    compact = _present_fields(raw, (
        "item", "block", "count", "destination", "position", "entity",
        "player", "max_distance", "effect", "query", "corner_a",
        "corner_b", "max_blocks", "weapon", "shots",
    ))
    result: dict[str, Any] = {}
    if isinstance(action_type, str) and action_type.strip():
        result["action_type"] = action_type
    result.update(compact)
    requested_tool = raw.get("requested_tool")
    if isinstance(requested_tool, str) and requested_tool.strip():
        result["tool"] = requested_tool
    return result


def _decision_equipment(raw: object) -> object:
    """Keep equipment identity and normalized remaining durability only."""
    if not isinstance(raw, Mapping):
        return raw
    compact: dict[str, Any] = {}
    for slot, item in raw.items():
        if item is None:
            compact[str(slot)] = None
            continue
        if isinstance(item, Mapping):
            value = _present_fields(item, (
                "name", "count", "durability_remaining_ratio",
            ))
            compact[str(slot)] = value if value else None
        else:
            compact[str(slot)] = item
    return compact


def _decision_nearby_entities(raw: object) -> object:
    """Drop entity transport/debug coordinates when action identity suffices."""
    if not (isinstance(raw, Sequence) and not isinstance(
        raw, (str, bytes, bytearray)
    )):
        return raw
    rows = tuple(
        _present_fields(row, (
            "runtime_id", "name", "mob_type", "type", "username", "distance",
        ))
        for row in raw if isinstance(row, Mapping)
    )
    return _lossless_row_table(rows)


def _lossless_row_table(raw: object) -> object:
    """Factor repeated keys from homogeneous public evidence rows.

    This is a presentation-only bijection for rows with one shared ordered
    schema. Heterogeneous or tiny inputs stay row-oriented, so this never
    invents, drops, ranks, or truncates provider evidence. The fast path does
    no JSON sizing and no row copies; it only removes repeated field names.
    """
    if not (isinstance(raw, Sequence) and not isinstance(
        raw, (str, bytes, bytearray)
    )):
        return raw
    rows = tuple(raw)
    if len(rows) < 3 or not isinstance(rows[0], Mapping):
        return raw
    fields = tuple(rows[0])
    if any(
        not isinstance(row, Mapping) or tuple(row) != fields
        for row in rows[1:]
    ):
        return raw
    return {
        "row_count": len(rows),
        "fields": fields,
        "rows": tuple(tuple(row.values()) for row in rows),
    }


def _compact_world_frontier(raw: object) -> object:
    if not isinstance(raw, Mapping):
        return raw
    result = dict(raw)
    candidates = raw.get("candidates")
    if not (isinstance(candidates, Sequence) and not isinstance(
        candidates, (str, bytes, bytearray)
    )):
        return result

    # Frontier candidates repeat two values that are mechanically derivable
    # from the chunk coordinates and often repeat one entirely-unobserved
    # reachability column.  Factor only when the complete source rows prove
    # the relation.  Every candidate remains represented; this is a bijective
    # source-owned encoding, not ranking or truncation.  The threshold avoids
    # paying metadata/CPU overhead for tiny frontiers where row form is cheaper.
    rows = tuple(candidates)
    if len(rows) < 8 or any(not isinstance(row, Mapping) for row in rows):
        result["candidates"] = _lossless_row_table(candidates)
        return result
    fields = tuple(rows[0])
    derived_centers = True
    unobserved_path = True
    for row in rows:
        if tuple(row) != fields:
            result["candidates"] = _lossless_row_table(candidates)
            return result
        if derived_centers and not (
            type(row.get("chunk_x")) is int
            and type(row.get("chunk_z")) is int
            and row.get("center_x") == row["chunk_x"] * 16 + 8
            and row.get("center_z") == row["chunk_z"] * 16 + 8
        ):
            derived_centers = False
        if unobserved_path and not (
            "path_reachable" in row and row["path_reachable"] is None
        ):
            unobserved_path = False

    derived: dict[str, object] = {}
    omitted: set[str] = set()
    if derived_centers:
        omitted.update(("center_x", "center_z"))
        derived.update({
            "center_x": "chunk_x*16+8",
            "center_z": "chunk_z*16+8",
        })
    if unobserved_path:
        omitted.add("path_reachable")
        derived["path_reachable"] = None

    if not omitted:
        result["candidates"] = _lossless_row_table(candidates)
        return result
    retained_fields = tuple(field for field in fields if field not in omitted)
    result["candidates"] = {
        "row_count": len(rows),
        "fields": retained_fields,
        "rows": tuple(
            tuple(row[field] for field in retained_fields)
            for row in rows
        ),
    }
    result["derived_candidate_fields"] = derived
    return result


def _compact_public_action_outcome(
    action: Mapping[str, Any] | None,
    outcome: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove only mechanically redundant fields from decision feedback.

    Durable Provider evidence remains complete.  This projection never drops
    an independent prerequisite, recovery hint, non-empty tool constraint, or
    physical delta; it factors values exactly recoverable from the same public
    action/outcome pair.
    """
    result = dict(outcome)
    action = action if isinstance(action, Mapping) else {}
    for field in (
        "acceptable_tools", "unreachable_targets",
        "requested_tool", "tool_constraint_verified",
    ):
        if field in result and result[field] in (None, (), [], {}):
            result.pop(field)

    # Partial/recovered transitions need their explicit requested/effected
    # scope for causal reasoning.  Do not make the model reconstruct a
    # partial-effect proof from action arguments plus unrelated current state.
    if result.get("status") == "partial":
        return result

    requested_count = result.get("requested_count")
    if type(requested_count) is int and action.get("count") == requested_count:
        result.pop("requested_count", None)
    requested_resource = result.get("requested_resource")
    if (
        isinstance(requested_resource, str)
        and action.get("block") == requested_resource
    ):
        result.pop("requested_resource", None)

    if (
        "collected_delta" in result
        and "inventory_delta" in result
        and result["collected_delta"] == result["inventory_delta"]
    ):
        result.pop("collected_delta")

    progress = result.get("progress")
    if (
        isinstance(progress, Mapping)
        and type(progress.get("requested")) is int
        and type(progress.get("observed_collected")) is int
        and progress.get("requested") == action.get("count")
        and progress.get("observed_collected") == result.get("collected_count")
        and progress.get("remaining_in_request")
        == max(0, progress["requested"] - progress["observed_collected"])
        and result.get("status") != "partial"
    ):
        result.pop("progress")

    resource = requested_resource or action.get("block")
    if isinstance(resource, str):
        for field in ("source_blocks", "expected_items"):
            rows = result.get(field)
            if (
                isinstance(rows, Sequence)
                and not isinstance(rows, (str, bytes, bytearray))
                and len(rows) == 1
                and rows[0] == resource
            ):
                result.pop(field)

    frontier = result.get("world_frontier")
    action_name = action.get("tool") or action.get("action_type")
    if isinstance(frontier, Mapping) and action_name != "observe_blocks":
        candidates = frontier.get("candidates")
        empty_candidates = (
            candidates in (None, (), [], {})
            or (
                isinstance(candidates, Mapping)
                and candidates.get("row_count") == 0
            )
        )
        if empty_candidates:
            result.pop("world_frontier")
    return result


def _bounded_request_completion_constraint(
    action: Mapping[str, Any] | None,
    outcome: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Declare completion of one bounded collect request, not task success."""
    action = action if isinstance(action, Mapping) else {}
    action_name = action.get("tool") or action.get("action_type")
    requested = outcome.get("requested_count")
    observed = outcome.get("collected_count")
    if not (
        action_name == "collect_block"
        and outcome.get("status") == "applied"
        and outcome.get("code") == "BLOCKS_COLLECTED"
        and type(requested) is int and 0 < requested <= 64
        and action.get("count") == requested
        and type(observed) is int and observed >= requested
    ):
        return None
    return {
        "kind": "bounded_request_completed",
        "requested_count": requested,
        "observed_count": observed,
        "valid_until": "physical_effect",
    }


def _bounded_recipe_reference(row: Mapping[str, Any]) -> dict[str, Any]:
    """Decision-minimal recipe reference; full reference remains durable.

    The planner needs the declared input transformation, unresolved acquisition
    debt, station requirement and materially distinct alternatives. Provenance,
    ranking explanations and audit disclaimers stay in source evidence rather
    than being re-transmitted on every decision.
    """
    result: dict[str, Any] = {
        **_present_fields(row, ("item", "count")),
        "authority": "declared_vanilla_reference",
    }
    if row.get("item_known") is False:
        result["item_known"] = False
    if row.get("root_recipes_truncated") is True:
        result["root_recipes_truncated"] = True

    raw_profiles = row.get("root_alternative_dependency_profiles", ())
    profiles = (
        tuple(profile for profile in raw_profiles if isinstance(profile, Mapping))
        if isinstance(raw_profiles, Sequence)
        and not isinstance(raw_profiles, (str, bytes, bytearray))
        else ()
    )
    selected_profile = profiles[0] if profiles else {}
    raw_steps = row.get("reference_crafting_steps")
    if not (isinstance(raw_steps, Sequence) and not isinstance(
        raw_steps, (str, bytes, bytearray)
    )):
        raw_steps = selected_profile.get("reference_crafting_steps", ())
    steps = []
    if isinstance(raw_steps, Sequence) and not isinstance(
        raw_steps, (str, bytes, bytearray)
    ):
        for step in raw_steps:
            if not isinstance(step, Mapping):
                continue
            compact = _present_fields(step, (
                "output_item", "output_count", "batches", "input_items",
                "requires_crafting_table",
            ))
            if step.get("cyclic_recipe_dependency_unresolved") is True:
                compact["cyclic_dependency"] = True
            steps.append(compact)

    unresolved = row.get("unresolved_acquisition_inputs")
    if not isinstance(unresolved, Mapping):
        unresolved = selected_profile.get("unresolved_acquisition_inputs", {})
    unresolved = dict(unresolved) if isinstance(unresolved, Mapping) else {}
    cycles = row.get("cycles_detected")
    if not (isinstance(cycles, Sequence) and not isinstance(
        cycles, (str, bytes, bytearray)
    )):
        cycles = selected_profile.get("cycles_detected", ())
    cycles = tuple(cycles) if isinstance(cycles, Sequence) and not isinstance(
        cycles, (str, bytes, bytearray)
    ) else ()

    selected: dict[str, Any] = {
        **({"recipe_index": selected_profile["reference_recipe_index"]}
           if "reference_recipe_index" in selected_profile else {}),
        "steps": tuple(steps),
        "unresolved_inputs": unresolved,
    }
    if cycles:
        selected["cycles"] = cycles
    result["selected"] = selected

    # Only multiple materially distinct root alternatives affect the next
    # decision. One alternative needs no count/sample wrapper.
    if len(profiles) > 1:
        sample = []
        for profile in profiles[:4]:
            shortages = profile.get("unresolved_acquisition_inputs", {})
            profile_cycles = profile.get("cycles_detected", ())
            sample.append({
                **_present_fields(profile, (
                    "reference_recipe_index", "result_count_per_batch",
                )),
                "unresolved_inputs": (
                    dict(shortages) if isinstance(shortages, Mapping) else {}
                ),
                "cycle_count": (
                    len(profile_cycles) if isinstance(profile_cycles, Sequence)
                    and not isinstance(profile_cycles, (str, bytes, bytearray)) else 0
                ),
            })
        result["alternatives"] = {
            "count": len(profiles),
            "sample": tuple(sample),
            **({"truncated": True} if len(profiles) > 4 else {}),
        }
    # Source opt-in used by execution-history retention. It is compact and
    # provider-owned; the complete reference remains in the durable outcome.
    return result

def _declared_dependency_constraint(
    recipe_view: Mapping[str, Any],
    source_reference: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Source-owned unresolved dependency debt for cross-observation planning.

    This metadata is not rendered directly to the model: the current recipe
    facet already exposes the same declared facts. It exists only so a generic
    planner can retain the minimal unresolved obligation across later PURE
    observations without understanding Minecraft recipe fields.
    """
    selected = recipe_view.get("selected")
    if not isinstance(selected, Mapping):
        return None
    raw = selected.get("unresolved_inputs")
    if not isinstance(raw, Mapping):
        return None
    requirements = {
        str(name): count
        for name, count in raw.items()
        if isinstance(name, str) and name and type(count) is int and count > 0
    }
    if not requirements:
        return None

    # The Provider's reference allocator consumes a COPY of the latest
    # observed inventory.  A positive before→after decrement therefore proves
    # that quantity was already assigned to this selected reference path.  It
    # is a planner-control fact only: no physical inventory was changed.
    # Never close a target that still appears in unresolved debt; partial
    # allocation is not satisfaction.
    satisfied_targets: list[dict[str, Any]] = []
    source = source_reference if isinstance(source_reference, Mapping) else {}
    before = source.get("inventory_before", {})
    after = source.get("inventory_after_reference_allocation", {})
    before = before if isinstance(before, Mapping) else {}
    after = after if isinstance(after, Mapping) else {}
    selected_steps = selected.get("steps", ())
    input_names: set[str] = set()
    if isinstance(selected_steps, Sequence) and not isinstance(
        selected_steps, (str, bytes, bytearray)
    ):
        for step in selected_steps:
            if not isinstance(step, Mapping):
                continue
            inputs = step.get("input_items", {})
            if isinstance(inputs, Mapping):
                input_names.update(
                    str(name) for name in inputs
                    if isinstance(name, str) and name
                )
    for name in sorted(input_names):
        if name in requirements:
            continue
        before_count = before.get(name, 0)
        after_count = after.get(name, before_count)
        if (
            type(before_count) is int and before_count >= 0
            and type(after_count) is int and after_count >= 0
            and before_count > after_count
        ):
            satisfied_targets.append({
                "role": "inventory_gain_target",
                "value": name,
                "allocated_count": before_count - after_count,
            })

    return {
        "kind": "declared_dependency",
        "requirements": dict(sorted(requirements.items())),
        **({"satisfied_effect_targets": tuple(satisfied_targets)}
           if satisfied_targets else {}),
        "valid_until": "physical_effect",
    }


def _unquantified_dependency_reference_constraint(
    reference: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Expose input relevance without inventing a quantity deficit.

    A plain recipe lookup owns the declared input relation but explicitly does
    not inspect current inventory or requested output quantity.  Publish that
    authority boundary as control metadata so Method cannot turn a weak public
    reference into repeated physical acquisition.  The source also names the
    stronger observation that can resolve the missing quantity.
    """
    if (
        reference.get("source") != "version_pinned_vanilla_minecraft_data"
        or reference.get("authoritative_for_current_world") is not False
        or reference.get("datapack_rules_included") is not False
    ):
        return None
    item = reference.get("item")
    recipes = reference.get("recipes")
    if (
        not isinstance(item, str) or not item
        or isinstance(recipes, (str, bytes, bytearray))
        or not isinstance(recipes, Sequence)
    ):
        return None
    inputs: set[str] = set()
    for recipe in recipes:
        if not isinstance(recipe, Mapping):
            continue
        shape = recipe.get("shape")
        if isinstance(shape, Sequence) and not isinstance(shape, (str, bytes, bytearray)):
            for row in shape:
                if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
                    inputs.update(
                        value for value in row
                        if isinstance(value, str) and value
                    )
        ingredients = recipe.get("ingredients")
        if isinstance(ingredients, Sequence) and not isinstance(
            ingredients, (str, bytes, bytearray)
        ):
            inputs.update(
                value for value in ingredients
                if isinstance(value, str) and value
            )
    if not inputs:
        return None
    return {
        "kind": "unquantified_dependency_reference",
        "unquantified_effect_targets": tuple(
            {"role": "inventory_gain_target", "value": value}
            for value in sorted(inputs)
        ),
        "resolver": {
            "action_type": "recipe_dependencies",
            "arguments": {"item": item},
            "required_arguments": ("count",),
        },
        "valid_until": "physical_effect",
    }


def _bounded_local_acquisition_sources(
    row: Mapping[str, Any],
    dependency_reference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decision-minimal local source evidence without quantity ambiguity.

    Physical candidate cardinality and recipe input debt are different facts.
    Keep them adjacent, but never let an observed count masquerade as a required
    acquisition quantity.  Requirement rows are joined only by the provider's
    own reference-recipe indices; no strategy or preferred material is inferred.
    """
    result = _present_fields(row, (
        "observation_status", "max_distance",
    ))
    result["scope"] = "loaded_world_presence_not_harvestability"
    raw = row.get("candidates", ())
    candidates = (
        tuple(candidate for candidate in raw if isinstance(candidate, Mapping))
        if isinstance(raw, Sequence)
        and not isinstance(raw, (str, bytes, bytearray))
        else ()
    )
    counts: dict[str, int] = {}
    relations: dict[str, dict[str, set[Any]]] = {}
    for candidate in candidates:
        block = candidate.get("source_block")
        if not isinstance(block, str) or not block:
            continue
        counts[block] = counts.get(block, 0) + 1
        relation = relations.setdefault(block, {"items": set(), "recipes": set()})
        names = candidate.get("matched_reference_item_names", ())
        if isinstance(names, Sequence) and not isinstance(names, (str, bytes, bytearray)):
            relation["items"].update(name for name in names if isinstance(name, str) and name)
        indices = candidate.get("matched_reference_recipe_indices", ())
        if isinstance(indices, Sequence) and not isinstance(indices, (str, bytes, bytearray)):
            relation["recipes"].update(index for index in indices if type(index) is int)
    result["observed_candidate_count"] = len(candidates)
    result["count_semantics"] = "observed_presence_only_not_required_acquisition_quantity"

    requirements_by_recipe: dict[int, dict[str, int]] = {}
    if isinstance(dependency_reference, Mapping):
        profiles = dependency_reference.get("root_alternative_dependency_profiles", ())
        if isinstance(profiles, Sequence) and not isinstance(
            profiles, (str, bytes, bytearray)
        ):
            for profile in profiles:
                if not isinstance(profile, Mapping):
                    continue
                recipe_index = profile.get("reference_recipe_index")
                unresolved = profile.get("unresolved_acquisition_inputs")
                if type(recipe_index) is not int or not isinstance(unresolved, Mapping):
                    continue
                required = {
                    str(name): count
                    for name, count in unresolved.items()
                    if isinstance(name, str) and name and type(count) is int and count > 0
                }
                if required:
                    requirements_by_recipe[recipe_index] = dict(sorted(required.items()))

    if relations:
        matches = []
        for block, value in sorted(relations.items()):
            recipe_indices = tuple(sorted(value["recipes"]))
            requirement_profiles = tuple(
                {
                    "recipe_index": index,
                    "unresolved_inputs": requirements_by_recipe[index],
                }
                for index in recipe_indices
                if index in requirements_by_recipe
            )
            matches.append({
                "source_block": block,
                "observed_candidate_blocks": counts[block],
                **({"items": tuple(sorted(value["items"]))} if value["items"] else {}),
                **({"recipe_indices": recipe_indices} if recipe_indices else {}),
                **({"matching_recipe_requirements": requirement_profiles}
                   if requirement_profiles else {}),
            })
        result["reference_matches"] = tuple(matches)
    return result


# Provider-owned, deliberately bounded presentation fields. Each key must
# already occur in a real, visibility-cut physical action outcome. No private
# trace, pathfinding internals, evaluator state, or fabricated preconditions.
# The universal compiler stays environment-agnostic; these facts belong here.
_PUBLIC_ACTION_EFFECTS: Mapping[str, tuple[str, ...]] = {
    "goto": ("start", "position", "target", "within_radius", "distance", "moved"),
    "goto_block": ("start", "position", "block_position", "moved", "target_selection"),
    "goto_entity": ("start", "position", "entity_id", "entity_distance", "moved"),
    "move_away": ("start", "position", "entity_id", "entity_distance", "moved"),
    "follow_player": ("final_distance", "updates", "moved"),
    "collect_block": ("source_blocks", "expected_items", "removed_count", "removal_effect",
                      "requested_tool", "tool_constraint_verified", "held_before", "held_after"),
    "excavate_region": ("region", "removed", "removed_count", "remaining_count",
                         "remaining", "blocked_position", "blocked_code",
                         "max_blocks"),
    "craft_item": ("crafted", "executions", "output_per_craft",
                   "used_table", "unexpected_produced"),
    "smelt_item": ("furnace", "output", "produced"),
    "place_block": ("position", "block", "target_selection"),
    "equip_item": ("item", "destination", "equipped"),
    "attack_nearest": ("target_id", "target_name", "hits", "attack_signals",
                       "hurt_signals", "own_hurt_signals", "target_valid_after"),
    "attack_entity": ("target_id", "target_name", "hits", "attack_signals",
                      "hurt_signals", "own_hurt_signals", "target_valid_after"),
    "attack_player": ("target_id", "target_name", "hits", "attack_signals",
                      "hurt_signals", "own_hurt_signals", "target_valid_after"),
    "ranged_attack": ("target_id", "target_name", "hits", "attack_signals",
                      "hurt_signals", "own_hurt_signals", "target_valid_after"),
    "fire_projectile": ("weapon", "ammo", "ammo_before", "ammo_after",
                        "ammo_consumed", "shots_released", "charge_ticks",
                        "aim_mode", "no_target_selected", "hit_or_damage_claimed"),
    "pickup_items": ("matching_gain", "gained", "collected",
                     "skipped_nonmatching_or_unidentified"),
    "observe_blocks": ("exact_position", "observed", "block",
                       "observation_constraint", "distance",
                       "searched_max_distance", "loaded_world_only"),
}


# These are paths in the *single* source-owned decision projection, not
# extra capabilities or independently maintained copies of world state.
# The universal compiler only interprets the path shape, never its MC names.
_DECISION_PATHS: Mapping[str, tuple[str, ...]] = {
    "minecraft.action_usage": ("actions", "usage"),
    "minecraft.local_state": ("world", "local"),
    "minecraft.holdings": ("actor", "holdings"),
    "minecraft.last_action_feedback": ("execution", "last"),
    "minecraft.registry_name_candidates": ("knowledge", "name_candidates"),
    "minecraft.crafting_dependency_alternatives": ("knowledge", "recipes"),
    "minecraft.crafting_local_source_candidates": ("knowledge", "observed_sources"),
    "minecraft.public_reference_not_physical_possession": ("knowledge", "reference"),
    "minecraft.local_sensing": ("world", "last_sensing"),
    "minecraft.nearby_loaded_blocks": ("world", "nearby_loaded_blocks"),
    "minecraft.combat_effect_evidence": ("execution", "combat_evidence"),
    "minecraft.combat_equipment_selection_reference": ("knowledge", "weapon_reference"),
    "minecraft.navigation_effect_progress": ("execution", "navigation_progress"),
}


def minecraft_agent_context_facets(
    agent_visible_state: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    if not isinstance(agent_visible_state, Mapping):
        raise TypeError("Minecraft agent context source must be a visible observation")

    facets: list[dict[str, Any]] = []
    def add(
        label: str, truth: str, value: object, *,
        history_retention: str | None = None,
        decision_constraint: Mapping[str, Any] | None = None,
    ) -> None:
        # The same facet is used for execution evidence and model projection;
        # path is an ordering/presentation annotation, never another truth.
        # Retention is provider control metadata consumed by the Context Engine
        # and deliberately excluded from the model-facing JSONL value.
        facet = {
            "label": label,
            "path": _DECISION_PATHS[label],
            "truth_class": truth,
            "source": "environment.minecraft.authorized_observation",
            "value": value,
        }
        if history_retention is not None:
            facet["history_retention"] = history_retention
        if decision_constraint is not None:
            facet["decision_constraint"] = dict(decision_constraint)
        facets.append(facet)

    # Static execution invariants remain decision-visible, but as typed codes
    # rather than repeated prose. The full explanatory contract belongs to
    # source documentation/evidence, while the model needs only its semantics.
    add("minecraft.action_usage", "declared", {
        "reference_truth": "declared_not_physical",
        "observation_scope": "loaded_world_not_global",
        "action_scope": "authorized_catalog_only",
        "count_scope": "bounded_action_effect_only",
        "effect_scope": "bounded_transition_not_task_goal",
        "indeterminate_retry": "observe_before_retry",
        "rejected_retry": "change_evidence_or_arguments",
        "partial_progress": "preserve",
        "strategy_owner": "method",
    })

    status = _present_fields(agent_visible_state, (
        "position", "dimension", "biome", "weather", "time_of_day",
        "health", "food",
    ))
    surroundings = agent_visible_state.get("surroundings")
    if isinstance(surroundings, Mapping):
        immediate = _present_fields(surroundings, (
            "below", "legs", "head", "first_solid_above_head",
        ))
        if immediate:
            status["surroundings"] = immediate
    entities = agent_visible_state.get("nearby_entities")
    if isinstance(entities, Sequence) and not isinstance(
        entities, (str, bytes, bytearray)
    ):
        status["nearby_entities"] = _decision_nearby_entities(entities)
    if status:
        add("minecraft.local_state", "observed", status)

    # The default nearby view answers whether useful block types are locally
    # present. Exact coordinates are not needed for name-based actions and are
    # available through explicit observe_blocks when a position matters.
    nearby = agent_visible_state.get("nearby_blocks")
    if isinstance(nearby, (tuple, list)):
        by_type: dict[str, int] = {}
        nearest: dict[str, float] = {}
        for row in nearby:
            if not isinstance(row, Mapping):
                continue
            name = row.get("name")
            distance = row.get("distance")
            if not isinstance(name, str) or not name:
                continue
            by_type[name] = by_type.get(name, 0) + 1
            if type(distance) in (int, float):
                value = float(distance)
                if name not in nearest or value < nearest[name]:
                    nearest[name] = value
        add("minecraft.nearby_loaded_blocks", "observed", {
            "visible_block_name_counts": dict(sorted(by_type.items())),
            "nearest_distance_by_name": dict(sorted(nearest.items())),
            "loaded_world_only": True,
            "searched_max_distance": 16,
            "witness_scope": "presence_not_harvestability",
        })

    if "inventory" in agent_visible_state or "equipment" in agent_visible_state:
        inventory = agent_visible_state.get("inventory")
        observed = False
        items: dict[str, int] = {}
        if isinstance(inventory, Mapping):
            observed = True
            for key, value in inventory.items():
                if isinstance(key, str) and type(value) is int and value > 0:
                    items[key] = value
        elif isinstance(inventory, Sequence) and not isinstance(inventory, (str, bytes, bytearray)):
            observed = True
            for entry in inventory:
                if not isinstance(entry, Mapping):
                    continue
                name, count = entry.get("name"), entry.get("count")
                if isinstance(name, str) and type(count) is int and count > 0:
                    items[name] = items.get(name, 0) + count
        equipment = agent_visible_state.get("equipment")
        add("minecraft.holdings", "observed", {
            "inventory_status": (
                "not_observed" if not observed else
                "observed_nonempty" if items else "observed_empty"
            ),
            "item_counts": dict(sorted(items.items())),
            **({"equipment": _decision_equipment(equipment)}
               if isinstance(equipment, Mapping) else {}),
        })

    last = agent_visible_state.get("last_outcome")
    action = agent_visible_state.get("last_action")
    if isinstance(last, Mapping):
        public_outcome = _fields(last, (
            "code", "status", "reason", "semantic_domain",
            "target_classification", "resolution", "acceptable_tools",
            "prerequisites", "inventory_delta", "produced_items",
            "recovery", "rejected_argument_constraints", "moved",
            "loaded_world_candidate_count", "candidate_frontier_exhausted",
            "goal_satisfied",
            "requested_count", "collected_count",
            "collection_candidates_exhausted",
            "collected_delta", "requested_resource", "target", "observed_block",
            "matching_gain", "observed_drop_entities", "candidates",
            "skipped_nonmatching_or_unidentified", "gained", "collected",
            "loaded_world_only",
            "collected_count", "available_count", "initial_count",
            "target_met_by_verified_inventory", "completed_substeps",
            "blocked_reason", "public_reference_unresolved_inputs",
            "world_frontier", "unreachable_targets",
            "recovered_prior_effect", "prior_outcome_not_current_world_truth",
        ))
        if "world_frontier" in public_outcome:
            public_outcome["world_frontier"] = _compact_world_frontier(
                public_outcome["world_frontier"]
            )
        # Every authorized action gets the same status/code contract, plus
        # domain-owned, action-specific *observed* evidence. Method and memory
        # policies never select, reinterpret or synthesize these facts.
        action_name = (
            action.get("tool") or action.get("action_type")
            if isinstance(action, Mapping) else None
        )
        if isinstance(action_name, str):
            public_outcome.update(
                _fields(last, _PUBLIC_ACTION_EFFECTS.get(action_name, ()))
            )
        if action_name == "excavate_region":
            # Provider/WAL evidence remains complete.  The Agent receives one
            # bounded decision projection so long local excavations do not
            # consume prompt budget with redundant child rows.
            for field in ("removed", "remaining"):
                raw_rows = last.get(field)
                if isinstance(raw_rows, Sequence) and not isinstance(
                    raw_rows, (str, bytes, bytearray)
                ):
                    sample = tuple(raw_rows[:8])
                    public_outcome[field] = sample
                    public_outcome[field + "_sample_count"] = len(sample)
                    public_outcome[field + "_truncated"] = len(raw_rows) > len(sample)
            raw_children = last.get("child_results")
            if isinstance(raw_children, Sequence) and not isinstance(
                raw_children, (str, bytes, bytearray)
            ):
                status_counts: dict[str, int] = {}
                for child in raw_children:
                    if not isinstance(child, Mapping):
                        continue
                    status = str(child.get("status", "unknown")).strip() or "unknown"
                    status_counts[status] = status_counts.get(status, 0) + 1
                public_outcome["child_effect_summary"] = {
                    "count": len(raw_children),
                    "status_counts": dict(sorted(status_counts.items())),
                    "full_rows_retained_in_evidence_only": True,
                }
        # Raw navigation stacks contain internal paths or even private
        # instrumentation; only the typed public code/name are useful.
        navigation = last.get("navigation_error")
        if isinstance(navigation, Mapping):
            public_outcome["navigation_error"] = _fields(navigation, ("code", "name"))
        # One decision-facing effect summary, not a second copy of the
        # full collection journal. Detailed low-level steps remain in evidence.
        requested = last.get("requested_count")
        collected = last.get("collected_count")
        if (
            isinstance(action_name, str) and action_name == "collect_block"
            and type(requested) is int and 0 < requested <= 64
            and type(collected) is int and 0 <= collected
            and last.get("code") in {
                "BLOCKS_COLLECTED", "COLLECTION_SEGMENT_APPLIED",
                "BLOCK_NOT_COLLECTED",
            }
        ):
            public_outcome["progress"] = {
                "requested": requested,
                "observed_collected": collected,
                "remaining_in_request": max(0, requested - collected),
                "scope": "this_action_not_task_goal",
            }
        public_outcome = _compact_public_action_outcome(
            action if isinstance(action, Mapping) else None, public_outcome
        )
        add(
            "minecraft.last_action_feedback", "observed", {
                "action": _decision_last_action(action),
                "outcome": public_outcome,
            },
            decision_constraint=_bounded_request_completion_constraint(
                action if isinstance(action, Mapping) else None, last
            ),
        )
        combat_actions = {
            "attack_nearest", "attack_entity", "attack_player",
            "defend_self", "ranged_attack", "fire_projectile",
        }
        action_name = (
            action.get("tool") or action.get("action_type")
            if isinstance(action, Mapping) else None
        )
        if action_name in combat_actions:
            # Combat exposes *attributable* hit and ammo evidence. No
            # strategy, aim recommendation or implicit victory is inferred.
            # Distinguish observed attack events from target damage and
            # recognize that concurrent entities can hurt the same target.
            observable = _fields(last, (
                "weapon", "ammo", "ammo_before", "ammo_after", "ammo_consumed",
                "shots_released", "hits", "attack_signals", "hurt_signals",
                "own_hurt_signals", "native_attack_invoked",
                "target_id", "target_valid_after", "targets_observed",
                "targets_engaged", "remaining", "damage_attribution",
            ))
            rows = last.get("target_outcomes")
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                observable["target_outcomes"] = tuple(
                    _fields(row, (
                        "target_id", "status", "code", "attack_signals",
                        "hurt_signals", "own_hurt_signals", "target_valid_after",
                    ))
                    for row in rows if isinstance(row, Mapping)
                )
            if observable:
                add("minecraft.combat_effect_evidence", "observed", {
                    **observable,
                    "source_action": action_name,
                    "outcome_code": last.get("code"),
                    "outcome_status": last.get("status"),
                    "not_a_benchmark_goal_judgment": True,
                    "unattributed_damage_not_credited": True,
                    "unknown_physical_effect_must_not_be_replayed": True,
                })
            selection = last.get("weapon_selection")
            if isinstance(selection, Mapping):
                add("minecraft.combat_equipment_selection_reference", "declared", {
                    **_fields(selection, (
                        "selected_weapon", "selection_basis",
                        "registry_damage_available", "selected_declared_damage",
                        "selected_durability_remaining", "equipped",
                    )),
                    "source": "versioned_registry_and_observed_inventory",
                    "not_an_optimal_strategy_or_dps_proof": True,
                    "no_assertion_of_unobserved_equipment": True,
                })
        # Rejected/partial status and typed blocker facts already live once in
        # execution.last.outcome. Do not add a second blocker wrapper or a
        # Minecraft error-code -> planning-prose table. The Method owns strategy.
        if (
            last.get("code") == "PATH_INTERRUPTED"
            and last.get("status") in {"partial", "rejected"}
        ):
            # A route failure does not imply zero displacement. The native
            # Provider reports the actual movement and typed error, which
            # remain observed effect evidence rather than a replan command.
            displacement = last.get("moved")
            if type(displacement) in (int, float) and 0 <= displacement < float("inf"):
                add("minecraft.navigation_effect_progress", "observed", {
                    "displacement_blocks": displacement,
                    "physical_displacement_observed": displacement > 0,
                    "destination_confirmed": False,
                    "outcome_status": last.get("status"),
                    "navigation_error": public_outcome.get("navigation_error"),
                    "not_proof_of_global_unreachability": True,
                })
        # Name suggestions are public registry references, not proof of item
        # possession and not observations of dynamic hidden world rules.
        candidates = _fields(last, (
            "canonical_item_candidates", "canonical_block_candidates",
            "target_classification", "resolution",
        ))
        if candidates:
            for field in ("canonical_item_candidates", "canonical_block_candidates"):
                if field in candidates:
                    candidates[field] = _lossless_row_table(candidates[field])
            add("minecraft.registry_name_candidates", "declared", {
                **candidates, "not_physical_world_proof": True,
            })
        # A craft rejection may carry the same independently sourced,
        # read-only reference as recipe_dependencies. Use ONE projection
        # path and retain declared versus observed truth separation.
        production_reference = (
            last.get("production_reference")
            if last.get("status") == "rejected"
            and last.get("code") in {
                "NO_RECIPE_OR_MATERIALS", "CRAFTING_TABLE_REQUIRED",
            }
            else last if (
                last.get("status") == "applied"
                and last.get("code") == "RECIPE_DEPENDENCIES_REFERENCED"
            ) else None
        )
        if (
            isinstance(production_reference, Mapping)
            and production_reference.get("source") == "version_pinned_vanilla_minecraft_data"
            and production_reference.get("datapack_rules_included") is False
            and production_reference.get("authoritative_for_current_world_recipe") is False
            and production_reference.get("no_physical_effect") is True
        ):
            # Do not mark physical inventory as declared recipe knowledge.
            # Full profile fan-out remains durable in the action evidence; the
            # Agent sees the provider-selected path and bounded alternatives.
            recipe_view = _bounded_recipe_reference(production_reference)
            add(
                "minecraft.crafting_dependency_alternatives", "declared",
                recipe_view,
                history_retention="source_declared_reference",
                decision_constraint=_declared_dependency_constraint(
                    recipe_view, production_reference,
                ),
            )
            sources = production_reference.get("observed_local_acquisition_sources")
            if (isinstance(sources, Mapping)
                and sources.get("truth_class") == "observed"
                and sources.get("loaded_world_only") is True):
                add("minecraft.crafting_local_source_candidates", "observed",
                    _bounded_local_acquisition_sources(
                        sources, production_reference,
                    ))
        if last.get("status") == "applied" and last.get("truth_class") == "declared":
            reference: dict[str, Any] = {}
            reference_retention: str | None = None
            if (
                last.get("code") == "ACTION_DESCRIBED"
                and last.get("authorized") is True
                and last.get("physical_world_observed") is False
                and isinstance(last.get("action_contract"), Mapping)
            ):
                reference = _fields(last, (
                    "action_contract", "argument_guide", "invocation_format",
                    "truth_class", "physical_world_observed",
                ))
            elif (
                last.get("code") in {"VANILLA_RECIPES_REFERENCED", "REGISTRY_SEARCHED"}
                and last.get("authoritative_for_current_world") is False
                and last.get("datapack_rules_included") is not True
            ):
                reference = _fields(last, (
                    "item", "item_known", "minecraft_version", "recipe_kind",
                    "recipes", "recipes_recorded", "recipes_truncated",
                    "query", "items", "blocks", "entities", "ranked_candidates",
                    "truth_class", "source", "authoritative_for_current_world",
                ))
                # This is a version/source-pinned public reference, not a
                # current-world observation. Preserve that Provider-owned
                # retention fact for Method memory/control without copying
                # historical reference contents into the live prompt.
                reference_retention = "source_declared_reference"
            if reference:
                if "ranked_candidates" in reference:
                    reference["ranked_candidates"] = _lossless_row_table(
                        reference["ranked_candidates"]
                    )
                add(
                    "minecraft.public_reference_not_physical_possession",
                    "declared", reference,
                    history_retention=reference_retention,
                    decision_constraint=(
                        _unquantified_dependency_reference_constraint(last)
                        if last.get("code") == "VANILLA_RECIPES_REFERENCED"
                        else None
                    ),
                )
        if (
            last.get("status") == "applied"
            and last.get("truth_class") == "observed"
            and last.get("authoritative_for_current_world") is True
            and last.get("code") in {"BLOCKS_OBSERVED", "BLOCK_POSITION_OBSERVED", "BLOCK_POSITION_UNOBSERVED", "ENTITIES_OBSERVED"}
        ):
            sensing_fields = (
                "query", "observed_count", "searched_max_distance", "loaded_world_only",
                "blocks", "counts", "entities",
                "exact_position", "observed", "block", "observation_constraint", "distance",
            )
            sensing = _fields(last, sensing_fields)
            # An unfiltered BLOCKS_OBSERVED scan is the default local discovery
            # view. Its full coordinate rows duplicate nearby_loaded_blocks and
            # rarely change the next semantic action: name/count/range are enough
            # until the Method explicitly asks for a named or exact witness.
            # Explicit query/position observations retain their full rows. The
            # source outcome remains complete in durable evidence either way.
            if last.get("code") == "BLOCKS_OBSERVED":
                explicit_query = (
                    isinstance(action, Mapping)
                    and isinstance(action.get("query"), str)
                    and bool(action.get("query", "").strip())
                )
                explicit_position = (
                    isinstance(action, Mapping)
                    and isinstance(action.get("position"), Mapping)
                )
                if not explicit_query and not explicit_position:
                    sensing.pop("blocks", None)
                    sensing.pop("query", None)
                    sensing["detail_scope"] = "summary_until_explicit_query"
            for field in ("blocks", "entities"):
                if field in sensing:
                    sensing[field] = _lossless_row_table(sensing[field])
            if "world_frontier" in last:
                sensing["world_frontier_path"] = "execution.last.outcome.world_frontier"
            add("minecraft.local_sensing", "observed", sensing)
    return tuple(facets)
