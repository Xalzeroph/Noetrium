from __future__ import annotations

import os
from pathlib import Path
from time import time

from noetrium_platform.infrastructure.lifecycle.process.api import ProcessSupervisorPort
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity

from .capture_paths import ServiceCapturePaths
from noetrium_platform.infrastructure.lifecycle.service.api.environment import MaterializedServiceEnvironment
from .linux_children import LinuxChildRegistry
from .linux_identity import LinuxExactProcessVerifier
from .linux_procfs import LinuxProcfsReader
from .linux_start_marker import (
    LINUX_PREPARED_START_ENV,
    decode_linux_start_handle,
    prepare_linux_start_handle,
)
from .linux_signal import LinuxProcessSignaler
from .linux_spawn import LinuxProcessSpawner
from .prepared_start import (
    PreparedServiceStartReconcileResult,
    PreparedServiceStartStatus,
    ServiceStartRecoveryHandle,
)
from .process_contracts import ProcessReconcileResult, ProcessReconcileStatus


class LinuxProcessBackend:
    """Exact Linux process façade with crash-durable prepared-start discovery."""

    start_recovery_durability = "crash_durable"
    _PREPARED_START_SETTLEMENT_SECONDS = 2.0

    def __init__(
        self,
        process_supervisor: ProcessSupervisorPort,
        *,
        proc_root: Path = Path("/proc"),
        procfs: LinuxProcfsReader | None = None,
    ) -> None:
        self._procfs = procfs or LinuxProcfsReader(proc_root)
        children = LinuxChildRegistry()
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

    def prepare_start_recovery(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        *,
        intent_id: str,
        attempt: int,
    ) -> ServiceStartRecoveryHandle:
        del captures
        return prepare_linux_start_handle(
            contract,
            environment,
            intent_id=intent_id,
            attempt=attempt,
        )

    def start_prepared(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        token = decode_linux_start_handle(handle, contract, environment)
        return self._spawner.start(
            contract,
            environment,
            captures,
            launch_marker=(LINUX_PREPARED_START_ENV, token.token),
        )

    def reconcile_prepared_start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> PreparedServiceStartReconcileResult:
        del captures
        token = decode_linux_start_handle(handle, contract, environment)
        marker_processes: list[int] = []
        exact_roots: list[ServiceProcessIdentity] = []
        uncertain_same_uid: list[int] = []
        evidence: list[str] = []
        controller_uid = os.geteuid()

        for visible_pid in self._procfs.process_ids():
            try:
                process_uid = self._procfs.effective_uid(visible_pid)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (PermissionError, OSError, RuntimeError):
                # A procfs entry hidden by host policy cannot be attributed to
                # this controller. Same-UID entries remain visible under the
                # supported Linux ownership contract and are handled below.
                continue
            if process_uid != controller_uid:
                continue
            try:
                observed_environment = self._procfs.environment(visible_pid)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (PermissionError, OSError):
                uncertain_same_uid.append(visible_pid)
                continue
            if observed_environment.get(LINUX_PREPARED_START_ENV) != token.token:
                continue
            marker_processes.append(visible_pid)
            try:
                control_pid = self._procfs.control_pid(visible_pid)
                process = self._verifier.identity(control_pid)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (PermissionError, OSError, RuntimeError):
                uncertain_same_uid.append(visible_pid)
                continue
            if (
                process.process_group_id is None
                or process.process_group_id != process.execution_pid
            ):
                # Prepared-start metadata is inherited by descendants. Only the
                # start_new_session root may be adopted as the service owner.
                continue
            reconciled = self._verifier.reconcile(process, contract, environment)
            evidence.extend(reconciled.evidence_refs)
            if reconciled.status is ProcessReconcileStatus.EXACT:
                exact_roots.append(process)

        if uncertain_same_uid:
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.UNKNOWN,
                None,
                tuple(evidence),
                (
                    "same-UID Linux process facts are not fully observable during "
                    "prepared-start reconciliation: "
                    + ",".join(str(pid) for pid in sorted(set(uncertain_same_uid)))
                ),
            )
        if len(exact_roots) == 1:
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.PROCESS_CONFIRMED,
                exact_roots[0],
                tuple(evidence),
            )
        if len(exact_roots) > 1:
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.UNKNOWN,
                None,
                tuple(evidence),
                "multiple exact Linux process roots carry one prepared-start token",
            )
        if marker_processes:
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.DRIFT,
                None,
                tuple(evidence),
                "prepared Linux start has marker-bearing processes but no exact session leader",
            )

        age = time() - float(token.prepared_at_epoch_s)
        if not age >= self._PREPARED_START_SETTLEMENT_SECONDS:
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.UNKNOWN,
                None,
                (),
                "prepared Linux start is still inside the spawn settlement window",
            )
        return PreparedServiceStartReconcileResult(
            PreparedServiceStartStatus.NOT_STARTED,
            None,
            (),
        )

    def alive(self, process: ServiceProcessIdentity) -> bool:
        return self._signaler.alive(process)

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        return self._signaler.stop(process, contract)


__all__ = ["LinuxProcessBackend"]
