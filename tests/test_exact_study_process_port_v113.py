from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

from tests_support import context_action_runtime_bindings, frozen_runtime_manifest

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRunProcessPort, RunLaunchIdentity, RunProcessBinding, RunProcessBindingError
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.runtime_endpoint import ExactServiceRuntimeEndpoint
from noetrium_platform.infrastructure.lifecycle.service.runtime import ExactServiceSupervisor


def h(v): return hashlib.sha256(v.encode()).hexdigest()


def manifest():
    return frozen_runtime_manifest(release_digest=h("release"), prompt_generation_digest="pg", prompt_promotion_digest="pp", role_model_manifest_digest="roles", target_host_identity_digest=h("host"), participant_bindings=context_action_runtime_bindings(method_id="sem", method_abi="mabi", method_config=h("method-config"), environment_id="minecraft", environment_abi="eabi", environment_config=h("env-config")), experiment_spec_digest=h("study"))


class Adapter:
    def __init__(self): self.calls=[]; self.live=None
    def reconcile(self,state,c): self.calls.append("reconcile"); return state.process if self.live is not False else None,("reconcile",)
    def start(self,c): self.calls.append("start"); self.live=True; return ServiceProcessIdentity(77,"start:77",77),("start",)
    def wait_ready(self,p,c): self.calls.append("ready"); return ready_evidence(p,c)
    def stop(self,p,c): self.calls.append("stop"); self.live=False; return ()


def port(root: Path, m):
    identity=RunLaunchIdentity.from_manifest(m); exe="/opt/rp/python"
    contract=ServiceLaunchContract("study.main",identity.digest(),exe,(exe,"-m","study"),"/srv/rp",h("env"),h("artifact"),h("runtime"),10,10,1)
    adapter=Adapter(); supervisor=make_service_supervisor(FileServiceStateStore(root/"study.json"),adapter)
    return ExactRunProcessPort(RunProcessBinding(identity,contract,ExactServiceRuntimeEndpoint(supervisor))),adapter


class ExactRunProcessPortV113Tests(unittest.TestCase):
    def test_final_status_reproves_study_process_identity(self):
        with tempfile.TemporaryDirectory() as td:
            m=manifest(); p,a=port(Path(td),m)
            self.assertEqual(p.reconcile(m),("run-reconcile:no-state",))
            p.start_exact(m)
            refs=p.final_status(m)
            self.assertTrue(any(x.startswith("run-final:start:77:") for x in refs))
            self.assertEqual(a.calls,["reconcile","start","ready","reconcile"])

    def test_study_exit_before_final_status_is_a_runtime_failure(self):
        with tempfile.TemporaryDirectory() as td:
            m=manifest(); p,a=port(Path(td),m); p.start_exact(m); a.live=False
            with self.assertRaisesRegex(RuntimeError,"not running at FINAL_STATUS"):
                p.final_status(m)

    def test_manifest_participant_configuration_drift_cannot_reuse_study_process(self):
        with tempfile.TemporaryDirectory() as td:
            m=manifest(); p,a=port(Path(td),m)
            with self.assertRaises(RunProcessBindingError):
                p.reconcile(replace(m, participant_binding_manifest_digest=h("other-binding-manifest")))
            self.assertEqual(a.calls,[])


if __name__ == "__main__": unittest.main()
