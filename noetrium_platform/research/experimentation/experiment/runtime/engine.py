from __future__ import annotations

from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity, DecisionCycleIdentityProvider
from noetrium_platform.research.execution.decision.cycle_result import DecisionCycleResult
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity, RunIdentityProvider
from noetrium_platform.research.experimentation.run.api import RunSessionPort
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec, ExperimentTrialProtocolIdentityMismatch

from .components import ExperimentRuntimeComponents
from .trial_protocol_identity import verify_trial_protocol_identity


class ExperimentRuntime:
    """Domain Experiment runtime over pre-composed runtime components."""

    def __init__(
        self,
        components: ExperimentRuntimeComponents,
        *,
        run_identity_provider: RunIdentityProvider,
        cycle_identity_provider: DecisionCycleIdentityProvider,
    ) -> None:
        self._components = components
        self.cycle_identity_provider = cycle_identity_provider
        self.run_identity_provider = run_identity_provider

    @property
    def trial_protocol_identity(self):
        return self._components.trial_protocol_identity

    @property
    def cycle_runtime(self):
        return self._components.cycle_runtime

    @property
    def run_runtime(self):
        return self._components.run_runtime

    def open_run(
        self,
        spec: ExperimentSpec,
        *,
        run_identity: RunIdentity | None = None,
        restore_checkpoint_id: str | None = None,
        restore_cycle_identity: DecisionCycleIdentity | None = None,
    ) -> RunSessionPort:
        verify_trial_protocol_identity(spec, self.trial_protocol_identity)
        identity = run_identity or self.run_identity_provider.allocate()
        return self.run_runtime.open(
            spec,
            identity,
            restore_checkpoint_id=restore_checkpoint_id,
            restore_cycle_identity=restore_cycle_identity,
        )

    def execute_cycle(
        self,
        spec: ExperimentSpec,
        *,
        task: object,
        input_kind: str = "input",
        input_payload: object = None,
        cycle_identity: DecisionCycleIdentity | None = None,
    ) -> DecisionCycleResult:
        verify_trial_protocol_identity(spec, self.trial_protocol_identity)
        identity = cycle_identity or self.cycle_identity_provider.allocate()
        return self.cycle_runtime.run(
            spec,
            identity,
            task=task,
            input_kind=input_kind,
            input_payload=input_payload,
        )


__all__ = ["ExperimentRuntime"]
