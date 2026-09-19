from __future__ import annotations

from tests_support import frozen_runtime_manifest

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import time
import unittest

from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.providers.runtime_qualification_storage import DirectoryRuntimeQualificationEvidenceStore
from noetrium_platform.capabilities.model.serving.runtime.runtime_qualification_service import RuntimeQualificationPublisher
from noetrium_platform.capabilities.model.serving.api.qualified_deployment import QualificationCertificate, QualifiedDeploymentManifest, ResourceEnvelope, RoleModelAssignment, RoleModelManifest
from noetrium_platform.capabilities.model.serving.api.placement import DeploymentPlacement
from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat
from noetrium_platform.composition.model_deployments import freeze_model_deployment_set
from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat_storage import FileServiceHeartbeatStore
from noetrium_platform.infrastructure.lifecycle.launch_control import FrozenDeploymentVerificationPort, HeartbeatRuntimeQualificationVerifier


def h(v): return hashlib.sha256(v.encode()).hexdigest()


def deployment() -> QualifiedDeploymentManifest:
    identity=ImmutableModelIdentity("planner","repo/model","rev","engine","1","bfloat16",None,4096)
    artifacts=ModelArtifactClosure(h("w"),h("t"),h("c")); runtime=RuntimeBuildIdentity(h("container"),h("engine"),h("lock"),"cuda","nccl","torch",h("ext"))
    stack=ModelStackSpec(identity,artifacts,runtime,1,1,1,1,None,None,None,None,"fcfs")
    cert=QualificationCertificate(stack.digest(),h("evidence"),("planner",),ResourceEnvelope(1,1,1,1,1,1),h("host"))
    return QualifiedDeploymentManifest("d1",stack,cert,DeploymentPlacement(("GPU-1",)),h("host"))


def frozen(ds):
    return frozen_runtime_manifest(prompt_generation_digest="pg", role_model_manifest_digest=ds.role_manifest_digest, qualified_deployment_digests=tuple(d.deployment_digest for d in ds.deployments), target_host_identity_digest=h("host"))


class RuntimeModelPortsV112Tests(unittest.TestCase):
    def test_deployment_verifier_is_read_only_and_exact(self):
        d=deployment(); ds=freeze_model_deployment_set(RoleModelManifest((RoleModelAssignment("planner","d1"),)),(d,)); m=frozen(ds)
        refs=FrozenDeploymentVerificationPort().verify(m,ds)
        self.assertTrue(any(ref.startswith("model-stack:d1:") for ref in refs))
        with self.assertRaises(ValueError):
            FrozenDeploymentVerificationPort().verify(replace(m,target_host_identity_digest=h("other")),ds)

    def test_live_qualification_receipt_is_durable_and_role_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d=deployment(); ds=freeze_model_deployment_set(RoleModelManifest((RoleModelAssignment("planner","d1"),)),(d,)); m=frozen(ds)
            heartbeats=FileServiceHeartbeatStore(root/"heartbeats")
            hb=ServiceHeartbeat("d1",d.stack.digest(),123,"start",h("argv"),True,d.certificate.digest(),time.time())
            heartbeats.write(hb)
            evidence=DirectoryRuntimeQualificationEvidenceStore(root/"qualification")
            port=HeartbeatRuntimeQualificationVerifier(heartbeats,RuntimeQualificationPublisher(evidence, (d,)),max_heartbeat_age_seconds=10)
            refs=port.verify(m,ds)
            self.assertTrue(any(ref.startswith("runtime-qualification:d1:") for ref in refs))
            receipt=evidence.load(m.digest(),"d1")
            self.assertEqual(receipt.qualified_roles,("planner",))
            self.assertEqual(receipt.qualification_certificate_digest,d.certificate.digest())

    def test_live_qualification_rejects_certificate_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); d=deployment(); ds=freeze_model_deployment_set(RoleModelManifest((RoleModelAssignment("planner","d1"),)),(d,)); m=frozen(ds)
            heartbeats=FileServiceHeartbeatStore(root/"heartbeats")
            heartbeats.write(ServiceHeartbeat("d1",d.stack.digest(),123,"start",h("argv"),True,h("wrong-cert"),time.time()))
            port=HeartbeatRuntimeQualificationVerifier(heartbeats,RuntimeQualificationPublisher(DirectoryRuntimeQualificationEvidenceStore(root/"q"), (d,)),max_heartbeat_age_seconds=10)
            with self.assertRaises(ValueError): port.verify(m,ds)


if __name__ == "__main__": unittest.main()
