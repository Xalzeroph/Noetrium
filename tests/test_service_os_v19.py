from noetrium_platform.infrastructure.lifecycle.service.api import ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence
from pathlib import Path
import hashlib
import tempfile
import unittest

from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactRestartPolicy,
    ExactServiceSupervisor,
    RestartHistory,
    ServiceExitClass,
    ServicePhase,
    SystemdRenderer,
    SystemdUnitSpec,
)


def h(x): return hashlib.sha256(x.encode()).hexdigest()

def contract(gen="g1"):
    exe="/opt/rp/bin/python"
    return ServiceLaunchContract("model.planner",gen,exe,(exe,"-m","model_server"),"/srv/rp",h("env"),h("artifact"),h("runtime"),120,60,10)


class Adapter:
    def __init__(self,existing=None,fail_ready=False): self.calls=[]; self.existing=existing; self.fail_ready=fail_ready
    def reconcile(self,state,c): self.calls.append("reconcile"); return self.existing,("reconcile",)
    def start(self,c): self.calls.append("start"); return ServiceProcessIdentity(123,"pid:123:start:7",123),("start",)
    def wait_ready(self,p,c):
        self.calls.append("ready")
        if self.fail_ready: raise TimeoutError("not ready")
        return ready_evidence(p,c,"ready.json","stdout.manifest","stderr.manifest")
    def stop(self,p,c): self.calls.append("stop"); return ("stopped",)


class ServiceOSV19Tests(unittest.TestCase):
    def test_start_exact_persists_ready_identity_and_capture_refs(self):
        with tempfile.TemporaryDirectory() as td:
            a=Adapter(); store=FileServiceStateStore(Path(td)/"state.json"); report=make_service_supervisor(store,a).start_exact(contract())
            self.assertEqual(report.state.phase,ServicePhase.RUNNING); self.assertEqual(report.state.process.start_identity,"pid:123:start:7"); self.assertEqual(report.state.stdout_capture_ref,"stdout.manifest")
            self.assertEqual(a.calls,["reconcile","start","ready"])

    def test_reconciled_process_is_reverified_not_restarted(self):
        with tempfile.TemporaryDirectory() as td:
            existing=ServiceProcessIdentity(9,"pid:9:start:1",9); a=Adapter(existing); store=FileServiceStateStore(Path(td)/"state.json")
            make_service_supervisor(store,a).start_exact(contract()); self.assertEqual(a.calls,["reconcile","ready"])

    def test_contract_drift_never_reuses_existing_service_state(self):
        with tempfile.TemporaryDirectory() as td:
            store=FileServiceStateStore(Path(td)/"state.json"); make_service_supervisor(store,Adapter()).start_exact(contract("g1"))
            with self.assertRaises(ServiceContractDrift): make_service_supervisor(store,Adapter()).start_exact(contract("g2"))

    def test_restart_policy_only_allows_bounded_temporary_exact_restart(self):
        p=ExactRestartPolicy(max_restarts=2,window_s=100)
        self.assertFalse(p.decide(ServiceExitClass.CONFIGURATION,RestartHistory(),now=100).restart)
        d1=p.decide(ServiceExitClass.TEMPORARY,RestartHistory(),now=100); self.assertTrue(d1.restart)
        d2=p.decide(ServiceExitClass.TEMPORARY,d1.history,now=101); self.assertTrue(d2.restart)
        d3=p.decide(ServiceExitClass.TEMPORARY,d2.history,now=102); self.assertFalse(d3.restart)

    def test_systemd_renderer_has_no_shell_or_fallback_path(self):
        unit=SystemdRenderer().render(SystemdUnitSpec("rp-model.service","RP model",("/opt/rp/bin/python","-m","noetrium_platform.infrastructure.lifecycle.service.runtime.entrypoint"),"/srv/rp","/etc/rp/model.env"))
        self.assertIn("Type=notify",unit); self.assertIn("RestartPreventExitStatus=70 74 78",unit); self.assertIn("KillMode=control-group",unit)
        self.assertNotIn("/bin/sh",unit); self.assertNotIn("fallback",unit.lower())

if __name__=='__main__': unittest.main()
