from __future__ import annotations
from tests._concurrency_support import process_capture

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

from pathlib import Path
import tempfile
import unittest

from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.composition.service_crash_failure import service_crash_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from tests._concurrency_support import segmented_byte_capture
from noetrium_platform.infrastructure.reliability.primitives import CrashEvidence
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceSupervisor,
)
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import FailureDiagnosisService
import hashlib


def h(x): return hashlib.sha256(x.encode()).hexdigest()

def contract():
    exe="/opt/rp/bin/python"
    return ServiceLaunchContract("model.planner","g1",exe,(exe,"-m","server"),"/srv",h("e"),h("a"),h("r"),120,60,10)

class Proc:
    def reconcile(self,s,c): return None,("reconcile",)
    def start(self,c): return ServiceProcessIdentity(7,"pid:7:start:1",7),("start",)
    def wait_ready(self,p,c): return ready_evidence(p,c,"ready","out","err")
    def stop(self,p,c): return ()

class Crash:
    def __init__(self,root):
        self.out=segmented_byte_capture(root/"o","stdout"); self.err=segmented_byte_capture(root/"e","stderr")
        self.err.append(b"CUDA out of memory")
    def inspect_crash(self,p,c): return CrashEvidence(exit_code=137,oom_killed=True)
    def captures(self,p,c): return self.out,self.err

class FailureDiagnosisTaxonomyV85Tests(unittest.TestCase):
    def test_why_includes_registered_taxonomy_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); c=contract(); sup=make_service_supervisor(FileServiceStateStore(root/"service.json"),Proc()); sup.start_exact(c)
            report=sup.prepare_unexpected_exit(c,Crash(root/"capture"))
            ctx=ExecutionContext("run","trace","span",operation_id="op",component_id="model.planner")
            failure=service_crash_failure(report,ctx)
            with ForensicStore(root/"forensics") as store:
                store.append_failure(failure)
                diag=FailureDiagnosisService(ForensicDiagnosticEvidence(store)).why(failure.failure_id)
                self.assertTrue(diag.taxonomy["registered"])
                self.assertEqual(diag.taxonomy["default_recovery"],"restart_exact_model")
                self.assertEqual(diag.taxonomy["comparability_risk"],"medium")
                self.assertTrue(any("failure-catalog" in x for x in diag.next_commands))

    def test_unregistered_failure_is_explicit_not_silently_reinterpreted(self):
        with tempfile.TemporaryDirectory() as td:
            from noetrium_platform.infrastructure.reliability.failure.api import build_failure
            root=Path(td); ctx=ExecutionContext("run","trace","span")
            f=build_failure(component_id="x",failure_domain="UNKNOWN",failure_code="X",stage="s",context=ctx,exc=RuntimeError("x"))
            with ForensicStore(root) as store:
                store.append_failure(f)
                diag=FailureDiagnosisService(ForensicDiagnosticEvidence(store)).why(f.failure_id)
                self.assertFalse(diag.taxonomy["registered"])
                self.assertEqual(diag.taxonomy["code"],"X")

if __name__=="__main__": unittest.main()
