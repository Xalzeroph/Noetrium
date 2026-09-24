from __future__ import annotations

import hashlib
import os
from pathlib import Path
import signal
import subprocess

from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.infrastructure.lifecycle.process.api import ProcessSupervisorPort, ProcessTerminationPolicy
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity

from .capture_paths import ServiceCapturePaths
from noetrium_platform.infrastructure.lifecycle.service.api.environment import MaterializedServiceEnvironment
from .linux_children import LinuxChildRegistry
from .linux_procfs import LinuxProcfsReader
from .linux_signal import signal_new_session_process_group


class _SpawnCleanupProcess:
    def __init__(self, child: subprocess.Popen[bytes]) -> None:
        self._child = child
        self.pid = int(child.pid)

    def poll(self) -> int | None:
        code = self._child.poll()
        return None if code is None else int(code)

    def terminate(self) -> None:
        signal_new_session_process_group(self.pid, signal.SIGTERM)

    def kill(self) -> None:
        signal_new_session_process_group(self.pid, signal.SIGKILL)


class LinuxProcessSpawner:
    """The sole local ``subprocess.Popen`` authority for supervised services."""

    def __init__(
        self,
        procfs: LinuxProcfsReader,
        children: LinuxChildRegistry,
        process_supervisor: ProcessSupervisorPort,
    ) -> None:
        self._procfs = procfs
        self._children = children
        self._process_supervisor = process_supervisor

    def start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        *,
        launch_marker: tuple[str, str] | None = None,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        captures.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        captures.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        child_environment = environment.as_dict()
        if launch_marker is not None:
            marker_key, marker_value = launch_marker
            if marker_key in child_environment:
                raise ValueError(
                    f"service launch marker collides with frozen environment: {marker_key}"
                )
            child_environment[marker_key] = marker_value
        with captures.stdout_path.open("ab", buffering=0) as stdout, captures.stderr_path.open(
            "ab", buffering=0
        ) as stderr:
            child = subprocess.Popen(
                contract.argv,
                executable=contract.executable,
                cwd=contract.cwd,
                env=child_environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
        try:
            visible_pid = self._procfs.visible_pid(child.pid)
            start_identity = self._procfs.start_identity(visible_pid)
            pgid = os.getpgid(child.pid)
        except BaseException as primary:
            cleanup = _SpawnCleanupProcess(child)
            policy = ProcessTerminationPolicy(
                poll_interval_seconds=0.01,
                graceful_timeout_seconds=0.1,
                kill_timeout_seconds=2.0,
            )
            try:
                self._process_supervisor.terminate(
                    f"service-spawn-cleanup:{child.pid}",
                    cleanup,
                    deadline=Deadline.after(3.0),
                    policy=policy,
                ).result(timeout=3.5)
            except BaseException as supervisor_cleanup:
                fallback_errors: list[BaseException] = []
                try:
                    cleanup.kill()
                except BaseException as exc:
                    fallback_errors.append(exc)
                try:
                    child.wait(timeout=policy.kill_timeout_seconds)
                except BaseException as exc:
                    fallback_errors.append(exc)
                if fallback_errors:
                    raise BaseExceptionGroup(
                        "service spawn failed and physical cleanup did not converge",
                        [primary, supervisor_cleanup, *fallback_errors],
                    ) from primary
                primary.add_note(
                    "structured spawn cleanup failed but force-kill/reap fallback "
                    f"converged: {type(supervisor_cleanup).__name__}: "
                    f"{supervisor_cleanup}"
                )
            raise
        self._children.remember(child)
        control_pid = None if visible_pid == child.pid else child.pid
        process = ServiceProcessIdentity(visible_pid, start_identity, pgid, control_pid)
        launch_payload = f"{contract.digest()}:{visible_pid}:{control_pid}:{start_identity}:{pgid}"
        evidence = "proc-start:" + hashlib.sha256(launch_payload.encode()).hexdigest()
        return process, (evidence,)


__all__ = ["LinuxProcessSpawner"]
