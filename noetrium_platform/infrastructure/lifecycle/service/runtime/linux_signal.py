from __future__ import annotations

from dataclasses import dataclass
import os
import signal

from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.infrastructure.lifecycle.process.api import (
    ProcessSupervisorPort,
    ProcessTerminationPolicy,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)

from .linux_children import LinuxChildRegistry
from .linux_procfs import LinuxProcfsReader
from .process_contracts import ServiceProcessDrift


def signal_new_session_process_group(pid: int, sig: signal.Signals) -> bool:
    """Signal a freshly spawned Linux session leader through the sole killpg authority."""

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
    """Non-blocking adapter preserving target and ownership-anchor generations."""

    identity: ServiceProcessIdentity
    procfs: LinuxProcfsReader
    child: object | None = None

    @property
    def pid(self) -> int:
        return int(self.identity.ownership_pid)

    def _target_alive_exact(self) -> bool:
        if not self.procfs.alive_pid(self.identity.execution_pid):
            return False
        try:
            return (
                self.procfs.start_identity(self.identity.pid)
                == self.identity.start_identity
            )
        except (FileNotFoundError, ProcessLookupError):
            return False

    def _anchor_alive_exact(self) -> bool:
        if self.identity.anchor_pid is None:
            return self._target_alive_exact()
        assert self.identity.anchor_start_identity is not None
        anchor_control_pid = self.identity.anchor_execution_pid
        assert anchor_control_pid is not None
        if not self.procfs.alive_pid(anchor_control_pid):
            return False
        try:
            return (
                self.procfs.start_identity(self.identity.anchor_pid)
                == self.identity.anchor_start_identity
            )
        except (FileNotFoundError, ProcessLookupError):
            return False

    def poll(self) -> int | None:
        if self.child is not None:
            code = self.child.poll()
            if code is not None:
                return int(code)
        return None if self._anchor_alive_exact() else 0

    def _require_start_identity(self, pid: int, expected: str, label: str) -> None:
        try:
            observed = self.procfs.start_identity(pid)
        except (FileNotFoundError, ProcessLookupError) as exc:
            raise ProcessLookupError(pid) from exc
        if observed != expected:
            raise ServiceProcessDrift(
                f"{label} start identity drift; refusing to signal reused PID"
            )

    def _pidfd_signal(
        self,
        visible_pid: int,
        control_pid: int,
        expected_start_identity: str,
        sig: signal.Signals,
        *,
        label: str,
    ) -> None:
        pidfd_open = getattr(os, "pidfd_open", None)
        pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
        if pidfd_open is None or pidfd_send_signal is None:
            raise ServiceProcessDrift(
                f"{label} pidfd signaling unavailable; refusing racy PID signal"
            )
        self._require_start_identity(
            visible_pid,
            expected_start_identity,
            label,
        )
        try:
            descriptor = int(pidfd_open(control_pid, 0))
        except ProcessLookupError:
            raise
        try:
            # Re-prove after opening. Once the pidfd exists, later numeric PID
            # reuse cannot retarget the signal.
            self._require_start_identity(
                visible_pid,
                expected_start_identity,
                label,
            )
            pidfd_send_signal(descriptor, sig, None, 0)
        finally:
            os.close(descriptor)

    def _signal_anchor(self, sig: signal.Signals) -> None:
        anchor_pid = self.identity.anchor_pid
        anchor_start = self.identity.anchor_start_identity
        anchor_control_pid = self.identity.anchor_execution_pid
        assert (
            anchor_pid is not None
            and anchor_start is not None
            and anchor_control_pid is not None
        )
        self._require_start_identity(anchor_pid, anchor_start, "ownership anchor")
        try:
            observed_pgid = os.getpgid(anchor_control_pid)
        except ProcessLookupError:
            raise
        if observed_pgid != anchor_control_pid:
            raise ServiceProcessDrift(
                "ownership anchor process-group drift; refusing signal"
            )
        self._require_start_identity(anchor_pid, anchor_start, "ownership anchor")
        # TERM asks the guardian to forward graceful termination to the target
        # group. Force cleanup is guardian-private SIGUSR1 so the guardian stays
        # alive long enough to kill/reap setsid and double-fork descendants.
        delivered = signal.SIGTERM if sig == signal.SIGTERM else signal.SIGUSR1
        self._pidfd_signal(
            anchor_pid,
            anchor_control_pid,
            anchor_start,
            delivered,
            label="ownership anchor",
        )

    def _signal_target_group(self, sig: signal.Signals) -> None:
        pgid = self.identity.process_group_id
        if pgid is None:
            raise ServiceProcessDrift(
                "cannot safely signal process without frozen process-group identity"
            )

        self._require_start_identity(
            self.identity.pid,
            self.identity.start_identity,
            "process",
        )
        observed_pgid = os.getpgid(self.identity.execution_pid)
        if observed_pgid != pgid:
            raise ServiceProcessDrift(
                "process group drift; refusing to signal unrelated process"
            )
        self._require_start_identity(
            self.identity.pid,
            self.identity.start_identity,
            "process",
        )
        os.killpg(pgid, sig)

    def _signal(self, sig: signal.Signals) -> None:
        if self.identity.anchor_pid is not None:
            self._signal_anchor(sig)
            return
        self._signal_target_group(sig)

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)


