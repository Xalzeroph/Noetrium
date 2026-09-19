from __future__ import annotations

from dataclasses import replace

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionNotApplied,
    ActionRecoveryRequired,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    ActionScientificCommitContradiction,
    require_reconciliation_identity,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty

from .effect_safety import EffectSafetyPolicy


class ActionReconciliationPolicy:
    """Pure reconciliation and trial-consistency policy.

    No dispatcher, Environment provider, journal, or persistence authority is allowed
    here.  This keeps safety semantics independently testable and reusable.
    """

    def __init__(self, *, effect_policy: type[EffectSafetyPolicy] = EffectSafetyPolicy) -> None:
        self._effect_policy = effect_policy

    def validate(
        self, request: ActionRequest, reconciliation: ActionReconciliationResult
    ) -> ActionReconciliationResult:
        reconciliation = require_reconciliation_identity(request, reconciliation)
        return self.validate_disposition(reconciliation)

    def validate_disposition(
        self, reconciliation: ActionReconciliationResult
    ) -> ActionReconciliationResult:
        disposition = reconciliation.disposition
        result = reconciliation.result
        if disposition is ActionReconciliationDisposition.UNKNOWN:
            return reconciliation
        if result is None:
            raise ActionRecoveryRequired(
                f"action {reconciliation.action_id} reconciliation has disposition={disposition.value} but no result"
            )
        effect = self._effect_policy.require_resolved(result.effect)
        if disposition is ActionReconciliationDisposition.APPLIED and not result.accepted:
            raise ActionRecoveryRequired("APPLIED reconciliation returned accepted=False")
        if disposition is ActionReconciliationDisposition.REJECTED and result.accepted:
            raise ActionRecoveryRequired("REJECTED reconciliation returned accepted=True")
        if disposition is ActionReconciliationDisposition.NOT_APPLIED:
            if result.accepted:
                raise ActionRecoveryRequired("NOT_APPLIED reconciliation returned accepted=True")
            if effect.certainty is not EffectCertainty.NO_EFFECT:
                raise ActionRecoveryRequired("NOT_APPLIED reconciliation must carry NO_EFFECT proof")
        return reconciliation

    @staticmethod
    def effect(reconciliation: ActionReconciliationResult):
        return reconciliation.result.effect if reconciliation.result is not None else None

    @staticmethod
    def require_continuation(reconciliation: ActionReconciliationResult) -> ActionResult:
        if reconciliation.disposition is ActionReconciliationDisposition.UNKNOWN:
            raise ActionRecoveryRequired(
                f"action {reconciliation.action_id} remains uncertain after reconciliation"
            )
        if reconciliation.disposition is ActionReconciliationDisposition.NOT_APPLIED:
            raise ActionNotApplied(
                f"action {reconciliation.action_id} is authoritatively not applied; "
                "task completion is forbidden"
            )
        if reconciliation.result is None:
            raise ActionRecoveryRequired("reconciliation result missing")
        return reconciliation.result

    def require_committed_method_consistency(
        self, existing_effect, reconciliation: ActionReconciliationResult
    ) -> ActionResult:
        if (
            existing_effect is not None
            and not self._effect_policy.needs_reconciliation(existing_effect)
            and existing_effect.certainty is EffectCertainty.NO_EFFECT
        ):
            raise ActionScientificCommitContradiction(
                "method completion is committed but journal contains authoritative NO_EFFECT proof"
            )
        if reconciliation.disposition in {
            ActionReconciliationDisposition.UNKNOWN,
            ActionReconciliationDisposition.NOT_APPLIED,
        }:
            raise ActionScientificCommitContradiction(
                "method completion is committed but external action reconciled as "
                f"{reconciliation.disposition.value}"
            )
        if reconciliation.result is None:
            raise ActionScientificCommitContradiction(
                "method completion is committed but action reconciliation returned no result"
            )
        effect = self._effect_policy.require_resolved(reconciliation.result.effect)
        if existing_effect is not None and not self._effect_policy.needs_reconciliation(existing_effect):
            expected_accepted = existing_effect.certainty is EffectCertainty.EFFECT_CONFIRMED
            if reconciliation.result.accepted != expected_accepted:
                raise ActionScientificCommitContradiction(
                    "external reconciliation contradicts the journal's final effect disposition"
                )
        return replace(reconciliation.result, effect=effect)


__all__ = ["ActionReconciliationPolicy"]
