from __future__ import annotations

from dataclasses import replace

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceQuiescenceOutcome,
)

from .contracts import ServiceExitClass, ServicePhase
from .prepared_start import (
    PreparedServiceStartStatus,
    crash_durable_start_adapter,
)
from .process_contracts import ServiceProcessDrift
from .quiescence import ExactServiceQuiescenceProbe
from .service_observation import ServiceObservationCoordinator
from .service_stop import ServiceStopCoordinator
from .start_intent_contracts import ServiceStartIntentPhase
from .start_effect_journal import ServiceStartEffectJournal
from .state_transition import ServiceStateTransitionWriter
from .supervision_contracts import ServiceProcessAdapter


class ServiceQuiescenceRecoveryRequired(RuntimeError):
    """Raised when exact service quiescence cannot be proven automatically."""


class ServiceQuiescenceCoordinator:
    """Converge one exact service contract to provider-observed absence.

    Causal Effect truth retains every confirmed process identity across
    supervisor-projection loss. Quiescence reconciles those identities against
    the physical backend before any projection may be treated as terminal.
    """

    def __init__(
        self,
        adapter: ServiceProcessAdapter,
        journal: ServiceStartEffectJournal,
        observation: ServiceObservationCoordinator,
        transitions: ServiceStateTransitionWriter,
        stop: ServiceStopCoordinator,
    ) -> None:
        self._adapter = adapter
        self._journal = journal
        self._observation = observation
        self._transitions = transitions
        self._stop = stop

    def inspect(
        self,
        contract: ServiceLaunchContract,
    ) -> ServiceQuiescenceOutcome:
        observed = ExactServiceQuiescenceProbe(
            self._observation,
            contract,
        ).observe()
        return ServiceQuiescenceOutcome(
            contract.digest(),
            observed.quiescent,
            observed.summary,
            tuple(observed.evidence_refs),
        )

    def _state_for_recovery(self, contract: ServiceLaunchContract):
        state = self._observation.observe_state(contract)
        if state is not None:
            return state
        return self._transitions.initialize(contract)

    def _quiesce_unresolved_start(
        self,
        contract: ServiceLaunchContract,
    ) -> None:
        intent = self._journal.unresolved(contract)
        if intent is None:
            return

        state = self._state_for_recovery(contract)
        process = intent.process

        if intent.phase is ServiceStartIntentPhase.PREPARED:
            durable = crash_durable_start_adapter(self._adapter)
            if durable is None or intent.recovery_handle is None:
                raise ServiceQuiescenceRecoveryRequired(
                    "prepared service start has no crash-durable recovery authority"
                )
            reconciled = durable.reconcile_prepared_start(
                contract,
                intent.recovery_handle,
            )
            if reconciled.status is PreparedServiceStartStatus.NOT_STARTED:
                self._journal.abort(intent)
                self._transitions.persist(
                    state,
                    ServicePhase.EXITED,
                    process=None,
                    last_exit_class=ServiceExitClass.CLEAN,
                )
                return
            if (
                reconciled.status
                is not PreparedServiceStartStatus.PROCESS_CONFIRMED
                or reconciled.process is None
            ):
                raise ServiceQuiescenceRecoveryRequired(
                    "prepared service start is not safely quiescent: "
                    + (
                        reconciled.reason
                        or reconciled.status.value
                    )
                )
            process = reconciled.process

        if process is None:
            raise ServiceQuiescenceRecoveryRequired(
                "unresolved service start lost exact process identity"
            )

        exact, _refs = self._adapter.reconcile(
            replace(state, process=process),
            contract,
        )
        if exact is not None and exact != process:
            raise ServiceQuiescenceRecoveryRequired(
                "unresolved service start reconciled to a different process"
            )
        if exact is not None:
            state = self._transitions.persist(
                state,
                ServicePhase.STOPPING,
                process=process,
            )
            self._adapter.stop(process, contract)

        self._journal.abort(intent)
        self._transitions.persist(
            state,
            ServicePhase.EXITED,
            process=None,
            last_exit_class=ServiceExitClass.CLEAN,
        )

    def quiesce(
        self,
        contract: ServiceLaunchContract,
    ) -> ServiceQuiescenceOutcome:
        self._quiesce_unresolved_start(contract)

        observed = self.inspect(contract)
        if observed.quiescent:
            return observed

        state = self._observation.observe_state(contract)
        try:
            exact = self._observation.reconcile_exact(contract)
        except ServiceProcessDrift as exc:
            raise ServiceQuiescenceRecoveryRequired(
                "service process generation drift prevents automatic quiescence"
            ) from exc
        if exact.process is None:
            if state is not None:
                self._transitions.persist(
                    state,
                    ServicePhase.EXITED,
                    process=None,
                    last_exit_class=ServiceExitClass.CLEAN,
                )
        elif state is None or state.process is None:
            # Effect truth recovered one exact live generation after projection
            # loss/staleness. Rebuild the minimum stop projection, then retire
            # the physical effect before publishing EXITED.
            if state is None:
                state = self._transitions.initialize(contract)
            state = self._transitions.persist(
                state,
                ServicePhase.STOPPING,
                process=exact.process,
            )
            self._adapter.stop(exact.process, contract)
            self._transitions.persist(
                state,
                ServicePhase.EXITED,
                process=None,
                last_exit_class=ServiceExitClass.CLEAN,
            )
        else:
            if exact.process != state.process:
                raise ServiceQuiescenceRecoveryRequired(
                    "service process generation changed before quiescence"
                )
            self._stop.stop_exact(
                contract,
                state.process,
            )

        observed = self.inspect(contract)
        if not observed.quiescent:
            raise ServiceQuiescenceRecoveryRequired(
                "service stop completed without exact quiescence proof: "
                + observed.summary
            )
        return observed


__all__ = [
    "ServiceQuiescenceCoordinator",
    "ServiceQuiescenceRecoveryRequired",
]
