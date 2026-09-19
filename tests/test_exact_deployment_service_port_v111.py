from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

from tests_support import frozen_runtime_manifest

import hashlib
from pathlib import Path
import tempfile
import unittest

from noetrium_platform.composition.model_deployments import freeze_model_deployment_set
from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api.qualified_deployment import QualificationCertificate, QualifiedDeploymentManifest, ResourceEnvelope, RoleModelAssignment, RoleModelManifest
from noetrium_platform.capabilities.model.serving.api.placement import DeploymentPlacement
from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
from noetrium_platform.infrastructure.lifecycle.launch_control import (
    DeploymentServiceBinding,
    DeploymentServiceBindingError,
    ExactDeploymentServicePort,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.runtime_endpoint import ExactServiceRuntimeEndpoint
from noetrium_platform.infrastructure.lifecycle.service.runtime import ExactServiceSupervisor


def h(v): return hashlib.sha256(v.encode()).hexdigest()


def deployment(dep: str) -> QualifiedDeploymentManifest:
    identity=ImmutableModelIdentity(dep,f"repo/{dep}","rev","engine","1","bfloat16",None,4096)
    artifacts=ModelArtifactClosure(h(dep+"w"),h(dep+"t"),h(dep+"c"))
    runtime=RuntimeBuildIdentity(h(dep+"container"),h(dep+"engine"),h(dep+"lock"),"cuda","nccl","torch",h(dep+"ext"))
    stack=ModelStackSpec(identity,artifacts,runtime,1,1,1,1,None,None,None,None,"fcfs")
    cert=QualificationCertificate(stack.digest(),h("evidence"),("planner",),ResourceEnvelope(1,1,1,1,1,1),h("host"))
    return QualifiedDeploymentManifest(dep,stack,cert,DeploymentPlacement(("GPU-1",)),h("host"))


def frozen(ds):
    return frozen_runtime_manifest(prompt_generation_digest="pg", role_model_manifest_digest=ds.role_manifest_digest, qualified_deployment_digests=tuple(d.deployment_digest for d in ds.deployments), target_host_identity_digest=h("host"))


class Adapter:
    def __init__(self,pid): self.pid=pid; self.calls=[]
    def reconcile(self,state,c):
        self.calls.append("reconcile")
        return state.process,(f"reconcile:{self.pid}",) if state.process else ()
    def start(self,c):
        self.calls.append("start")
        return ServiceProcessIdentity(self.pid,f"start:{self.pid}",self.pid),(f"start:{self.pid}",)
    def wait_ready(self,p,c): self.calls.append("ready"); return ready_evidence(p,c,f"ready:{self.pid}",f"out:{self.pid}",f"err:{self.pid}")
    def stop(self,p,c): self.calls.append("stop"); return ()


def binding(root: Path, d: QualifiedDeploymentManifest, pid: int):
    exe="/opt/rp/python"
    c=ServiceLaunchContract(
        "model."+d.deployment_id,d.digest(),exe,(exe,"-m","server"),"/srv/rp",h("env"),
        d.stack.artifacts.digest(),d.stack.runtime.digest(),10,10,1,
    )
    a=Adapter(pid)
    s=make_service_supervisor(FileServiceStateStore(root/(d.deployment_id+".json")),a)
    return DeploymentServiceBinding(d.deployment_id,c,ExactServiceRuntimeEndpoint(s)),a


class ExactDeploymentServicePortV111Tests(unittest.TestCase):
    def test_each_deployment_keeps_an_independent_supervisor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d1=deployment("d1"); d2=deployment("d2")
            # Use distinct synthetic GPU identities to satisfy deployment-set exclusivity.
            from dataclasses import replace
            d2=replace(d2,placement=replace(d2.placement,gpu_uuids=("GPU-2",)))
            roles=RoleModelManifest((RoleModelAssignment("planner","d1"),RoleModelAssignment("meta","d2")))
            ds=freeze_model_deployment_set(roles,(d2,d1)); b1,a1=binding(root,d1,101); b2,a2=binding(root,d2,202)
            port=ExactDeploymentServicePort((b1,b2)); m=frozen(ds)
            self.assertEqual(port.reconcile(m,ds),("service-reconcile:d1:no-state","service-reconcile:d2:no-state"))
            refs=port.start_exact(m,ds)
            self.assertTrue(any(x.startswith("service-running:d1:") for x in refs))
            self.assertTrue(any(x.startswith("service-running:d2:") for x in refs))
            self.assertEqual(a1.calls,["reconcile","start","ready"])
            self.assertEqual(a2.calls,["reconcile","start","ready"])
            ready=port.verify_ready(m,ds)
            self.assertIn("ready:101",ready); self.assertIn("ready:202",ready)

    def test_binding_rejects_runtime_or_artifact_drift_before_process_action(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d=deployment("d1")
            ds=freeze_model_deployment_set(RoleModelManifest((RoleModelAssignment("planner","d1"),)),(d,))
            b,a=binding(root,d,1)
            from dataclasses import replace
            bad=replace(b,launch_contract=replace(b.launch_contract,artifact_digest=h("wrong")))
            port=ExactDeploymentServicePort((bad,))
            with self.assertRaises(DeploymentServiceBindingError): port.reconcile(frozen(ds),ds)
            self.assertEqual(a.calls,[])


if __name__ == "__main__": unittest.main()
