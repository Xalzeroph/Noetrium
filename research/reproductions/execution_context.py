from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
)


@dataclass(frozen=True, slots=True)
class ReproductionFleetExecutionContext:
    """One shared platform runtime for repository fleet authority factories.

    Scientific factories receive this context rather than constructing their own
    Docker, endpoint, compute, environment, model, workspace or execution-pool
    authorities.
    """

    state_root: Path
    runtime: ManagedResearchRuntime

    def __post_init__(self) -> None:
        if type(self.state_root) is not Path:
            raise TypeError("fleet execution context state_root must be pathlib.Path")
        if not isinstance(self.runtime, ManagedResearchRuntime):
            raise TypeError(
                "fleet execution context runtime must be ManagedResearchRuntime"
            )

    @property
    def execution_pool(self):
        return self.runtime.execution_pool

    @property
    def management(self):
        return self.runtime.management

    @property
    def resources(self):
        return self.runtime.resources

    @property
    def model_replica_pool(self):
        return self.runtime.model_replica_pool


__all__ = ["ReproductionFleetExecutionContext"]
