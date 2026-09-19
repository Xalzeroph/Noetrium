from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec

import pytest

from noetrium_platform.capabilities.environment.runtime.api import action_request_digest, ActionResult, EnvironmentIdentity, Observation
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


class MSession:
    completion_calls = 0
    def ingest(self, evidence, context): pass
    def recall(self, request): return RecallResult("ctx", "mg1")
    def task_completed(self, result, context):
        type(self).completion_calls += 1
        assert result.effect is not None
        assert result.effect.certainty is EffectCertainty.EFFECT_CONFIRMED
    def close(self): pass


class Method:
    identity = MethodIdentity("m", "1", "1", "1")
    def open_session(self, *, session_id, services): return MSession()


class ReconcileSession:
    reconcile_calls = 0
    leave_unknown = False
    def observe(self, context): return Observation("o1", "eg1", {})
    def act(self, request):
        return ActionResult(
            request.action_id,
            True,
            Observation("o2", "eg2", {}),
            EffectReceipt(
                "fx", action_request_digest(request), EffectClass.RECONCILABLE,
                EffectCertainty.EFFECT_UNKNOWN, "env", True,
            ),
            {},
        )
    def reconcile(self, effect, context):
        type(self).reconcile_calls += 1
        certainty = EffectCertainty.EFFECT_UNKNOWN if type(self).leave_unknown else EffectCertainty.EFFECT_CONFIRMED
        return EffectReceipt("fx", effect.request_digest, EffectClass.RECONCILABLE, certainty, "env", type(self).leave_unknown)
    def close(self): pass


class Env:
    identity = EnvironmentIdentity("e", "1", "1", "1")
    def open_session(self, *, session_id, services): return ReconcileSession()


def runtime():
    mr=FakeParticipantResolver(); mr.register("method", "m", Method)
    er=FakeParticipantResolver(); er.register("environment", "e", Env)
    return context_action_runtime(mr, er)


def spec(): return context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)


def test_uncertain_effect_is_reconciled_before_method_completion_and_updates_environment_generation():
    MSession.completion_calls = 0
    ReconcileSession.reconcile_calls = 0
    ReconcileSession.leave_unknown = False
    result = runtime().execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert MSession.completion_calls == 1
    assert ReconcileSession.reconcile_calls == 1
    assert any(x.operation_id.endswith("environment.reconcile") for x in result.operation_results)


def test_unresolved_effect_fails_before_method_completion():
    MSession.completion_calls = 0
    ReconcileSession.reconcile_calls = 0
    ReconcileSession.leave_unknown = True
    with pytest.raises(OperationFailure) as exc:
        runtime().execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert exc.value.result.operation_id.endswith("environment.reconcile")
    assert MSession.completion_calls == 0
    assert ReconcileSession.reconcile_calls == 1
