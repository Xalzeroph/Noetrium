from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import participant_component

from tests_support import environment_effect_intent

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from tests_support import context_action_spec

from pathlib import Path
import tempfile

import pytest

from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.composition.context_action import context_action_failure_classifier_chain
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, EffectIntentPhase
from noetrium_platform.infrastructure.reliability.effect.runtime import InMemoryEffectIntentJournal, SQLiteEffectIntentJournal
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    EnvironmentIdentity,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, EffectClass, EffectReceipt, ExecutionContext, OperationExecutor, OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodTaskCompletionReceipt, RecallResult, TaskCompletionSafetyCapabilityMissing
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.execution.decision import FixedDecisionCycleIdentityProvider, DecisionCycleIdentity


def _effect(request: ActionRequest) -> EffectReceipt:
    return EffectReceipt(
        "fx", action_request_digest(request), EffectClass.RECONCILABLE,
        EffectCertainty.EFFECT_CONFIRMED, "env-instance",
    )


class RecoverableEnvironmentSession:
    action_recovery_durability = "crash_durable"
    observe_calls = 0
    act_calls = 0

    def observe(self, context):
        type(self).observe_calls += 1
        return Observation("o", "eg", {})

    def act(self, request):
        type(self).act_calls += 1
        return ActionResult(request.action_id, True, None, _effect(request), {})

    def prepare_action_recovery(self, request, context):
        return PreparedEffectHandle.build(
            request_id=request.action_id, request_digest=action_request_digest(request),
            provider_schema="test.recovery.v1", opaque_payload=request.action_id.encode(),
            provider_instance_id="test-env",
        )

    def execute_prepared_action(self, request, handle):
        assert handle.request_id == request.action_id
        assert handle.request_digest == action_request_digest(request)
        return self.act(request)

    def reconcile_prepared_action(self, handle, context):
        effect = EffectReceipt(
            "fx", handle.request_digest, EffectClass.RECONCILABLE,
            EffectCertainty.EFFECT_CONFIRMED, "env-instance",
        )
        result = ActionResult(handle.request_id, True, None, effect, {"reconciled": True})
        return ActionReconciliationResult(handle.request_id, ActionReconciliationDisposition.APPLIED, result, {})


    def reconcile(self, effect, context):
        return effect

    def close(self):
        pass


ENV_ARTIFACT = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
METHOD_ARTIFACT = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

class RecoverableEnvironment:
    identity = EnvironmentIdentity("e", "1", "1", "1", ENV_ARTIFACT)
    def open_session(self, *, session_id, services):
        return RecoverableEnvironmentSession()


class NonIdempotentMethodSession:
    def ingest(self, evidence, context): pass
    def recall(self, request): return RecallResult("ctx", "mg")
    def task_completed(self, result, context): pass
    def close(self): pass


class NonIdempotentMethod:
    identity = MethodIdentity("m", "1", "1", "1", METHOD_ARTIFACT)
    def open_session(self, *, session_id, services):
        return NonIdempotentMethodSession()


def _spec() -> ExperimentSpec:
    return context_action_spec(study_id="study", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1, method_artifact_digest=METHOD_ARTIFACT, environment_artifact_digest=ENV_ARTIFACT)


def test_crash_durable_action_refuses_non_idempotent_method_before_trial_protocol_or_act():
    with tempfile.TemporaryDirectory() as td:
        mr = FakeParticipantResolver(); mr.register("method", "m", NonIdempotentMethod)
        er = FakeParticipantResolver(); er.register("environment", "e", RecoverableEnvironment)
        RecoverableEnvironmentSession.observe_calls = 0
        RecoverableEnvironmentSession.act_calls = 0
        with ForensicStore(Path(td) / "forensics") as store:
            runtime = context_action_runtime(
                mr, er,
                operation_executor=OperationExecutor(OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain())),
                effect_journal=SQLiteEffectIntentJournal(Path(td) / "actions.sqlite3"),
            )
            with pytest.raises(OperationFailure) as raised:
                runtime.execute_cycle(_spec(), task="t", input_kind="move", input_payload={})
            assert raised.value.result.operation_id.endswith("method.task_completion_safety_preflight")
            assert isinstance(raised.value.__cause__, TaskCompletionSafetyCapabilityMissing)
            assert RecoverableEnvironmentSession.observe_calls == 0
            assert RecoverableEnvironmentSession.act_calls == 0
            failure = store.failures.verified_payloads_after(0).payloads[-1]
            assert failure["failure_code"] == "TASK_COMPLETION_IDEMPOTENCY_MISSING"
            assert failure["recommended_recovery"] == "block_scientific_use"




