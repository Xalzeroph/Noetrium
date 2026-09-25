from __future__ import annotations

import hashlib
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.infrastructure.lifecycle.process.api import (
    ProcessSupervisorPort,
    ProcessTerminationPolicy,
)
from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime import (
    parent_bound_child as guardian_runtime,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)

from .capture_paths import ServiceCapturePaths
from noetrium_platform.infrastructure.lifecycle.service.api.environment import (
    MaterializedServiceEnvironment,
)
from .linux_children import LinuxChildRegistry
from .linux_procfs import LinuxProcfsReader
from .linux_start_marker import process_environment_without_start_marker


class _SpawnCleanupProcess:
    """Supervisor facade over the exact freshly-spawned service guardian."""

    def __init__(self, child: subprocess.Popen[bytes]) -> None:
        self._child = child
        self.pid = int(child.pid)

    def poll(self) -> int | None:
        code = self._child.poll()
        return None if code is None else int(code)

    def terminate(self) -> None:
        if self._child.poll() is None:
            self._child.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        if self._child.poll() is None:
            # Guardian-private force cleanup kills the complete owned descendant
            # tree, including setsid/double-fork descendants, before it exits.
            self._child.send_signal(signal.SIGUSR1)


class LinuxProcessSpawner:
    """Sole local subprocess spawn authority for supervised Linux services.

    Every service is rooted under a persistent Linux guardian. The logical
    target process remains the contract/readiness identity, while the guardian
    is the physical ownership anchor that survives controller restart and does
    not retire until the complete fork tree converges.
    """

    _EXEC_SETTLEMENT_SECONDS = 2.0

    def __init__(
        self,
        procfs: LinuxProcfsReader,
        children: LinuxChildRegistry,
        process_supervisor: ProcessSupervisorPort,
    ) -> None:
        self._procfs = procfs
        self._children = children
        self._process_supervisor = process_supervisor

    @staticmethod
    def _send_child_environment(
        fd: int,
        environment: dict[str, str],
    ) -> None:
        payload = guardian_runtime.encode_child_environment(environment)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(
                    "service guardian child-environment pipe made no progress"
                )
            view = view[written:]

    @staticmethod
    def _read_guarded_child_pid(
        guardian: subprocess.Popen[bytes],
        read_fd: int,
        *,
        timeout_seconds: float,
    ) -> int:
        deadline = time.monotonic() + timeout_seconds
        payload = bytearray()
        while True:
            if guardian.poll() is not None:
                raise RuntimeError(
                    "service guardian exited before publishing target pid"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "service guardian did not publish target pid before deadline"
                )
            readable, _, _ = select.select(
                (read_fd,),
                (),
                (),
                min(0.05, remaining),
            )
            if not readable:
                continue
            chunk = os.read(read_fd, 64)
            if not chunk:
                raise RuntimeError(
                    "service guardian closed target-pid channel before publication"
                )
            payload.extend(chunk)
            if b"\n" not in payload:
                if len(payload) > 32:
                    raise RuntimeError("service guardian published invalid target pid")
                continue
            line, _separator, remainder = bytes(payload).partition(b"\n")
            if remainder:
                raise RuntimeError("service guardian target-pid channel contained extra data")
            try:
                pid = int(line.decode("ascii"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise RuntimeError(
                    "service guardian published invalid target pid"
                ) from exc
            if pid <= 0:
                raise RuntimeError("service guardian published non-positive target pid")
            return pid

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

        pid_read_fd, pid_write_fd = os.pipe()
        env_read_fd, env_write_fd = os.pipe()
        try:
            try:
                with captures.stdout_path.open(
                    "ab",
                    buffering=0,
                ) as stdout, captures.stderr_path.open(
                    "ab",
                    buffering=0,
                ) as stderr:
                    guardian_path = Path(guardian_runtime.__file__).resolve()
                    child = subprocess.Popen(
                        (
                            sys.executable,
                            "-E",
                            str(guardian_path),
                            "--parent-pid",
                            str(os.getpid()),
                            "--child-pid-fd",
                            str(pid_write_fd),
                            "--child-env-fd",
                            str(env_read_fd),
                            "--survive-parent-exit",
                            "--",
                            contract.executable,
                            *contract.argv[1:],
                        ),
                        executable=sys.executable,
                        cwd=contract.cwd,
                        env=child_environment,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout,
                        stderr=stderr,
                        start_new_session=True,
                        close_fds=True,
                        pass_fds=(pid_write_fd, env_read_fd),
                    )
            finally:
                os.close(pid_write_fd)
                os.close(env_read_fd)
        except BaseException:
            os.close(pid_read_fd)
            os.close(env_write_fd)
            raise

        try:
            try:
                self._send_child_environment(
                    env_write_fd,
                    child_environment,
                )
            finally:
                os.close(env_write_fd)

            try:
                target_control_pid = self._read_guarded_child_pid(
                    child,
                    pid_read_fd,
                    timeout_seconds=self._EXEC_SETTLEMENT_SECONDS,
                )
            finally:
                os.close(pid_read_fd)

            anchor_visible_pid = self._procfs.visible_pid(child.pid)
            anchor_start_identity = self._procfs.start_identity(anchor_visible_pid)
            if os.getpgid(child.pid) != child.pid:
                raise RuntimeError(
                    "service guardian did not retain exact session-leader identity"
                )

            visible_pid = self._procfs.visible_pid(target_control_pid)
            start_identity = self._procfs.start_identity(visible_pid)
            pgid = os.getpgid(target_control_pid)
            if pgid != target_control_pid:
                raise RuntimeError(
                    "service target did not retain exact process-group root identity"
                )
            control_pid = (
                None
                if visible_pid == target_control_pid
                else target_control_pid
            )

            # Popen in the guardian does not publish the child pid until exec has
            # succeeded. Still verify the complete frozen target before exposing
            # ownership to higher layers.
            expected_executable = str(Path(contract.executable).resolve())
            expected_cwd = str(Path(contract.cwd).resolve())
            deadline = time.monotonic() + self._EXEC_SETTLEMENT_SECONDS
            while True:
                if child.poll() is not None:
                    raise RuntimeError(
                        "service guardian exited before target identity settled"
                    )
                try:
                    facts = self._procfs.facts(
                        visible_pid,
                        control_pid=control_pid,
                    )
                except (FileNotFoundError, ProcessLookupError):
                    facts = None
                if facts is not None:
                    observed_environment, _marker = (
                        process_environment_without_start_marker(
                            facts.environment
                        )
                    )
                    if (
                        facts.executable == expected_executable
                        and facts.argv == contract.argv
                        and facts.cwd == expected_cwd
                        and observed_environment == environment.as_dict()
                        and facts.process_group_id == pgid
                        and facts.parent_pid == anchor_visible_pid
                    ):
                        break
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "service target did not settle to exact frozen identity"
                    )
                from noetrium_platform.foundation.kernel.kernel.retry import (
                    blocking_wait,
                )

                blocking_wait(0.005)
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
                    "structured spawn cleanup failed but guardian force cleanup "
                    f"converged: {type(supervisor_cleanup).__name__}: "
                    f"{supervisor_cleanup}"
                )
            raise

        self._children.remember(child)
        anchor_control_pid = (
            None
            if anchor_visible_pid == child.pid
            else int(child.pid)
        )
        process = ServiceProcessIdentity(
            visible_pid,
            start_identity,
            pgid,
            control_pid,
            anchor_pid=anchor_visible_pid,
            anchor_start_identity=anchor_start_identity,
            anchor_control_pid=anchor_control_pid,
        )
        launch_payload = (
            f"{contract.digest()}:{visible_pid}:{control_pid}:{start_identity}:{pgid}:"
            f"{anchor_visible_pid}:{anchor_control_pid}:{anchor_start_identity}"
        )
        evidence = "proc-start:" + hashlib.sha256(
            launch_payload.encode()
        ).hexdigest()
        return process, (evidence,)


__all__ = ["LinuxProcessSpawner"]
