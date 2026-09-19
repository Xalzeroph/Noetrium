from __future__ import annotations
from tests._concurrency_support import process_capture

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

from pathlib import Path
import hashlib
import tempfile
import unittest

from noetrium_platform.infrastructure.reliability.failure.api import RecoveryAction

from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.forensics.composition.incident_adapter import ForensicIncidentProjection
from noetrium_platform.composition.service_crash_failure import service_crash_failure
from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from tests._concurrency_support import segmented_byte_capture
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import DebugSnapshotService
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import DebugSnapshotService, IncidentService
from noetrium_platform.infrastructure.reliability.primitives import CrashEvidence
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceSupervisor,
)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def contract() -> ServiceLaunchContract:
    exe="/opt/rp/bin/python"
    return ServiceLaunchContract(
        "model.planner","g1",exe,(exe,"-m","model_server"),"/srv/rp",
        h("env"),h("artifact"),h("runtime"),120,60,10,
    )


class ProcessAdapter:
    def reconcile(self,state,c): return None,("reconcile",)
    def start(self,c): return ServiceProcessIdentity(555,"pid:555:start:9",555),("start",)
    def wait_ready(self,p,c): return ready_evidence(p,c,"ready","stdout.active","stderr.active")
    def stop(self,p,c): return ("stopped",)


class CrashAdapter:
    def __init__(self,root:Path):
        self.stdout=segmented_byte_capture(root/"out","stdout",tail_bytes=64)
        self.stderr=segmented_byte_capture(root/"err","stderr",tail_bytes=64)
        self.stdout.append(b"request rq_9 running\n")
        self.stderr.append(b"CUDA out of memory allocating KV cache\n")
    def inspect_crash(self,p,c): return CrashEvidence(exit_code=137,oom_killed=True)
    def captures(self,p,c): return self.stdout,self.stderr


class ServiceCrashForensicsV55Tests(unittest.TestCase):
    def test_service_crash_becomes_queryable_failure_with_log_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            supervisor=make_service_supervisor(FileServiceStateStore(root/"service.json"),ProcessAdapter())
            supervisor.start_exact(contract())
            report=supervisor.prepare_unexpected_exit(contract(),CrashAdapter(root/"capture"))
            ctx=ExecutionContext(
                run_id="run-1",trace_id="trace-1",span_id="span-crash",
                task_id="task-4",decision_cycle_id="dc-7",
                operation_id="op-model-9",component_id="model.planner",
            )
            failure=service_crash_failure(report,ctx)

            self.assertEqual(failure.failure_domain,"MODEL_SERVING")
            self.assertEqual(failure.failure_code,"MODEL_SERVICE_OOM")
            self.assertEqual(failure.recommended_recovery,RecoveryAction.RESTART_EXACT_MODEL)
            self.assertTrue(any(x.startswith("capture-tail://stderr") for x in failure.output_artifacts))
            self.assertTrue(any("stderr.manifest.json" in x for x in failure.output_artifacts))

            with ForensicStore(root/"forensics") as store:
                store.append_failure(failure)
                snap=DebugSnapshotService(ForensicDiagnosticEvidence(store)).build(failure.failure_id)
                self.assertEqual(snap.object["failure_code"],"MODEL_SERVICE_OOM")
                self.assertEqual(snap.diagnosis.recovery,"restart_exact_model")
                self.assertIn("model.planner",snap.diagnosis.exact_location)

                incident=IncidentService(ForensicDiagnosticEvidence(store), ForensicIncidentProjection(store.failures, root/"incidents.sqlite3"), DebugSnapshotService(ForensicDiagnosticEvidence(store))).capture(failure.failure_id)
                self.assertEqual(incident.recovery,"restart_exact_model")
                self.assertFalse(incident.recurring)

    def test_clean_exit_cannot_be_misreported_as_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            supervisor=make_service_supervisor(FileServiceStateStore(root/"service.json"),ProcessAdapter())
            supervisor.start_exact(contract())

            class CleanCrash(CrashAdapter):
                def inspect_crash(self,p,c): return CrashEvidence(exit_code=0)

            report=supervisor.prepare_unexpected_exit(contract(),CleanCrash(root/"capture"))
            ctx=ExecutionContext("run","trace","span")
            with self.assertRaises(ValueError):
                service_crash_failure(report,ctx)


if __name__=="__main__":
    unittest.main()
