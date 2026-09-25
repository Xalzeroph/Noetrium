from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.service.composition import build_service_supervisor
from service_os_test_support import ready_evidence
from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import ServicePhase
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _contract() -> ServiceLaunchContract:
    executable = "/opt/rp/bin/python"
    return ServiceLaunchContract(
        "model.planner",
        "g1",
        executable,
        (executable, "-m", "model_server"),
        "/srv/rp",
        _sha("env"),
        _sha("artifact"),
        _sha("runtime"),
        30.0,
        30.0,
        5.0,
    )


class _Adapter:
    def reconcile(self, state, contract):
        return state.process, ()

    def start(self, contract):
        return ServiceProcessIdentity(321, "pid:321:start:1", 321), ()

    def wait_ready(self, process, contract):
        return ready_evidence(process, contract)

    def stop(self, process, contract):
        return ()


class ServiceStartStoreDecouplingV170Tests(unittest.TestCase):
    def test_state_and_start_intents_can_live_under_independent_roots(self) -> None:
        with TemporaryDirectory() as state_td, TemporaryDirectory() as intent_td:
            state_path = Path(state_td) / "authoritative" / "service.json"
            intent_root = Path(intent_td) / "journal" / "service-start"
            supervisor = build_service_supervisor(
                FileServiceStateStore(state_path),
                DirectoryServiceStartIntentStore(intent_root),
                _Adapter(),
            )

            report = supervisor.start_exact(_contract())

            self.assertEqual(report.state.phase, ServicePhase.RUNNING)
            self.assertTrue(state_path.exists())
            self.assertTrue(intent_root.exists())
            self.assertTrue(any(intent_root.glob("*.json")))
            self.assertFalse((state_path.parent / (state_path.name + ".start-intents")).exists())


if __name__ == "__main__":
    unittest.main()
