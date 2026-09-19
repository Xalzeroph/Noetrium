from pathlib import Path
import tempfile
import threading
import time
import unittest
import hashlib

from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement, ModelPhase, ModelRunState,
    QualificationCertificate, QualifiedDeploymentManifest, RecoveryStep,
    ResourceEnvelope, RoleModelAssignment, RoleModelManifest,
)
from noetrium_platform.capabilities.model.stack import ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
from noetrium_platform.capabilities.model.serving.runtime import (
    DurableExactRecoveryRunner, ModelAdmissionController, ModelAdmissionTimeout, RecoveryPlanner,
)

from noetrium_platform.capabilities.model.serving.providers.recovery_storage import FileDurableRecoveryStore


def stack_parts():
    h=lambda x: hashlib.sha256(x.encode()).hexdigest()
    return (
        ModelArtifactClosure(h("weights"),h("tokenizer"),h("config"),h("model-code"),h("chat-template")),
        RuntimeBuildIdentity(h("container"),h("engine-build"),h("python-lock"),"cuda-12.8","nccl-2.27","torch-2.8",h("kernels")),
    )

class _RecoveryExecutor:
    def __init__(self, fail_once_at=None): self.fail_once_at=fail_once_at; self.failed=False; self.calls=[]
    def run_step(self,step,plan):
        self.calls.append(step)
        if step==self.fail_once_at and not self.failed:
            self.failed=True; raise OSError("injected hard interruption")
        return (f"e:{step.value}",)


class ModelOSV11Tests(unittest.TestCase):
    def _identity(self): return ImmutableModelIdentity("q","model","rev","sglang","1","bfloat16",None,262144)
    def _stack(self): return ModelStackSpec(self._identity(),*stack_parts(),2,1,1,1,"qwen3",None,None,None,"default")

    def test_role_assignment_is_exactly_one_deployment(self):
        m=RoleModelManifest((RoleModelAssignment("planner","dep_a"),RoleModelAssignment("meta","dep_b")))
        self.assertEqual(m.deployment_for("planner"),"dep_a")
        with self.assertRaises(ValueError): RoleModelManifest((RoleModelAssignment("planner","a"),RoleModelAssignment("planner","b")))
        with self.assertRaises(KeyError): m.deployment_for("semantic")

    def test_deployment_certificate_is_stack_and_host_bound(self):
        stack=self._stack(); host_identity=hashlib.sha256(b"host").hexdigest()
        env=ResourceEnvelope(70<<30,100<<30,8,.5,.03,500)
        cert=QualificationCertificate(stack.digest(),"ev",("planner","semantic"),env,host_identity)
        dep=QualifiedDeploymentManifest("dep",stack,cert,DeploymentPlacement(("g0","g1")),host_identity)
        self.assertEqual(len(dep.digest()),64)
        with self.assertRaises(ValueError):
            QualifiedDeploymentManifest("dep",stack,cert,DeploymentPlacement(("g0","g1")),"other")

    def test_admission_backpressures_without_quality_change(self):
        c=ModelAdmissionController(1); first=c.acquire()
        with self.assertRaises(ModelAdmissionTimeout): c.acquire(timeout_seconds=.01)
        self.assertEqual(c.snapshot().active,1); first.release(); self.assertEqual(c.snapshot().active,0)

    def _plan(self):
        ident=self._identity(); state=ModelRunState.initial("r", ident, "d"*64).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
        return RecoveryPlanner().plan(state,ident,state.deployment_digest)

    def test_recovery_plan_reconciles_study_before_resume(self):
        p=self._plan(); i=p.steps.index(RecoveryStep.RESUME_RUN_EXACT)
        self.assertEqual(p.steps[i-1],RecoveryStep.RECONCILE_RUN)

    def test_interrupted_model_restart_reconciles_before_retry(self):
        with tempfile.TemporaryDirectory() as td:
            store=FileDurableRecoveryStore(Path(td)/"recovery.json", guard_path=Path(td)/"recovery.guard.lock"); plan=self._plan(); ex=_RecoveryExecutor(RecoveryStep.RESTART_EXACT_MODEL); runner=DurableExactRecoveryRunner(store,ex)
            with self.assertRaises(OSError): runner.run(plan,attempt_id="a")
            self.assertEqual(store.load().current_effect_certainty,"unknown")
            ex.calls.clear(); report=runner.run(plan,attempt_id="a")
            self.assertEqual(ex.calls[0],RecoveryStep.RECONCILE_PROCESS)
            self.assertEqual(report.attempt.phase.value,"succeeded")
            self.assertEqual(report.attempt.completed_steps,tuple(x.value for x in plan.steps))

    def test_interrupted_study_resume_reconciles_before_retry(self):
        with tempfile.TemporaryDirectory() as td:
            store=FileDurableRecoveryStore(Path(td)/"recovery.json", guard_path=Path(td)/"recovery.guard.lock"); plan=self._plan(); ex=_RecoveryExecutor(RecoveryStep.RESUME_RUN_EXACT); runner=DurableExactRecoveryRunner(store,ex)
            with self.assertRaises(OSError): runner.run(plan,attempt_id="a")
            ex.calls.clear(); runner.run(plan,attempt_id="a")
            self.assertEqual(ex.calls[0],RecoveryStep.RECONCILE_RUN)

if __name__=='__main__': unittest.main()
