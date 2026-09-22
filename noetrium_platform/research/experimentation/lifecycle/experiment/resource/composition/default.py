from __future__ import annotations

from noetrium_platform.research.execution.api import ComputeLeaseGuardFactoryPort, ComputeSchedulerPort
from noetrium_platform.research.experimentation.lifecycle.experiment.resource.api import ExperimentResourceBinderPort
from noetrium_platform.research.experimentation.lifecycle.experiment.resource.runtime import ExperimentResourceBinder


def build_experiment_resource_binder(
    scheduler: ComputeSchedulerPort | None = None,
    lease_guard_factory: ComputeLeaseGuardFactoryPort | None = None,
) -> ExperimentResourceBinderPort:
    return ExperimentResourceBinder(scheduler, lease_guard_factory)


__all__ = ["build_experiment_resource_binder"]
