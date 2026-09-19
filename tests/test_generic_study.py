from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime
from tests_support import context_action_spec
import hashlib, unittest
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot, RecallResult
from noetrium_platform.capabilities.environment.runtime.api import action_request_digest, EnvironmentIdentity, Observation, ActionResult
from noetrium_platform.foundation.kernel.kernel import EffectReceipt, EffectClass, EffectCertainty, OperationExecutor, OperationFailure
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec

class MSession:
    def ingest(self,e,c): self.e=e
    def recall(self,r): return RecallResult("generic-context","g1")
    def task_completed(self,r,c): self.r=r
    def checkpoint(self): return MethodSnapshot("m","1","1","","s",hashlib.sha256(b'x').hexdigest(),b'x')
    def restore(self,s): pass
    def diagnostics(self): return {}
    def close(self): pass
class Method:
    identity=MethodIdentity("m","1","1","1")
    def open_session(self,*,session_id,services): return MSession()
class ESession:
    def observe(self,c): return Observation("o","e1",{"state":1})
    def act(self,r): return ActionResult(r.action_id,True,Observation("o2","e1",{"state":2}),EffectReceipt("fx",action_request_digest(r),EffectClass.RECONCILABLE,EffectCertainty.EFFECT_CONFIRMED),{})
    def reconcile(self,e,c): return e
    def checkpoint(self): return b'e'
    def restore(self,p): pass
    def close(self): pass
class Env:
    identity=EnvironmentIdentity("e","1","1","1")
    def open_session(self,*,session_id,services): return ESession()

class GenericStudyTests(unittest.TestCase):
    def test_method_environment_are_replaceable(self):
        mr=FakeParticipantResolver(); er=FakeParticipantResolver(); mr.register("method", "m",Method); er.register("environment", "e",Env)
        s=context_action_spec(study_id="study", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)
        r=context_action_runtime(mr,er).execute_cycle(s,task="task",input_kind="act",input_payload={})
        self.assertEqual(r.context_text,"generic-context")
        self.assertTrue(r.primary_result.accepted)
        self.assertEqual([x.status.value for x in r.operation_results],["succeeded"]*11)
        self.assertEqual(len(r.operation_results),11)
        act=next(x for x in r.operation_results if x.operation_id.endswith("environment.act"))
        self.assertEqual(len(act.effect_receipts),1)

if __name__=="__main__": unittest.main()
