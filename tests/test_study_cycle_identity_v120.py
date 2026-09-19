from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec

from noetrium_platform.capabilities.environment.runtime.api import action_request_digest, ActionResult, EnvironmentIdentity, Observation
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.execution.decision import FixedDecisionCycleIdentityProvider, DecisionCycleIdentity


class MethodSession:
    def ingest(self, evidence, context): pass
    def recall(self, request): return RecallResult("ctx", "mg1")
    def task_completed(self, result, context): pass
    def close(self): pass


class Method:
    identity=MethodIdentity("m", "1", "1", "1", "c" * 64)
    def open_session(self, *, session_id, services): return MethodSession()


class EnvironmentSession:
    def observe(self, context):
        return Observation("obs1", "eg1", {"x": 1})
    def act(self, request):
        return ActionResult(
            request.action_id, True, None,
            EffectReceipt(effect_id="e1", request_digest=action_request_digest(request), effect_class=EffectClass.IDEMPOTENT, certainty=EffectCertainty.NO_EFFECT, provider_instance_id="env", verification_required=False),
            {},
        )
    def close(self): pass


class Environment:
    identity=EnvironmentIdentity("e", "1", "1", "1", "e" * 64)
    def open_session(self, *, session_id, services): return EnvironmentSession()


def spec():
    return context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1, method_artifact_digest="c" * 64, environment_artifact_digest="e" * 64)


def runtime(provider=None):
    mr=FakeParticipantResolver(); mr.register("method", "m", Method)
    er=FakeParticipantResolver(); er.register("environment", "e", Environment)
    return context_action_runtime(mr, er, cycle_identity_provider=provider)


def test_exact_cycle_identity_is_reused_by_all_operation_ids_and_context():
    identity=DecisionCycleIdentity("run_fixed", "dc_fixed", "session_fixed", "task_fixed", "trace_fixed")
    result=runtime(FixedDecisionCycleIdentityProvider(identity)).execute_cycle(
        spec(), task="t", input_kind="noop", input_payload={},
    )
    assert result.run_id == "run_fixed"
    assert result.decision_cycle_id == "dc_fixed"
    assert all(op.operation_id.startswith("dc_fixed:") for op in result.operation_results)
    assert result.cycle_identity == identity


def test_explicit_identity_overrides_random_provider_for_crash_replay():
    identity=DecisionCycleIdentity("run_replay", "dc_replay", "session_replay", "task_replay", "trace_replay")
    first=runtime().execute_cycle(spec(), task="t", input_kind="noop", input_payload={}, cycle_identity=identity)
    second=runtime().execute_cycle(spec(), task="t", input_kind="noop", input_payload={}, cycle_identity=identity)
    assert [x.operation_id for x in first.operation_results] == [x.operation_id for x in second.operation_results]
    assert first.cycle_identity == second.cycle_identity == identity


def test_cycle_identity_digest_changes_for_any_recovery_identity_field():
    base=DecisionCycleIdentity("r", "d", "s", "t", "tr")
    changed=DecisionCycleIdentity("r", "d2", "s", "t", "tr")
    assert base.digest() != changed.digest()
