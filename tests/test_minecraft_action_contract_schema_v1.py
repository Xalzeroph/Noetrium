from __future__ import annotations

from noetrium_platform.capabilities.environment.minecraft.api import (
    minecraft_action_catalog,
    validate_minecraft_action,
)
from noetrium_platform.foundation.kernel.kernel import thaw_json


def test_every_minecraft_planner_contract_has_machine_readable_object_schema() -> None:
    catalog = minecraft_action_catalog()
    assert len(catalog) == len({row.action_type for row in catalog})
    assert len({row.action_type for row in catalog}) == len(catalog)
    for row in catalog:
        schema = thaw_json(row.argument_schema)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert isinstance(schema["properties"], dict)


def test_attack_nearest_planner_schema_matches_provider_numeric_bounds() -> None:
    contract = next(
        row for row in minecraft_action_catalog()
        if row.action_type == "attack_nearest"
    )
    schema = thaw_json(contract.argument_schema)
    assert schema["required"] == ["entity"]
    assert schema["properties"]["max_hits"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 20,
    }
    assert schema["properties"]["max_distance"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 128,
    }
    assert validate_minecraft_action(
        "attack_nearest",
        {"entity": "zombie", "max_hits": 20, "max_distance": 128},
    )["max_hits"] == 20


def test_nested_position_contract_is_derived_without_loss() -> None:
    contract = next(row for row in minecraft_action_catalog() if row.action_type == "goto")
    schema = thaw_json(contract.argument_schema)
    position = schema["properties"]["position"]
    assert position["type"] == "object"
    assert position["required"] == ["x", "y", "z"]
    assert position["properties"] == {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "z": {"type": "number"},
    }



def test_collect_block_supports_exact_target_in_same_authorized_semantic_action() -> None:
    contract = next(row for row in minecraft_action_catalog()
                    if row.action_type == "collect_block")
    schema = thaw_json(contract.argument_schema)
    target = schema["properties"]["position"]
    assert target["type"] == "object"
    assert target["required"] == ["x", "y", "z"]
    assert set(target["properties"]) == {"x", "y", "z"}
    assert all(spec["type"] == "integer" for spec in target["properties"].values())
    assert validate_minecraft_action(
        "collect_block", {"block": "oak_log", "count": 3}
    )["count"] == 3
    exact = validate_minecraft_action(
        "collect_block", {"block": "oak_log", "position": {"x": 2, "y": 64, "z": 5}}
    )
    assert exact["count"] == 1
    assert exact["position"] == {"x": 2, "y": 64, "z": 5}
    for payload, code in (
        ({"block": "oak_log", "count": 2, "position": {"x": 2, "y": 64, "z": 5}},
         "EXACT_TARGET_COUNT"),
        ({"block": "oak_log", "position": {"x": 2.5, "y": 64, "z": 5}},
         "POSITION_BLOCK_GRID"),
    ):
        try:
            validate_minecraft_action("collect_block", payload)
        except ValueError as exc:
            assert code in str(exc)
        else:
            raise AssertionError("invalid exact-target collection was accepted")


def test_pickup_items_optional_exact_item_filter_is_authorized_and_nonbreaking() -> None:
    contracts = {c.action_type: c for c in minecraft_action_catalog()}
    schema = thaw_json(contracts["pickup_items"].argument_schema)
    assert "item" not in schema.get("required", [])
    assert schema["properties"]["item"]["type"] == "string"
    default = validate_minecraft_action("pickup_items", {})
    assert "item" not in default
    selected = validate_minecraft_action("pickup_items", {
        "item": "oak_log", "max_distance": 16, "max_items": 3
    })
    assert selected["item"] == "oak_log"
    assert selected["max_items"] == 3
    try:
        validate_minecraft_action("pickup_items", {"item": ""})
    except ValueError:
        pass
    else:
        raise AssertionError("blank physical item selector was allowed")


def test_exact_block_removal_is_same_action_but_has_independent_effect_semantics():
    from noetrium_platform.capabilities.environment.minecraft.api.action_codecs import (
        validate_minecraft_action,
    )
    target = {"x": 3, "y": 65, "z": -2}
    requested = validate_minecraft_action("collect_block", {
        "block": "oak_log", "position": target, "effect": "remove",
    })
    assert requested["effect"] == "remove"
    assert requested["count"] == 1
    assert requested["position"] == target
    for args in (
        {"block": "oak_log", "effect": "remove"},
        {"block": "oak_log", "effect": "remove", "count": 2, "position": target},
        {"block": "oak_log", "effect": "unknown", "position": target},
    ):
        try:
            validate_minecraft_action("collect_block", args)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid removal request was authorized")


def test_local_composite_child_authority_is_a_noetrium_unit_closure() -> None:
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MINECRAFT_ACTION_SPEC_BY_TYPE,
        minecraft_action_required_actions,
        minecraft_action_unavailable_dependencies,
        minecraft_action_unit,
        MinecraftActionCategory,
    )
    unit = MINECRAFT_ACTION_SPEC_BY_TYPE["excavate_region"]
    assert minecraft_action_required_actions(unit) == ("collect_block",)
    assert minecraft_action_unavailable_dependencies(
        "excavate_region", frozenset({"excavate_region"})
    ) == ("collect_block",)
    assert minecraft_action_unavailable_dependencies(
        "excavate_region", frozenset({"excavate_region", "collect_block"})
    ) == ()
    with __import__("pytest").raises(ValueError):
        minecraft_action_unit(
            "recursive", MinecraftActionCategory.RESOURCE, True,
            "bad", "{}", required_actions=("recursive",)
        )


def test_workstation_placement_is_optional_unit_effect_not_mandatory_crafting_permission() -> None:
    from noetrium_platform.capabilities.environment.minecraft.api import (
        MINECRAFT_ACTION_SPEC_BY_TYPE,
        minecraft_action_optional_actions,
        minecraft_action_required_actions,
        minecraft_action_unavailable_dependencies,
    )
    unit = MINECRAFT_ACTION_SPEC_BY_TYPE["craft_item"]
    assert minecraft_action_optional_actions(unit) == ("place_block",)
    assert minecraft_action_required_actions(unit) == ()
    assert minecraft_action_unavailable_dependencies(
        "craft_item", frozenset({"craft_item"})
    ) == ()


def test_skill_examples_are_source_typed_schema_valid_and_never_world_evidence() -> None:
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_action_catalog,
        validate_minecraft_action,
    )
    catalog = {row.action_type: row for row in minecraft_action_catalog()}
    assert catalog["craft_item"].syntax_examples
    for name, contract in catalog.items():
        view = contract.as_payload()
        assert view["examples_are_public_syntax_not_world_evidence"] is True
        for example in contract.syntax_examples:
            assert validate_minecraft_action(name, example) is not None
