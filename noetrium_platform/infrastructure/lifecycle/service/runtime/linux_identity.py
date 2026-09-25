from __future__ import annotations

import os
from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.lifecycle.service.api.environment import (
    MaterializedServiceEnvironment,
)

from .linux_procfs import LinuxProcfsReader
from .linux_start_marker import process_environment_without_start_marker
from .process_contracts import (
    ProcessReconcileResult,
    ProcessReconcileStatus,
)


class LinuxExactProcessVerifier:
    """Read-only Linux target + ownership-anchor identity authority."""

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
            "anchor_pid": process.anchor_pid,
            "anchor_start_identity": process.anchor_start_identity,
            "status": status.value,
            "facts": facts,
        }
        digest = canonical_digest(payload)
        return f"proc-reconcile:{digest}"

    @staticmethod
    def _missing(
        process: ServiceProcessIdentity,
        prefix: str,
    ) -> ProcessReconcileResult:
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

    def guarded_identity(
        self,
        target_pid: int,
        anchor_pid: int,
    ) -> ServiceProcessIdentity:
        target_visible = self._procfs.visible_pid(target_pid)
        anchor_visible = self._procfs.visible_pid(anchor_pid)
        if os.getpgid(anchor_pid) != anchor_pid:
            raise RuntimeError(
                "service ownership anchor is not an exact session leader"
            )
        return ServiceProcessIdentity(
            target_visible,
            self._procfs.start_identity(target_visible),
            os.getpgid(target_pid),
            None if target_visible == target_pid else target_pid,
            anchor_pid=anchor_pid,
            anchor_start_identity=self._procfs.start_identity(anchor_visible),
        )

    def _anchor_status(
        self,
        process: ServiceProcessIdentity,
    ) -> tuple[bool, str | None]:
        if process.anchor_pid is None:
            return True, None
        assert process.anchor_start_identity is not None
        if not self._procfs.alive_pid(process.anchor_pid):
            return False, "ownership anchor is missing"
        try:
            observed = self._procfs.start_identity(process.anchor_pid)
        except (FileNotFoundError, ProcessLookupError):
            return False, "ownership anchor disappeared"
        if observed != process.anchor_start_identity:
            return False, "ownership anchor generation drifted"
        try:
            if os.getpgid(process.anchor_pid) != process.anchor_pid:
                return False, "ownership anchor process-group identity drifted"
        except ProcessLookupError:
            return False, "ownership anchor disappeared"
        return True, None

    def reconcile(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
    ) -> ProcessReconcileResult:
        anchor_exact, anchor_reason = self._anchor_status(process)
        target_alive = self._procfs.alive_pid(process.execution_pid)

        if not target_alive:
            if process.anchor_pid is not None and anchor_exact:
                return ProcessReconcileResult(
                    ProcessReconcileStatus.DRIFT,
                    (
                        self._evidence_ref(
                            process=process,
                            status=ProcessReconcileStatus.DRIFT,
                            facts={"anchor": "alive", "target": "missing"},
                        ),
                    ),
                    (
                        "service target exited while fork-tree ownership anchor "
                        "still owns descendants"
                    ),
                )
            try:
                if (
                    self._procfs.start_identity(process.pid)
                    != process.start_identity
                ):
                    return self._missing(process, "proc-pid-reused")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
            return self._missing(process, "proc-missing")

        if process.anchor_pid is not None and not anchor_exact:
            return ProcessReconcileResult(
                ProcessReconcileStatus.DRIFT,
                (
                    self._evidence_ref(
                        process=process,
                        status=ProcessReconcileStatus.DRIFT,
                        facts={
                            "target": "alive",
                            "anchor": anchor_reason or "invalid",
                        },
                    ),
                ),
                (
                    "live service target lost its exact fork-tree ownership "
                    f"anchor: {anchor_reason or 'unknown'}"
                ),
            )

        try:
            facts = self._procfs.facts(
                process.pid,
                control_pid=process.control_pid,
            )
        except FileNotFoundError:
            return self._missing(process, "proc-pid-reused")
        if facts.start_identity != process.start_identity:
            return self._missing(process, "proc-pid-reused")

        expected_exe = str(Path(contract.executable).resolve())
        observed_environment, prepared_start_marker = (
            process_environment_without_start_marker(facts.environment)
        )
        anchor_parent_exact = True
        anchor_visible_pid: int | None = None
        if process.anchor_pid is not None:
            try:
                anchor_visible_pid = self._procfs.visible_pid(
                    process.anchor_pid
                )
            except (FileNotFoundError, ProcessLookupError):
                anchor_parent_exact = False
            else:
                anchor_parent_exact = facts.parent_pid == anchor_visible_pid

        evidence_facts = {
            "exe": facts.executable,
            "argv": facts.argv,
            "cwd": facts.cwd,
            "pgid": facts.process_group_id,
            "parent_pid": facts.parent_pid,
            "anchor_visible_pid": anchor_visible_pid,
            "environment_digest": environment.digest,
            "prepared_start_marker_present": (
                prepared_start_marker is not None
            ),
        }
        exact = (
            facts.executable == expected_exe
            and facts.argv == contract.argv
            and facts.cwd == str(Path(contract.cwd).resolve())
            and observed_environment == environment.as_dict()
            and (
                process.process_group_id is None
                or facts.process_group_id == process.process_group_id
            )
            and anchor_parent_exact
        )
        status = (
            ProcessReconcileStatus.EXACT
            if exact
            else ProcessReconcileStatus.DRIFT
        )
        return ProcessReconcileResult(
            status,
            (
                self._evidence_ref(
                    process=process,
                    status=status,
                    facts=evidence_facts,
                ),
            ),
            (
                None
                if exact
                else (
                    "live process identity differs from frozen launch contract "
                    "or fork-tree ownership anchor"
                )
            ),
        )


__all__ = ["LinuxExactProcessVerifier"]
