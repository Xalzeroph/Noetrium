from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.experimentation.lifecycle.experiment.api import ExperimentTrialProtocolIdentity


@dataclass(frozen=True, slots=True)
class ExperimentRuntimeComponents:
    trial_protocol_identity: ExperimentTrialProtocolIdentity
    cycle_runtime: object
    run_runtime: object


__all__ = ["ExperimentRuntimeComponents"]
