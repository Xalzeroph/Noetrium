from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.experimentation.run.api import DecisionCycleRuntimePort, RunRuntimePort
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity


@dataclass(frozen=True, slots=True)
class ExperimentRuntimeComponents:
    trial_protocol_identity: ExperimentTrialProtocolIdentity
    cycle_runtime: DecisionCycleRuntimePort
    run_runtime: RunRuntimePort


__all__ = ["ExperimentRuntimeComponents"]
