from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle
from noetrium_platform.infrastructure.reliability.effect.runtime import InMemoryEffectIntentJournal
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionIdentityViolation,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    EnvironmentIdentity,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, ExecutionContext, OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.execution.decision import FixedDecisionCycleIdentityProvider, DecisionCycleIdentity


def receipt(digest: str, certainty: EffectCertainty = EffectCertainty.EFFECT_CONFIRMED) -> EffectReceipt:
    return EffectReceipt("fx", digest, EffectClass.RECONCILABLE, certainty, "env", certainty is EffectCertainty.EFFECT_UNKNOWN)


class MS:
    completed = 0
    def ingest(self, evidence, context): pass
    def recall(self, request): return RecallResult("ctx", "mg")
    def task_completed(self, result, context): type(self).completed += 1
    def close(self): pass


class M:
    identity = MethodIdentity("m", "1", "1", "1")
    def open_session(self, *, session_id, services): return MS()


class ReconcileDigestMismatchSession:
    def observe(self, context): return Observation("o", "eg", {})
    def act(self, request):
        return ActionResult(
            request.action_id, True, None,
            receipt(action_request_digest(request), EffectCertainty.EFFECT_UNKNOWN), {},
        )
    def reconcile(self, effect, context):
        return receipt("wrong-digest", EffectCertainty.EFFECT_CONFIRMED)
    def close(self): pass


class ReconcileActionDigestMismatchSession:
    execute_calls = 0
    action_recovery_durability = "process_local"
    def observe(self, context): return Observation("o", "eg", {})
    def act(self, request): raise AssertionError("journal-backed execution must never call raw act")
    def prepare_action_recovery(self, request, context):
        return PreparedEffectHandle.build(
            request_id=request.action_id, request_digest=action_request_digest(request),
            provider_schema="test.digest-mismatch.v1", opaque_payload=b"prepared", provider_instance_id="env",
        )
    def execute_prepared_action(self, request, handle):
        type(self).execute_calls += 1
        raise RuntimeError("transport lost after possible effect")
    def reconcile_prepared_action(self, handle, context):
        result = ActionResult(handle.request_id, True, None, receipt("wrong-digest"), {})
        return ActionReconciliationResult(handle.request_id, ActionReconciliationDisposition.APPLIED, result, {})
    def close(self): pass


class E1:
    identity = EnvironmentIdentity("e", "1", "1", "1")
    def open_session(self, *, session_id, services): return ReconcileDigestMismatchSession()


class E2:
    identity = EnvironmentIdentity("e", "1", "1", "1")
    def open_session(self, *, session_id, services): return ReconcileActionDigestMismatchSession()


def spec() -> ExperimentSpec:
    return context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)


def runtime(env, *, journal=None) -> ExperimentRuntime:
    mr = FakeParticipantResolver(); mr.register("method", "m", M)
    er = FakeParticipantResolver(); er.register("environment", "e", env)
    identity = DecisionCycleIdentity("run", "dc", "session", "task", "trace")
    return context_action_runtime(
        mr, er,
        cycle_identity_provider=FixedDecisionCycleIdentityProvider(identity),
        effect_journal=journal,
    )


def test_reconcile_effect_receipt_must_match_original_action_semantic_digest():
    MS.completed = 0
    with pytest.raises(OperationFailure) as exc:
        runtime(E1).execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert exc.value.result.operation_id.endswith("environment.reconcile")
    assert isinstance(exc.value.__cause__, ActionIdentityViolation)
    assert MS.completed == 0


def test_reconciled_effect_receipt_must_match_prepared_action_semantic_digest_and_never_replays_act():
    ReconcileActionDigestMismatchSession.execute_calls = 0
    journal = InMemoryEffectIntentJournal()
    with pytest.raises(OperationFailure):
        runtime(E2, journal=journal).execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert ReconcileActionDigestMismatchSession.execute_calls == 1
    with pytest.raises(OperationFailure) as exc:
        runtime(E2, journal=journal).execute_cycle(spec(), task="t", input_kind="move", input_payload={})
    assert exc.value.result.operation_id.endswith("environment.reconcile_prepared_action")
    assert isinstance(exc.value.__cause__, ActionIdentityViolation)
    assert ReconcileActionDigestMismatchSession.execute_calls == 1
    assert MS.completed == 0


def test_action_semantic_digest_excludes_trace_span_but_binds_scientific_cycle_identity():
    a = ActionRequest(
        "a", "move", {"x": 1},
        ExecutionContext("run", "trace-a", "span-a", study_id="s", lifetime_id="life", task_id="task", decision_cycle_id="dc"),
    )
    b = ActionRequest(
        "a", "move", {"x": 1},
        ExecutionContext("run", "trace-b", "span-b", study_id="s", lifetime_id="life", task_id="task", decision_cycle_id="dc"),
    )
    c = ActionRequest(
        "a", "move", {"x": 1},
        ExecutionContext("run", "trace-b", "span-b", study_id="s", lifetime_id="life", task_id="other-task", decision_cycle_id="dc"),
    )
    assert action_request_digest(a) == action_request_digest(b)
    assert action_request_digest(a) != action_request_digest(c)

    d = ActionRequest(
        "a", "move", {"x": 1},
        ExecutionContext(
            "run", "trace-b", "span-b", study_id="s", lifetime_id="life",
            task_id="task", decision_cycle_id="dc", checkpoint_id="cp-1",
            participant_generations=(("environment", "eg-1"),),
        ),
    )
    e = ActionRequest(
        "a", "move", {"x": 1},
        ExecutionContext(
            "run", "trace-c", "span-c", study_id="s", lifetime_id="life",
            task_id="task", decision_cycle_id="dc", checkpoint_id="cp-2",
            participant_generations=(("environment", "eg-1"),),
        ),
    )
    f = ActionRequest(
        "a", "move", {"x": 1},
        ExecutionContext(
            "run", "trace-c", "span-c", study_id="s", lifetime_id="life",
            task_id="task", decision_cycle_id="dc", checkpoint_id="cp-1",
            participant_generations=(("environment", "eg-2"),),
        ),
    )
    assert action_request_digest(d) != action_request_digest(e)
    # The exact side-effect request is bound to the observed pre-action environment generation.
    assert action_request_digest(d) != action_request_digest(f)
