from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from tests_support import frozen_runtime_manifest

from pathlib import Path
from dataclasses import FrozenInstanceError
import tempfile
import unittest
import hashlib

from noetrium_platform.composition.model_deployments import freeze_model_deployment_set
from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api.qualified_deployment import (
    QualificationCertificate, QualifiedDeploymentManifest, ResourceEnvelope,
    RoleModelAssignment, RoleModelManifest,
)
from noetrium_platform.capabilities.model.serving.api.placement import DeploymentPlacement
from noetrium_platform.capabilities.model.serving.api.inventory import (
    CPUInventory, CPUNode, GPUInventory, HostLimits, MemoryInventory, MountInventory, RuntimeInventory, HostInventory,
)
from noetrium_platform.capabilities.model.serving.providers.host_verification_storage import DirectoryHostInventoryEvidenceStore
from noetrium_platform.composition.host_runtime_verification import HostInventoryRuntimeVerification
from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure, RuntimeBuildIdentity, ModelStackSpec
from noetrium_platform.capabilities.model.serving.api import FrozenDeploymentSet
from noetrium_platform.capabilities.model.serving.api.host_verification import build_host_inventory_receipt
from noetrium_platform.foundation.kernel.kernel.durability import decode_checksummed_document, encode_checksummed_document
from noetrium_platform.infrastructure.lifecycle.launch_control import (
    ExactRuntimeController, RuntimeAction,
    RuntimeControlStore, RuntimePlatformAuthorities, ServerRuntimeAdapter, ServerRuntimeControlPlane,
)


def runtime_host() -> HostInventory:
    G=1024**3
    return HostInventory(
        "srv",1.0,
        CPUInventory("x86_64",16,tuple(range(16)),None,(CPUNode(0,tuple(range(16)),128*G),)),
        MemoryInventory(128*G,100*G,None,None),
        (
            GPUInventory("GPU-1","H100",80*G,70*G,"0000:01:00.0",0,"9.0",700),
            GPUInventory("GPU-2","H100",80*G,70*G,"0000:02:00.0",0,"9.0",700),
        ),
        (),
        (MountInventory("/srv","xfs","dev",1<<40,1<<39,100000,True),),
        RuntimeInventory("6.8","3.12",None,None,"590","13.0","13","0.5.13",None),
        HostLimits(1048576,1048576,100000),
        (),
    )

HOST_ID=runtime_host().identity_digest()

class StaticHostProvider:
    def __init__(self): self.calls=0
    def capture(self): self.calls+=1; return runtime_host()

def runtime_adapter(authorities, ds, root: Path):
    provider=StaticHostProvider()
    host_verification=HostInventoryRuntimeVerification(provider,DirectoryHostInventoryEvidenceStore(root/"host-evidence"))
    adapter=ServerRuntimeAdapter(authorities,ds,host_verification)
    return adapter,provider


def identity(name: str) -> ImmutableModelIdentity:
    return ImmutableModelIdentity(name, f"repo/{name}", "rev", "sglang", "1", "bfloat16", None, 32768)


def deployment(dep: str, gpu: str) -> QualifiedDeploymentManifest:
    ident = identity(dep)
    stack = ModelStackSpec(ident, *stack_parts(), 1, 1, 1, 1, None, None, None, None, "fcfs")
    env = ResourceEnvelope(1, 1, 1, 0.1, 0.1, 1.0)
    cert = QualificationCertificate(stack.digest(), "evidence", ("planner",), env, HOST_ID)
    placement = DeploymentPlacement((gpu,))
    return QualifiedDeploymentManifest(dep, stack, cert, placement, HOST_ID)


def manifest(ds: FrozenDeploymentSet):
    return frozen_runtime_manifest(release_digest="release", prompt_generation_digest="pg", prompt_promotion_digest="pp", role_model_manifest_digest=ds.role_manifest_digest, qualified_deployment_digests=tuple(d.deployment_digest for d in ds.deployments), target_host_identity_digest=HOST_ID)



