from __future__ import annotations

from tests_support import FakeParticipantResolver, participant, model_role_for_test
from tests_support import context_action_runtime

from dataclasses import replace
import unittest

from noetrium_platform.capabilities.environment.runtime.api import action_request_digest, ActionResult, EnvironmentIdentity, Observation
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.execution.workflow.implementations.context_action import CONTEXT_ACTION_TRIAL_CONFIGURATION_DIGEST
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantIdentityMismatch
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantSpec
from noetrium_platform.research.execution.workflow.implementations.context_action import (
    CONTEXT_ACTION_TRIAL_CONFIGURATION_DIGEST,
)


class MethodSession:
    def ingest(self,e,c): pass
    def recall(self,r): return RecallResult("ctx","g")
    def task_completed(self,r,c): pass
    def checkpoint(self): return MethodSnapshot("actual","2","schema-2","cfg-m","s","d",b"")
    def restore(self,s): pass
    def diagnostics(self): return {}
    def close(self): pass


class WrongMethod:
    identity=MethodIdentity("actual","2","abi-2","schema-2","c" * 64)
    def open_session(self,*,session_id,services): return MethodSession()


class EnvSession:
    def observe(self,c): return Observation("o","eg",{})
    def act(self,r): return ActionResult(r.action_id,True,None,EffectReceipt("fx",action_request_digest(r),EffectClass.PURE,EffectCertainty.NO_EFFECT),{})
    def reconcile(self,e,c): return e
    def checkpoint(self): return b""
    def restore(self,p): pass
    def close(self): pass


class Env:
    identity=EnvironmentIdentity("env","3","abi-3","schema-3","cfg-e")
    def open_session(self,*,session_id,services): return EnvSession()


def runtime(method_factory=WrongMethod):
    methods=FakeParticipantResolver(); envs=FakeParticipantResolver(); methods.register("method", "requested",method_factory); envs.register("environment", "env",Env)
    return context_action_runtime(methods,envs)


def spec(*, method_id="requested", method_implementation_version="2", method_abi_version="abi-2", method_schema_version="schema-2", method_configuration_digest="cfg-m"):
    return ExperimentSpec(
        experiment_id="study",
        study_id="default-study",
        project_id="default-project",
        participants=(
            participant(
                "method", "method", method_id, implementation_version=method_implementation_version,
                abi_version=method_abi_version, schema_version=method_schema_version,
                configuration_digest=method_configuration_digest,
            ),
            participant("environment", "environment", "env", implementation_version="3", abi_version="abi-3", schema_version="schema-3", configuration_digest="cfg-e"),
        ),
        model_roles=(model_role_for_test(),), workload_digest="b" * 64,
        seed_digest="c" * 64, repetitions=1, trial_protocol_id="context_action.v5",
        trial_protocol_configuration_digest=CONTEXT_ACTION_TRIAL_CONFIGURATION_DIGEST,
    )



class TrialIdentityFreezeV115Tests(unittest.TestCase):
    def test_registry_cannot_return_a_different_logical_method_identity(self):
        with self.assertRaisesRegex(ParticipantIdentityMismatch,"implementation mismatch"):
            runtime().execute_cycle(spec(),task="x",input_kind="a",input_payload={})

    def test_version_abi_schema_all_participate_in_study_identity(self):
        a=spec(method_implementation_version="2")
        b=spec(method_implementation_version="9")
        c=spec(method_schema_version="schema-9")
        self.assertNotEqual(a.identity_digest(),b.identity_digest())
        self.assertNotEqual(a.identity_digest(),c.identity_digest())

    def test_matching_logical_identity_then_rejects_schema_drift_before_session_open(self):
        class Matching(WrongMethod):
            identity=MethodIdentity("requested","2","abi-2","schema-WRONG","c" * 64)
        with self.assertRaisesRegex(ParticipantIdentityMismatch,"implementation mismatch"):
            runtime(Matching).execute_cycle(spec(),task="x",input_kind="a",input_payload={})


if __name__ == "__main__": unittest.main()
