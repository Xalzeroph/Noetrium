from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import EffectReceipt
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from .contracts import ActionReconciliationResult, ActionRequest, ActionResult, action_request_digest


class ActionIdentityViolation(ValueError):
    """A provider response cannot be proven to belong to the requested action."""


@dataclass(frozen=True, slots=True)
class ActionSemanticIdentity:
    action_id: str
    request_digest: str

    @classmethod
    def from_request(cls, request: ActionRequest) -> "ActionSemanticIdentity":
        return cls(request.action_id, action_request_digest(request))

    def require_action_id(self, actual: str, *, source: str) -> None:
        if actual != self.action_id:
            raise ActionIdentityViolation(
                f"{source} action identity mismatch: expected={self.action_id} actual={actual}"
            )

    def require_effect(self, effect: EffectReceipt | None, *, source: str) -> None:
        if effect is not None:
            require_effect_receipt_digest(
                effect,
                expected_digest=self.request_digest,
                action_id=self.action_id,
                source=source,
            )


def require_effect_receipt_digest(
    effect: EffectReceipt,
    *,
    expected_digest: str,
    action_id: str | None = None,
    source: str = "effect receipt",
) -> EffectReceipt:
    if effect.request_digest != expected_digest:
        suffix = f" action_id={action_id}" if action_id else ""
        raise ActionIdentityViolation(
            f"{source} action digest mismatch:{suffix} "
            f"expected={expected_digest} actual={effect.request_digest}"
        )
    return effect


def require_action_result_identity(
    request: ActionRequest,
    result: ActionResult,
    *,
    source: str = "environment act",
) -> ActionResult:
    if not isinstance(result, ActionResult):
        raise TypeError(f"{source} must return ActionResult")
    identity = ActionSemanticIdentity.from_request(request)
    identity.require_action_id(result.action_id, source=source)
    identity.require_effect(result.effect, source=f"{source} effect receipt")
    return result


def require_action_recovery_handle_identity(
    request: ActionRequest,
    handle: PreparedEffectHandle,
) -> PreparedEffectHandle:
    identity = ActionSemanticIdentity.from_request(request)
    identity.require_action_id(handle.request_id, source="action recovery handle")
    if handle.request_digest != identity.request_digest:
        raise ActionIdentityViolation(
            "action recovery handle request digest does not match frozen ActionRequest"
        )
    return handle


def require_recovery_handle_reconciliation_identity(
    handle: PreparedEffectHandle,
    reconciliation: ActionReconciliationResult,
) -> ActionReconciliationResult:
    if not isinstance(reconciliation, ActionReconciliationResult):
        raise TypeError("reconcile_prepared_action must return ActionReconciliationResult")
    if reconciliation.action_id != handle.request_id:
        raise ActionIdentityViolation(
            "reconcile_prepared_action action identity mismatch: "
            f"expected={handle.request_id} actual={reconciliation.action_id}"
        )
    if reconciliation.result is not None and reconciliation.result.effect is not None:
        require_effect_receipt_digest(
            reconciliation.result.effect,
            expected_digest=handle.request_digest,
            action_id=handle.request_id,
            source="reconcile_prepared_action effect receipt",
        )
    return reconciliation


def require_reconciliation_identity(
    request: ActionRequest,
    reconciliation: ActionReconciliationResult,
) -> ActionReconciliationResult:
    if not isinstance(reconciliation, ActionReconciliationResult):
        raise TypeError("action reconciliation must return ActionReconciliationResult")
    identity = ActionSemanticIdentity.from_request(request)
    identity.require_action_id(reconciliation.action_id, source="action reconciliation")
    if reconciliation.result is not None:
        identity.require_action_id(
            reconciliation.result.action_id,
            source="action reconciliation result",
        )
        identity.require_effect(
            reconciliation.result.effect,
            source="action reconciliation effect receipt",
        )
    return reconciliation


__all__ = [
    "ActionIdentityViolation",
    "ActionSemanticIdentity",
    "require_action_result_identity",
    "require_effect_receipt_digest",
    "require_reconciliation_identity",
    "require_action_recovery_handle_identity",
    "require_recovery_handle_reconciliation_identity",
]