def stack_parts():
    h=lambda x: hashlib.sha256(x.encode()).hexdigest()
    return (
        ModelArtifactClosure(h("weights"),h("tokenizer"),h("config"),h("model-code"),h("chat-template")),
        RuntimeBuildIdentity(h("container"),h("engine-build"),h("python-lock"),"cuda-12.8","nccl-2.27","torch-2.8",h("kernels")),
    )

class CallRecorder:
    def __init__(self, fail: RuntimeAction | None = None): self.calls=[]; self.fail=fail
    def call(self, action):
        self.calls.append(action)
        if action == self.fail: raise RuntimeError("injected")
        return (f"proof:{action.value}",)

class UnaryAuthority:
    def __init__(self, recorder, action): self.recorder=recorder; self.action=action
    def verify(self, manifest): return self.recorder.call(self.action)

class BinaryAuthority:
    def __init__(self, recorder, action): self.recorder=recorder; self.action=action
    def verify(self, manifest, deployments): return self.recorder.call(self.action)

class ServiceAuthority:
    def __init__(self, recorder): self.recorder=recorder
    def reconcile(self,m,d): return self.recorder.call(RuntimeAction.RECONCILE_SERVICES)
    def start_exact(self,m,d): return self.recorder.call(RuntimeAction.START_EXACT_SERVICES)
    def verify_ready(self,m,d): return self.recorder.call(RuntimeAction.VERIFY_SERVICES_READY)
    def final_status(self,m,d): return self.recorder.call(RuntimeAction.FINAL_STATUS)

class StudyAuthority:
    def __init__(self, recorder): self.recorder=recorder
    def reconcile(self,m): return self.recorder.call(RuntimeAction.RECONCILE_RUN)
    def start_exact(self,m): return self.recorder.call(RuntimeAction.START_EXACT_RUN)
    def final_status(self,m): return ("proof:run-final",)

def authorities(recorder):
    return RuntimePlatformAuthorities(
        UnaryAuthority(recorder,RuntimeAction.VERIFY_RELEASE),
        UnaryAuthority(recorder,RuntimeAction.VERIFY_PROMPT_PROMOTION),
        BinaryAuthority(recorder,RuntimeAction.VERIFY_DEPLOYMENTS),
        ServiceAuthority(recorder),
        BinaryAuthority(recorder,RuntimeAction.VERIFY_RUNTIME_QUALIFICATION),
        UnaryAuthority(recorder,RuntimeAction.VERIFY_PARTICIPANT_IMPLEMENTATIONS),
        UnaryAuthority(recorder,RuntimeAction.VERIFY_PARTICIPANT_RUNTIMES),
        UnaryAuthority(recorder,RuntimeAction.VERIFY_PARTICIPANT_BINDINGS),
        StudyAuthority(recorder),
    )



class ServerRuntimeControlV29Tests(unittest.TestCase):
    def setUp(self):
        self.d1=deployment("d1","GPU-1")
        self.d2=deployment("d2","GPU-2")
        self.roles=RoleModelManifest((RoleModelAssignment("planner","d1"),RoleModelAssignment("meta","d2")))
        self.ds=freeze_model_deployment_set(self.roles,(self.d1,self.d2))

    def test_gpu_overlap_across_independent_deployments_is_forbidden(self):
        with self.assertRaises(ValueError):
            freeze_model_deployment_set(self.roles,(self.d1,deployment("d2","GPU-1")))

    def test_unknown_role_deployment_is_forbidden(self):
        roles=RoleModelManifest((RoleModelAssignment("planner","missing"),))
        with self.assertRaises(ValueError): freeze_model_deployment_set(roles,(self.d1,))

    def test_exact_server_control_runs_full_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            recorder=CallRecorder(); adapter,provider=runtime_adapter(authorities(recorder),self.ds,Path(td))
            ctl=ExactRuntimeController(make_runtime_control_store(Path(td)/"runtime.json"),adapter)
            report=ServerRuntimeControlPlane(ctl,adapter).run_exact(manifest(self.ds),control_id="ctl")
            self.assertEqual(len(recorder.calls),13); self.assertEqual(provider.calls,2)
            self.assertEqual(report.executed_actions[-1],RuntimeAction.FINAL_STATUS)

    def test_manifest_deployment_drift_fails_before_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            from dataclasses import replace
            recorder=CallRecorder(); adapter,provider=runtime_adapter(authorities(recorder),self.ds,Path(td))
            ctl=ExactRuntimeController(make_runtime_control_store(Path(td)/"runtime.json"),adapter)
            with self.assertRaises(ValueError):
                ServerRuntimeControlPlane(ctl,adapter).run_exact(replace(manifest(self.ds),qualified_deployment_digests=("bad",)),control_id="ctl")
            self.assertEqual(recorder.calls,[])

    def test_role_manifest_drift_fails_before_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            recorder=CallRecorder(); adapter,provider=runtime_adapter(authorities(recorder),self.ds,Path(td))
            ctl=ExactRuntimeController(make_runtime_control_store(Path(td)/"runtime.json"),adapter)
            m=manifest(self.ds)
            from dataclasses import replace
            with self.assertRaises(ValueError):
                ServerRuntimeControlPlane(ctl,adapter).run_exact(replace(m,role_model_manifest_digest="bad"),control_id="ctl")
            self.assertEqual(recorder.calls,[])




