from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionRecoveryRequired,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, ExecutionContext
from noetrium_platform.research.execution.workflow.implementations.context_action.action_reconciliation import ActionReconciliationPolicy


def request() -> ActionRequest:
    return ActionRequest(
        "action",
        "move",
        {"x": 1},
        ExecutionContext(run_id="run", trace_id="trace", span_id="span"),
    )


def result(req: ActionRequest, *, accepted: bool, certainty: EffectCertainty) -> ActionResult:
    return ActionResult(
        req.action_id,
        accepted,
        None,
        EffectReceipt(
            "effect",
            action_request_digest(req),
            EffectClass.RECONCILABLE,
            certainty,
        ),
        {},
    )


def test_applied_reconciliation_cannot_claim_rejected_result():
    req=request()
    row=ActionReconciliationResult(
        req.action_id,
        ActionReconciliationDisposition.APPLIED,
        result(req,accepted=False,certainty=EffectCertainty.EFFECT_CONFIRMED),
        {},
    )
    with pytest.raises(ActionRecoveryRequired,match="APPLIED"):
        ActionReconciliationPolicy().validate(req,row)


def test_not_applied_requires_authoritative_no_effect_proof():
    req=request()
    row=ActionReconciliationResult(
        req.action_id,
        ActionReconciliationDisposition.NOT_APPLIED,
        result(req,accepted=False,certainty=EffectCertainty.EFFECT_CONFIRMED),
        {},
    )
    with pytest.raises(ActionRecoveryRequired,match="NO_EFFECT"):
        ActionReconciliationPolicy().validate(req,row)


def test_not_applied_with_no_effect_is_valid_but_cannot_continue():
    req=request()
    row=ActionReconciliationResult(
        req.action_id,
        ActionReconciliationDisposition.NOT_APPLIED,
        result(req,accepted=False,certainty=EffectCertainty.NO_EFFECT),
        {},
    )
    validated=ActionReconciliationPolicy().validate(req,row)
    assert validated is row
