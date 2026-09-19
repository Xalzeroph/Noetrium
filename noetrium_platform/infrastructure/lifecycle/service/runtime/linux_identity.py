from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity
from noetrium_platform.foundation.kernel.kernel import canonical_digest
import os
from pathlib import Path

from .environment import MaterializedServiceEnvironment
from .linux_procfs import LinuxProcfsReader
from .process_contracts import ProcessReconcileResult, ProcessReconcileStatus


class LinuxExactProcessVerifier:
    """Read-only Linux process identity authority shared by local launch backends.

    This component never spawns or signals processes.  It only proves whether a
    PID/start-identity still represents the exact frozen executable/argv/cwd/env.
    Keeping this verification independent prevents the direct-Popen and tmux
    launch transports from developing subtly different process identity rules.
    """

    def __init__(self, procfs: LinuxProcfsReader) -> None:
        self._procfs = procfs

    @staticmethod
    def _evidence_ref(
        *,
        process: ServiceProcessIdentity,
        status: ProcessReconcileStatus,
        facts: dict[str, object],
    ) -> str:
        payload = {
            "pid": process.pid,
            "start_identity": process.start_identity,
            "status": status.value,
            "facts": facts,
        }
        digest = canonical_digest(payload)
        return f"proc-reconcile:{digest}"

    @staticmethod
    def _missing(process: ServiceProcessIdentity, prefix: str) -> ProcessReconcileResult:
        return ProcessReconcileResult(
            ProcessReconcileStatus.MISSING,
            (f"{prefix}:{process.pid}",),
        )

    def identity(self, pid: int) -> ServiceProcessIdentity:
        visible_pid = self._procfs.visible_pid(pid)
        return ServiceProcessIdentity(
            visible_pid,
            self._procfs.start_identity(visible_pid),
            os.getpgid(pid),
            None if visible_pid == pid else pid,
        )

    def reconcile(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
    ) -> ProcessReconcileResult:
        if not self._procfs.alive_pid(process.execution_pid):
            try:
                if self._procfs.start_identity(process.pid) != process.start_identity:
                    return self._missing(process, "proc-pid-reused")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
            return self._missing(process, "proc-missing")
        try:
            facts = self._procfs.facts(process.pid, control_pid=process.control_pid)
        except FileNotFoundError:
            # The control namespace still reports the PID as alive, but the
            # procfs identity disappeared between the liveness and facts
            # reads.  That is an identity race, not proof that the persisted
            # process can safely be adopted.
            return self._missing(process, "proc-pid-reused")
        if facts.start_identity != process.start_identity:
            return self._missing(process, "proc-pid-reused")
        expected_exe = str(Path(contract.executable).resolve())
        evidence_facts = {
            "exe": facts.executable,
            "argv": facts.argv,
            "cwd": facts.cwd,
            "pgid": facts.process_group_id,
            "environment_digest": environment.digest,
        }
        exact = (
            facts.executable == expected_exe
            and facts.argv == contract.argv
            and facts.cwd == str(Path(contract.cwd).resolve())
            and facts.environment == environment.as_dict()
            and (
                process.process_group_id is None
                or facts.process_group_id == process.process_group_id
            )
        )
        status = ProcessReconcileStatus.EXACT if exact else ProcessReconcileStatus.DRIFT
        return ProcessReconcileResult(
            status,
            (self._evidence_ref(process=process, status=status, facts=evidence_facts),),
            None if exact else "live process identity differs from frozen launch contract",
        )




__all__ = ["LinuxExactProcessVerifier"]
