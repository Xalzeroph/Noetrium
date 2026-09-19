from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime
from tests_support import context_action_spec
import unittest

from noetrium_platform.capabilities.environment.runtime.api import EnvironmentIdentity
from noetrium_platform.foundation.kernel.kernel import OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.lifecycle.api import RunCleanupFailure


class MethodSession:
    def __init__(self,state): self.state=state
    def close(self): self.state.append("method.close")
class Method:
    identity=MethodIdentity("m","1","1","1")
    def __init__(self,state): self.state=state
    def open_session(self,*,session_id,services): self.state.append("method.open"); return MethodSession(self.state)
class EnvOpenFails:
    identity=EnvironmentIdentity("e","1","1","1")
    def __init__(self,state): self.state=state
    def open_session(self,*,session_id,services): self.state.append("env.open"); raise OSError("bridge")


class StudyLifecycleV108Tests(unittest.TestCase):
    def test_partial_open_failure_closes_already_open_method_session(self):
        state=[]; mr=FakeParticipantResolver(); er=FakeParticipantResolver()
        mr.register("method", "m",lambda:Method(state)); er.register("environment", "e",lambda:EnvOpenFails(state))
        spec=context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)
        with self.assertRaises(OperationFailure):
            context_action_runtime(mr,er).execute_cycle(spec,task="x",input_kind="a",input_payload={})
        self.assertEqual(state,["method.open","env.open","method.close"])

    def test_cleanup_failure_after_success_is_explicit_not_silent(self):
        from tests.test_generic_study import Method as GoodMethod, Env as GoodEnv, ESession
        class BadCloseESession(ESession):
            def close(self): raise OSError("close failed")
        class BadCloseEnv(GoodEnv):
            def open_session(self,*,session_id,services): return BadCloseESession()
        mr=FakeParticipantResolver(); er=FakeParticipantResolver(); mr.register("method", "m",GoodMethod); er.register("environment", "e",BadCloseEnv)
        spec=context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)
        with self.assertRaises(RunCleanupFailure) as cm:
            context_action_runtime(mr,er).execute_cycle(spec,task="x",input_kind="a",input_payload={})
        self.assertTrue(cm.exception.trial_completed)
        self.assertEqual(len(cm.exception.report.failures),1)
        self.assertTrue(cm.exception.report.failures[0].operation_id.endswith("environment.close:environment"))


if __name__=='__main__': unittest.main()
