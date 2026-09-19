from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceSupervisor,
    PreparedServiceStartReconcileResult,
    PreparedServiceStartStatus,
    ServicePhase,
    ServiceStartRecoveryHandle,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def contract() -> ServiceLaunchContract:
    return ServiceLaunchContract(
        "model.meta",
        "g1",
        "/bin/echo",
        ("/bin/echo", "meta"),
        "/tmp",
        h("env"),
        h("artifact"),
        h("runtime"),
        5.0,
        5.0,
        1.0,
    )


class SimulatedCrashAfterStart(RuntimeError):
    pass


class DurableAdapter:
    start_recovery_durability = "crash_durable"

    def __init__(self, provider_state: dict[str, object], *, crash_on_start: bool = False) -> None:
        self.provider_state = provider_state
        self.crash_on_start = crash_on_start
        self.start_prepared_calls = 0
        self.normal_start_calls = 0

    def reconcile(self, state, launch):
        process = state.process
        if process is None:
            return None, ()
        live = self.provider_state.get("process")
        return (process, ("exact-process",)) if live == process else (None, ("missing-process",))

    def start(self, launch):
        self.normal_start_calls += 1
        raise AssertionError("crash-durable adapter must not use legacy start")

    def wait_ready(self, process, launch):
        return ready_evidence(process, launch, "ready:provider", "stdout:provider", "stderr:provider")

    def stop(self, process, launch):
        self.provider_state.pop("process", None)
        return ("stopped",)

    def prepare_start_recovery(self, launch, *, intent_id: str, attempt: int):
        payload = f"provider-start:{intent_id}:{attempt}".encode()
        handle = ServiceStartRecoveryHandle.from_payload("fake-provider.v1", payload)
        self.provider_state["handle"] = handle
        return handle

    def start_prepared(self, launch, handle):
        self.start_prepared_calls += 1
        self.assert_handle(handle)
        process = ServiceProcessIdentity(501, "provider-start:501", 501)
        self.provider_state["process"] = process
        if self.crash_on_start:
            raise SimulatedCrashAfterStart("process started; caller died before receipt")
        return process, ("provider-started",)

    def reconcile_prepared_start(self, launch, handle):
        self.assert_handle(handle)
        process = self.provider_state.get("process")
        if process is None:
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.NOT_STARTED,
                None,
                ("provider:not-started",),
            )
        return PreparedServiceStartReconcileResult(
            PreparedServiceStartStatus.PROCESS_CONFIRMED,
            process,
            ("provider:confirmed",),
        )

    def assert_handle(self, handle):
        expected = self.provider_state.get("handle")
        if expected is not None and expected != handle:
            raise AssertionError("provider recovery handle drift")


class LegacyCrashAdapter:
    def __init__(self) -> None:
        self.start_calls = 0

    def reconcile(self, state, launch):
        return state.process, ()

    def start(self, launch):
        self.start_calls += 1
        raise SimulatedCrashAfterStart("legacy start outcome unknown")

    def wait_ready(self, process, launch):
        return ready_evidence(process, launch)

    def stop(self, process, launch):
        return ()


class ServicePreparedStartRecoveryV146Tests(unittest.TestCase):
    def test_crash_after_provider_start_is_reconciled_without_second_start(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            state_store = FileServiceStateStore(root / "service.json")
            provider: dict[str, object] = {}
            first = DurableAdapter(provider, crash_on_start=True)
            with self.assertRaises(SimulatedCrashAfterStart):
                make_service_supervisor(state_store, first).start_exact(contract())
            self.assertEqual(first.start_prepared_calls, 1)
            self.assertEqual(state_store.read().phase, ServicePhase.START_CHILD)

            journal_store = DirectoryServiceStartIntentStore(
                Path(state_store.reference()).with_name(Path(state_store.reference()).name + ".start-intents")
            )
            unresolved = journal_store.unresolved(contract().service_id, contract().digest())
            self.assertEqual(len(unresolved), 1)
            self.assertEqual(unresolved[0].phase.value, "prepared")
            self.assertIsNotNone(unresolved[0].recovery_handle)

            second = DurableAdapter(provider)
            report = make_service_supervisor(state_store, second).start_exact(contract())
            self.assertEqual(second.start_prepared_calls, 0)
            self.assertEqual(second.normal_start_calls, 0)
            self.assertEqual(report.state.phase, ServicePhase.RUNNING)
            self.assertEqual(report.state.process, provider["process"])
            self.assertEqual(
                journal_store.unresolved(contract().service_id, contract().digest()), ()
            )
            all_intents = journal_store.all()
            self.assertEqual(len(all_intents), 1)
            self.assertEqual(all_intents[0].phase.value, "complete")
            self.assertTrue(any(ref == "provider:confirmed" for ref in report.evidence_refs))

    def test_legacy_start_crash_is_fail_closed_and_never_replayed(self) -> None:
        with TemporaryDirectory() as td:
            state_store = FileServiceStateStore(Path(td) / "service.json")
            first = LegacyCrashAdapter()
            with self.assertRaises(SimulatedCrashAfterStart):
                make_service_supervisor(state_store, first).start_exact(contract())
            self.assertEqual(first.start_calls, 1)

            second = LegacyCrashAdapter()
            from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceStartRecoveryRequired

            with self.assertRaises(ServiceStartRecoveryRequired):
                make_service_supervisor(state_store, second).start_exact(contract())
            self.assertEqual(second.start_calls, 0)

    def test_recovery_handle_repr_never_exposes_opaque_payload(self) -> None:
        handle = ServiceStartRecoveryHandle.from_payload("provider.v1", b"top-secret-token")
        self.assertNotIn("top-secret-token", repr(handle))
        self.assertIn(handle.payload_sha256, repr(handle))


if __name__ == "__main__":
    unittest.main()
