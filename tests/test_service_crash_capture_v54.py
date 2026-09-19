from __future__ import annotations
from tests._concurrency_support import process_capture

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceContractDrift, ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

from pathlib import Path
import hashlib
import tempfile
import unittest

from tests._concurrency_support import segmented_byte_capture
from noetrium_platform.infrastructure.reliability.primitives import CrashClass, CrashEvidence
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime.service_state_contracts import ServiceSupervisorState
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceSupervisor,
    ServiceExitClass,
    ServicePhase,
)


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def contract(generation: str = "g1") -> ServiceLaunchContract:
    exe = "/opt/rp/bin/python"
    return ServiceLaunchContract(
        "model.planner",
        generation,
        exe,
        (exe, "-m", "model_server"),
        "/srv/rp",
        h("env"),
        h("artifact"),
        h("runtime"),
        120,
        60,
        10,
    )


class ProcessAdapter:
    def reconcile(self, state, contract):
        return None, ("reconcile",)

    def start(self, contract):
        return ServiceProcessIdentity(123, "pid:123:start:7", 123), ("start",)

    def wait_ready(self, process, contract):
        return ready_evidence(process, contract, "ready.json", "stdout.active", "stderr.active")

    def stop(self, process, contract):
        return ("stopped",)


class CrashAdapter:
    def __init__(self, root: Path, evidence: CrashEvidence):
        self.inspect_calls = 0
        self.capture_calls = 0
        self.evidence = evidence
        self.stdout = segmented_byte_capture(root / "stdout", "stdout", max_segment_bytes=64, fsync_every_bytes=64, tail_bytes=32)
        self.stderr = segmented_byte_capture(root / "stderr", "stderr", max_segment_bytes=64, fsync_every_bytes=64, tail_bytes=32)
        self.stdout.append(b"planner boot\nready\n")
        self.stderr.append(b"cuda allocator: out of memory\n")

    def inspect_crash(self, process, contract):
        self.inspect_calls += 1
        return self.evidence

    def captures(self, process, contract):
        self.capture_calls += 1
        return self.stdout, self.stderr


class ServiceCrashCaptureV54Tests(unittest.TestCase):
    def test_oom_exit_freezes_logs_and_requires_exact_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = FileServiceStateStore(root / "state.json")
            supervisor = make_service_supervisor(store, ProcessAdapter())
            supervisor.start_exact(contract())
            crash = CrashAdapter(root / "capture", CrashEvidence(exit_code=137, oom_killed=True))

            report = supervisor.prepare_unexpected_exit(contract(), crash)
            supervisor.commit_handoff_transition(
                contract(),
                process=report.process,
                exit_class=report.exit_class,
                stdout_capture_ref=report.capture.stdout_manifest_ref,
                stderr_capture_ref=report.capture.stderr_manifest_ref,
                failure_id="failure-test",
            )
            state = store.read()

            self.assertEqual(report.diagnosis.crash_class, CrashClass.OUT_OF_MEMORY)
            self.assertTrue(report.diagnosis.exact_recovery_required)
            self.assertEqual(report.exit_class, ServiceExitClass.TEMPORARY)
            self.assertEqual(state.phase, ServicePhase.RECOVERY_REQUIRED)
            self.assertIsNone(state.process)
            self.assertEqual(crash.inspect_calls, 1)
            self.assertEqual(crash.capture_calls, 1)
            self.assertTrue(report.capture.stdout_manifest.sealed)
            self.assertTrue(report.capture.stderr_manifest.sealed)
            self.assertEqual(len(report.capture.stdout_tail.sha256), 64)
            self.assertEqual(len(report.capture.stderr_tail.sha256), 64)
            self.assertTrue(Path(report.capture.stdout_manifest_ref).exists())
            self.assertTrue(Path(report.capture.stderr_manifest_ref).exists())

    def test_non_clean_handoff_cannot_commit_without_failure_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = FileServiceStateStore(root / "state.json")
            supervisor = make_service_supervisor(store, ProcessAdapter())
            supervisor.start_exact(contract())
            crash = CrashAdapter(root / "capture", CrashEvidence(exit_code=137, oom_killed=True))
            report = supervisor.prepare_unexpected_exit(contract(), crash)
            with self.assertRaisesRegex(RuntimeError, "durable failure identity"):
                supervisor.commit_handoff_transition(
                    contract(),
                    process=report.process,
                    exit_class=report.exit_class,
                    stdout_capture_ref=report.capture.stdout_manifest_ref,
                    stderr_capture_ref=report.capture.stderr_manifest_ref,
                )
            self.assertEqual(store.read().phase, ServicePhase.RUNNING)

    def test_clean_exit_is_not_promoted_to_recovery_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = FileServiceStateStore(root / "state.json")
            supervisor = make_service_supervisor(store, ProcessAdapter())
            supervisor.start_exact(contract())
            crash = CrashAdapter(root / "capture", CrashEvidence(exit_code=0))

            report = supervisor.prepare_unexpected_exit(contract(), crash)
            supervisor.commit_clean_exit(contract(), report)
            self.assertEqual(report.diagnosis.crash_class, CrashClass.CLEAN_EXIT)
            self.assertFalse(report.diagnosis.exact_recovery_required)
            self.assertEqual(report.exit_class, ServiceExitClass.CLEAN)
            self.assertEqual(store.read().phase, ServicePhase.EXITED)

    def test_contract_drift_fails_before_crash_evidence_is_touched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = FileServiceStateStore(root / "state.json")
            supervisor = make_service_supervisor(store, ProcessAdapter())
            supervisor.start_exact(contract("g1"))
            crash = CrashAdapter(root / "capture", CrashEvidence(exit_code=1))

            with self.assertRaises(ServiceContractDrift):
                supervisor.prepare_unexpected_exit(contract("g2"), crash)

            self.assertEqual(crash.inspect_calls, 0)
            self.assertEqual(crash.capture_calls, 0)
            crash.stdout.close()
            crash.stderr.close()

    def test_missing_persisted_process_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = FileServiceStateStore(root / "state.json")
            initial = ServiceSupervisorState.initial("model.planner", contract().digest())
            store.write(initial)
            supervisor = make_service_supervisor(store, ProcessAdapter())
            crash = CrashAdapter(root / "capture", CrashEvidence(exit_code=1))
            with self.assertRaises(RuntimeError):
                supervisor.prepare_unexpected_exit(contract(), crash)
            self.assertEqual(crash.inspect_calls, 0)
            crash.stdout.close()
            crash.stderr.close()


if __name__ == "__main__":
    unittest.main()
