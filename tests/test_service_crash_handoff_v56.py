from __future__ import annotations
from tests._concurrency_support import process_capture

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

from pathlib import Path
import hashlib
import tempfile
import unittest

from noetrium_platform.composition.service_crash import CrashHandoffPhase
from noetrium_platform.composition.service_crash import DurableCrashHandoffStore
from noetrium_platform.composition.service_crash import DurableServiceCrashCoordinator
from noetrium_platform.composition.service_crash_failure import service_crash_failure
from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from tests._concurrency_support import segmented_byte_capture
from noetrium_platform.infrastructure.reliability.primitives import CrashEvidence
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceSupervisor,
    ServicePhase,
)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def contract() -> ServiceLaunchContract:
    exe="/opt/rp/bin/python"
    return ServiceLaunchContract(
        "model.planner","g1",exe,(exe,"-m","model_server"),"/srv/rp",
        h("env"),h("artifact"),h("runtime"),120,60,10,
    )


def context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-v56",
        trace_id="trace-v56",
        span_id="span-v56",
        task_id="task-4",
        decision_cycle_id="dc-9",
        operation_id="op-model-crash",
        component_id="model.planner",
    )


class ProcessAdapter:
    def reconcile(self,state,c): return None,("reconcile",)
    def start(self,c): return ServiceProcessIdentity(880,"pid:880:start:11",880),("start",)
    def wait_ready(self,p,c): return ready_evidence(p,c,"ready","stdout.active","stderr.active")
    def stop(self,p,c): return ("stopped",)


class CrashAdapter:
    def __init__(self,root:Path):
        self.stdout=segmented_byte_capture(root/"out","stdout",tail_bytes=64)
        self.stderr=segmented_byte_capture(root/"err","stderr",tail_bytes=64)
        self.stdout.append(b"request rq-v56 started\n")
        self.stderr.append(b"CUDA out of memory in KV allocator\n")
    def inspect_crash(self,p,c): return CrashEvidence(exit_code=137,oom_killed=True)
    def captures(self,p,c): return self.stdout,self.stderr


class ServiceCrashHandoffV56Tests(unittest.TestCase):
    def _setup(self, root: Path):
        contract_ = contract()
        state_store=FileServiceStateStore(root/"service.json")
        supervisor=make_service_supervisor(state_store,ProcessAdapter())
        supervisor.start_exact(contract_)
        forensics=ForensicStore(root/"forensics")
        journal=DurableCrashHandoffStore(root/"crash_handoff.json")
        coordinator=DurableServiceCrashCoordinator(
            supervisor=supervisor,
            failures=forensics,
            journal=journal,
        )
        return contract_,state_store,supervisor,forensics,journal,coordinator

    def test_full_handoff_is_complete_and_failure_is_queryable_once(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            c,state_store,supervisor,forensics,journal,coordinator=self._setup(root)
            try:
                report=coordinator.handle(c,CrashAdapter(root/"capture"),context())
                self.assertEqual(report.handoff.phase,CrashHandoffPhase.COMPLETE)
                self.assertTrue(report.failure_appended)
                self.assertEqual(forensics.failures.verify()[0],1)
                state=state_store.read()
                self.assertEqual(state.phase,ServicePhase.RECOVERY_REQUIRED)
                self.assertEqual(state.last_failure_id,report.handoff.failure.failure_id)
                located=forensics.index.locate(report.handoff.failure.failure_id)
                self.assertEqual(located.to_payload()["failure_code"],"MODEL_SERVICE_OOM")
            finally:
                forensics.close()

    def test_crash_after_failure_append_before_journal_advance_replays_without_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            c,state_store,supervisor,forensics,journal,coordinator=self._setup(root)
            try:
                handoff=coordinator.prepare(c,CrashAdapter(root/"capture"),context())
                appended,_=forensics.append_failure_once(handoff.failure)
                self.assertTrue(appended)
                self.assertEqual(journal.read().phase,CrashHandoffPhase.PREPARED)

                resumed=coordinator.resume(c)
                self.assertFalse(resumed.failure_appended)
                self.assertEqual(resumed.handoff.phase,CrashHandoffPhase.COMPLETE)
                self.assertEqual(forensics.failures.verify()[0],1)
                self.assertEqual(state_store.read().last_failure_id,handoff.failure.failure_id)
            finally:
                forensics.close()

    def test_crash_after_state_commit_before_journal_advance_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            c,state_store,supervisor,forensics,journal,coordinator=self._setup(root)
            try:
                handoff=coordinator.prepare(c,CrashAdapter(root/"capture"),context())
                forensics.append_failure_once(handoff.failure)
                handoff=coordinator._advance(handoff,CrashHandoffPhase.FAILURE_DURABLE)

                supervisor.commit_handoff_transition(
                    c,
                    process=handoff.process,
                    exit_class=handoff.exit_class,
                    stdout_capture_ref=handoff.stdout_capture_ref,
                    stderr_capture_ref=handoff.stderr_capture_ref,
                    failure_id=handoff.failure.failure_id,
                )
                self.assertEqual(journal.read().phase,CrashHandoffPhase.FAILURE_DURABLE)
                self.assertEqual(state_store.read().phase,ServicePhase.RECOVERY_REQUIRED)

                resumed=coordinator.resume(c)
                self.assertEqual(resumed.handoff.phase,CrashHandoffPhase.COMPLETE)
                self.assertEqual(forensics.failures.verify()[0],1)
            finally:
                forensics.close()

    def test_journal_contract_drift_fails_before_any_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            c,state_store,supervisor,forensics,journal,coordinator=self._setup(root)
            try:
                coordinator.prepare(c,CrashAdapter(root/"capture"),context())
                exe="/opt/rp/bin/python"
                wrong=ServiceLaunchContract(
                    "model.planner","g2",exe,(exe,"-m","model_server"),"/srv/rp",
                    h("env"),h("artifact"),h("runtime"),120,60,10,
                )
                with self.assertRaises(RuntimeError):
                    coordinator.resume(wrong)
                self.assertEqual(forensics.failures.verify()[0],0)
                self.assertEqual(state_store.read().phase,ServicePhase.RUNNING)
            finally:
                forensics.close()


if __name__=="__main__":
    unittest.main()
