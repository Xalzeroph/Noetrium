from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_ACTION_SPEC_BY_TYPE,
    minecraft_action_effect_class as declared_action_effect_class,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.action_coordinator import (
    _minecraft_action_effect_class,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass, EffectCertainty, EffectReceipt,
)
from noetrium_platform.research.execution.workflow.runtime import program_lowering as lowering
from noetrium_platform.research.execution.workflow.api import MethodNodeKind


class MinecraftEffectTruthTests(unittest.TestCase):
    def test_all_mc_actions_derive_effect_class_from_canonical_typed_spec(self):
        self.assertGreaterEqual(len(MINECRAFT_ACTION_SPEC_BY_TYPE), 40)
        for name, spec in MINECRAFT_ACTION_SPEC_BY_TYPE.items():
            with self.subTest(action=name):
                self.assertIs(
                    _minecraft_action_effect_class(name),
                    declared_action_effect_class(spec),
                )
        self.assertIs(_minecraft_action_effect_class("not_registered"), EffectClass.RECONCILABLE)
        # stay can displace the agent, while wait consumes physical world time;
        # neither operation is a replay-safe PURE observation.
        self.assertIs(_minecraft_action_effect_class("stay"), EffectClass.RECONCILABLE)
        self.assertIs(_minecraft_action_effect_class("wait"), EffectClass.RECONCILABLE)
        for name in ("observe_blocks", "observe_entities", "recipe_lookup", "registry_search"):
            self.assertIs(_minecraft_action_effect_class(name), EffectClass.PURE)

    def test_observe_registry_and_recipe_queries_cannot_reset_physical_livelock(self):
        for name in ("observe_blocks", "observe_entities", "recipe_lookup", "registry_search"):
            effect_class = _minecraft_action_effect_class(name)
            receipt = EffectReceipt(
                effect_id=f"minecraft-action:{name}", request_digest="digest",
                effect_class=effect_class, certainty=EffectCertainty.EFFECT_CONFIRMED,
            )
            result = SimpleNamespace(effect_receipts=(receipt,))
            node = SimpleNamespace(unit_id="environment")
            with patch.object(lowering, "method_node_kind", return_value=MethodNodeKind.CAPABILITY):
                progress, fingerprint = lowering._capability_progress_signal(node, result)
            self.assertIsNone(progress)
            self.assertIsNone(fingerprint)

    def test_verified_mutations_remain_distinct_from_success_of_the_paper_task(self):
        receipt = EffectReceipt(
            effect_id="minecraft-action:collect_block", request_digest="digest",
            effect_class=_minecraft_action_effect_class("collect_block"),
            certainty=EffectCertainty.EFFECT_CONFIRMED,
        )
        with patch.object(lowering, "method_node_kind", return_value=MethodNodeKind.CAPABILITY):
            result = lowering._capability_progress_signal(
                SimpleNamespace(unit_id="environment"),
                SimpleNamespace(effect_receipts=(receipt,)),
            )
        self.assertEqual(result, (True, None))


if __name__ == "__main__":
    unittest.main()
