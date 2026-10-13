from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from noetrium_platform.capabilities.environment.minecraft.api.agent_context import (
    minecraft_agent_context_facets,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.session import (
    MinecraftEnvironmentSession,
)
from noetrium_platform.research.execution.workflow.composition.agent_context import (
    compile_agent_context,
)
from noetrium_platform.research.execution.workflow.composition.model_agent import (
    MethodViewChatRequestFactory,
)


class UniversalContextTests(unittest.TestCase):
    def test_static_authority_index_prefix_precedes_changing_goal_and_world(self):
        from os.path import commonprefix
        from noetrium_platform.capabilities.environment.minecraft.api import (
            minecraft_action_catalog,
        )
        from noetrium_platform.research.execution.workflow.api.agent_authoring import (
            compact_authorized_action_catalog,
        )

        catalog = compact_authorized_action_catalog(tuple(
            contract.as_payload() for contract in minecraft_action_catalog()
        ))
        samples = []
        for step in (0, 1):
            facets = minecraft_agent_context_facets({
                "position": {"x": step, "y": 64, "z": 1},
                "inventory": {"oak_log": step + 1},
            })
            samples.append(compile_agent_context({
                "goal": {"goal": f"task at step {step}", "step_index": step},
                "environment": {"agent_context_facets": facets},
                "capabilities": {"actions": catalog},
                "memory": {"items": [{"step": step}]},
            }))
        self.assertTrue(samples[0].text.startswith("## ENVIRONMENT_CONTEXT"))
        self.assertEqual(samples[0].section_count, samples[1].section_count)
        static_prefix = commonprefix(tuple(x.text for x in samples))
        self.assertIn('"details_via":"describe_action"', static_prefix)
        action_column = catalog["columns"].index("action_type")
        self.assertIn(
            f'"{catalog["rows"][-1][action_column]}"',
            static_prefix,
        )
        for step, compiled in enumerate(samples):
            self.assertIn(f'"goal":"task at step {step}"', compiled.text)
            self.assertIn(f'"x":{step}', compiled.text)
            self.assertIn(f'"step":{step}', compiled.text)
            self.assertIn('"truth":"authorized"', compiled.text)
            self.assertIn("## RETRIEVED_METHOD_MEMORY", compiled.text)

    def test_minecraft_gui_and_embodiment_use_exactly_same_compiler(self):
        for label, body in [
            ("minecraft.holdings", {"inventory_status": "observed_empty"}),
            ("gui.active_control", {"role": "button", "title": "Save"}),
            ("robot.proprioception", {"joints": [0.1, 0.3], "gripper_open": True}),
        ]:
            facets = [{
                "label": label,
                "truth_class": "observed",
                "source": "environment." + label.split(".")[0],
                "value": body,
            }]
            compiled = compile_agent_context({
                "goal": {"goal": "Complete authorized task"},
                "environment": {"agent_context_facets": facets},
                "memory": {"graph": {"nodes": [{"ref": "past", "belief": "stale"}]}},
            })
            self.assertIn(label, compiled.text)
            self.assertIn("RETRIEVED_METHOD_MEMORY", compiled.text)
            self.assertIn("recalled_not_live_observation", compiled.text)
            self.assertNotIn("PAST_WORLD_TRUTH", compiled.text)
            self.assertEqual(compiled.section_count, 5)

    def test_compiler_is_deterministic_lossless_and_does_not_conflate_memory_with_observation(self):
        data = {
            "goal": {"goal": "find target"},
            "environment": [{"label": "sensor", "truth_class": "observed",
                             "source": "environment.sensor", "value": {"count": 0}}],
            "memory": {"items": [{"asserted": "count=27", "confidence": 0.2}],
                       "arbitrary_memory_unit": {"children": [{"edge": "derived"}]}},
            "method": {"policy": "method-specific"},
        }
        a, b = compile_agent_context(data), compile_agent_context(data)
        self.assertEqual(a, b)
        self.assertIn("count=27", a.text)
        self.assertIn('"count":0', a.text)
        self.assertIn('"policy":"method-specific"', a.text)


    def test_durable_action_history_is_not_an_implicit_model_memory_channel(self):
        rows = [
            {"action": {"action_type": "equip_item", "arguments": {"item": "iron_pickaxe"}},
             "outcome": {"effect_receipt": {"certainty": "indeterminate"},
                         "state": {"last_outcome": {"code": "ITEM_EQUIPPED",
                                                  "hidden_rule_manifest": "SECRET"}}}},
            {"action": {"action_type": "equip_item", "arguments": {"item": "iron_pickaxe"}},
             "outcome": {"effect_receipt": {"certainty": "effect_rejected"},
                         "state": {"last_outcome": {"code": "ITEM_NOT_AVAILABLE"}}}},
        ]
        compiled = compile_agent_context({
            "goal": {"goal": "find diamond"},
            "history": {"action_results": rows},
        }).text
        # Durable execution history remains available to runtime watchdogs and
        # explicit Method memory, but is never replayed into the planner for free.
        for token in ("UNKNOWN_EFFECT", "ITEM_NOT_AVAILABLE", "ITEM_EQUIPPED",
                      "executed_action_count", "action_results", "SECRET"):
            self.assertNotIn(token, compiled)
        self.assertNotIn("CAUSAL_HISTORY", compiled)

    def test_declared_reference_must_reenter_through_current_environment_or_method_memory(self):
        recipe = {
            "label": "environment.crafting_reference",
            "truth_class": "declared",
            "source": "environment.workbench",
            "history_retention": "source_declared_reference",
            "value": {
                "steps": ["harvest_log", "craft_planks", "craft_stick"],
                "authoritative_for_current_world": False,
            },
        }
        actions = [{
            "action": {"action_type": "recipe_dependencies", "arguments": {"item": "stick"}},
            "outcome": {
                "effect_receipt": {"certainty": "effect_confirmed", "effect_class": "pure"},
                "agent_context_facets": [recipe],
                "state": {"last_outcome": {"code": "REFERENCE_READ"}},
            },
        }, {
            "action": {"action_type": "collect_block", "arguments": {"block": "oak_log"}},
            "outcome": {
                "effect_receipt": {"certainty": "effect_confirmed", "effect_class": "physical"},
                "agent_context_facets": [{
                    "label": "environment.inventory",
                    "truth_class": "observed",
                    "source": "environment.workbench",
                    "value": {"oak_log": 1},
                }],
                "state": {"last_outcome": {"code": "BLOCKS_COLLECTED",
                                          "hidden_evaluator_value": "SECRET"}},
            },
        }]
        # Once the current Environment has moved on, the old reference is not
        # replayed by the universal compiler. If the Method still needs it, it
        # must retrieve it explicitly from its own memory channel.
        prompt = compile_agent_context({
            "goal": {"goal": "craft stick"},
            "environment": [actions[-1]["outcome"]["agent_context_facets"][0]],
            "history": {"action_results": actions},
        }).text
        self.assertNotIn("retained_declared_reference", prompt)
        self.assertNotIn("craft_planks", prompt)
        self.assertIn('"oak_log":1', prompt)
        self.assertNotIn("SECRET", prompt)

        # A reference that is part of the *current* Environment observation is
        # still visible immediately; current state is not memory leakage.
        current = compile_agent_context({
            "goal": {"goal": "craft stick"},
            "environment": [recipe],
            "history": {"action_results": actions[:1]},
        }).text
        self.assertIn("craft_planks", current)
        self.assertNotIn("retained_declared_reference", current)

    def test_method_cannot_override_platform_compiled_execution_history(self):
        with self.assertRaises(ValueError):
            compile_agent_context({
                "goal": {"goal": "test"},
                "history": {"action_results": (), "action_evidence": {"forged": True}},
            })

    def test_unknown_or_ambiguous_environment_truth_fails_closed(self):
        cases = [
            {"goal": {"goal": "act"}, "environment": {"state": {"secret": True}}},
            {"goal": {"goal": "act"}, "environment": [
                {"label": "danger", "truth_class": "recalled",
                 "source": "method", "value": {"lies": True}}]},
            {"goal": {"goal": "act"}, "environment": [
                {"label": "danger", "truth_class": "observed",
                 "source": "", "value": {}}]},
            {"goal": {"goal": "act"}, "memory": {"items": []}, "environment": [],
             "raw_hidden_world": {"rule_manifest": "secret"}},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises((TypeError, ValueError)):
                compile_agent_context(case)

    def test_model_factory_compiles_exactly_one_authorized_context_and_method_policy(self):
        request = SimpleNamespace(view={
            "system": "The method owns memory retrieval and planning.",
            "agent_context": {
                "goal": {"goal": "click Save"},
                "environment": [{"label": "gui.focus", "truth_class": "observed",
                    "source": "gui.projection", "value": {"button": "Save"}}],
                "memory": {"recalled": ["old dialog opened"]},
            },
            "prompt": "legacy prompt must not override context",
        })
        messages = MethodViewChatRequestFactory._messages(request)
        self.assertEqual(len(messages), 2)
        self.assertIn("method owns memory", messages[0]["content"])
        self.assertIn("gui.focus", messages[1]["content"])
        self.assertNotIn("legacy prompt", messages[1]["content"])

    def test_minecraft_visibility_projection_cannot_leak_hidden_states(self):
        hidden = {"inventory": {},
                  "last_outcome": {
                      "code": "REGISTRY_SEARCHED", "status": "applied",
                      "truth_class": "declared",
                      "authoritative_for_current_world": False,
                      "ranked_candidates": ["diamond"],
                      "hidden_rule_manifest": "PRIVATE",
                  },
                  "hidden_rule_manifest": "PRIVATE"}
        mock = SimpleNamespace(
            _visible_state_fields=frozenset({"inventory", "last_outcome"}),
            _project_agent_state=lambda row: {
                k: v for k, v in row.items() if k in {"inventory", "last_outcome"}
            },
        )
        # The state visibility cut may authorize last_outcome, but it does
        # not authorize arbitrary hidden keys within it. The facet projector
        # only selects explicit public fields from that outcome.
        output = MinecraftEnvironmentSession._agent_observation_payload(
            mock, {"kind": "mc", "state": hidden, "private_token": "SECRET"},
        )
        serialized = json.dumps(output["agent_context_facets"])
        self.assertIn("observed_empty", serialized)
        self.assertNotIn("PRIVATE", serialized)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("private_token", output)

    def test_recovered_partial_skill_is_not_presented_as_fresh_goal_success(self):
        facets = minecraft_agent_context_facets({
            "inventory": [{"name": "oak_log", "count": 1}],
            "last_action": {"tool": "collect_block", "block": "oak_log", "count": 4},
            "last_outcome": {
                "status": "partial", "code": "COLLECTION_GOAL_PARTIALLY_FULFILLED",
                "requested_count": 4, "collected_count": 1,
                "recovered_prior_effect": True,
                "prior_outcome_not_current_world_truth": True,
                "private_handler_trace": "DO_NOT_EXPOSE",
            },
        })
        prompt = compile_agent_context({
            "goal": {"goal": "collect four logs"},
            "environment": facets,
        }).text
        self.assertIn("recovered_prior_effect", prompt)
        self.assertIn("prior_outcome_not_current_world_truth", prompt)
        self.assertIn('"collected_count":1', prompt)
        self.assertIn('"requested_count":4', prompt)
        self.assertNotIn("DO_NOT_EXPOSE", prompt)

    def test_default_local_block_sensing_follows_unchanged_visibility_cut(self):
        blocks = [{"name": "oak_log", "position": {"x": 2, "y": 64, "z": 2},
                   "distance": 2.83}]
        state = {"inventory": {"oak_log": 1}, "nearby_blocks": blocks,
                 "hidden_recipe": "PRIVATE"}
        unrestricted = minecraft_agent_context_facets(state)
        labels = {row["label"]: row for row in unrestricted}
        nearby = labels["minecraft.nearby_loaded_blocks"]["value"]
        self.assertEqual(nearby["visible_block_name_counts"], {"oak_log": 1})
        self.assertEqual(nearby["nearest_distance_by_name"], {"oak_log": 2.83})
        self.assertNotIn("blocks", nearby)
        mock = SimpleNamespace(
            _visible_state_fields=frozenset({"inventory"}),
            _project_agent_state=lambda row: {
                k: v for k, v in row.items() if k == "inventory"
            },
        )
        restricted = MinecraftEnvironmentSession._agent_observation_payload(
            mock, {"kind": "minecraft_snapshot", "state": state},
        )
        prompt = compile_agent_context({
            "goal": {"goal": "get logs"}, "environment": restricted,
        }).text
        self.assertNotIn("nearby_loaded_blocks", prompt)
        self.assertNotIn("PRIVATE", prompt)




    def test_structured_context_keeps_provenance_durable_not_model_visible(self):
        compiled = compile_agent_context({
            "goal": {"goal": "inspect current state"},
            "environment": [{
                "label": "robot.camera",
                "path": ("world", "camera"),
                "truth_class": "observed",
                "source": "environment.robot.authorized_observation",
                "evidence_ref": "opaque:evidence:123",
                "validity": {
                    "generation": "opaque-generation",
                    "observation_id": "opaque-observation-id",
                    "temporal_scope": "at_observation",
                },
                "value": {"visible": ["handle"]},
            }],
        }).text
        self.assertIn('"truth":"observed"', compiled)
        self.assertIn('"visible":["handle"]', compiled)
        for token in (
            "opaque:evidence:123", "opaque-generation", "opaque-observation-id",
            "environment.robot.authorized_observation", "temporal_scope",
        ):
            self.assertNotIn(token, compiled)

    def test_unknown_physical_result_invalidates_current_snapshot_claim(self):
        compiled = compile_agent_context({
            "goal": {"goal": "collect iron"},
            "environment": {
                "effect_receipt": {"certainty": "indeterminate"},
                "agent_context_facets": [{
                    "label": "minecraft.holdings", "truth_class": "observed",
                    "source": "environment.minecraft.authorized_observation",
                    "value": {"inventory_status": "observed_empty"},
                    "validity": {"temporal_scope": "at_observation"},
                }],
            },
        }).text
        self.assertIn("previous_snapshot_not_current_effect_proof", compiled)
        self.assertIn("observed_empty", compiled)

    def test_action_help_reference_survives_context_projection(self):
        facets = minecraft_agent_context_facets({
            "inventory": {},
            "last_action": {"tool": "describe_action"},
            "last_outcome": {
                "code": "ACTION_DESCRIBED", "status": "applied",
                "truth_class": "declared", "authorized": True,
                "physical_world_observed": False,
                "action_contract": {"action_type": "equip_item",
                    "argument_schema": {"destination_enum": ["hand", "head"]}},
            },
        })
        text = compile_agent_context({
            "goal": {"goal": "make a pickaxe"},
            "environment": facets,
        }).text
        self.assertIn("equip_item", text)
        self.assertIn("destination_enum", text)
        self.assertIn("observed_empty", text)
        self.assertIn('"knowledge":{"reference":', text)

    def test_stagnant_read_only_observation_signals_unchanged_public_evidence(self):
        observation = {
            "label": "robot.camera", "truth_class": "observed",
            "source": "environment.robot", "value": {"visible": ["handle"]},
        }
        def row(action_type="look", facet=observation, certainty="effect_applied"):
            return {
                "action": {"action_type": action_type, "arguments": {}},
                "outcome": {
                    "effect_receipt": {"certainty": certainty},
                    "agent_context_facets": [
                        facet,
                        {"label": "robot.hidden", "truth_class": "declared",
                         "source": "environment.robot", "value": {"password": "SECRET"}},
                    ],
                },
            }

        def context(actions, mutation=False):
            return {
                "goal": {"goal": "inspect and open the handle"},
                "capabilities": {"actions": {
                    "columns": ["action_type", "mutates_world"],
                    "rows": [["look", mutation], ["open", True]],
                }},
                "history": {"action_results": actions},
            }

        repeated = compile_agent_context(context([row(), row()]))
        self.assertIn("EXECUTION_PROGRESS_SIGNAL", repeated.text)
        self.assertIn("robot.camera", repeated.text)
        self.assertIn("unchanged_public_observation_labels", repeated.text)
        self.assertIn("read-only action exactly repeats", repeated.text)
        self.assertEqual(repeated.section_count, 6)
        self.assertNotIn("SECRET", repeated.text)
        self.assertNotIn("robot.hidden", repeated.text)
        before_facet = {
            **observation,
            "validity": {
                "generation": "world-epoch-a",
                "observation_id": "observation:7",
                "temporal_scope": "at_observation",
            },
        }
        after_facet = {
            **observation,
            "validity": {
                "generation": "world-epoch-a",
                "observation_id": "observation:8",
                "temporal_scope": "at_observation",
            },
        }
        fresh = compile_agent_context(context([
            row(facet=before_facet), row(facet=after_facet),
        ]))
        self.assertIn("EXECUTION_PROGRESS_SIGNAL", fresh.text)
        different_generation = compile_agent_context(context([
            row(facet=before_facet),
            row(facet={
                **after_facet,
                "validity": {
                    **after_facet["validity"], "generation": "world-epoch-b",
                },
            }),
        ]))
        self.assertNotIn("EXECUTION_PROGRESS_SIGNAL", different_generation.text)

        # No claim of stagnation without identical read-only operations
        # and matching authoritative observations.
        cases = (
            context([row(), row("open")]),
            context([row(), row()], mutation=True),
            context([row(), row(certainty="indeterminate")]),
            context([row(), row(facet={
                **observation, "value": {"visible": ["door"]},
            })]),
        )
        for item in cases:
            with self.subTest(item=item):
                compiled = compile_agent_context(item)
                self.assertNotIn("EXECUTION_PROGRESS_SIGNAL", compiled.text)
                self.assertEqual(compiled.section_count, 5)

    def test_previous_provider_feedback_is_not_reconstructed_from_execution_trace(self):
        def row(index, *, certainty="effect_confirmed"):
            action = {"action_type": "craft_item", "arguments": {"item": f"item_{index}"}}
            return {"action": action, "outcome": {
                "effect_receipt": {"certainty": certainty},
                "state": {"last_outcome": {"code": "ITEM_CRAFTED", "secret": "HIDDEN"}},
                "agent_context_facets": [{
                    "label": "minecraft.last_action_feedback",
                    "truth_class": "observed",
                    "source": "environment.minecraft.authorized_observation",
                    "value": {"outcome": {"code": "ITEM_CRAFTED",
                                          "inventory_delta": {"stick": 1}}},
                }],
            }}
        actions = [row(i) for i in range(10)]
        projection = compile_agent_context({
            "goal": {"goal": "craft sticks"},
            "history": {"action_results": actions},
        }).text
        for token in ("recent_causal_steps", "earlier_steps_count", "sequence_index",
                      "public_action_feedback", "ITEM_CRAFTED", "HIDDEN"):
            self.assertNotIn(token, projection)
        self.assertNotIn("CAUSAL_HISTORY", projection)

    def test_current_control_feedback_is_visible_without_replaying_action_history(self):
        projection = compile_agent_context({
            "goal": {"goal": "obtain tools"},
            "history": {
                "action_results": [{
                    "action": {"action_type": "craft_item", "arguments": {"item": "wooden_shovel"}},
                    "outcome": {"state": {"last_outcome": {"code": "NO_RECIPE_OR_MATERIALS"}}},
                }],
                "planner_contract_feedback": {
                    "code": "planner.provider_recovery",
                    "instruction": "choose the current authorized recovery",
                },
            },
        }).text
        self.assertIn("CURRENT_CONTROL_FEEDBACK", projection)
        self.assertIn("planner.provider_recovery", projection)
        self.assertIn("choose the current authorized recovery", projection)
        self.assertNotIn("NO_RECIPE_OR_MATERIALS", projection)
        self.assertNotIn("recent_causal_steps", projection)

    def test_inventory_aware_recipe_dependency_is_visible_as_reference_not_world_truth(self):
        observed = {
            "inventory": {"oak_log": 2},
            "last_action": {"tool": "recipe_dependencies", "item": "stick"},
            "last_outcome": {
                "code": "RECIPE_DEPENDENCIES_REFERENCED", "status": "applied",
                "truth_class": "declared",
                "source": "version_pinned_vanilla_minecraft_data",
                "item": "stick", "count": 4, "item_known": True,
                "minecraft_version": "1.21.1",
                "authoritative_for_current_world": False,
                "authoritative_for_current_world_recipe": False,
                "datapack_rules_included": False,
                "no_physical_effect": True,
                "declared_reference_truth": True,
                "observed_inventory_truth": True,
                "inventory_source": "currently_observed_mineflayer_inventory",
                "inventory_before": {"oak_log": 2},
                "inventory_after_reference_allocation": {"oak_log": 1},
                "reference_crafting_steps": [{"output_item": "stick",
                                                "input_items": {"oak_planks": 2}}],
                "unresolved_acquisition_inputs": {"oak_planks": 2},
                "secret_rule": "NEVER_EXPOSE",
            },
        }
        facets = minecraft_agent_context_facets(observed)
        by_label = {row["label"]: row for row in facets}
        self.assertEqual(
            by_label["minecraft.crafting_dependency_alternatives"]["truth_class"],
            "declared",
        )
        self.assertNotIn("minecraft.reference_crafting_dependencies", by_label)
        self.assertNotIn("minecraft.dependency_inventory_snapshot", by_label)
        self.assertEqual(
            by_label["minecraft.holdings"]["value"]["item_counts"],
            {"oak_log": 2},
        )
        prompt = compile_agent_context({
            "goal": {"goal": "craft sticks"}, "environment": facets,
        }).text
        self.assertIn("unresolved_inputs", prompt)
        self.assertIn("oak_planks", prompt)
        self.assertNotIn("inventory_after_reference_allocation_is_hypothetical", prompt)
        self.assertNotIn("NEVER_EXPOSE", prompt)
        # A hidden active-world rule or an unverified inventory reference
        # must not be promoted into an authorized public planning document.
        invalid = dict(observed)
        invalid["last_outcome"] = {
            **observed["last_outcome"], "datapack_rules_included": True,
        }
        labels = {row["label"] for row in minecraft_agent_context_facets(invalid)}
        self.assertNotIn("minecraft.reference_crafting_dependencies", labels)


def test_rejection_stall_signal_does_not_cross_confirmed_physical_effect():
    from noetrium_platform.research.execution.workflow.composition.agent_context import compile_agent_context

    def rejected():
        return {
            "action": {"action_type": "craft_item", "arguments": {"item": "stick"}},
            "outcome": {
                "effect_receipt": {"certainty": "effect_rejected"},
                "agent_context_facets": [{
                    "label": "minecraft.last_action_feedback",
                    "truth_class": "observed",
                    "source": "environment.minecraft.authorized_observation",
                    "value": {"outcome": {"code": "NO_RECIPE_OR_MATERIALS", "status": "rejected"}},
                }],
            },
        }

    changed = {
        "action": {"action_type": "collect_block", "arguments": {"block": "oak_log"}},
        "outcome": {
            "effect_receipt": {"certainty": "effect_confirmed"},
            "agent_context_facets": [],
        },
    }
    catalog = {"actions": {
        "columns": ("action_type", "mutates_world"),
        "rows": (("craft_item", True), ("collect_block", True)),
    }}
    # Two old rejections separated from the current rejection by a real world
    # change must not be summarized as a current repeated-failure signal.
    text = compile_agent_context({
        "goal": {"goal": "obtain sticks"},
        "history": {"action_results": [rejected(), rejected(), changed, rejected()]},
        "capabilities": catalog,
    }).text
    assert "repeated_rejected_mutating_actions" not in text




def test_fulfilled_bounded_mutation_emits_request_scope_progress_signal():
    from noetrium_platform.research.execution.workflow.composition.agent_context import (
        compile_agent_context,
    )

    def result(*, certainty="effect_confirmed", requested=6, observed=6):
        return {
            "action": {
                "action_type": "collect_resource",
                "arguments": {"resource": "opaque_wood", "count": 6},
            },
            "outcome": {
                "effect_receipt": {
                    "certainty": certainty,
                    "effect_class": "reconcilable",
                },
                "state": {"private_world_secret": "NEVER_EXPOSE"},
                "decision_constraints": ({
                    "truth_class": "observed",
                    "source": "environment.synthetic.authorized_observation",
                    "constraint": {
                        "kind": "bounded_request_completed",
                        "requested_count": requested,
                        "observed_count": observed,
                        "valid_until": "physical_effect",
                    },
                },),
            },
        }

    catalog = {
        "actions": {
            "columns": ("action_type", "mutates_world"),
            "rows": (("collect_resource", True),),
        },
    }
    prompt = compile_agent_context({
        "goal": {"objective": "obtain enough material for the goal"},
        "history": {"action_results": [result()]},
        "capabilities": catalog,
    }).text
    assert "fulfilled_bounded_request" in prompt
    assert '"scope":"request_only_not_task_goal"' in prompt
    assert "complete, not the task" in prompt
    assert "NEVER_EXPOSE" not in prompt
    assert "bounded_request_completed" not in prompt

    # Incomplete or uncertain evidence cannot become a completion signal.
    for row in (
        result(observed=4),
        result(certainty="indeterminate"),
    ):
        text = compile_agent_context({
            "goal": {"objective": "obtain enough material for the goal"},
            "history": {"action_results": [row]},
            "capabilities": catalog,
        }).text
        assert "fulfilled_bounded_request" not in text

    # Authority classification is required; source metadata alone cannot turn
    # a read-only operation into physical progress.
    read_only_catalog = {
        "actions": {
            "columns": ("action_type", "mutates_world"),
            "rows": (("collect_resource", False),),
        },
    }
    text = compile_agent_context({
        "goal": {"objective": "obtain enough material for the goal"},
        "history": {"action_results": [result()]},
        "capabilities": read_only_catalog,
    }).text
    assert "fulfilled_bounded_request" not in text


if __name__ == "__main__":
    unittest.main()


def test_repeated_rejected_mutations_emit_a_visibility_safe_no_progress_signal():
    from noetrium_platform.research.execution.workflow.composition.agent_context import (
        compile_agent_context,
    )

    def attempt(name: str, args: dict, code: str):
        return {
            "action": {"action_type": name, "arguments": args},
            "outcome": {
                "effect_receipt": {"certainty": "effect_rejected"},
                # The model must never receive unprojected hidden state.
                "state": {"last_outcome": {
                    "code": code,
                    "hidden_rule_manifest": "PRIVATE_WORLD_SECRET",
                }},
                "agent_context_facets": [{
                    "label": "minecraft.last_action_feedback",
                    "truth_class": "observed",
                    "source": "environment.minecraft.authorized_observation",
                    "value": {"outcome": {"code": code, "status": "rejected"}},
                }],
            },
        }

    history = {
        "action_results": [
            attempt("collect_block", {"block": "stick"}, "BLOCK_NOT_COLLECTED"),
            attempt("craft_item", {"item": "stick"}, "CRAFTING_TABLE_REQUIRED"),
            attempt("collect_block", {"block": "stick"}, "BLOCK_NOT_COLLECTED"),
            attempt("craft_item", {"item": "stick"}, "CRAFTING_TABLE_REQUIRED"),
        ],
    }
    catalog = {
        "actions": {
            "columns": ("action_type", "mutates_world"),
            "rows": (("collect_block", True), ("craft_item", True)),
        },
    }
    prompt = compile_agent_context({
        "goal": {"objective": "obtain one stick"},
        "history": history,
        "capabilities": catalog,
    }).text
    assert "repeated_rejected_mutating_actions" in prompt
    assert '"rejection_count":2' in prompt
    assert "BLOCK_NOT_COLLECTED" in prompt
    assert "CRAFTING_TABLE_REQUIRED" in prompt
    assert "PRIVATE_WORLD_SECRET" not in prompt
    assert "The world may have changed" in prompt

    # Indeterminate outcomes must never become an assertion of rejection.
    for step in history["action_results"]:
        step["outcome"]["effect_receipt"]["certainty"] = "indeterminate"
    uncertain = compile_agent_context({
        "goal": {"objective": "obtain one stick"},
        "history": history,
        "capabilities": catalog,
    }).text
    assert "repeated_rejected_mutating_actions" not in uncertain


def test_minecraft_blocked_collection_prompts_for_authorized_dependencies_not_hidden_recipes():
    from noetrium_platform.capabilities.environment.minecraft.api.agent_context import (
        minecraft_agent_context_facets,
    )
    facets = minecraft_agent_context_facets({
        "inventory": [],
        "last_action": {"tool": "collect_block", "block": "stick"},
        "last_outcome": {
            "status": "rejected",
            "code": "BLOCK_NOT_COLLECTED",
            "alternative_production_evidence": {
                "source": "private_datapack_rules",
                "recipe_secret": "NEVER_EXPOSE_THIS",
            },
        },
    })
    labels = {row["label"]: row for row in facets}
    assert "minecraft.physical_blocker" not in labels
    feedback = labels["minecraft.last_action_feedback"]["value"]["outcome"]
    assert feedback["status"] == "rejected"
    assert feedback["code"] == "BLOCK_NOT_COLLECTED"
    prompt = compile_agent_context({
        "goal": {"task": "get sticks"},
        "environment": facets,
    }).text
    assert '"code":"BLOCK_NOT_COLLECTED"' in prompt
    assert "NEVER_EXPOSE_THIS" not in prompt
    assert "private_datapack_rules" not in prompt
