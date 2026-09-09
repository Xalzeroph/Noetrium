from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.participant.core.api import BoundParticipants, ParticipantSessionBinding
from noetrium_platform.research.execution.workflow.api import (
    EffectIntentOperationPort,
    OperationDispatchPort,
    TrialCycleExecution,
    WorkflowSurfaceBindingContext,
    WorkflowSurfaceFactory,
    WorkflowSurfaceReuseScope,
    workflow_surface_id,
)
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocol

from .workflow_surfaces import ExperimentWorkflowSurfaceRegistry


class ExperimentTrialCycleExecutor:
    """Binds generic operation ports to an injected trial protocol."""

    def __init__(
        self,
        dispatcher: OperationDispatchPort,
        trial_protocol: ExperimentTrialProtocol,
        *,
        effect_intents: EffectIntentOperationPort | None = None,
        workflow_surface_factories: tuple[WorkflowSurfaceFactory, ...] = (),
    ) -> None:
        self.dispatcher = dispatcher
        self.trial_protocol = trial_protocol
        self.effect_intents = effect_intents
        self._surface_registry = ExperimentWorkflowSurfaceRegistry(workflow_surface_factories)
        self._run_surface_key: tuple[object, ...] | None = None
        self._run_surface: object | None = None

    def _surface_for(
        self,
        *,
        surface_id: str,
        run_id: str,
        surface_context: WorkflowSurfaceBindingContext,
    ) -> object:
        if self._surface_registry.reuse_scope(surface_id) is not WorkflowSurfaceReuseScope.RUN:
            return self._surface_registry.bind(surface_id, surface_context)

        # RunSession executes cycles serially.  Keeping one active run binding
        # avoids rebuilding all workflow collaborators for every cycle while
        # ensuring a new run never inherits the prior run's mutable recovery
        # state.  Unknown/custom surfaces remain cycle-scoped above.
        key = (
            surface_id,
            run_id,
            id(surface_context.bound),
            id(surface_context.participant_sessions),
            id(surface_context.effect_intents),
        )
        if self._run_surface_key != key or self._run_surface is None:
            self._run_surface = self._surface_registry.bind(surface_id, surface_context)
            self._run_surface_key = key
        return self._run_surface

    def execute(
        self,
        *,
        bound: BoundParticipants,
        participant_sessions: tuple[ParticipantSessionBinding, ...],
        context: ExecutionContext,
        task: object,
        input_kind: str,
        input_payload: object,
    ) -> TrialCycleExecution:
        surface_context = WorkflowSurfaceBindingContext(
            self.dispatcher,
            bound,
            participant_sessions,
            self.effect_intents,
        )
        surface = self._surface_for(
            surface_id=workflow_surface_id(self.trial_protocol),
            run_id=context.run_id,
            surface_context=surface_context,
        )
        result = self.trial_protocol.run(
            surface,
            context,
            task=task,
            input_kind=input_kind,
            input_payload=input_payload,
        )
        if not isinstance(result, TrialCycleExecution):
            raise TypeError("ExperimentTrialProtocol must return TrialCycleExecution")
        return result


__all__ = ["ExperimentTrialCycleExecutor"]
