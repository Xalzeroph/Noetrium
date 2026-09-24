from __future__ import annotations

from noetrium_platform.research.execution.api import DecisionCycleIdentity, DecisionCycleIdentityProvider
from noetrium_platform.research.execution.api import DecisionCycleResult
from noetrium_platform.research.experimentation.lifecycle.run.api.identity import RunIdentity
from noetrium_platform.research.experimentation.lifecycle.experiment.api import ExperimentSpec, ExperimentTrialProtocolIdentityMismatch

from .trial_protocol_identity import verify_trial_protocol_identity


class ExperimentRuntime:
    """Domain Experiment runtime over pre-composed runtime components."""

    def __init__(
        self,
        trial_protocol_identity: object,
        cycle_runtime: object,
        run_runtime: object,
        *,
        run_identity_provider: object,
        cycle_identity_provider: DecisionCycleIdentityProvider,
    ) -> None:
        self.trial_protocol_identity = trial_protocol_identity
        self.cycle_runtime = cycle_runtime
        self.run_runtime = run_runtime
        self.cycle_identity_provider = cycle_identity_provider
        self.run_identity_provider = run_identity_provider

    def open_run(
        self,
        spec: ExperimentSpec,
        *,
        run_identity: RunIdentity | None = None,
        restore_checkpoint_id: str | None = None,
        restore_cycle_identity: DecisionCycleIdentity | None = None,
    ) -> object:
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