class IdempotentMethodSession:
    task_completion_idempotency = "test.v1"
    ingest_calls = 0
    completion_calls = 0

    def ingest(self, evidence, context):
        type(self).ingest_calls += 1

    def recall(self, request):
        return RecallResult("ctx", "mg")

    def task_completion_key(self, context):
        return f"cycle:{context.run_id}:{context.decision_cycle_id}"

    def task_completed(self, result, context):
        type(self).completion_calls += 1
        return MethodTaskCompletionReceipt(self.task_completion_key(context), "mg")

    def close(self): pass


class IdempotentMethod:
    identity = MethodIdentity("m", "1", "1", "1", METHOD_ARTIFACT)
    def open_session(self, *, session_id, services):
        return IdempotentMethodSession()


def _fixed_runtime(journal, identity: DecisionCycleIdentity) -> ExperimentRuntime:
    mr = FakeParticipantResolver(); mr.register("method", "m", IdempotentMethod)
    er = FakeParticipantResolver(); er.register("environment", "e", RecoverableEnvironment)
    return context_action_runtime(
        mr, er,
        cycle_identity_provider=FixedDecisionCycleIdentityProvider(identity),
        effect_journal=journal,
    )


def test_consumed_exact_replay_is_blocked_before_observe_ingest_or_external_action():
    identity = DecisionCycleIdentity("run", "dc", "session", "task", "trace")
    journal = InMemoryEffectIntentJournal()
    RecoverableEnvironmentSession.observe_calls = 0
    RecoverableEnvironmentSession.act_calls = 0
    IdempotentMethodSession.ingest_calls = 0
    IdempotentMethodSession.completion_calls = 0

    _fixed_runtime(journal, identity).execute_cycle(
        _spec(), task="t", input_kind="move", input_payload={}
    )
    assert RecoverableEnvironmentSession.observe_calls == 1
    assert RecoverableEnvironmentSession.act_calls == 1
    assert IdempotentMethodSession.ingest_calls == 1
    assert IdempotentMethodSession.completion_calls == 1

    with pytest.raises(OperationFailure) as raised:
        _fixed_runtime(journal, identity).execute_cycle(
            _spec(), task="t", input_kind="move", input_payload={}
        )
    assert raised.value.result.operation_id.endswith("environment.effect.replay_guard")
    assert RecoverableEnvironmentSession.observe_calls == 1
    assert RecoverableEnvironmentSession.act_calls == 1
    assert IdempotentMethodSession.ingest_calls == 1
    assert IdempotentMethodSession.completion_calls == 1


def test_prior_nonterminal_action_blocks_new_cycle_in_same_run_lifetime_before_workflow():
    journal = InMemoryEffectIntentJournal()
    old_context = ExecutionContext(
        "run", "trace-old", "span-old", study_id="study",
        task_id="task-old", decision_cycle_id="dc-old",
    )
    old_request = ActionRequest("action_dc-old", "move", {"x": 1}, old_context)
    old_intent = environment_effect_intent(old_request, participant_component(next(row for row in _spec().participants if row.role == "environment")), operation_id="dc-old:environment.act")
    journal.prepare(old_intent)

    RecoverableEnvironmentSession.observe_calls = 0
    RecoverableEnvironmentSession.act_calls = 0
    IdempotentMethodSession.ingest_calls = 0
    identity = DecisionCycleIdentity("run", "dc-new", "session", "task-new", "trace-new")
    with pytest.raises(OperationFailure) as raised:
        _fixed_runtime(journal, identity).execute_cycle(
            _spec(), task="t", input_kind="move", input_payload={"x": 2}
        )
    assert ":effect.intent.pending_check:" in raised.value.result.operation_id
    assert RecoverableEnvironmentSession.observe_calls == 0
    assert RecoverableEnvironmentSession.act_calls == 0
    assert IdempotentMethodSession.ingest_calls == 0


