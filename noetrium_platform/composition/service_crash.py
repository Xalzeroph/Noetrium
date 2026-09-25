from __future__ import annotations

import time

from noetrium_platform.infrastructure.reliability.failure.api import FailureLedgerPort
from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from noetrium_platform.infrastructure.lifecycle.service.runtime import ExactServiceSupervisor, ServiceCrashEvidenceAdapter

from .service_crash_contracts import CrashHandoffPhase, CrashHandoffReport, DurableCrashHandoff
from .service_crash_failure import service_crash_failure
from .service_crash_store import DurableCrashHandoffStore


class DurableServiceCrashCoordinator:
    """Replayable crash handoff coordinator across independent failure/service authorities."""

    def __init__(
        self,
        *,
        supervisor: ExactServiceSupervisor,
        failures: FailureLedgerPort,
        journal: DurableCrashHandoffStore,
    ) -> None:
        self.supervisor = supervisor
        self.failures = failures
        self.journal = journal

    def prepare(
        self,
        contract: ServiceLaunchContract,
        crash_adapter: ServiceCrashEvidenceAdapter,
        context: ExecutionContext,
    ) -> DurableCrashHandoff:
        report = self.supervisor.prepare_unexpected_exit(contract, crash_adapter)
        failure = service_crash_failure(report, context)
        now = time.time()
        handoff = DurableCrashHandoff(
            schema_version=self.journal.SCHEMA_VERSION,
            handoff_id=f"crash-handoff:{failure.failure_id}",
            service_id=contract.service_id,
            contract_digest=contract.digest(),
            process=report.process,
            exit_class=report.exit_class,
            stdout_capture_ref=report.capture.stdout_manifest_ref,
            stderr_capture_ref=report.capture.stderr_manifest_ref,
            failure=failure,
            phase=CrashHandoffPhase.PREPARED,
            created_at=now,
            updated_at=now,
        )
        self.journal.write(handoff)
        return handoff

    def _advance(self, handoff: DurableCrashHandoff, phase: CrashHandoffPhase) -> DurableCrashHandoff:
        updated = DurableCrashHandoff(
            schema_version=handoff.schema_version,
            handoff_id=handoff.handoff_id,
            service_id=handoff.service_id,
            contract_digest=handoff.contract_digest,
            process=handoff.process,
            exit_class=handoff.exit_class,
            stdout_capture_ref=handoff.stdout_capture_ref,
            stderr_capture_ref=handoff.stderr_capture_ref,
            failure=handoff.failure,
            phase=phase,
            created_at=handoff.created_at,
            updated_at=time.time(),
        )
        self.journal.write(updated)
        return updated

    def resume(
        self,
        contract: ServiceLaunchContract,
        handoff: DurableCrashHandoff | None = None,
    ) -> CrashHandoffReport:
        handoff = handoff or self.journal.read()
        if handoff.contract_digest != contract.digest() or handoff.service_id != contract.service_id:
            raise RuntimeError("durable crash handoff belongs to a different immutable service contract")

        appended = False
        if handoff.phase is CrashHandoffPhase.PREPARED:
            appended, _ = self.failures.append_failure_once(handoff.failure)
            handoff = self._advance(handoff, CrashHandoffPhase.FAILURE_DURABLE)
        if handoff.phase is CrashHandoffPhase.FAILURE_DURABLE:
            self.supervisor.commit_handoff_transition(
                contract,
                process=handoff.process,
                exit_class=handoff.exit_class,
                stdout_capture_ref=handoff.stdout_capture_ref,
                stderr_capture_ref=handoff.stderr_capture_ref,
                failure_id=handoff.failure.failure_id,
            )
            handoff = self._advance(handoff, CrashHandoffPhase.STATE_COMMITTED)
        if handoff.phase is CrashHandoffPhase.STATE_COMMITTED:
            handoff = self._advance(handoff, CrashHandoffPhase.COMPLETE)
        return CrashHandoffReport(handoff=handoff, failure_appended=appended)

    def handle(
        self,
        contract: ServiceLaunchContract,
        crash_adapter: ServiceCrashEvidenceAdapter,
        context: ExecutionContext,
    ) -> CrashHandoffReport:
        return self.resume(contract, self.prepare(contract, crash_adapter, context))


__all__ = ["DurableServiceCrashCoordinator"]
