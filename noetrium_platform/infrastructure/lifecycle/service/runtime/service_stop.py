from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from .contracts import ServiceExitClass, ServicePhase
from .service_observation import ServiceObservationCoordinator
from .service_state_contracts import ServiceSupervisorState
from .state_transition import ServiceStateTransitionWriter
from .stop_resume import ServiceStopDisposition, ServiceStopRecoveryRequired, decide_service_stop_resume
from .supervision_contracts import ServiceProcessAdapter


class ServiceStopCoordinator:
    """Exact stop state machine only; observation and persistence are injected authorities."""

    def __init__(
        self,
        observation: ServiceObservationCoordinator,
        adapter: ServiceProcessAdapter,
        transitions: ServiceStateTransitionWriter,
    ) -> None:
        self._observation = observation
        self._adapter = adapter
        self._transitions = transitions

    def stop_exact(self, contract: ServiceLaunchContract) -> ServiceSupervisorState:
        state = self._observation.observe_state(contract)
        if state is None:
            raise RuntimeError("service supervisor state is missing")
        decision = decide_service_stop_resume(state)
        if decision.blocked:
            raise ServiceStopRecoveryRequired(state, decision)
        if decision.disposition is ServiceStopDisposition.NO_PROCESS_EFFECT:
            if state.phase is ServicePhase.EXITED:
                return state
            return self._transitions.persist(
                state,
                ServicePhase.EXITED,
                last_exit_class=ServiceExitClass.CLEAN,
            )
        assert state.process is not None
        state = self._transitions.persist(state, ServicePhase.STOPPING)
        self._adapter.stop(state.process, contract)
        return self._transitions.persist(
            state,
            ServicePhase.EXITED,
            process=None,
            last_exit_class=ServiceExitClass.CLEAN,
        )


__all__ = ["ServiceStopCoordinator"]
