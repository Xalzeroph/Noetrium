from __future__ import annotations

from dataclasses import dataclass
import os
import signal

from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import (
    ProcessSupervisorPort,
    ProcessTerminationPolicy,
)
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity

from .linux_children import LinuxChildRegistry
from .linux_procfs import LinuxProcfsReader
from .process_contracts import ServiceProcessDrift


def signal_new_session_process_group(pid: int, sig: signal.Signals) -> bool:
    """Signal a freshly spawned Linux session leader through the sole killpg authority.

    The service spawner launches children with ``start_new_session=True``.  Cleanup
    is allowed only while that child is still the leader of the process group whose
    id equals its pid.  Returning ``False`` means the process already disappeared.
    """

    try:
        if os.getpgid(pid) != pid:
            raise ServiceProcessDrift(
                "spawned process-group drift; refusing to signal unrelated process"
            )
        os.killpg(pid, sig)
    except ProcessLookupError:
        return False
    return True


@dataclass(slots=True)
class _ExactLinuxProcess:
    """Non-blocking process adapter preserving frozen Linux process-group identity."""

    identity: ServiceProcessIdentity
    procfs: LinuxProcfsReader
    child: object | None = None

    @property
    def pid(self) -> int:
        return int(self.identity.execution_pid)

    def _alive_exact(self) -> bool:
        if not self.procfs.alive_pid(self.identity.execution_pid):
            return False
        try:
            return self.procfs.start_identity(self.identity.pid) == self.identity.start_identity
        except (FileNotFoundError, ProcessLookupError):
            return False

    def poll(self) -> int | None:
        if self.child is not None:
            code = self.child.poll()
            if code is not None:
                return int(code)
        return None if self._alive_exact() else 0

    def _signal(self, sig: signal.Signals) -> None:
        pgid = self.identity.process_group_id
        if pgid is None:
            raise ServiceProcessDrift(
                "cannot safely signal process without frozen process-group identity"
            )
        if os.getpgid(self.identity.execution_pid) != pgid:
            raise ServiceProcessDrift(
                "process group drift; refusing to signal unrelated process"
            )
        os.killpg(pgid, sig)

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)


class LinuxProcessSignaler:
    """Exact Linux process-group signal authority with async exit supervision."""

    def __init__(
        self,
        procfs: LinuxProcfsReader,
        children: LinuxChildRegistry,
        process_supervisor: ProcessSupervisorPort,
    ) -> None:
        self._procfs = procfs
        self._children = children
        self._process_supervisor = process_supervisor

    def alive(self, process: ServiceProcessIdentity) -> bool:
        if not self._procfs.alive_pid(process.execution_pid):
            return False
        try:
            return self._procfs.start_identity(process.pid) == process.start_identity
        except (FileNotFoundError, ProcessLookupError):
            return False

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        child = self._children.get(process.execution_pid)
        exact = _ExactLinuxProcess(process, self._procfs, child)
        if exact.poll() is not None:
            self._children.forget(process.execution_pid)
            return (f"proc-already-exited:{process.pid}",)

        policy = ProcessTerminationPolicy(
            poll_interval_seconds=min(0.05, max(0.005, contract.stop_timeout_s / 100.0)),
            graceful_timeout_seconds=contract.stop_timeout_s,
            kill_timeout_seconds=max(1.0, min(5.0, contract.stop_timeout_s)),
        )
        receipt = self._process_supervisor.terminate(
            f"service:{contract.service_id}:{process.pid}",
            exact,
            deadline=Deadline.after(policy.graceful_timeout_seconds + policy.kill_timeout_seconds + 1.0),
            policy=policy,
        ).result(timeout=policy.graceful_timeout_seconds + policy.kill_timeout_seconds + 2.0)
        self._children.forget(process.execution_pid)
        prefix = "proc-killed" if receipt.escalated_to_kill else "proc-stopped"
        return (f"{prefix}:{process.pid}",)


__all__ = ["LinuxProcessSignaler", "signal_new_session_process_group"]
