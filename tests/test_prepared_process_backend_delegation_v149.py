from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.foundation.kernel.concurrency.api import TaskFailurePolicy
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime

from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    DirectoryCapturePathProvider,
    LocalServiceProcessAdapter,
    PreparedServiceStartReconcileResult,
    PreparedServiceStartStatus,
    ProcessAliveReadinessProbe,
    ServiceStartRecoveryHandle,
    StaticServiceEnvironmentProvider,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.environment import MaterializedServiceEnvironment


def h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def contract(env_digest: str) -> ServiceLaunchContract:
    return ServiceLaunchContract(
        "svc", "g", "/bin/echo", ("/bin/echo", "x"), "/tmp",
        env_digest, h("artifact"), h("runtime"), 1, 1, 1,
    )


class DurableBackend:
    start_recovery_durability = "crash_durable"

    def __init__(self):
        self.calls = []
        self.process = ServiceProcessIdentity(77, "start", 77)

    def reconcile(self, process, launch, environment):
        raise AssertionError("not used")
    def start(self, launch, environment, captures):
        raise AssertionError("legacy start must not be used")
    def alive(self, process): return True
    def stop(self, process, launch): return ()

    def prepare_start_recovery(self, launch, environment, captures, *, intent_id, attempt):
        self.calls.append(("prepare", environment.digest, str(captures.stdout_path), intent_id, attempt))
        return ServiceStartRecoveryHandle.from_payload("backend.v1", b"token")

    def start_prepared(self, launch, environment, captures, handle):
        self.calls.append(("start", environment.digest, handle.payload_sha256))
        return self.process, ("backend-start",)

    def reconcile_prepared_start(self, launch, environment, captures, handle):
        self.calls.append(("reconcile", environment.digest, handle.payload_sha256))
        return PreparedServiceStartReconcileResult(
            PreparedServiceStartStatus.PROCESS_CONFIRMED, self.process, ("backend-reconcile",)
        )


class PreparedProcessBackendDelegationTests(unittest.TestCase):
    def setUp(self):
        self._concurrency_runtime = build_concurrency_runtime()
        self._task_group = self._concurrency_runtime.open_task_group(
            f"test-prepared-process:{id(self)}",
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )

    def tearDown(self):
        self._task_group.close()
        self._concurrency_runtime.close()

    def test_local_adapter_transparently_exposes_backend_prepared_start(self):
        with TemporaryDirectory() as td:
            env = MaterializedServiceEnvironment.from_mapping({"A": "1"}, "env-ref")
            backend = DurableBackend()
            adapter = LocalServiceProcessAdapter(
                StaticServiceEnvironmentProvider((env,)),
                DirectoryCapturePathProvider(Path(td) / "captures"),
                backend,
                ProcessAliveReadinessProbe(self._task_group),
            )
            launch = contract(env.digest)
            self.assertEqual(adapter.start_recovery_durability, "crash_durable")
            handle = adapter.prepare_start_recovery(launch, intent_id="intent", attempt=2)
            process, refs = adapter.start_prepared(launch, handle)
            reconciled = adapter.reconcile_prepared_start(launch, handle)
            self.assertEqual(process, backend.process)
            self.assertIn("backend-start", refs)
            self.assertEqual(reconciled.process, backend.process)
            self.assertEqual([row[0] for row in backend.calls], ["prepare", "start", "reconcile"])

    def test_linux_or_plain_backend_remains_process_local(self):
        class Plain:
            def reconcile(self,*a): raise AssertionError
            def start(self,*a): raise AssertionError
            def alive(self,*a): return False
            def stop(self,*a): return ()
        env = MaterializedServiceEnvironment.from_mapping({}, "env")
        adapter = LocalServiceProcessAdapter(
            StaticServiceEnvironmentProvider((env,)),
            DirectoryCapturePathProvider(Path("/tmp/captures")),
            Plain(),
            ProcessAliveReadinessProbe(self._task_group),
        )
        self.assertEqual(adapter.start_recovery_durability, "process_local")


if __name__ == "__main__": unittest.main()