def test_sqlite_unresolved_scope_excludes_terminal_rows_and_exact_recovery_intent():
    with tempfile.TemporaryDirectory() as td:
        journal = SQLiteEffectIntentJournal(Path(td) / "actions.sqlite3")
        context = ExecutionContext(
            "run", "trace", "span", study_id="study", lifetime_id="life",
            task_id="task", decision_cycle_id="dc",
        )
        request = ActionRequest("action_dc", "move", {}, context)
        intent = environment_effect_intent(
            request, ComponentIdentity("environment.e", "e", "1", "1", "impl:1"),
            operation_id="dc:environment.act",
        )
        journal.prepare(intent)
        rows = journal.unresolved_for_scope(run_id="run", lifetime_id="life")
        assert [row.intent.intent_id for row in rows] == [intent.intent_id]
        assert journal.unresolved_for_scope(
            run_id="run", lifetime_id="life", exclude_intent_id=intent.intent_id
        ) == ()
        journal.record_result(intent.intent_id, request_digest=intent.request_digest, effect=_effect(request))
        completion = MethodTaskCompletionReceipt("cycle:run:dc", "mg")
        # Convert the method receipt to the journal's cross-component proof.
        from noetrium_platform.infrastructure.reliability.effect.api import EffectCompletionEvidence
        journal.record_consumed(
            intent.intent_id,
            request_digest=intent.request_digest,
            consumption=EffectCompletionEvidence(
                completion.completion_key, "dc:method.task_completed", "method-digest", completion.method_generation
            ),
        )
        assert journal.load(intent.intent_id).phase is EffectIntentPhase.CONSUMED
        assert journal.unresolved_for_scope(run_id="run", lifetime_id="life") == ()


def test_crash_durable_exact_nonterminal_intent_requires_checkpoint_anchor_before_workflow():
    with tempfile.TemporaryDirectory() as td:
        journal = SQLiteEffectIntentJournal(Path(td) / "actions.sqlite3")
        identity = DecisionCycleIdentity("run", "dc", "session", "task", "trace")
        context = ExecutionContext(
            "run", "trace", "dc", study_id="study", task_id="task", decision_cycle_id="dc"
        )
        request = ActionRequest("action_dc", "move", {}, context)
        intent = environment_effect_intent(request, participant_component(next(row for row in _spec().participants if row.role == "environment")), operation_id="dc:environment.act")
        journal.prepare(intent)
        RecoverableEnvironmentSession.observe_calls = 0
        RecoverableEnvironmentSession.act_calls = 0
        IdempotentMethodSession.ingest_calls = 0
        with tempfile.TemporaryDirectory() as forensic_dir:
            mr = FakeParticipantResolver(); mr.register("method", "m", IdempotentMethod)
            er = FakeParticipantResolver(); er.register("environment", "e", RecoverableEnvironment)
            with ForensicStore(Path(forensic_dir) / "forensics") as store:
                runtime = context_action_runtime(
                    mr, er,
                    operation_executor=OperationExecutor(OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain())),
                    cycle_identity_provider=FixedDecisionCycleIdentityProvider(identity),
                    effect_journal=journal,
                )
                with pytest.raises(OperationFailure) as raised:
                    runtime.execute_cycle(_spec(), task="t", input_kind="move", input_payload={})
                assert raised.value.result.operation_id.endswith("environment.effect.recovery_anchor_guard")
                assert RecoverableEnvironmentSession.observe_calls == 0
                assert RecoverableEnvironmentSession.act_calls == 0
                assert IdempotentMethodSession.ingest_calls == 0
                failure = store.failures.verified_payloads_after(0).payloads[-1]
                assert failure["failure_code"] == "EFFECT_RECOVERY_ANCHOR_MISSING"
                assert failure["recommended_recovery"] == "restore_checkpoint"
