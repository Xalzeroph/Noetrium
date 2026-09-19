from __future__ import annotations

from pathlib import Path
import tempfile

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.composition.context_action import context_action_failure_classifier_chain
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, ExecutionContext, OperationExecutor, OperationRequest, canonical_digest


def request(operation_type: str, component_id: str = "environment.e"):
    ident = ComponentIdentity(component_id, "impl", "1", "1", "g")
    payload = {"x": 1}
    context = ExecutionContext("run", "trace", "span", operation_id="op", component_id=component_id)
    return OperationRequest("op", "invocation:test-taxonomy", operation_type, context, ident, ident, payload, "v1", canonical_digest(payload))


def record(operation_type: str):
    td = tempfile.TemporaryDirectory()
    store = ForensicStore(Path(td.name))
    sink = OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain())
    result = OperationExecutor(sink).execute(request(operation_type), lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    row = store.failures.verified_payloads_after(0).payloads[0]
    store.close(); td.cleanup()
    return result, row


def test_reconcile_failure_has_effect_specific_taxonomy():
    _, row = record("environment.reconcile_prepared_action")
    assert row["failure_domain"] == "ENVIRONMENT"
    assert row["failure_code"] == "EFFECT_RECONCILIATION_FAILURE"
    assert row["effect_certainty"] == EffectCertainty.EFFECT_UNKNOWN.value
    assert row["recommended_recovery"] == "reconcile_effect"


def test_effect_journal_prepare_failure_is_safe_to_retry():
    _, row = record("effect.intent.prepare")
    assert row["failure_code"] == "EFFECT_INTENT_PREPARE_FAILURE"
    assert row["recommended_recovery"] == "retry_operation"


def test_post_effect_journal_failure_requires_effect_reconciliation():
    _, row = record("effect.intent.result_record")
    assert row["failure_code"] == "EFFECT_INTENT_POST_EFFECT_RECORD_FAILURE"
    assert row["recommended_recovery"] == "reconcile_effect"
    assert row["effect_certainty"] == EffectCertainty.EFFECT_UNKNOWN.value


def test_action_not_applied_has_replan_recovery():
    from noetrium_platform.capabilities.environment.runtime.api import ActionNotApplied
    with tempfile.TemporaryDirectory() as td:
        with ForensicStore(Path(td)) as store:
            sink = OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain())
            result = OperationExecutor(sink).execute(
                request("environment.action_recovery_decision"),
                lambda _: (_ for _ in ()).throw(ActionNotApplied("proved not applied")),
            )
            row = store.failures.verified_payloads_after(0).payloads[0]
            assert result.failure_id
            assert row["failure_code"] == "ACTION_NOT_APPLIED"
            assert row["recommended_recovery"] == "replan_action"
            assert row["effect_certainty"] == "no_effect"
