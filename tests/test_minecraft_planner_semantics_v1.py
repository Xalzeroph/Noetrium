from __future__ import annotations

import unittest

from noetrium_platform.capabilities.environment.minecraft.api import minecraft_action_catalog


class MinecraftPlannerSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.by_type = {
            contract.action_type: contract
            for contract in minecraft_action_catalog()
        }

    def test_block_navigation_is_a_distinct_block_domain(self) -> None:
        contract = self.by_type["goto_block"]
        self.assertEqual(
            contract.argument_semantics["block"],
            "minecraft.block_name",
        )
        self.assertIn(
            "Semantic domain: minecraft.block_name",
            contract.argument_schema["properties"]["block"]["description"],
        )
        self.assertTrue(
            any("interaction range" in rule for rule in contract.applicability)
        )

    def test_entity_navigation_exposes_entity_domain(self) -> None:
        contract = self.by_type["goto_entity"]
        self.assertEqual(
            contract.argument_semantics["entity"],
            "minecraft.entity_type",
        )
        self.assertTrue(
            any("never a block" in rule for rule in contract.applicability)
        )

    def test_collection_preserves_drop_name_capability(self) -> None:
        contract = self.by_type["collect_block"]
        self.assertEqual(
            contract.argument_semantics["block"],
            "minecraft.block_or_block_drop_name",
        )

    def test_inventory_gain_targets_are_typed_and_removal_mode_is_excluded(self) -> None:
        collect = self.by_type["collect_block"]
        craft = self.by_type["craft_item"]
        pickup = self.by_type["pickup_items"]
        withdraw = self.by_type["chest_withdraw"]
        self.assertEqual(
            collect.argument_effects[0]["role"],
            "inventory_gain_target",
        )
        self.assertEqual(tuple(collect.argument_effects[0]["argument_path"]), ("block",))
        self.assertEqual(
            collect.argument_effects[0]["unless_arguments"][0]["value"],
            "remove",
        )
        for contract, argument in ((craft, "item"), (pickup, "item"), (withdraw, "item")):
            self.assertEqual(contract.argument_effects[0]["role"], "inventory_gain_target")
            self.assertEqual(tuple(contract.argument_effects[0]["argument_path"]), (argument,))
        self.assertEqual(self.by_type["smelt_item"].argument_effects, ())
        self.assertEqual(self.by_type["place_block"].argument_effects, ())

    def test_crafting_exposes_platform_owned_applicability(self) -> None:
        contract = self.by_type["craft_item"]
        self.assertEqual(
            contract.argument_semantics["item"],
            "minecraft.item_name",
        )
        payload = contract.as_payload()
        self.assertIn("argument_semantics", payload)
        self.assertIn("applicability", payload)
        self.assertTrue(
            any("crafting table" in rule for rule in payload["applicability"])
        )

    def test_recipe_reference_never_discloses_hidden_rule_changes(self) -> None:
        contract = self.by_type["recipe_lookup"]
        self.assertFalse(contract.mutates_world)
        self.assertIn("vanilla", contract.description)
        self.assertTrue(any("hidden rules" in rule for rule in contract.applicability))

    def test_registry_search_documents_ontology_recovery(self) -> None:
        contract = self.by_type["registry_search"]
        self.assertTrue(
            any(
                "item, block and entity" in rule
                for rule in contract.applicability
            )
        )




def test_observation_queries_expose_provider_semantic_domains():
    contracts = {
        contract.action_type: contract
        for contract in minecraft_action_catalog()
    }
    assert contracts["observe_blocks"].argument_semantics["query"] == "minecraft.block_name_query"
    assert contracts["registry_search"].argument_semantics["query"] == "minecraft.registry_name_query"
    assert "Semantic domain: minecraft.block_name_query" in (
        contracts["observe_blocks"].argument_schema["properties"]["query"]["description"]
    )
    assert "Semantic domain: minecraft.registry_name_query" in (
        contracts["registry_search"].argument_schema["properties"]["query"]["description"]
    )


if __name__ == "__main__":
    unittest.main()
