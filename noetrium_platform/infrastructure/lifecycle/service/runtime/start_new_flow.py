from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from .contracts import ServiceExitClass, ServicePhase
from .prepared_start import crash_durable_start_adapter
from .service_state_contracts import ServiceSupervisorState
from .start_flow_common import ServiceReadinessCommitter, service_start_intent_refs
from .start_journal import ServiceStartJournal, service_start_intent_id
from .state_transition import ServiceStateTransitionWriter
from .supervision_contracts import ServiceProcessAdapter, ServiceStartReport


class NewServiceStartFlow:
    """Normal exact-start path when no unresolved start intent exists."""

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

    def execute(
        self,
        contract: ServiceLaunchContract,
        state: ServiceSupervisorState,
        *,
        initial_evidence: tuple[str, ...] = (),
    ) -> ServiceStartReport:
        evidence: list[str] = list(initial_evidence)
        state = self._transitions.persist(state, ServicePhase.VERIFY_CONTRACT)
        state = self._transitions.persist(state, ServicePhase.RECONCILE_PRIOR)
        existing, refs = self._adapter.reconcile(state, contract)
        evidence.extend(refs)
        intent = None

        if existing is not None:
            process = existing
        else:
            attempt = state.attempt + 1
            durable = crash_durable_start_adapter(self._adapter)
            handle = (
                None
                if durable is None
                else durable.prepare_start_recovery(
                    contract,
                    intent_id=service_start_intent_id(contract, attempt),
                    attempt=attempt,
                )
            )
            intent = self._journal.prepare(
                contract,
                attempt=attempt,
                recovery_handle=handle,
            )
            evidence.extend(service_start_intent_refs(intent))
            state = self._transitions.persist(
                state,
                ServicePhase.START_CHILD,
                attempt=attempt,
                process=None,
                ready_evidence_ref=None,
                ready_at=None,
            )
            if durable is None:
                process, refs = self._adapter.start(contract)
            else:
                assert handle is not None
                process, refs = durable.start_prepared(contract, handle)
            evidence.extend(refs)
            intent = self._journal.record_process(intent, process)

        state = self._transitions.persist(
            state,
            ServicePhase.WAIT_READY,
            process=process,
        )
        if intent is not None:
            intent = self._journal.state_committed(intent)
        try:
            state, ready_refs = self._readiness.commit(
                contract,
                state,
                process,
            )
        except BaseException as readiness_exc:
            if intent is None:
                raise
            cleanup_errors: list[BaseException] = []
            try:
                state = self._transitions.persist(
                    state,
                    ServicePhase.STOPPING,
                )
                self._adapter.stop(process, contract)
            except BaseException as cleanup_exc:
                cleanup_errors.append(cleanup_exc)
            else:
                try:
                    self._journal.abort(intent)
                except BaseException as journal_exc:
                    cleanup_errors.append(journal_exc)
                try:
                    state = self._transitions.persist(
                        state,
                        ServicePhase.EXITED,
                        process=None,
                        last_exit_class=ServiceExitClass.CLEAN,
                    )
                except BaseException as transition_exc:
                    cleanup_errors.append(transition_exc)
            if cleanup_errors:
                raise ExceptionGroup(
                    "service readiness failed and exact process cleanup failed",
                    [readiness_exc, *cleanup_errors],
                ) from readiness_exc
            raise
        evidence.extend(ready_refs)
        if intent is not None:
            self._journal.complete(intent)
        return ServiceStartReport(state, tuple(evidence))


__all__ = ["NewServiceStartFlow"]
