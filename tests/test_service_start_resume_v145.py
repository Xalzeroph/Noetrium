from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from service_os_test_support import make_service_supervisor, ready_evidence

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ExactServiceSupervisor,
    ServicePhase,
    ServiceStartRecoveryRequired,
    ServiceSupervisorState,
)


def contract() -> ServiceLaunchContract:
    digest = "a" * 64
    return ServiceLaunchContract(
        "model.planner",
        "g1",
        "/bin/echo",
        ("/bin/echo", "ok"),
        "/tmp",
        digest,
        digest,
        digest,
        5.0,
        5.0,
        1.0,
    )


class Adapter:
    def __init__(self) -> None:
        self.start_calls = 0
        self.reconcile_calls = 0

    def reconcile(self, state, launch):
        self.reconcile_calls += 1
        return state.process, ()

    def start(self, launch):
        self.start_calls += 1
        return ServiceProcessIdentity(11, "start:11", 11), ()

    def wait_ready(self, process, launch):
        return ready_evidence(process, launch)

    def stop(self, process, launch):
        return ()


class ServiceStartResumeV145Tests(unittest.TestCase):
    def test_start_child_without_process_identity_is_never_replayed(self) -> None:
        with TemporaryDirectory() as td:
            launch = contract()
            store = FileServiceStateStore(Path(td) / "service.json")
            state = replace(
                ServiceSupervisorState.initial(launch.service_id, launch.digest()),
                phase=ServicePhase.START_CHILD,
                attempt=1,
                process=None,
            )
            store.write(state)
            adapter = Adapter()
            with self.assertRaisesRegex(ServiceStartRecoveryRequired, "side effect may have happened"):
                make_service_supervisor(store, adapter).start_exact(launch)
            self.assertEqual(adapter.start_calls, 0)
            self.assertEqual(adapter.reconcile_calls, 0)
            self.assertEqual(store.read().phase, ServicePhase.START_CHILD)

    def test_recovery_required_state_cannot_be_auto_started(self) -> None:
        with TemporaryDirectory() as td:
            launch = contract()
            store = FileServiceStateStore(Path(td) / "service.json")
            store.write(
                replace(
                    ServiceSupervisorState.initial(launch.service_id, launch.digest()),
                    phase=ServicePhase.RECOVERY_REQUIRED,
                )
            )
            adapter = Adapter()
            with self.assertRaises(ServiceStartRecoveryRequired):
                make_service_supervisor(store, adapter).start_exact(launch)
            self.assertEqual(adapter.start_calls, 0)

    def test_running_process_is_reconciled_not_restarted(self) -> None:
        with TemporaryDirectory() as td:
            launch = contract()
            process = ServiceProcessIdentity(22, "start:22", 22)
            store = FileServiceStateStore(Path(td) / "service.json")
            store.write(
                replace(
                    ServiceSupervisorState.initial(launch.service_id, launch.digest()),
                    phase=ServicePhase.RUNNING,
                    process=process,
                )
            )
            adapter = Adapter()
            report = make_service_supervisor(store, adapter).start_exact(launch)
            self.assertEqual(report.state.phase, ServicePhase.RUNNING)
            self.assertEqual(report.state.process, process)
            self.assertEqual(adapter.reconcile_calls, 1)
            self.assertEqual(adapter.start_calls, 0)

    def test_stopping_state_is_not_overwritten_by_start_verification(self) -> None:
        with TemporaryDirectory() as td:
            launch = contract()
            process = ServiceProcessIdentity(33, "start:33", 33)
            store = FileServiceStateStore(Path(td) / "service.json")
            store.write(
                replace(
                    ServiceSupervisorState.initial(launch.service_id, launch.digest()),
                    phase=ServicePhase.STOPPING,
                    process=process,
                )
            )
            adapter = Adapter()
            with self.assertRaises(ServiceStartRecoveryRequired):
                make_service_supervisor(store, adapter).start_exact(launch)
            self.assertEqual(store.read().phase, ServicePhase.STOPPING)
            self.assertEqual(adapter.start_calls, 0)


if __name__ == "__main__":
    unittest.main()

class ServiceStopResumeV145Tests(unittest.TestCase):
    def test_uncertain_start_cannot_be_misreported_as_exited(self) -> None:
        with TemporaryDirectory() as td:
            from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceStopRecoveryRequired

            launch = contract()
            store = FileServiceStateStore(Path(td) / "service.json")
            store.write(
                replace(
                    ServiceSupervisorState.initial(launch.service_id, launch.digest()),
                    phase=ServicePhase.START_CHILD,
                    attempt=1,
                    process=None,
                )
            )
            adapter = Adapter()
            with self.assertRaises(ServiceStopRecoveryRequired):
                make_service_supervisor(store, adapter).stop_exact(launch)
            self.assertEqual(store.read().phase, ServicePhase.START_CHILD)
            self.assertEqual(adapter.start_calls, 0)

    def test_stopping_with_exact_process_identity_is_idempotently_resumed(self) -> None:
        with TemporaryDirectory() as td:
            launch = contract()
            process = ServiceProcessIdentity(44, "start:44", 44)
            store = FileServiceStateStore(Path(td) / "service.json")
            store.write(
                replace(
                    ServiceSupervisorState.initial(launch.service_id, launch.digest()),
                    phase=ServicePhase.STOPPING,
                    process=process,
                )
            )
            adapter = Adapter()
            stopped = make_service_supervisor(store, adapter).stop_exact(launch)
            self.assertEqual(stopped.phase, ServicePhase.EXITED)
            self.assertIsNone(stopped.process)
