"""All authorized Minecraft action handbooks remain complete and schema-correct."""
from __future__ import annotations

import unittest
from pathlib import Path

from noetrium_platform.capabilities.environment.minecraft.api import (
    minecraft_action_catalog,
    validate_minecraft_action,
)
from noetrium_platform.capabilities.environment.minecraft.api.agent_context import (
    minecraft_agent_context_facets,
)
from noetrium_platform.capabilities.environment.minecraft.api.usage_guides import (
    minecraft_action_usage_guide,
    minecraft_action_handbook_markdown,
    minecraft_action_usage_guide_types,
)
from noetrium_platform.research.execution.workflow.api.agent_authoring import (
    compact_authorized_action_catalog,
)


class ActionUsageGuideTests(unittest.TestCase):
    def test_all_current_actions_have_complete_grounded_guides(self):
        catalog = minecraft_action_catalog()
        names = {row.action_type for row in catalog}
        self.assertTrue(names)
        self.assertEqual(names, minecraft_action_usage_guide_types())
        for row in catalog:
            with self.subTest(action=row.action_type):
                guide = minecraft_action_usage_guide(row.action_type)
                self.assertEqual(set(guide), {
                    "use_when", "prepare", "verify", "when_not_completed",
                    "few_shots", "counterexamples",
                })
                for key in ("use_when", "prepare", "verify", "when_not_completed"):
                    self.assertGreater(len(guide[key]), 35)
                self.assertGreaterEqual(len(guide["few_shots"]), 2)
                self.assertGreaterEqual(len(guide["counterexamples"]), 2)
                for example in guide["few_shots"]:
                    self.assertEqual(set(example), {
                        "only_when", "arguments", "check_afterwards",
                    })
                    self.assertGreater(len(example["only_when"]), 15)
                    self.assertGreater(len(example["check_afterwards"]), 15)
                    # Never suggest an invocation rejected by the real codec.
                    validate_minecraft_action(row.action_type, example["arguments"])
                for example in guide["counterexamples"]:
                    self.assertEqual(set(example), {"arguments", "why_not"})
                    self.assertGreater(len(example["why_not"]), 20)

    def test_generated_markdown_matches_authoritative_handbook(self):
        markdown = Path(__file__).resolve().parents[1] / "docs" / "minecraft_agent_action_handbook.md"
        generated = minecraft_action_handbook_markdown()
        self.assertEqual(markdown.read_text(encoding="utf-8"), generated)
        self.assertEqual(generated.count("### Few-shot "), 2 * len(minecraft_action_catalog()))
        self.assertEqual(generated.count("### Forbidden or mistaken example "), 2 * len(minecraft_action_catalog()))
        self.assertEqual(generated.count("\n## `"), len(minecraft_action_catalog()))

    def test_observational_details_are_exposed_as_declared_not_physical_facts(self):
        guide = minecraft_action_usage_guide("collect_block")
        outcome = {
            "status": "applied",
            "code": "ACTION_DESCRIBED",
            "truth_class": "declared",
            "authorized": True,
            "physical_world_observed": False,
            "action_contract": {
                "action_type": "collect_block",
                "usage_guide": guide,
            },
        }
        facets = minecraft_agent_context_facets({
            "last_action": {"tool": "describe_action", "action_type": "collect_block"},
            "last_outcome": outcome,
        })
        references = [r for r in facets
                      if r["label"] == "minecraft.public_reference_not_physical_possession"]
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["truth_class"], "declared")
        self.assertEqual(references[0]["value"]["action_contract"]["usage_guide"], guide)
        self.assertFalse(any(r["label"] == "minecraft.holdings" for r in facets))
        self.assertFalse(any(r["label"] == "minecraft.local_sensing" for r in facets))

    def test_default_index_does_not_carry_bulk_handbook_or_schema(self):
        catalog = minecraft_action_catalog()
        rows = tuple(row.as_payload() for row in catalog)
        index = compact_authorized_action_catalog(rows)
        self.assertEqual(len(index["rows"]), len(catalog))
        self.assertEqual(index["details_via"], "describe_action")
        self.assertNotIn("usage_guide", index["columns"])
        self.assertNotIn("argument_schema", index["columns"])
        self.assertNotIn("applicability", index["columns"])
        self.assertNotIn("argument_semantics", index["columns"])
        self.assertNotIn("argument_effects", index["columns"])
        self.assertNotIn("description", index["columns"])
        self.assertNotIn("syntax_examples", index["columns"])
        self.assertNotIn("examples_are_public_syntax_not_world_evidence", index["columns"])
        self.assertEqual(
            set(index["columns"]),
            {"action_type", "category", "arguments", "mutates_world", "may_move_actor"},
        )
        self.assertEqual({r[index["columns"].index("action_type")]
                          for r in index["rows"]}, minecraft_action_usage_guide_types())
        action_col=index["columns"].index("action_type")
        move_col=index["columns"].index("may_move_actor")
        movement={row[action_col]: row[move_col] for row in index["rows"]}
        self.assertTrue(movement["attack_entity"])
        self.assertTrue(movement["collect_block"])
        self.assertTrue(movement["chest_inspect"])
        self.assertFalse(movement["observe_entities"])
        self.assertFalse(movement["recipe_lookup"])

    def test_unauthorized_or_unknown_handbook_cannot_be_inferred(self):
        for name in ("not_a_tool", "", "../private", 7):
            with self.subTest(action=name):
                with self.assertRaises(ValueError):
                    minecraft_action_usage_guide(name)


if __name__ == "__main__":
    unittest.main()
