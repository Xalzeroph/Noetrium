from __future__ import annotations

import unittest

from noetrium_platform.capabilities.environment.api import EnvironmentCapabilityDescriptor
from noetrium_platform.capabilities.environment.minecraft.api import minecraft_action_catalog
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor, CapabilityRequest, CapabilityResult,
    capability_request_digest, capability_request_effect_class,
)
from noetrium_platform.composition.environment_capabilities.capability import (
    EnvironmentCapabilityProvider, environment_capability_descriptor_metadata,
)
from noetrium_platform.composition.workflows.agent_turn.capability_effects import (
    CapabilityEffectIdentityConflict, require_capability_effect_result,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass, EffectCertainty, EffectReceipt, ExecutionContext,
)


def descriptor():
    catalog = minecraft_action_catalog()
    provider = EnvironmentCapabilityDescriptor(
        capability_id="minecraft.world", version="1.21.1",
        action_types=tuple(c.action_type for c in catalog),
        query_types=("state",),
        metadata={"action_contracts": tuple(c.as_payload() for c in catalog)},
    )
    return CapabilityDescriptor(
        capability_id="environment.act", interface_version="1",
        request_schema="minecraft.test.action", result_schema="minecraft.test.result",
        effect_class=EffectClass.RECONCILABLE,
        metadata=environment_capability_descriptor_metadata((provider,)),
    )


def request(name):
    return CapabilityRequest(
        capability_id="environment.act",
        payload={"action_type": name, "payload": {"action_type": "equip_item"} if name == "describe_action" else {}},
        context=ExecutionContext("run", "trace", "span", task_id="task"),
        idempotency_key="request:" + name,
    )


def receipt(request_, kind):
    return EffectReceipt(
        effect_id="provider:test",
        request_digest="a" * 64,
        effect_class=kind,
        certainty=EffectCertainty.EFFECT_CONFIRMED,
    )


class ConditionalEffectTruthTests(unittest.TestCase):
    def test_catalog_action_class_is_unique_and_bounded(self):
        d = descriptor()
        classes = d.metadata["action_effect_classes"]
        self.assertEqual(len(classes), len(minecraft_action_catalog()))
        self.assertEqual(
            capability_request_effect_class(d, request("describe_action")),
            EffectClass.PURE,
        )
        self.assertEqual(
            capability_request_effect_class(d, request("observe_blocks")),
            EffectClass.PURE,
        )
        self.assertEqual(
            capability_request_effect_class(d, request("collect_block")),
            EffectClass.RECONCILABLE,
        )

    def test_adapter_and_executor_preserve_exact_pure_receipt(self):
        d = descriptor()
        wrapper = object.__new__(EnvironmentCapabilityProvider)
        wrapper._descriptor = d
        r = request("describe_action")
        result_receipt = wrapper._outer_effect(r, receipt(r, EffectClass.PURE))
        self.assertEqual(result_receipt.effect_class, EffectClass.PURE)
        self.assertEqual(result_receipt.certainty, EffectCertainty.EFFECT_CONFIRMED)
        result = CapabilityResult(
            capability_id=d.capability_id,
            payload={"accepted": True},
            effect=result_receipt,
            request_digest=capability_request_digest(r),
        )
        self.assertIs(
            require_capability_effect_result(result, descriptor=d, request=r), result
        )

    def test_mutating_action_stays_reconcilable(self):
        d = descriptor()
        wrapper = object.__new__(EnvironmentCapabilityProvider)
        wrapper._descriptor = d
        r = request("collect_block")
        result_receipt = wrapper._outer_effect(r, receipt(r, EffectClass.RECONCILABLE))
        self.assertEqual(result_receipt.effect_class, EffectClass.RECONCILABLE)

    def test_provider_lies_about_class_is_always_rejected(self):
        d = descriptor()
        wrapper = object.__new__(EnvironmentCapabilityProvider)
        wrapper._descriptor = d
        r = request("describe_action")
        with self.assertRaisesRegex(ValueError, "effect class does not match"):
            wrapper._outer_effect(r, receipt(r, EffectClass.RECONCILABLE))
        r = request("collect_block")
        with self.assertRaisesRegex(ValueError, "effect class does not match"):
            wrapper._outer_effect(r, receipt(r, EffectClass.PURE))

    def test_unknown_action_can_never_invent_authorized_effect_class(self):
        with self.assertRaisesRegex(ValueError, "no authorized effect class"):
            capability_request_effect_class(descriptor(), request("private_hidden_action"))

    def test_standard_fixed_class_capabilities_remain_strict(self):
        d = CapabilityDescriptor(
            capability_id="generic", interface_version="1",
            request_schema="input", result_schema="output",
            effect_class=EffectClass.RECONCILABLE,
        )
        r = CapabilityRequest(
            capability_id="generic", payload={"action_type": "observe_blocks"},
            context=ExecutionContext("run", "trace", "span"),
            idempotency_key="test",
        )
        self.assertEqual(capability_request_effect_class(d, r), EffectClass.RECONCILABLE)


if __name__ == "__main__":
    unittest.main()
