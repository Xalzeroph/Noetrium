from __future__ import annotations
from runtime_manager_test_support import make_runtime_control_store, runtime_history_path
from pathlib import Path
import tempfile, time, unittest

from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat_storage import FileServiceHeartbeatStore
from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat import assert_exact_heartbeat
from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeControlStore, ServiceHeartbeat
from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLeaseBusy
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.reliability.primitives import CrashClass, CrashEvidence, classify_crash

class RuntimeOperabilityV31Tests(unittest.TestCase):
    def test_runtime_state_writes_always_append_hash_chained_history(self):
        with tempfile.TemporaryDirectory() as td:
            state_path=Path(td)/"runtime.json"
            history_path=runtime_history_path(state_path)
            store=make_runtime_control_store(state_path)
            s=store.create("ctl","manifest")
            self.assertEqual(store.history.verify(),())
            store.write(s)
            self.assertEqual(store.history.verify(),())
            lines=history_path.read_text().splitlines(); self.assertEqual(len(lines),2)
            history_path.write_text(lines[0]+"\n"+lines[1].replace('"planned"','"running"')+"\n")
            self.assertTrue(store.history.verify())

    def test_service_heartbeat_is_bound_to_exact_stack_and_qualification(self):
        with tempfile.TemporaryDirectory() as td:
            store=FileServiceHeartbeatStore(Path(td))
            hb=ServiceHeartbeat("d1","stack",123,"start","argv",True,"qual",time.time())
            store.write(hb); self.assertEqual(assert_exact_heartbeat(store.read("d1"), deployment_id="d1", stack_digest="stack", max_age_seconds=5).pid,123)
            with self.assertRaises(RuntimeError): assert_exact_heartbeat(store.read("d1"), deployment_id="d1", stack_digest="other", max_age_seconds=5)

    def test_recovery_lease_prevents_concurrent_operator_resume(self):
        with tempfile.TemporaryDirectory() as td:
            s=recovery_lease_state(Path(td)/"lease.json")
            s.acquire("op1","m",ttl_seconds=10,now=1)
            with self.assertRaises(RecoveryLeaseBusy): s.acquire("op2","m",ttl_seconds=10,now=2)
            s.release("op1","m")
            self.assertEqual(s.acquire("op2","m",ttl_seconds=10,now=3).owner_id,"op2")

    def test_crash_classification_keeps_root_evidence_distinct(self):
        self.assertEqual(classify_crash(CrashEvidence(oom_killed=True)).crash_class,CrashClass.OUT_OF_MEMORY)
        self.assertEqual(classify_crash(CrashEvidence(gpu_xid=79)).crash_class,CrashClass.GPU_DRIVER)
        self.assertEqual(classify_crash(CrashEvidence(heartbeat_stale=True)).crash_class,CrashClass.HEARTBEAT_LOSS)
        self.assertFalse(classify_crash(CrashEvidence(exit_code=0)).exact_recovery_required)

if __name__=="__main__": unittest.main()
