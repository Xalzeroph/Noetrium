from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle
from noetrium_platform.infrastructure.reliability.effect.runtime import InMemoryEffectIntentJournal
from noetrium_platform.capabilities.environment.runtime.api import (
    action_request_digest,
    ActionReconciliationDisposition, ActionReconciliationResult, ActionResult,
    EnvironmentIdentity, Observation,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.execution.decision import FixedDecisionCycleIdentityProvider, DecisionCycleIdentity
from noetrium_platform.research.execution.workflow.implementations.context_action.safe_action import ActionNotApplied


class MS:
    completed=0
    def ingest(self,e,c): pass
    def recall(self,r): return RecallResult("ctx","mg")
    def task_completed(self,r,c): type(self).completed += 1
    def close(self): pass
class M:
    identity=MethodIdentity("m","1","1","1")
    def open_session(self,*,session_id,services): return MS()


def no_effect(request): return EffectReceipt("fx",action_request_digest(request),EffectClass.RECONCILABLE,EffectCertainty.NO_EFFECT,"env")


class ES:
    execute_calls=0
    action_recovery_durability = "process_local"
    def observe(self,c): return Observation("o","eg",{})
    def act(self,r): raise AssertionError("journal-backed execution must never call raw act")
    def prepare_action_recovery(self, r, c):
        return PreparedEffectHandle.build(
            request_id=r.action_id, request_digest=action_request_digest(r),
            provider_schema="test.not-applied.v1", opaque_payload=b"prepared", provider_instance_id="env",
        )
    def execute_prepared_action(self,r,handle):
        type(self).execute_calls += 1
        raise RuntimeError("crash after external effect before authoritative receipt")
    def reconcile_prepared_action(self, handle, c):
        effect=EffectReceipt(
            effect_id="fx", request_digest=handle.request_digest, effect_class=EffectClass.RECONCILABLE,
            certainty=EffectCertainty.NO_EFFECT, provider_instance_id="env",
        )
        result=ActionResult(handle.request_id,False,None,effect,{"proof":"not_applied"})
        return ActionReconciliationResult(handle.request_id,ActionReconciliationDisposition.NOT_APPLIED,result,{})
    def close(self): pass

class E:
    identity=EnvironmentIdentity("e","1","1","1")
    def open_session(self,*,session_id,services): return ES()


def rt(j):
    mr=FakeParticipantResolver(); mr.register("method", "m",M); er=FakeParticipantResolver(); er.register("environment", "e",E)
    ident=DecisionCycleIdentity("run","dc","session","task","trace")
    return context_action_runtime(mr,er,cycle_identity_provider=FixedDecisionCycleIdentityProvider(ident),effect_journal=j)

def spec(): return context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)


def test_authoritative_not_applied_never_becomes_method_task_completed():
    ES.execute_calls=0; MS.completed=0
    journal=InMemoryEffectIntentJournal()
    with pytest.raises(OperationFailure):
        rt(journal).execute_cycle(spec(),task="t",input_kind="move",input_payload={})
    assert ES.execute_calls == 1
    with pytest.raises(OperationFailure) as exc:
        rt(journal).execute_cycle(spec(),task="t",input_kind="move",input_payload={})
    assert isinstance(exc.value.__cause__, ActionNotApplied)
    assert ES.execute_calls == 1
    assert MS.completed == 0
