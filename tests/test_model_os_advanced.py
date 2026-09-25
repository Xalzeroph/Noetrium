import unittest
import hashlib
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api import (
    ModelRunState, ModelPhase, PerformanceSample, QualificationEvidence,
    QualificationPolicy, RoleCanaryResult, evaluate_qualification,
)
from noetrium_platform.capabilities.model.stack import ModelArtifactClosure, RuntimeBuildIdentity, ModelStackSpec
from noetrium_platform.capabilities.model.serving.runtime import (
    ProcessIdentity, ProcessIdentityReconciler, RecoveryPlanner, RecoveryTransaction,
)



def stack_parts():
    h=lambda x: hashlib.sha256(x.encode()).hexdigest()
    return (
        ModelArtifactClosure(h("weights"),h("tokenizer"),h("config"),h("model-code"),h("chat-template")),
        RuntimeBuildIdentity(h("container"),h("engine-build"),h("python-lock"),"cuda-12.8","nccl-2.27","torch-2.8",h("kernels")),
    )

class ModelOSAdvancedTests(unittest.TestCase):
    def test_model_stack_digest_changes_on_quality_setting(self):
        i=ImmutableModelIdentity("m","id","rev","sglang","v","bfloat16",None,262144)
        a=ModelStackSpec(i,*stack_parts(),4,1,1,1,"qwen3",None,None,None,"default")
        b=ModelStackSpec(i,*stack_parts(),2,1,1,1,"qwen3",None,None,None,"default")
        self.assertNotEqual(a.digest(), b.digest())


    def test_qualification_requires_critical_and_repro(self):
        ev=QualificationEvidence("x",(RoleCanaryResult("planner",100,100,10,10,0),),(PerformanceSample(8,.1,.3,.01,.02,1000,0.0),),True,True,True)
        self.assertTrue(evaluate_qualification(ev, QualificationPolicy()).qualified)
        bad=QualificationEvidence("x",(RoleCanaryResult("planner",100,99,10,9,0),),(PerformanceSample(8,.1,.3,.01,.02,1000,0.0),),False,True,True)
        self.assertFalse(evaluate_qualification(bad, QualificationPolicy()).qualified)

    def test_process_identity_detects_pid_reuse(self):
        a=ProcessIdentity.from_argv(10,"100",("python","server.py"))
        b=ProcessIdentity.from_argv(10,"200",("python","server.py"))
        self.assertEqual(ProcessIdentityReconciler().reconcile(a,b), "pid_reused_or_identity_drift")

    def test_recovery_transaction_is_ordered(self):
        i=ImmutableModelIdentity("m","id","rev","sglang","v","bfloat16",None,262144)
        s=ModelRunState.initial("r", i, "d"*64).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
        plan=RecoveryPlanner().plan(s,i,s.deployment_digest)
        txn=RecoveryTransaction(plan); txn.start()
        with self.assertRaises(RuntimeError): txn.complete_step(plan.steps[1])
        for step in plan.steps: txn.complete_step(step)
        self.assertEqual(txn.state.value,"succeeded")

if __name__ == "__main__": unittest.main()
