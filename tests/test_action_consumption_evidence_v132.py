from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec, participant_component, environment_effect_intent

import json
from pathlib import Path
import tempfile

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectCompletionEvidence,
    EffectIntentConflict,
    EffectIntentPhase,
)
from noetrium_platform.infrastructure.reliability.effect.runtime import (
    EffectJournalDocumentCodec,
    InMemoryEffectIntentJournal,
    SQLiteEffectIntentJournal,
)
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    EnvironmentIdentity,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectCertainty, EffectClass, EffectReceipt, ExecutionContext
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodTaskCompletionReceipt, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.execution.decision import FixedDecisionCycleIdentityProvider, DecisionCycleIdentity


def effect(request: ActionRequest) -> EffectReceipt:
    return EffectReceipt(
        "fx", action_request_digest(request), EffectClass.RECONCILABLE,
        EffectCertainty.EFFECT_CONFIRMED, "env",
    )


class MS:
    task_completion_idempotency = "fake.v1"
    def ingest(self, evidence, context): pass
    def recall(self, request): return RecallResult("ctx", "mg-before")
    def task_completion_key(self, context): return f"completion:{context.task_id}:{context.decision_cycle_id}"
    def task_completed(self, result, context):
        return MethodTaskCompletionReceipt(self.task_completion_key(context), "mg-final")
    def close(self): pass


class M:
    identity = MethodIdentity("m", "1", "1", "1")
    def open_session(self, *, session_id, services): return MS()


class ES:
    action_recovery_durability = "crash_durable"
    def observe(self, context): return Observation("o1", "eg1", {})
    def act(self, request): return ActionResult(request.action_id, True, Observation("o2", "eg2", {}), effect(request), {})
    def prepare_action_recovery(self, request, context):
        del context
        return PreparedEffectHandle.build(
            request_id=request.action_id,
            request_digest=action_request_digest(request),
            provider_schema="test-env.v1",
            opaque_payload=request.action_id.encode(),
            provider_instance_id="env",
        )
    def execute_prepared_action(self, request, handle):
        assert handle.request_digest == action_request_digest(request)
        return self.act(request)
    def reconcile_prepared_action(self, handle, context):
        request = ActionRequest(handle.request_id, "move", {}, context)
        result = ActionResult(handle.request_id, True, self.observe(context), EffectReceipt(
            "fx", handle.request_digest, EffectClass.RECONCILABLE,
            EffectCertainty.EFFECT_CONFIRMED, "env",
        ), {})
        return ActionReconciliationResult(handle.request_id, ActionReconciliationDisposition.APPLIED, result, {})
    def close(self): pass


class E:
    identity = EnvironmentIdentity("e", "1", "1", "1")
    def open_session(self, *, session_id, services): return ES()


def test_consumed_terminal_binds_method_completion_identity_and_generation():
    journal = InMemoryEffectIntentJournal()
    mr = FakeParticipantResolver(); mr.register("method", "m", M)
    er = FakeParticipantResolver(); er.register("environment", "e", E)
    identity = DecisionCycleIdentity("run", "dc", "session", "task", "trace")
    runtime = context_action_runtime(
        mr, er,
        cycle_identity_provider=FixedDecisionCycleIdentityProvider(identity),
        effect_journal=journal,
    )
    spec = context_action_spec("s", "m", "e")
    runtime.execute_cycle(spec, task="t", input_kind="move", input_payload={})

    context = ExecutionContext(
        "run", "trace", "dc", study_id="s", task_id="task", decision_cycle_id="dc",
        participant_generations=(("environment", "eg1"),),
    )
    request = ActionRequest("action_dc", "move", {}, context)
    intent = environment_effect_intent(
        request, participant_component(next(row for row in spec.participants if row.role == "environment")), operation_id="dc:environment.act",
    )
    row = journal.load(intent.intent_id)
    assert row is not None and row.phase is EffectIntentPhase.CONSUMED
    assert row.consumption is not None
    assert row.consumption.completion_key == "completion:task:dc"
    assert row.consumption.completion_operation_id == "dc:method.task_completed"
    assert row.consumption.consumer_generation == "mg-final"
    assert row.consumption.consumer_component_digest

    conflicting = EffectCompletionEvidence(
        "other-key", row.consumption.completion_operation_id,
        row.consumption.consumer_component_digest, row.consumption.consumer_generation,
    )
    with pytest.raises(EffectIntentConflict):
        journal.record_consumed(intent.intent_id, request_digest=intent.request_digest, consumption=conflicting)


def test_sqlite_effect_journal_uses_only_current_schema_and_round_trips():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "effects.sqlite3"
        context = ExecutionContext("run", "trace", "dc", study_id="s", task_id="task", decision_cycle_id="dc")
        request = ActionRequest("a", "move", {"x": 1}, context)
        intent = environment_effect_intent(
            request, ComponentIdentity("participant.environment", "impl", "1", "1", "default"), operation_id="dc:environment.act",
        )
        journal = SQLiteEffectIntentJournal(path)
        journal.prepare(intent)
        reopened = SQLiteEffectIntentJournal(path).load(intent.intent_id)
        assert reopened is not None
        assert reopened.intent == intent
        assert reopened.phase is EffectIntentPhase.PREPARED


def test_effect_intent_document_rejects_unknown_future_schema_fail_closed():
    context = ExecutionContext("run", "trace", "dc", study_id="s", task_id="task", decision_cycle_id="dc")
    request = ActionRequest("a", "move", {"x": 1}, context)
    intent = environment_effect_intent(
        request, ComponentIdentity("participant.environment", "impl", "1", "1", "default"), operation_id="dc:environment.act",
    )
    codec = EffectJournalDocumentCodec()
    text, _ = codec.encode_intent(intent)
    payload = json.loads(text)
    payload["document_schema"] = "effect-intent.v999"
    with pytest.raises(ValueError, match="unsupported effect intent document schema"):
        codec.decode_intent(json.dumps(payload))
