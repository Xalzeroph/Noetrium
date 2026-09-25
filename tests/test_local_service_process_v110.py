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
import time
import unittest
from unittest.mock import patch

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
            controller_nice = os.getpriority(os.PRIO_PROCESS, 0)
            controller_oom_score_adj = int(
                Path("/proc/self/oom_score_adj").read_text("utf-8").strip()
            )
            report=supervisor.start_exact(c)
            self.assertEqual(report.state.phase,ServicePhase.RUNNING)
            process=report.state.process
            self.assertIsNotNone(process)
            self.assertIsNotNone(process.anchor_pid)
            self.assertIsNotNone(process.anchor_start_identity)
            self.assertEqual(process.ownership_pid, process.anchor_pid)
            self.assertEqual(os.getpgid(process.anchor_pid), process.anchor_pid)
            target_stat = (
                Path("/proc") / str(process.pid) / "stat"
            ).read_text("utf-8")
            target_fields = target_stat[target_stat.rfind(")") + 2 :].split()
            self.assertEqual(int(target_fields[1]), process.anchor_pid)
            self.assertEqual(
                os.getpriority(os.PRIO_PROCESS, process.execution_pid),
                controller_nice,
            )
            oom_score_adj = int(
                (
                    Path("/proc")
                    / str(process.pid)
                    / "oom_score_adj"
                ).read_text("utf-8").strip()
            )
            self.assertEqual(oom_score_adj, controller_oom_score_adj)
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
                stopped=supervisor.stop_exact(c, process)
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
            self.assertIsNotNone(original.anchor_pid)
            self.assertIsNotNone(original.anchor_start_identity)
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
            self.assertEqual(
                report.state.process.anchor_pid,
                original.anchor_pid,
            )
            self.assertEqual(
                report.state.process.anchor_start_identity,
                original.anchor_start_identity,
            )
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
                stopped = second.stop_exact(launch, report.state.process)
                self.assertEqual(stopped.phase, ServicePhase.EXITED)

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "Linux fork-tree ownership requires Linux subreaper/pidfd",
    )
    def test_service_stop_reaps_forked_setsid_descendant(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            environment = MaterializedServiceEnvironment.from_mapping(
                {"RP_SENTINEL": "fork-tree"},
                "env:fork-tree",
            )
            pid_file = root / "service-tree.pids"
            detached_ready = root / "service-tree.detached-ready"
            executable = str(Path(sys.executable).resolve())
            code = "\n".join(
                (
                    "import os,pathlib,signal,time",
                    "pid=os.fork()",
                    "if pid == 0:",
                    "    os.setsid()",
                    "    signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                    f"    pathlib.Path({str(detached_ready)!r}).write_text(str(os.getpid()))",
                    "    time.sleep(60)",
                    "    os._exit(0)",
                    f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())+','+str(pid))",
                    "time.sleep(60)",
                )
            )
            launch = ServiceLaunchContract(
                "study.fork-tree",
                "g1",
                executable,
                (executable, "-c", code),
                str(root),
                environment.digest,
                h("fork-tree-artifact"),
                h("fork-tree-runtime"),
                3.0,
                0.1,
                0.05,
            )
            backend = LinuxProcessBackend(
                build_process_supervisor(self._task_group)
            )
            adapter = LocalServiceProcessAdapter(
                StaticServiceEnvironmentProvider((environment,)),
                DirectoryCapturePathProvider(root / "captures"),
                backend,
                ProcessAliveReadinessProbe(
                    self._task_group,
                    poll_interval_s=0.01,
                ),
            )
            state = FileServiceStateStore(root / "state.json")
            supervisor = make_service_supervisor(state, adapter)
            report = supervisor.start_exact(launch)
            process = report.state.process
            self.assertIsNotNone(process)
            self.assertIsNotNone(process.anchor_pid)

            deadline = time.monotonic() + 3.0
            while (
                (not pid_file.exists() or not detached_ready.exists())
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertTrue(pid_file.exists())
            self.assertTrue(detached_ready.exists())
            target_pid, detached_pid = map(
                int,
                pid_file.read_text().split(","),
            )
            self.assertEqual(target_pid, process.pid)
            self.assertEqual(
                detached_pid,
                int(detached_ready.read_text()),
            )
            anchor_pid = process.anchor_pid
            stopped = supervisor.stop_exact(launch, process)
            self.assertEqual(stopped.phase, ServicePhase.EXITED)

            deadline = time.monotonic() + 3.0
            owned_pids = (anchor_pid, target_pid, detached_pid)
            while time.monotonic() < deadline:
                if all(_pid_absent_or_zombie(pid) for pid in owned_pids):
                    break
                time.sleep(0.02)
            else:
                self.fail(
                    "service fork/setsid descendant survived exact stop"
                )

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
                    self.signals = []

                def poll(self):
                    return self.returncode

                def send_signal(self, sig):
                    self.signals.append(sig)
                    self.returncode = -int(sig)

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
                LinuxProcessSpawner,
                "_send_child_environment",
                return_value=None,
            ), patch.object(
                LinuxProcessSpawner,
                "_read_guarded_child_pid",
                return_value=9876,
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

            self.assertEqual(child.signals, [signal.SIGUSR1])
            self.assertEqual(child.wait_calls, 1)
            notes = "\n".join(getattr(caught.exception, "__notes__", ()))
            self.assertIn("structured spawn cleanup failed", notes)
            self.assertIn("guardian force cleanup converged", notes)

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


def _pid_absent_or_zombie(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    stat_path = Path("/proc") / str(pid) / "stat"
    if not stat_path.exists():
        return True
    stat = stat_path.read_text("utf-8")
    close = stat.rfind(")")
    if close < 0:
        return False
    fields = stat[close + 2 :].split()
    return bool(fields) and fields[0] == "Z"


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
            self.assertEqual(facts.parent_pid, 0)
            self.assertEqual(facts.start_identity, "linux-proc:boot-test:777")
            self.assertEqual(facts.argv, ("python", "-m", "worker"))
            self.assertEqual(facts.environment, {"A": "1", "B": "two"})
