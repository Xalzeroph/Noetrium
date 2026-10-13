from __future__ import annotations

import unittest

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, thaw_json
from noetrium_platform.research.execution.workflow.composition.model_agent import (
    MethodViewChatRequestFactory,
)
from noetrium_platform.research.execution.workflow.api.method_machine import (
    MethodAgentRequest,
)
from noetrium_platform.research.execution.workflow.api import (
    capability_authorized_action_contracts,
    compact_authorized_action_catalog,
    compile_authorized_action_generation,
)


def row(name, schema, domain):
    return {
        "action_type": name,
        "description": "Authorized " + name,
        "category": domain,
        "arguments": name + " signature",
        "argument_schema": schema,
        "argument_semantics": {},
        "applicability": (),
        "mutates_world": True,
    }


def envelope(actions, authorized):
    return {"environment_capabilities": [{
        "action_types": authorized,
        "metadata": {"action_contracts": actions},
    }]}


class UniversalAuthoringTests(unittest.TestCase):
    def test_gui_and_robotic_action_schemas_share_the_same_authority(self):
        gui = row("click", {
            "type": "object", "properties": {"control_id": {"type": "string"}},
            "required": ["control_id"], "additionalProperties": False,
        }, "gui")
        robot = row("move_joint", {
            "type": "object", "properties": {
                "joint": {"type": "integer", "minimum": 0, "maximum": 7},
                "target_radians": {"type": "number", "minimum": -3.14, "maximum": 3.14},
            },
            "required": ["joint", "target_radians"], "additionalProperties": False,
        }, "embodiment")
        actions = capability_authorized_action_contracts(
            envelope([gui, robot], ("click", "move_joint"))
        )
        compact = compact_authorized_action_catalog(actions)
        self.assertEqual(len(compact["rows"]), 2)
        self.assertNotIn("argument_schema", compact["columns"])
        self.assertEqual(set(compact["columns"]), set(gui) - {"argument_schema"})
        result = compile_authorized_action_generation(
            actions, name="multimodal_action", optional_fields={
                "reason": {"type": "string"},
            }
        )
        self.assertEqual(result["response_format"]["json_schema"]["name"], "multimodal_action")
        schema = result["response_format"]["json_schema"]["schema"]
        branches = schema["properties"]["action"]["anyOf"]
        self.assertEqual(len(branches), 2)
        joint = next(x for x in branches if x["properties"]["action_type"]["enum"] == ["move_joint"])
        self.assertEqual(joint["properties"]["arguments"]["properties"]["joint"]["maximum"], 7)

    def test_non_authorized_action_never_enters_model_context(self):
        entry = row("secret", {"type": "object", "properties": {}}, "gui")
        with self.assertRaisesRegex(ValueError, "non-authorized action"):
            capability_authorized_action_contracts(envelope([entry], ()))

    def test_capability_conflicts_fail_closed(self):
        entry = row("click", {"type": "object", "properties": {}}, "gui")
        other = {**entry, "description": "conflicting"}
        m = {"environment_capabilities": [
            {"action_types": ["click"], "metadata": {"action_contracts": [entry]}},
            {"action_types": ["click"], "metadata": {"action_contracts": [other]}},
        ]}
        with self.assertRaisesRegex(ValueError, "incompatible authorized action"):
            capability_authorized_action_contracts(m)

    def test_model_must_not_override_action_discriminant(self):
        entry = row("click", {"type": "object", "properties": {}}, "gui")
        with self.assertRaisesRegex(ValueError, "cannot override"):
            compile_authorized_action_generation(
                [entry], optional_fields={"action": {"type": "object"}},
            )

    def test_actual_model_factory_generates_matching_authorized_prompt_and_grammar(self):
        gui = row("click", {
            "type": "object", "properties": {
                "control_id": {"type": "string"},
            }, "required": ["control_id"], "additionalProperties": False,
        }, "gui")
        authorized = envelope([gui], ("click",))
        view = {
            "system": "Apply the method's own decision rules.",
            "agent_context": {
                "goal": {"goal": "Save the document"},
                "environment": [{"label": "gui.controls", "truth_class": "observed",
                                 "source": "environment.gui", "value": {"active": "Save"}}],
                "memory": {"records": [{"subject": "document", "status": "pending"}]},
                "capabilities": {"actions": [{"action_type": "FORGED_DELETE"}]},
            },
            "action_authoring": {
                "capability_metadata": authorized,
                "schema_name": "save_action",
                "max_tokens": 384,
            },
        }
        request = MethodAgentRequest(
            agent_id="gui.agent", goal=None, view=view,
            input_value=None, previous_value=None,
            context=ExecutionContext("run", "trace", "span", task_id="task"),
        )
        compiled = MethodViewChatRequestFactory("gui-model", {}).compile(request)
        body = compiled.body
        self.assertEqual(body["model"], "gui-model")
        self.assertEqual(len(body["messages"]), 2)
        self.assertIn("Apply the method", body["messages"][0]["content"])
        self.assertIn("gui.controls", body["messages"][1]["content"])
        self.assertIn("records", body["messages"][1]["content"])
        self.assertNotIn("FORGED_DELETE", body["messages"][1]["content"])
        self.assertIn("click", body["messages"][1]["content"])
        self.assertEqual(
            thaw_json(body["response_format"]["json_schema"]["schema"]["properties"]["action"]["anyOf"][0]
            ["properties"]["arguments"]), gui["argument_schema"]
        )
        self.assertEqual(body["response_format"]["json_schema"]["name"], "save_action")

    def test_default_json_object_contract_upgrades_but_second_custom_schema_rejects(self):
        action = row("click", {
            "type": "object", "properties": {
                "control_id": {"type": "string"}
            }, "additionalProperties": False,
        }, "gui")
        info = {
            "goal": {"goal": "click Save"},
            "environment": [{"label": "gui.controls", "truth_class": "observed",
                             "source": "gui.provider", "value": {"visible": ["Save"]}}],
        }
        request = MethodAgentRequest(
            agent_id="gui.agent", goal=None,
            view={"system": "Use your own strategy", "agent_context": info,
                  "action_authoring": {"capability_metadata":
                      envelope([action], ("click",))}},
            input_value=None, previous_value=None,
            context=ExecutionContext("run", "trace", "span"),
        )
        factory = MethodViewChatRequestFactory("model", {
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0.0,
        })
        compiled = factory.compile(request)
        self.assertEqual(compiled.body["response_format"]["type"], "json_schema")
        self.assertEqual(compiled.body["chat_template_kwargs"]["enable_thinking"], False)
        self.assertEqual(compiled.body["temperature"], 0.0)
        blocked = MethodViewChatRequestFactory("model", {
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "second", "schema": {"type": "object"}}},
        })
        with self.assertRaisesRegex(ValueError, "conflicts"):
            blocked.compile(request)

    def test_detail_discovery_compacts_only_the_default_decision_catalog(self):
        inspect = row("describe_action", {
            "type": "object",
            "properties": {"action_type": {"type": "string"}},
            "required": ["action_type"], "additionalProperties": False,
        }, "inspection")
        act = row("click", {
            "type": "object",
            "properties": {"control_id": {"type": "string"}},
            "required": ["control_id"], "additionalProperties": False,
        }, "gui")
        act["argument_semantics"] = {"control_id": "visible authorized control"}
        act["applicability"] = ("only a visible authorized control",)
        compact = compact_authorized_action_catalog((act, inspect))
        self.assertEqual(compact["details_via"], "describe_action")
        self.assertNotIn("applicability", compact["columns"])
        self.assertNotIn("argument_semantics", compact["columns"])
        self.assertNotIn("description", compact["columns"])
        self.assertEqual(
            set(compact["columns"]),
            {"action_type", "category", "arguments", "mutates_world"},
        )
        self.assertEqual([r[0] for r in compact["rows"]], ["click", "describe_action"])
        compiled = compile_authorized_action_generation((act, inspect))
        branches = compiled["response_format"]["json_schema"]["schema"]["properties"]["action"]["anyOf"]
        self.assertEqual(len(branches), 2)
        self.assertEqual(
            branches[0]["properties"]["arguments"],
            act["argument_schema"],
        )
        # Without an authorized detail action no prose/applicability facts are
        # lost from the Agent's available decision view.
        unexpanded = compact_authorized_action_catalog((act,))["columns"]
        self.assertIn("applicability", unexpanded)
        self.assertIn("description", unexpanded)

    def test_catalog_requires_exactly_matching_columnar_fields(self):
        entry = row("click", {"type": "object", "properties": {}}, "gui")
        other = {**entry, "action_type": "wait"}
        other.pop("description")
        with self.assertRaises(ValueError):
            compact_authorized_action_catalog([entry, other])


if __name__ == "__main__":
    unittest.main()