class HostInventoryEvidenceAuthorityV29Tests(unittest.TestCase):
    def test_manifest_rebinding_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "host-evidence"
            store = DirectoryHostInventoryEvidenceStore(root)
            receipt = build_host_inventory_receipt(HOST_ID, runtime_host(), phase="pre_start")
            source = Path(store.publish("a" * 64, receipt))
            rebound = root / f"{'b' * 64}.pre_start.host-inventory.json"
            rebound.write_bytes(source.read_bytes())

            with self.assertRaisesRegex(ValueError, "runtime manifest binding mismatch"):
                store.load("b" * 64, "pre_start")

    def test_checksum_valid_malformed_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = DirectoryHostInventoryEvidenceStore(Path(td) / "host-evidence")
            receipt = build_host_inventory_receipt(HOST_ID, runtime_host(), phase="pre_start")
            path = Path(store.publish("c" * 64, receipt))
            document = decode_checksummed_document(
                path.read_bytes(), expected_schema="host-inventory-evidence.v2"
            )
            payload = dict(document.payload)
            malformed = dict(payload["receipt"])
            malformed["schema_version"] = 2
            payload["receipt"] = malformed
            path.write_bytes(
                encode_checksummed_document("host-inventory-evidence.v2", payload)
            )

            with self.assertRaisesRegex(ValueError, "schema_version must equal 1"):
                store.load("c" * 64, "pre_start")

    def test_published_identity_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            from dataclasses import replace

            store = DirectoryHostInventoryEvidenceStore(Path(td) / "host-evidence")
            first = build_host_inventory_receipt(HOST_ID, runtime_host(), phase="pre_start")
            later_inventory = replace(runtime_host(), captured_at_unix=2.0)
            second = build_host_inventory_receipt(HOST_ID, later_inventory, phase="pre_start")
            store.publish("d" * 64, first)

            with self.assertRaisesRegex(ValueError, "already exists with different content"):
                store.publish("d" * 64, second)

    def test_phase_path_injection_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = DirectoryHostInventoryEvidenceStore(Path(td) / "host-evidence")
            with self.assertRaisesRegex(ValueError, "stable token"):
                store.load("e" * 64, "../pre_start")

    def test_runtime_snapshot_is_typed_and_deeply_immutable(self):
        receipt = build_host_inventory_receipt(HOST_ID, runtime_host(), phase="pre_start")
        self.assertIs(type(receipt.runtime), RuntimeInventory)
        with self.assertRaises(FrozenInstanceError):
            receipt.runtime.kernel = "tampered"  # type: ignore[misc]

        with tempfile.TemporaryDirectory() as td:
            store = DirectoryHostInventoryEvidenceStore(Path(td) / "host-evidence")
            store.publish("f" * 64, receipt)
            loaded = store.load("f" * 64, "pre_start")
            self.assertIs(type(loaded.runtime), RuntimeInventory)
            with self.assertRaises(FrozenInstanceError):
                loaded.runtime.python = "tampered"  # type: ignore[misc]


if __name__ == "__main__": unittest.main()
