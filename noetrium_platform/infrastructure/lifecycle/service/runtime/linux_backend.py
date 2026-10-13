from __future__ import annotations

import os
from pathlib import Path
from time import monotonic

from noetrium_platform.foundation.kernel.kernel.retry import blocking_wait
from noetrium_platform.infrastructure.lifecycle.process.api import ProcessSupervisorPort
from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime import (
    parent_bound_child as guardian_runtime,
)
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

    def _guarded_prepared_candidate(
        self,
        *,
        visible_pid: int,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        token,
    ) -> tuple[ServiceProcessIdentity | None, tuple[str, ...], str | None]:
        """Prove one marker-bearing target and its persistent guardian."""

        try:
            target_control_pid = self._procfs.control_pid(visible_pid)
            target = self._verifier.identity(target_control_pid)
            if (
                target.process_group_id is None
                or target.process_group_id != target.execution_pid
            ):
                return None, (), None
            target_facts = self._procfs.facts(
                target.pid,
                control_pid=target.control_pid,
            )
        except (FileNotFoundError, ProcessLookupError):
            return None, (), None
        except (PermissionError, OSError, RuntimeError) as exc:
            return None, (), (
                f"target identity unavailable for marker pid={visible_pid}: "
                f"{type(exc).__name__}:{exc}"
            )

        anchor_visible_pid = int(target_facts.parent_pid)
        if anchor_visible_pid <= 0:
            return None, (), (
                f"marker target has no valid guardian parent: pid={visible_pid}"
            )
        try:
            if self._procfs.effective_uid(anchor_visible_pid) != os.geteuid():
                return None, (), (
                    "marker target guardian belongs to a different effective uid: "
                    f"target={visible_pid} guardian={anchor_visible_pid}"
                )
            anchor_environment = self._procfs.environment(anchor_visible_pid)
            if anchor_environment.get(LINUX_PREPARED_START_ENV) != token.token:
                return None, (), (
                    "marker target parent does not carry the same prepared-start "
                    f"token: target={visible_pid} guardian={anchor_visible_pid}"
                )
            anchor_control_pid = self._procfs.control_pid(anchor_visible_pid)
            anchor_facts = self._procfs.facts(
                anchor_visible_pid,
                control_pid=anchor_control_pid,
            )
        except (FileNotFoundError, ProcessLookupError):
            return None, (), (
                "prepared-start guardian disappeared while proving ownership: "
                f"target={visible_pid} guardian={anchor_visible_pid}"
            )
        except (PermissionError, OSError, RuntimeError) as exc:
            return None, (), (
                "prepared-start guardian facts are not fully observable: "
                f"target={visible_pid} guardian={anchor_visible_pid} "
                f"{type(exc).__name__}:{exc}"
            )

        guardian_path = str(Path(guardian_runtime.__file__).resolve())
        argv = anchor_facts.argv
        try:
            separator = argv.index("--")
        except ValueError:
            separator = -1
        guardian_exact = (
            guardian_path in argv
            and "--survive-parent-exit" in argv
            and separator >= 0
            and tuple(argv[separator + 1 :]) == contract.argv
            and anchor_facts.process_group_id == anchor_control_pid
        )
        if not guardian_exact:
            return None, (), (
                "prepared-start parent is not the exact persistent service guardian: "
                f"target={visible_pid} guardian={anchor_visible_pid}"
            )

        try:
            guarded = self._verifier.guarded_identity(
                target_control_pid,
                anchor_control_pid,
            )
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, RuntimeError) as exc:
            return None, (), (
                "prepared-start guarded identity could not be reconstructed: "
                f"target={visible_pid} guardian={anchor_visible_pid} "
                f"{type(exc).__name__}:{exc}"
            )
        reconciled = self._verifier.reconcile(
            guarded,
            contract,
            environment,
        )
        if reconciled.status is not ProcessReconcileStatus.EXACT:
            return None, tuple(reconciled.evidence_refs), (
                reconciled.reason
                or "prepared-start guarded target differs from frozen contract"
            )
        return guarded, tuple(reconciled.evidence_refs), None

    def _observe_prepared_start_once(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        token,
    ) -> PreparedServiceStartReconcileResult | None:
        marker_processes: list[int] = []
        exact_roots: list[ServiceProcessIdentity] = []
        uncertain_same_uid: list[int] = []
        ownership_errors: list[str] = []
        evidence: list[str] = []
        controller_uid = os.geteuid()

        for visible_pid in self._procfs.process_ids():
            try:
                process_uid = self._procfs.effective_uid(visible_pid)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (PermissionError, OSError, RuntimeError):
                # Hidden other-UID entries are irrelevant. Same-UID uncertainty
                # is recorded below once marker visibility is known.
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
            candidate, refs, error = self._guarded_prepared_candidate(
                visible_pid=visible_pid,
                contract=contract,
                environment=environment,
                token=token,
            )
            evidence.extend(refs)
            if candidate is not None:
                exact_roots.append(candidate)
            elif error is not None:
                ownership_errors.append(error)

        # One exact token-bearing guarded root is sufficient ownership proof.
        # Unrelated same-UID processes can race exit/exec while /proc is scanned
        # (and hardened hosts may hide their environ). They must not veto an
        # already-proven exact prepared-start generation.
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
                (
                    "multiple exact guarded Linux service roots carry one "
                    "prepared-start token"
                ),
            )
        if uncertain_same_uid:
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.UNKNOWN,
                None,
                tuple(evidence),
                (
                    "same-UID Linux process facts are not fully observable during "
                    "prepared-start reconciliation: "
                    + ",".join(
                        str(pid) for pid in sorted(set(uncertain_same_uid))
                    )
                ),
            )
        if marker_processes:
            detail = (
                "; ".join(ownership_errors[:8])
                if ownership_errors
                else "no exact guarded service root"
            )
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.DRIFT,
                None,
                tuple(evidence),
                (
                    "prepared Linux start has marker-bearing processes but no "
                    f"recoverable fork-tree ownership anchor: {detail}"
                ),
            )
        return None

    def reconcile_prepared_start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> PreparedServiceStartReconcileResult:
        del captures
        token = decode_linux_start_handle(handle, contract, environment)

        # Wall-clock age cannot prove spawn quiescence: NTP/admin clock jumps
        # can make a freshly prepared intent look old. Recovery therefore owns
        # one bounded local monotonic observation window. Only complete absence
        # throughout this window proves NOT_STARTED.
        deadline = monotonic() + self._PREPARED_START_SETTLEMENT_SECONDS
        transient_uncertainty: PreparedServiceStartReconcileResult | None = None
        while True:
            observed = self._observe_prepared_start_once(
                contract,
                environment,
                token,
            )
            if observed is not None:
                if (
                    observed.status is PreparedServiceStartStatus.UNKNOWN
                    and observed.reason is not None
                    and observed.reason.startswith(
                        "same-UID Linux process facts are not fully observable"
                    )
                ):
                    # /proc enumeration races with unrelated same-UID process
                    # exit/exec. Do not permanently block recovery on one
                    # instantaneous unreadable row; retry for the bounded
                    # settlement window. If it stays unreadable, preserve the
                    # fail-closed UNKNOWN result rather than claiming NOT_STARTED.
                    transient_uncertainty = observed
                else:
                    return observed
            remaining = deadline - monotonic()
            if remaining <= 0:
                if transient_uncertainty is not None:
                    return transient_uncertainty
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.NOT_STARTED,
                    None,
                    (),
                )
            blocking_wait(min(0.05, remaining))

    def alive(self, process: ServiceProcessIdentity) -> bool:
        return self._signaler.alive(process)

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        return self._signaler.stop(process, contract)


__all__ = ["LinuxProcessBackend"]
