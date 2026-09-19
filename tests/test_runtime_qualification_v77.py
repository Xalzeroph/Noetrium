from __future__ import annotations

import time
import unittest

from noetrium_platform.capabilities.model.serving import build_runtime_qualification_receipt
from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeAction, exact_runtime_plan
from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat import ServiceHeartbeat
from noetrium_platform.capabilities.model.serving.runtime.recovery import RecoveryPlanner, RecoveryStep
from noetrium_platform.capabilities.model.serving.api.state import ModelPhase, ModelRunState

from test_server_runtime_control_v29 import deployment


class RuntimeQualificationV77Tests(unittest.TestCase):
    def test_exact_runtime_plan_requires_live_qualification_after_ready(self):
        actions=tuple(x.action for x in exact_runtime_plan().steps)
        self.assertLess(actions.index(RuntimeAction.VERIFY_SERVICES_READY),actions.index(RuntimeAction.VERIFY_RUNTIME_QUALIFICATION))
        self.assertLess(actions.index(RuntimeAction.VERIFY_RUNTIME_QUALIFICATION),actions.index(RuntimeAction.START_EXACT_RUN))

    def test_live_receipt_binds_stack_certificate_roles_and_fresh_heartbeat(self):
        d=deployment("planner","GPU-0")
        cert=d.certificate.digest()
        hb=ServiceHeartbeat(d.deployment_id,d.stack.digest(),123,"start","a"*64,True,cert,100.0)
        heartbeat_ref=(f"heartbeat:{hb.deployment_id}:{hb.pid}:"
                       f"{hb.process_start_marker}:{hb.timestamp}")
        receipt=build_runtime_qualification_receipt(
            d,hb,
            required_roles=("planner",),
            evidence_refs=(heartbeat_ref,f"canary:sha256:{'c'*64}",f"performance:sha256:{'d'*64}"),
            max_heartbeat_age_seconds=5,
            now=102.0,
        )
        self.assertEqual(receipt.qualification_certificate_digest,cert)
        self.assertEqual(len(receipt.digest()),64)

    def test_live_receipt_rejects_stale_or_wrong_qualification_digest(self):
        d=deployment("planner","GPU-0")
        stale=ServiceHeartbeat(d.deployment_id,d.stack.digest(),123,"start","a"*64,True,d.certificate.digest(),100.0)
        with self.assertRaises(ValueError):
            build_runtime_qualification_receipt(d,stale,required_roles=("planner",),evidence_refs=("x",),max_heartbeat_age_seconds=1,now=102.0)
        wrong=ServiceHeartbeat(d.deployment_id,d.stack.digest(),123,"start","a"*64,True,"bad",102.0)
        with self.assertRaises(ValueError):
            build_runtime_qualification_receipt(d,wrong,required_roles=("planner",),evidence_refs=("x",),max_heartbeat_age_seconds=5,now=102.0)

    def test_model_recovery_plan_requalifies_exact_runtime_before_study_resume(self):
        identity=deployment("planner","GPU-0").stack.identity
        state=ModelRunState.initial("run", identity, "d"*64).transition(ModelPhase.FAILED)
        steps=RecoveryPlanner().plan(state,identity,state.deployment_digest).steps
        self.assertIn(RecoveryStep.VERIFY_RUNTIME_QUALIFICATION,steps)
        self.assertLess(steps.index(RecoveryStep.WAIT_READY),steps.index(RecoveryStep.VERIFY_RUNTIME_QUALIFICATION))
        self.assertLess(steps.index(RecoveryStep.VERIFY_RUNTIME_QUALIFICATION),steps.index(RecoveryStep.RESUME_RUN_EXACT))


if __name__=="__main__": unittest.main()
