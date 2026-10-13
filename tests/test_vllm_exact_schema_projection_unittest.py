"""Fast local decoding must preserve every original output constraint."""
from __future__ import annotations

import copy
import json
import unittest
from types import SimpleNamespace

from noetrium_platform.foundation.kernel.kernel import freeze_json
from noetrium_platform.capabilities.model.serving.provider.structured_schema import (
    strict_original_schema, validate_original_structured_response,
    xgrammar_wire_projection,
)


class ExactSchemaProjectionTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "action",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["collect_block"],
                            },
                            "minimum": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 32,
                            },
                            "radius": {
                                "type": "number",
                                "minimum": 0.1,
                                "maximum": 64,
                            },
                            "subgoals": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": 8,
                            },
                        },
                        "required": ["action", "minimum", "radius", "subgoals"],
                        "additionalProperties": False,
                    },
                },
            }
        }
        self.valid = {
            "action": "collect_block",
            "minimum": 16,
            "radius": 0.5,
            "subgoals": ["collect"],
        }

    def test_wire_projection_is_nonmutating_and_keeps_property_names(self):
        before = copy.deepcopy(self.original)
        wire = xgrammar_wire_projection(self.original)
        self.assertEqual(self.original, before)
        schema = strict_original_schema(wire)
        self.assertIn("minimum", schema["properties"])
        self.assertNotIn("minimum", schema["properties"]["minimum"])
        self.assertNotIn("maximum", schema["properties"]["radius"])
        self.assertNotIn("maxItems", schema["properties"]["subgoals"])
        self.assertNotIn("prefixItems", schema["properties"]["subgoals"])
        self.assertEqual(
            schema["properties"]["subgoals"]["items"],
            {"type": "string"},
        )
        self.assertEqual(schema["required"], before["response_format"]["json_schema"]["schema"]["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            wire["guided_decoding_backend"],
            "xgrammar:disable-any-whitespace",
        )
        self.assertNotIn("guided_decoding_backend", self.original)

    def test_wire_does_not_synthesize_prefix_items_for_xgrammar_0_1_18(self):
        wire = xgrammar_wire_projection(self.original)
        self.assertIsNotNone(wire)
        subgoals = strict_original_schema(wire)["properties"]["subgoals"]
        self.assertEqual(subgoals["items"], {"type": "string"})
        self.assertNotIn("prefixItems", subgoals)
        self.assertNotIn("maxItems", subgoals)

    def test_semantic_bounds_still_validate_exactly(self):
        for key, invalid in [
            ("minimum", 0),
            ("minimum", 33),
            ("radius", 0.09),
            ("radius", 64.1),
            ("subgoals", []),
            ("subgoals", ["x"] * 9),
            ("action", "unauthorized"),
        ]:
            with self.subTest(key=key, invalid=invalid):
                output = dict(self.valid, **{key: invalid})
                with self.assertRaisesRegex(ValueError, "original JSON schema"):
                    validate_original_structured_response(json.dumps(output), self.original)
        validate_original_structured_response(json.dumps(self.valid), self.original)

    def test_missing_required_or_extra_fields_are_rejected(self):
        for invalid in (
            {"action": "collect_block"},
            {**self.valid, "unauthorized": True},
        ):
            with self.assertRaises(ValueError):
                validate_original_structured_response(json.dumps(invalid), self.original)

    def test_json_syntax_and_type_failure_are_closed(self):
        with self.assertRaises(ValueError):
            validate_original_structured_response("not json", self.original)
        with self.assertRaises(ValueError):
            validate_original_structured_response('{"action":123}', self.original)

    def test_compilation_is_reused_without_reusing_model_outputs(self):
        from noetrium_platform.capabilities.model.serving.provider.structured_schema import (
            _compiled_xgrammar_projection,
            _compiled_exact_validator,
        )
        body = freeze_json(self.original)
        before = _compiled_xgrammar_projection.cache_info().hits
        first = xgrammar_wire_projection(body)
        second = xgrammar_wire_projection(body)
        assert first is not None and second is not None
        self.assertGreater(_compiled_xgrammar_projection.cache_info().hits, before)
        self.assertIs(
            first["response_format"]["json_schema"]["schema"],
            second["response_format"]["json_schema"]["schema"],
        )
        before_validation = _compiled_exact_validator.cache_info().hits
        validate_original_structured_response(json.dumps(self.valid), body)
        validate_original_structured_response(json.dumps(self.valid), body)
        self.assertGreater(_compiled_exact_validator.cache_info().hits, before_validation)
        invalid = dict(self.valid, minimum=0)
        with self.assertRaises(ValueError):
            validate_original_structured_response(json.dumps(invalid), body)

    def test_frozen_noetrium_request_preserves_json_array_types(self):
        frozen = freeze_json(self.original)
        projected = xgrammar_wire_projection(frozen)
        self.assertIsNotNone(projected)
        validate_original_structured_response(json.dumps(self.valid), frozen)
        self.assertIsInstance(strict_original_schema(frozen)["required"], list)

    def test_native_vllm_provider_plan_preserves_original_schema(self):
        from noetrium_platform.capabilities.model.serving.provider.api import (
            ModelProviderRequestPlanner,
        )
        from noetrium_platform.capabilities.model.serving.provider.native import (
            NativeModelProviderProfileResolver,
            NativeModelProviderProtocolRegistry,
        )
        from noetrium_platform.capabilities.model.serving.endpoint.providers.native import (
            NativeModelProviderEndpoint,
        )
        profile = NativeModelProviderProfileResolver().resolve(
            logical_model_name="Qwen3-8B",
            provider_model_name="Qwen3-8B",
            model_engine="vllm",
        )

        class Probe:
            _planner = ModelProviderRequestPlanner()
            _protocols = NativeModelProviderProtocolRegistry()
            _api_key = ""

            def _provider_profile(self, request):
                return profile

        request = SimpleNamespace(body=freeze_json({
            "model": "Qwen3-8B",
            "messages": ({"role": "user", "content": "Return an action"},),
            **self.original,
        }))
        plan, wire = NativeModelProviderEndpoint._plan(Probe(), request)
        full = strict_original_schema(plan.standard_body)
        fast = strict_original_schema(wire.body)
        self.assertEqual(full["properties"]["minimum"]["minimum"], 1)
        self.assertNotIn("minimum", fast["properties"]["minimum"])
        self.assertTrue(wire.wire_bytes)
        self.assertNotEqual(full, fast)
        self.assertEqual(
            wire.body["guided_decoding_backend"],
            "xgrammar:disable-any-whitespace",
        )
        self.assertNotIn("guided_decoding_backend", plan.standard_body)

    def test_vllm_unsupported_formats_multiples_and_array_membership_remain_exact(self):
        schema = {
            "type": "object",
            "properties": {
                "format": {"type": "integer", "multipleOf": 3},
                "address": {"type": "string", "format": "ipv4"},
                "numbers": {
                    "type": "array", "items": {"type": "integer"},
                    "uniqueItems": True, "contains": {"const": 9},
                    "minContains": 1, "maxContains": 2,
                },
            },
            "required": ["format", "address", "numbers"],
            "additionalProperties": False,
        }
        original = {"response_format": {
            "type": "json_schema", "json_schema": {
                "name": "constraints", "strict": True, "schema": schema,
            },
        }}
        wire = xgrammar_wire_projection(freeze_json(original))
        self.assertIsNotNone(wire)
        fast = strict_original_schema(wire)
        self.assertIn("format", fast["properties"])
        self.assertNotIn("multipleOf", fast["properties"]["format"])
        self.assertNotIn("format", fast["properties"]["address"])
        for key in ("uniqueItems", "contains", "minContains", "maxContains"):
            self.assertNotIn(key, fast["properties"]["numbers"])
        valid = {"format": 6, "address": "192.168.0.1", "numbers": [1, 9, 2]}
        validate_original_structured_response(json.dumps(valid), original)
        for invalid in (
            {**valid, "format": 7},
            {**valid, "address": "not-an-ip"},
            {**valid, "numbers": [1, 1, 9]},
            {**valid, "numbers": [1, 2, 3]},
            {**valid, "numbers": [9, 9, 1]},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "original JSON schema"):
                    validate_original_structured_response(json.dumps(invalid), original)


    def test_union_failure_reports_specific_nested_constraint_for_repair(self):
        original = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "planner",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "anyOf": [
                                    {
                                        "type": "object",
                                        "properties": {
                                            "action_type": {"type": "string", "enum": ["collect_block"]},
                                            "arguments": {
                                                "type": "object",
                                                "properties": {
                                                    "block": {"type": "string"},
                                                    "max_distance": {"type": "number", "minimum": 4, "maximum": 128},
                                                },
                                                "required": ["block"],
                                                "additionalProperties": False,
                                            },
                                        },
                                        "required": ["action_type", "arguments"],
                                        "additionalProperties": False,
                                    },
                                    {
                                        "type": "object",
                                        "properties": {
                                            "action_type": {"type": "string", "enum": ["observe_blocks"]},
                                            "arguments": {"type": "object", "additionalProperties": False},
                                        },
                                        "required": ["action_type", "arguments"],
                                        "additionalProperties": False,
                                    },
                                ]
                            }
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                },
            }
        }
        invalid = {
            "action": {
                "action_type": "collect_block",
                "arguments": {"block": "oak_log", "max_distance": 2},
            }
        }
        with self.assertRaisesRegex(
            ValueError, r"minimum at action/arguments/max_distance.*less than the minimum of 4"
        ):
            validate_original_structured_response(json.dumps(invalid), original)

    def test_plain_json_object_is_untouched_but_strict_schema_gets_whitespace_guard(self):
        self.assertIsNone(xgrammar_wire_projection({"response_format": {"type": "json_object"}}))
        orig=copy.deepcopy(self.original)
        schema=orig["response_format"]["json_schema"]["schema"]
        schema["properties"]["minimum"].pop("minimum")
        schema["properties"]["minimum"].pop("maximum")
        schema["properties"]["radius"].pop("minimum")
        schema["properties"]["radius"].pop("maximum")
        schema["properties"]["subgoals"].pop("minItems")
        schema["properties"]["subgoals"].pop("maxItems")
        wire = xgrammar_wire_projection(orig)
        self.assertIsNotNone(wire)
        self.assertEqual(
            wire["guided_decoding_backend"],
            "xgrammar:disable-any-whitespace",
        )
        self.assertEqual(strict_original_schema(wire), schema)
        self.assertNotIn("guided_decoding_backend", orig)

    def test_existing_xgrammar_options_are_merged_without_overriding_other_backends(self):
        xgrammar = copy.deepcopy(self.original)
        xgrammar["guided_decoding_backend"] = "xgrammar:no-fallback"
        wire = xgrammar_wire_projection(xgrammar)
        self.assertIsNotNone(wire)
        self.assertEqual(
            wire["guided_decoding_backend"],
            "xgrammar:disable-any-whitespace,no-fallback",
        )
        other = copy.deepcopy(self.original)
        other["guided_decoding_backend"] = "outlines"
        self.assertIsNone(xgrammar_wire_projection(other))
        self.assertEqual(other["guided_decoding_backend"], "outlines")


if __name__ == "__main__":
    unittest.main()
