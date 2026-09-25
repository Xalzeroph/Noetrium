from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from dataclasses import replace

from .contracts import ServicePhase
from .prepared_start import PreparedServiceStartStatus, crash_durable_start_adapter
from .service_state_contracts import ServiceSupervisorState
from .start_flow_common import ServiceReadinessCommitter, service_start_intent_refs
from .start_intent_contracts import ServiceStartIntent, ServiceStartIntentPhase
from .start_journal import ServiceStartJournal
from .start_resume import (
    ServiceStartDisposition,
    ServiceStartRecoveryRequired,
    ServiceStartResumeDecision,
)
from .state_transition import ServiceStateTransitionWriter
from .supervision_contracts import ServiceProcessAdapter, ServiceStartReport


class ServicePreparedStartRecoveryRequired(ServiceStartRecoveryRequired):
    def __init__(self, state: ServiceSupervisorState, reason: str) -> None:
        super().__init__(
            state,
            ServiceStartResumeDecision(ServiceStartDisposition.BLOCK_EFFECT_UNCERTAIN, reason),
        )


class PreparedServiceStartRecoveryFlow:
    """Resolve one durable start intent without sharing state with normal start flow."""

    def __init__(
        self,
        adapter: ServiceProcessAdapter,
        transitions: ServiceStateTransitionWriter,
        journal: ServiceStartJournal,
        readiness: ServiceReadinessCommitter,
    ) -> None:
        self._adapter = adapter
        self._transitions = transitions
        self._journal = journal
        self._readiness = readiness

    def recover(
        self,
        contract: ServiceLaunchContract,
        state: ServiceSupervisorState,
        intent: ServiceStartIntent,
    ) -> ServiceStartReport:
        evidence = list(service_start_intent_refs(intent))
        if intent.attempt not in {state.attempt, state.attempt + 1}:
            raise ServicePreparedStartRecoveryRequired(
                state,
                "start-intent attempt is not adjacent to persisted supervisor state",
            )

        durable = crash_durable_start_adapter(self._adapter)
        process = intent.process
        if intent.phase is ServiceStartIntentPhase.PREPARED:
            process, intent, refs = self._resolve_prepared(
                contract,
                state,
                intent,
                durable,
            )
            evidence.extend(refs)

        if process is None:
            raise ServicePreparedStartRecoveryRequired(
                state,
                "start intent reached post-prepare phase without process identity",
            )

        exact, refs = self._adapter.reconcile(replace(state, process=process), contract)
        evidence.extend(refs)
        if exact is None or exact != process:
            raise ServicePreparedStartRecoveryRequired(
                state,
                "journaled process is no longer an exact live process; explicit restart recovery is required",
            )

        state = self._transitions.persist(
            state,
            ServicePhase.WAIT_READY,
            attempt=max(state.attempt, intent.attempt),
            process=process,
        )
        intent = self._journal.state_committed(intent)
        state, ready_refs = self._readiness.commit(contract, state, process)
        evidence.extend(ready_refs)
        self._journal.complete(intent)
        return ServiceStartReport(state, tuple(evidence))

    def _resolve_prepared(self, contract, state, intent, durable):
        if durable is None or intent.recovery_handle is None:
            raise ServicePreparedStartRecoveryRequired(
                state,
                "prepared child-start has no crash-durable provider recovery handle; manual reconciliation required",
            )
        reconciled = durable.reconcile_prepared_start(contract, intent.recovery_handle)
        evidence = list(reconciled.evidence_refs)
        if reconciled.status is PreparedServiceStartStatus.PROCESS_CONFIRMED:
            assert reconciled.process is not None
            process = reconciled.process
        elif reconciled.status is PreparedServiceStartStatus.NOT_STARTED:
            process, refs = durable.start_prepared(contract, intent.recovery_handle)
            evidence.extend(refs)
        else:
            raise ServicePreparedStartRecoveryRequired(
                state,
                reconciled.reason
                or f"prepared child-start reconciliation returned {reconciled.status.value}",
            )
        return process, self._journal.record_process(intent, process), tuple(evidence)


__all__ = ["PreparedServiceStartRecoveryFlow", "ServicePreparedStartRecoveryRequired"]
