from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectReceipt


class EnvironmentEffectUnresolved(RuntimeError):
    pass


class EffectSafetyPolicy:
    """Pure decision policy; owns neither Environment nor persistence authority."""

    _FINAL = {
        EffectCertainty.NO_EFFECT,
        EffectCertainty.EFFECT_CONFIRMED,
        EffectCertainty.EFFECT_REJECTED,
    }

    @classmethod
    def needs_reconciliation(cls, effect: EffectReceipt | None) -> bool:
        return effect is None or effect.verification_required or effect.certainty not in cls._FINAL

    @classmethod
    def require_resolved(cls, effect: EffectReceipt | None) -> EffectReceipt:
        if effect is None:
            raise EnvironmentEffectUnresolved("environment action has no effect receipt")
        if effect.verification_required:
            raise EnvironmentEffectUnresolved(
                f"environment effect still requires verification: {effect.effect_id}"
            )
        if effect.certainty not in cls._FINAL:
            raise EnvironmentEffectUnresolved(
                f"environment effect remains uncertain: {effect.effect_id} certainty={effect.certainty}"
            )
        return effect