class LinuxProcessSignaler:
    """Exact Linux tree-signal authority with async exit supervision."""

    def __init__(
        self,
        procfs: LinuxProcfsReader,
        children: LinuxChildRegistry,
        process_supervisor: ProcessSupervisorPort,
    ) -> None:
        self._procfs = procfs
        self._children = children
        self._process_supervisor = process_supervisor

    def _anchor_alive(self, process: ServiceProcessIdentity) -> bool:
        if process.anchor_pid is None:
            return True
        assert process.anchor_start_identity is not None
        anchor_control_pid = process.anchor_execution_pid
        assert anchor_control_pid is not None
        if not self._procfs.alive_pid(anchor_control_pid):
            return False
        try:
            return (
                self._procfs.start_identity(process.anchor_pid)
                == process.anchor_start_identity
            )
        except (FileNotFoundError, ProcessLookupError):
            return False

    def alive(self, process: ServiceProcessIdentity) -> bool:
        if not self._anchor_alive(process):
            return False
        if not self._procfs.alive_pid(process.execution_pid):
            return False
        try:
            return (
                self._procfs.start_identity(process.pid)
                == process.start_identity
            )
        except (FileNotFoundError, ProcessLookupError):
            return False

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        owner_pid = process.ownership_pid
        child = self._children.get(owner_pid)
        exact = _ExactLinuxProcess(process, self._procfs, child)
        if exact.poll() is not None:
            self._children.forget(owner_pid)
            return (f"proc-already-exited:{process.pid}",)

        policy = ProcessTerminationPolicy(
            poll_interval_seconds=min(
                0.05,
                max(0.005, contract.stop_timeout_s / 100.0),
            ),
            graceful_timeout_seconds=contract.stop_timeout_s,
            kill_timeout_seconds=max(
                1.0,
                min(5.0, contract.stop_timeout_s),
            ),
        )
        receipt = self._process_supervisor.terminate(
            f"service:{contract.service_id}:{process.pid}",
            exact,
            deadline=Deadline.after(
                policy.graceful_timeout_seconds
                + policy.kill_timeout_seconds
                + 1.0
            ),
            policy=policy,
        ).result(
            timeout=(
                policy.graceful_timeout_seconds
                + policy.kill_timeout_seconds
                + 2.0
            )
        )
        self._children.forget(owner_pid)
        prefix = "proc-killed" if receipt.escalated_to_kill else "proc-stopped"
        return (f"{prefix}:{process.pid}",)


__all__ = ["LinuxProcessSignaler", "signal_new_session_process_group"]
