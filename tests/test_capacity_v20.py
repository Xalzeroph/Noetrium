import hashlib
import unittest

from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving import QualificationCertificate, ResourceEnvelope
from noetrium_platform.capabilities.model.stack import ModelArtifactClosure, RuntimeBuildIdentity, ModelStackSpec
from noetrium_platform.capabilities.model.serving.runtime.capacity import DeploymentRequirements, ExactCapacityPlanner, HostQualificationMismatch, PlacementCapacityError
from noetrium_platform.capabilities.model.serving.api.inventory import CPUInventory, CPUNode, GPUFabricLink, GPUInventory, HostLimits, MemoryInventory, MountInventory, RuntimeInventory, HostInventory


def stack_parts():
    h=lambda x: hashlib.sha256(x.encode()).hexdigest()
    return (
        ModelArtifactClosure(h("weights"),h("tokenizer"),h("config"),h("model-code"),h("chat-template")),
        RuntimeBuildIdentity(h("container"),h("engine-build"),h("python-lock"),"cuda-12.8","nccl-2.27","torch-2.8",h("kernels")),
    )

G=1024**3

def host(port=(),free0=70*G,free1=70*G,driver="590"):
    return HostInventory(
        "srv",1.0,
        CPUInventory("x86_64",32,tuple(range(32)),None,(CPUNode(0,tuple(range(16)),128*G),CPUNode(1,tuple(range(16,32)),128*G))),
        MemoryInventory(256*G,200*G,220*G,20*G),
        (GPUInventory("g0","H100",80*G,free0,"0000:01:00.0",0,"9.0",700),GPUInventory("g1","H100",80*G,free1,"0000:02:00.0",0,"9.0",700),GPUInventory("g2","H100",80*G,70*G,"0000:81:00.0",1,"9.0",700)),
        (GPUFabricLink("g0","g1","NVLink",900),GPUFabricLink("g0","g2","PCIe",64),GPUFabricLink("g1","g2","PCIe",64)),
        (MountInventory("/srv","xfs","dev1",4*1024**4,3*1024**4,1000000,True),),
        RuntimeInventory("6.8","3.12","24","21",driver,"13.0","13","0.5.13",None),HostLimits(1048576,1048576,100000),tuple(port))

def stack():
    ident=ImmutableModelIdentity("planner","org/model","rev","sglang","0.5.13","bfloat16",None,262144,"tokrev")
    return ModelStackSpec(ident,*stack_parts(),2,1,1,1,None,None,None,None,"fcfs",())

def cert(h,st):
    env=ResourceEnvelope(60*G,100*G,12,.5,.05,80)
    return QualificationCertificate(st.digest(),hashlib.sha256(b"evidence").hexdigest(),("planner",),env,h.identity_digest())

class CapacityV20Tests(unittest.TestCase):
    def test_identity_and_live_snapshot_are_separate(self):
        a=host(); transient=host(port=(8000,)); runtime_drift=host(driver="591")
        self.assertEqual(a.identity_digest(),transient.identity_digest())
        self.assertNotEqual(a.snapshot_digest(),transient.snapshot_digest())
        self.assertNotEqual(a.identity_digest(),runtime_drift.identity_digest())

    def test_planner_prefers_nvlink_and_local_numa(self):
        h=host(); st=stack(); plan=ExactCapacityPlanner().plan(h,st,cert(h,st),DeploymentRequirements("d",8000,"/srv/models"))
        self.assertEqual(set(plan.gpu_uuids),{"g0","g1"}); self.assertEqual(plan.numa_nodes,(0,)); self.assertEqual(plan.cpu_ids,tuple(range(16))); self.assertEqual(plan.max_admitted_concurrency,12)

    def test_host_runtime_identity_mismatch_is_not_requalified_silently(self):
        h=host(); other=host(driver="591"); st=stack()
        with self.assertRaises(HostQualificationMismatch): ExactCapacityPlanner().plan(other,st,cert(h,st),DeploymentRequirements("d",8000,"/srv/models"))

    def test_unrelated_transient_port_does_not_invalidate_host_qualification(self):
        h=host(); transient=host(port=(9,)); st=stack()
        plan=ExactCapacityPlanner().plan(transient,st,cert(h,st),DeploymentRequirements("d",8000,"/srv/models"))
        self.assertEqual(plan.host_identity_digest,h.identity_digest())
        self.assertEqual(plan.host_snapshot_digest,transient.snapshot_digest())

    def test_insufficient_vram_does_not_change_stack(self):
        h=host(free0=61*G,free1=61*G); st=stack(); c=cert(h,st)
        with self.assertRaises(PlacementCapacityError): ExactCapacityPlanner().plan(h,st,c,DeploymentRequirements("d",8000,"/srv/models",gpu_memory_headroom_bytes=2*G))
        self.assertEqual(st.tensor_parallel,2); self.assertEqual(st.identity.dtype,"bfloat16")

    def test_port_conflict_fails_explicitly(self):
        h=host(port=(8000,)); st=stack()
        with self.assertRaises(PlacementCapacityError): ExactCapacityPlanner().plan(h,st,cert(h,st),DeploymentRequirements("d",8000,"/srv/models"))

if __name__=='__main__': unittest.main()
