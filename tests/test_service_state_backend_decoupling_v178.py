from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import unittest

from noetrium_platform.infrastructure.lifecycle.service.composition import build_service_supervisor
from service_os_test_support import ready_evidence
from noetrium_platform.infrastructure.lifecycle.service.runtime import ServicePhase
from noetrium_platform.infrastructure.lifecycle.service.runtime.service_state_contracts import ServiceSupervisorState
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore


class MemoryServiceStateStore:
    """State backend with no filesystem/path attribute."""

    def __init__(self) -> None:
        self.value: ServiceSupervisorState | None = None

    def exists(self) -> bool:
        return self.value is not None

    def write(self, state: ServiceSupervisorState) -> None:
        self.value = state

    def read(self) -> ServiceSupervisorState:
        if self.value is None:
            raise RuntimeError("missing")
        return self.value

    def reference(self) -> str:
        return "memory://service-state"


class Adapter:
    def reconcile(self, state, contract):
        return None, ("reconcile",)

    def start(self, contract):
        return ServiceProcessIdentity(7, "pid:7:start:1", 7), ("start",)

    def wait_ready(self, process, contract):
        return ready_evidence(process, contract)

    def stop(self, process, contract):
        return ("stop",)


def contract() -> ServiceLaunchContract:
    digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
    exe = "/opt/research/python"
    return ServiceLaunchContract(
        "service.memory",
        "generation",
        exe,
        (exe, "-m", "service"),
        "/srv/research",
        digest("env"),
        digest("artifact"),
        digest("runtime"),
        30,
        10,
        5,
    )


class ServiceStateBackendDecouplingV178Tests(unittest.TestCase):
    def test_exact_supervisor_runs_with_non_file_state_backend(self) -> None:
        with TemporaryDirectory() as td:
            state = MemoryServiceStateStore()
            supervisor = build_service_supervisor(
                state,
                DirectoryServiceStartIntentStore(Path(td) / "intents"),
                Adapter(),
            )
            report = supervisor.start_exact(contract())
            self.assertEqual(report.state.phase, ServicePhase.RUNNING)
            self.assertEqual(state.reference(), "memory://service-state")
            stopped = supervisor.stop_exact(contract())
            self.assertEqual(stopped.phase, ServicePhase.EXITED)


if __name__ == "__main__":
    unittest.main()
