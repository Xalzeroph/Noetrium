from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import MaterializedServiceEnvironment, ServiceLaunchContract
from noetrium_platform.foundation.kernel.concurrency.api import TaskFailurePolicy
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_supervisor
from service_os_test_support import make_service_supervisor

from dataclasses import replace
import hashlib
import os
import signal
from pathlib import Path
import sys
import tempfile
import unittest

from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    DirectoryCapturePathProvider,
    ExactServiceSupervisor,
    LinuxProcessBackend,
    LocalServiceProcessAdapter,
    ProcessAliveReadinessProbe,
    ServicePhase,
    ServiceProcessDrift,
    StaticServiceEnvironmentProvider,
)


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def contract(root: Path, environment: MaterializedServiceEnvironment) -> ServiceLaunchContract:
    executable = str(Path(sys.executable).resolve())
    code = "import os,time; print(os.environ['RP_SENTINEL'], flush=True); time.sleep(60)"
    return ServiceLaunchContract(
        "study.worker","g1",executable,(executable,"-c",code),str(root),
        environment.digest,h("artifact"),h("runtime"),5.0,1.0,0.2,
    )


class LocalServiceProcessV110Tests(unittest.TestCase):
    def setUp(self):
        self._concurrency_runtime = build_concurrency_runtime()
        self._task_group = self._concurrency_runtime.open_task_group(
            f"test-local-service:{id(self)}",
            failure_policy=TaskFailurePolicy.COLLECT_ALL,
        )

    def tearDown(self):
        self._task_group.close()
        self._concurrency_runtime.close()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process backend requires /proc and POSIX process groups")
    def test_exact_local_process_can_start_reconcile_and_stop_without_host_env_merge(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            environment=MaterializedServiceEnvironment.from_mapping(
                {"RP_SENTINEL":"frozen-value"}, "env:evidence"
            )
            c=contract(root,environment)
            backend=LinuxProcessBackend(build_process_supervisor(self._task_group))
            adapter=LocalServiceProcessAdapter(
                StaticServiceEnvironmentProvider((environment,)),
                DirectoryCapturePathProvider(root/"captures"),
                backend,
                ProcessAliveReadinessProbe(self._task_group, poll_interval_s=0.01),
            )
            state=FileServiceStateStore(root/"state.json")
            supervisor=make_service_supervisor(state,adapter)
            report=supervisor.start_exact(c)
            self.assertEqual(report.state.phase,ServicePhase.RUNNING)
            process=report.state.process
            self.assertIsNotNone(process)
            try:
                reconciled,refs=adapter.reconcile(state.read(),c)
                self.assertEqual(reconciled,process)
                self.assertTrue(any(ref.startswith("proc-reconcile:") for ref in refs))
                actual_env=(Path("/proc")/str(process.pid)/"environ").read_bytes()
                self.assertIn(b"RP_SENTINEL=frozen-value",actual_env)
                # The child receives the frozen environment only, not arbitrary host variables.
                if "HOME" not in environment.as_dict():
                    self.assertNotIn(b"HOME=",actual_env)
            finally:
                stopped=supervisor.stop_exact(c)
                self.assertEqual(stopped.phase,ServicePhase.EXITED)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process backend requires /proc and POSIX process groups")
    def test_local_process_is_recovered_after_crash_between_spawn_and_process_journal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            environment = MaterializedServiceEnvironment.from_mapping(
                {"RP_SENTINEL": "recovery-value"}, "env:recovery"
            )
            launch = contract(root, environment)
            state = FileServiceStateStore(root / "state.json")
            first_backend = LinuxProcessBackend(
                build_process_supervisor(self._task_group)
            )
            first_adapter = LocalServiceProcessAdapter(
                StaticServiceEnvironmentProvider((environment,)),
                DirectoryCapturePathProvider(root / "captures"),
                first_backend,
                ProcessAliveReadinessProbe(self._task_group, poll_interval_s=0.01),
            )
            first = make_service_supervisor(state, first_adapter)
            from noetrium_platform.infrastructure.lifecycle.service.runtime.start_journal import (
                ServiceStartJournal,
            )

            spawned: dict[str, object] = {}

            def crash_before_process_journal(self, intent, process):
                del self, intent
                spawned["process"] = process
                raise RuntimeError("simulated controller crash after physical spawn")

            with patch.object(
                ServiceStartJournal,
                "record_process",
                crash_before_process_journal,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "simulated controller crash after physical spawn",
                ):
                    first.start_exact(launch)

            original = spawned["process"]
            self.assertTrue(first_backend.alive(original))
            self.assertEqual(state.read().phase, ServicePhase.START_CHILD)

            # Recompose every process-owned object. The new backend has no
            # in-memory Popen/child registry and must recover only from the
            # durable start intent plus the exact /proc launch marker.
            second_backend = LinuxProcessBackend(
                build_process_supervisor(self._task_group)
            )
            second_adapter = LocalServiceProcessAdapter(
                StaticServiceEnvironmentProvider((environment,)),
                DirectoryCapturePathProvider(root / "captures"),
                second_backend,
                ProcessAliveReadinessProbe(self._task_group, poll_interval_s=0.01),
            )
            second = make_service_supervisor(state, second_adapter)
            report = second.start_exact(launch)
            self.assertEqual(report.state.phase, ServicePhase.RUNNING)
            self.assertEqual(report.state.process, original)
            self.assertTrue(second_backend.alive(original))
            try:
                actual_env = (
                    Path("/proc") / str(original.pid) / "environ"
                ).read_bytes()
                self.assertIn(
                    b"NOETRIUM_INTERNAL_SERVICE_START_TOKEN=",
                    actual_env,
                )
            finally:
                stopped = second.stop_exact(launch)
                self.assertEqual(stopped.phase, ServicePhase.EXITED)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "Linux process backend requires POSIX process groups",
    )
    def test_spawn_identity_failure_force_fallback_is_reaped(self):
        from noetrium_platform.infrastructure.lifecycle.service.runtime import linux_spawn
        from noetrium_platform.infrastructure.lifecycle.service.runtime.linux_spawn import (
            LinuxProcessSpawner,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            environment = MaterializedServiceEnvironment.from_mapping(
                {"RP_SENTINEL": "cleanup"}, "env:spawn-cleanup"
            )
            launch = contract(root, environment)
            captures = DirectoryCapturePathProvider(
                root / "captures"
            ).paths(launch)

            class FakeChild:
                pid = 4321

                def __init__(self):
                    self.returncode = None
                    self.wait_calls = 0

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    del timeout
                    self.wait_calls += 1
                    if self.returncode is None:
                        raise TimeoutError("child was not killed")
                    return self.returncode

            class FailingProcfs:
                def visible_pid(self, pid):
                    del pid
                    raise RuntimeError("simulated identity capture failure")

            class Children:
                def remember(self, child):
                    raise AssertionError(
                        f"unidentified child must not be registered: {child}"
                    )

            class FailedHandle:
                def result(self, timeout=None):
                    del timeout
                    raise RuntimeError("simulated structured cleanup failure")

            class FailingSupervisor:
                def terminate(self, *args, **kwargs):
                    del args, kwargs
                    return FailedHandle()

            child = FakeChild()
            signals = []

            def force_group(pid, sig):
                signals.append((pid, sig))
                child.returncode = -int(sig)
                return True

            spawner = LinuxProcessSpawner(
                FailingProcfs(),
                Children(),
                FailingSupervisor(),
            )
            with patch.object(
                linux_spawn.subprocess,
                "Popen",
                return_value=child,
            ), patch.object(
                linux_spawn,
                "signal_new_session_process_group",
                force_group,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "simulated identity capture failure",
                ) as caught:
                    spawner.start(
                        launch,
                        environment,
                        captures,
                    )

            self.assertEqual(signals, [(4321, signal.SIGKILL)])
            self.assertEqual(child.wait_calls, 1)
            notes = "\n".join(getattr(caught.exception, "__notes__", ()))
            self.assertIn("structured spawn cleanup failed", notes)
            self.assertIn("force-kill/reap fallback converged", notes)

    def test_materialized_environment_drift_fails_before_spawn(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            good=MaterializedServiceEnvironment.from_mapping({"A":"1"},"good")
            wrong=MaterializedServiceEnvironment.from_mapping({"A":"2"},"wrong")

            class LyingProvider:
                def resolve(self,digest): return wrong

            adapter=LocalServiceProcessAdapter(
                LyingProvider(),DirectoryCapturePathProvider(root/"captures"),LinuxProcessBackend(build_process_supervisor(self._task_group)),ProcessAliveReadinessProbe(self._task_group)
            )
            with self.assertRaises(ServiceProcessDrift):
                adapter.start(contract(root,good))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process backend requires /proc and POSIX process groups")
    def test_pid_start_identity_mismatch_is_treated_as_missing_not_adopted(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            environment=MaterializedServiceEnvironment.from_mapping({"A":"1"},"env")
            c=contract(root,environment)
            backend=LinuxProcessBackend(build_process_supervisor(self._task_group))
            adapter=LocalServiceProcessAdapter(
                StaticServiceEnvironmentProvider((environment,)),DirectoryCapturePathProvider(root/"captures"),backend,ProcessAliveReadinessProbe(self._task_group)
            )
            process,_=adapter.start(c)
            try:
                fake=replace(process,start_identity=process.start_identity+":wrong")
                state=FileServiceStateStore(root/"fake-state.json")
                from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceSupervisorState
                state.write(replace(ServiceSupervisorState.initial(c.service_id,c.digest()),process=fake))
                reconciled,refs=adapter.reconcile(state.read(),c)
                self.assertIsNone(reconciled)
                self.assertTrue(any(ref.startswith("proc-pid-reused:") for ref in refs))
            finally:
                adapter.stop(process,c)


if __name__ == "__main__": unittest.main()


class LinuxProcfsSnapshotV110Tests(unittest.TestCase):
    def test_facts_resolves_process_directory_once(self):
        from noetrium_platform.infrastructure.lifecycle.service.runtime.linux_procfs import LinuxProcfsReader

        with tempfile.TemporaryDirectory() as td:
            proc_root = Path(td)
            process_dir = proc_root / "9001"
            process_dir.mkdir()
            boot_dir = proc_root / "sys" / "kernel" / "random"
            boot_dir.mkdir(parents=True)
            (boot_dir / "boot_id").write_text("boot-test\n", encoding="utf-8")
            fields = ["S", *("0" for _ in range(18)), "777"]
            (process_dir / "stat").write_text(
                "9001 (worker) " + " ".join(fields), encoding="utf-8"
            )
            (process_dir / "cmdline").write_bytes(b"python\0-m\0worker\0")
            (process_dir / "environ").write_bytes(b"A=1\0B=two\0")
            (process_dir / "exe").write_bytes(b"")
            (process_dir / "cwd").mkdir()

            class CountingReader(LinuxProcfsReader):
                def __init__(self, root: Path) -> None:
                    super().__init__(root)
                    self.directory_resolutions = 0

                def _process_directory(self, pid: int) -> Path:
                    self.directory_resolutions += 1
                    return super()._process_directory(pid)

            from unittest.mock import patch
            from noetrium_platform.infrastructure.lifecycle.service.runtime import linux_procfs

            reader = CountingReader(proc_root)
            with patch.object(linux_procfs.os, "getpgid", return_value=42, create=True):
                facts = reader.facts(9001, control_pid=os.getpid())

            self.assertEqual(reader.directory_resolutions, 1)
            self.assertEqual(facts.process_group_id, 42)
            self.assertEqual(facts.start_identity, "linux-proc:boot-test:777")
            self.assertEqual(facts.argv, ("python", "-m", "worker"))
            self.assertEqual(facts.environment, {"A": "1", "B": "two"})
