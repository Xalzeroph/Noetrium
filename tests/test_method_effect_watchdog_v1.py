from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass
from noetrium_platform.research.execution.workflow.runtime import program_lowering as lowering
from noetrium_platform.research.execution.workflow.api import MethodNodeKind


def effect(certainty, effect_class=EffectClass.RECONCILABLE):
    return SimpleNamespace(
        certainty=certainty,
        effect_class=effect_class,
        request_digest="request-1",
        provider_instance_id="minecraft-instance",
        before_artifact="observation-before",
        after_artifact="observation-after",
    )


class MechanicalProgressWatchdogTests(unittest.TestCase):
    def signal(self, *receipts, kind=MethodNodeKind.CAPABILITY):
        node = SimpleNamespace(unit_id="minecraft:effect")
        result = SimpleNamespace(effect_receipts=tuple(receipts))
        with patch.object(lowering, "method_node_kind", return_value=kind):
            return lowering._capability_progress_signal(node, result)

    def test_confirmed_physical_effect_breaks_false_no_progress_streak(self):
        self.assertEqual(self.signal(effect(EffectCertainty.EFFECT_CONFIRMED)), (True, None))
        self.assertEqual(
            self.signal(
                effect(EffectCertainty.EFFECT_REJECTED),
                effect(EffectCertainty.EFFECT_CONFIRMED),
            ), (True, None)
        )

    def test_rejected_and_no_effect_remain_mechanically_stalled(self):
        for certainty in (EffectCertainty.NO_EFFECT, EffectCertainty.EFFECT_REJECTED):
            progress, fingerprint = self.signal(effect(certainty))
            self.assertIs(progress, False)
            self.assertEqual(len(fingerprint), 64)

    def test_indeterminate_and_nonphysical_steps_do_not_invent_progress(self):
        self.assertEqual(self.signal(effect(EffectCertainty.INDETERMINATE)), (None, None))
        self.assertEqual(
            self.signal(effect(EffectCertainty.NO_EFFECT, EffectClass.PURE)),
            (None, None),
        )
        self.assertEqual(
            self.signal(effect(EffectCertainty.EFFECT_CONFIRMED, EffectClass.PURE)),
            (None, None),
        )
        # A read-only query can accompany a rejected physical command.
        # Only the mutating command contributes to the no-effect watchdog.
        physical, fingerprint = self.signal(
            effect(EffectCertainty.NO_EFFECT, EffectClass.PURE),
            effect(EffectCertainty.EFFECT_REJECTED),
        )
        self.assertIs(physical, False)
        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(self.signal(), (None, None))
        self.assertEqual(
            self.signal(effect(EffectCertainty.EFFECT_CONFIRMED), kind=MethodNodeKind.AGENT),
            (None, None),
        )


if __name__ == "__main__":
    unittest.main()
