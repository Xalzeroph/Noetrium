from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_supervisor
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity

from .capture_paths import ServiceCapturePaths
from .environment import MaterializedServiceEnvironment
from .linux_children import LinuxChildRegistry
from .linux_identity import LinuxExactProcessVerifier
from .linux_procfs import LinuxProcfsReader
from .linux_signal import LinuxProcessSignaler
from .linux_spawn import LinuxProcessSpawner
from .process_contracts import ProcessReconcileResult


class LinuxProcessBackend:
    """Exact process façade over read/spawn/signal and async wait authorities."""

    start_recovery_durability = "process_local"

    def __init__(
        self,
        task_group: TaskGroupPort,
        *,
        proc_root: Path = Path("/proc"),
        procfs: LinuxProcfsReader | None = None,
    ) -> None:
        self._procfs = procfs or LinuxProcfsReader(proc_root)
        children = LinuxChildRegistry()
        process_supervisor = build_process_supervisor(task_group)
        self._verifier = LinuxExactProcessVerifier(self._procfs)
        self._spawner = LinuxProcessSpawner(self._procfs, children, process_supervisor)
        self._signaler = LinuxProcessSignaler(self._procfs, children, process_supervisor)

    def reconcile(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
    ) -> ProcessReconcileResult:
        return self._verifier.reconcile(process, contract, environment)

    def start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        return self._spawner.start(contract, environment, captures)

    def alive(self, process: ServiceProcessIdentity) -> bool:
        return self._signaler.alive(process)

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        return self._signaler.stop(process, contract)


__all__ = ["LinuxProcessBackend"]
