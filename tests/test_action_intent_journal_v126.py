from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import environment_effect_intent

from tests_support import context_action_spec

from pathlib import Path
import tempfile

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, EffectIntentConflict

from noetrium_platform.infrastructure.reliability.effect.runtime import InMemoryEffectIntentJournal, SQLiteEffectIntentJournal
from noetrium_platform.capabilities.environment.runtime.api import action_request_digest, ActionReconciliationDisposition, ActionReconciliationResult, ActionRequest, ActionResult, ActionSafetyCapabilityMissing, EnvironmentIdentity, Observation
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, EffectClass, EffectReceipt, ExecutionContext, OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.execution.decision import FixedDecisionCycleIdentityProvider, DecisionCycleIdentity
from noetrium_platform.research.execution.workflow.implementations.context_action.safe_action import ActionRecoveryRequired


def ctx() -> ExecutionContext:
    return ExecutionContext(
        "run", "trace", "span", study_id="study", task_id="task",
        decision_cycle_id="dc", participant_generations=(("environment", "eg1"),),
    )


def intent(payload: object = None) -> EffectIntent:
    request = ActionRequest("action_dc", "move", {} if payload is None else payload, ctx())
    return environment_effect_intent(
        request, ComponentIdentity("environment.e", "e", "1", "1", "impl:1"),
        operation_id="dc:environment.act",
    )


def receipt(action_digest: str, certainty=EffectCertainty.EFFECT_CONFIRMED, *, verification=False):
    return EffectReceipt("fx", action_digest, EffectClass.RECONCILABLE, certainty, "env-1", verification)


def test_memory_journal_is_idempotent_and_rejects_identity_conflict():
    journal = InMemoryEffectIntentJournal()
    a = intent()
    assert journal.prepare(a).created is True
    assert journal.prepare(a).created is False
    journal.record_result(a.intent_id, request_digest=a.request_digest, effect=receipt(a.request_digest))
    row = journal.load(a.intent_id)
    assert row is not None and row.phase.value == "result_recorded"
    with pytest.raises(EffectIntentConflict):
        journal.prepare(intent({"different": True}))


def test_sqlite_prepared_intent_survives_reopen():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "actions.sqlite3"
        first = SQLiteEffectIntentJournal(path)
        a = intent()
        assert first.prepare(a).created is True
        second = SQLiteEffectIntentJournal(path)
        row = second.load(a.intent_id)
        assert row is not None and row.phase.value == "prepared"
        assert second.prepare(a).created is False
        second.record_reconciled(a.intent_id, request_digest=a.request_digest, effect=receipt(a.request_digest))
        third = SQLiteEffectIntentJournal(path)
        row = third.load(a.intent_id)
        assert row is not None and row.phase.value == "reconciled"
        assert row.effect is not None and row.effect.certainty is EffectCertainty.EFFECT_CONFIRMED


class MSession:
    def ingest(self, evidence, context): pass
    def recall(self, request): return RecallResult("ctx", "mg1")
    def task_completed(self, result, context): pass
    def close(self): pass


class Method:
    identity = MethodIdentity("m", "1", "1", "1")
    def open_session(self, *, session_id, services): return MSession()


class CrashyEnvironmentSession:
    execute_calls = 0
    reconcile_prepared_calls = 0
    fail_after_effect = True
    action_recovery_durability = "process_local"

    def observe(self, context): return Observation("o1", "eg1", {})
    def act(self, request):
        raise AssertionError("journal-backed execution must never call raw act")
    def prepare_action_recovery(self, request, context):
        return PreparedEffectHandle.build(
            request_id=request.action_id, request_digest=action_request_digest(request),
            provider_schema="test.environment.v1", opaque_payload=b"prepared", provider_instance_id="env-1",
        )
    def execute_prepared_action(self, request, handle):
        type(self).execute_calls += 1
        if type(self).fail_after_effect:
            raise RuntimeError("transport lost after external effect")
        return ActionResult(request.action_id, True, None, receipt(action_request_digest(request)), {})
    def reconcile_prepared_action(self, handle, context):
        type(self).reconcile_prepared_calls += 1
        result = ActionResult(
            handle.request_id, True, Observation("o2", "eg2", {}),
            receipt(handle.request_digest), {"reconciled": True},
        )
        return ActionReconciliationResult(handle.request_id, ActionReconciliationDisposition.APPLIED, result, {})
    def reconcile(self, effect, context): return effect
    def close(self): pass


class CrashyEnvironment:
    identity = EnvironmentIdentity("e", "1", "1", "1")
    def open_session(self, *, session_id, services): return CrashyEnvironmentSession()


def spec():
    return context_action_spec(study_id="study", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)


def runtime(journal):
    mr = FakeParticipantResolver(); mr.register("method", "m", Method)
    er = FakeParticipantResolver(); er.register("environment", "e", CrashyEnvironment)
    identity = DecisionCycleIdentity("run", "dc", "session", "task", "trace")
    return context_action_runtime(
        mr, er,
        cycle_identity_provider=FixedDecisionCycleIdentityProvider(identity),
        effect_journal=journal,
    )


def test_crash_after_external_effect_never_replays_act_and_uses_intent_reconciliation():
    CrashyEnvironmentSession.execute_calls = 0
    CrashyEnvironmentSession.reconcile_prepared_calls = 0
    CrashyEnvironmentSession.fail_after_effect = True
    journal = InMemoryEffectIntentJournal()
    with pytest.raises(OperationFailure):
        runtime(journal).execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert CrashyEnvironmentSession.execute_calls == 1

    CrashyEnvironmentSession.fail_after_effect = False
    result = runtime(journal).execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert result.primary_result.diagnostics["reconciled"] is True
    assert CrashyEnvironmentSession.execute_calls == 1
    assert CrashyEnvironmentSession.reconcile_prepared_calls == 1
    assert any(x.operation_id.endswith("environment.reconcile_prepared_action") for x in result.operation_results)


class NoIntentReconcileSession(CrashyEnvironmentSession):
    reconcile_prepared_action = None


class NoIntentReconcileEnvironment:
    identity = EnvironmentIdentity("e", "1", "1", "1")
    def open_session(self, *, session_id, services): return NoIntentReconcileSession()


def test_prepared_intent_fails_closed_without_prepared_reconciliation_capability():
    journal = InMemoryEffectIntentJournal()
    a = intent()
    journal.prepare(a)
    # This is a direct capability assertion: a stale PREPARED intent can never authorize another act.
    mr = FakeParticipantResolver(); mr.register("method", "m", Method)
    er = FakeParticipantResolver(); er.register("environment", "e", NoIntentReconcileEnvironment)
    identity = DecisionCycleIdentity("run", "dc", "session", "task", "trace")
    rt = context_action_runtime(mr, er, cycle_identity_provider=FixedDecisionCycleIdentityProvider(identity), effect_journal=journal)
    with pytest.raises(OperationFailure) as exc:
        rt.execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert exc.value.result.operation_id.endswith("environment.action_safety_preflight")
    assert isinstance(exc.value.__cause__, ActionSafetyCapabilityMissing)
