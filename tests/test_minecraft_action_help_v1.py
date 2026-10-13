from __future__ import annotations

import unittest
from types import SimpleNamespace

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_ACTION_TYPES, minecraft_action_catalog, validate_minecraft_action
)
from noetrium_platform.capabilities.environment.minecraft.runtime.action_coordinator import (
    MinecraftActionCoordinator, MinecraftActionCoordinatorBindings, _minecraft_action_effect_class
)
from noetrium_platform.capabilities.environment.api import ActionRequest
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext
from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL


class _Bridge:
    def __init__(self):
        self.calls = []

    def command(self, name, payload, *, timeout_s, control):
        self.calls.append((name, payload))
        raise RuntimeError("stop before any server effect")


def _coordinator(bridge, allowed):
    return MinecraftActionCoordinator(
        session_id="test", generation="f" * 64,
        provider_instance_id="minecraft:test", command_timeout_s=4.0,
        bridge=bridge,
        allowed_action_types=frozenset(allowed),
        bindings=MinecraftActionCoordinatorBindings(
            event_log=lambda *args, **kwargs: None,
            failure_log=lambda *args, **kwargs: None,
            ingest_events=lambda *args, **kwargs: None,
            observation=lambda **kwargs: None,
            state_payload=lambda: {"state": {"inventory": {}, "position": {}}},
            last_observation=lambda: None,
        ),
    )


def _request(target):
    return ActionRequest(
        "query-" + target, "describe_action", {"action_type": target},
        ExecutionContext("run", "trace", "span", task_id="task"),
    )


class ActionHelpContractTests(unittest.TestCase):
    def test_canonical_action_directory_contains_one_introspection_action(self):
        catalog = {r.action_type: r for r in minecraft_action_catalog()}
        self.assertEqual(len(catalog), len(MINECRAFT_ACTION_TYPES))
        self.assertIn("describe_action", catalog)
        self.assertEqual(_minecraft_action_effect_class("describe_action"), EffectClass.PURE)
        self.assertEqual(validate_minecraft_action(
            "describe_action", {"action_type": "equip_item"}
        ), {"action_type": "equip_item"})

    def test_provider_receives_only_authorized_exact_schema_from_unit(self):
        bridge = _Bridge()
        instance = _coordinator(bridge, {"equip_item", "describe_action"})
        with self.assertRaises(Exception):
            instance.act(_request("equip_item"), UNBOUNDED_EXECUTION_CONTROL)
        self.assertEqual(len(bridge.calls), 1)
        name, payload = bridge.calls[0]
        self.assertEqual(name, "describe_action")
        reference = payload["_authorized_action_reference"]
        canonical = {
            row.action_type: row for row in minecraft_action_catalog()
        }["equip_item"]
        self.assertEqual(reference["action_type"], canonical.action_type)
        self.assertEqual(reference["argument_schema"]["properties"]["destination"]["enum"],
                         ["hand", "off-hand", "head", "torso", "legs", "feet"])
        self.assertNotIn("main_hand", reference["argument_schema"]["properties"]["destination"]["enum"])
        self.assertNotIn("hidden_rule_manifest", str(reference))

    def test_restricted_target_cannot_introspect_forbidden_capability(self):
        bridge = _Bridge()
        instance = _coordinator(bridge, {"describe_action"})
        # Whether a refusal observation is present depends on the test
        # observation factory; neither branch may send any target metadata.
        try:
            instance.act(_request("equip_item"), UNBOUNDED_EXECUTION_CONTROL)
        except Exception:
            pass
        self.assertEqual(bridge.calls, [])

    def test_validator_never_accepts_unknown_help_arguments(self):
        from noetrium_platform.capabilities.environment.minecraft.api import (
            MinecraftActionContractError,
        )
        with self.assertRaises((ValueError, TypeError, MinecraftActionContractError)):
            validate_minecraft_action("describe_action",
                {"action_type": "equip_item", "_authorized_action_reference": {}})


if __name__ == "__main__":
    unittest.main()
