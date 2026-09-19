from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract


@dataclass(frozen=True, slots=True)
class AppliedModelDeployment:
    """Exact operational snapshot used to manage an already-applied process.

    Mutable model/environment registries are deliberately not consulted when an
    existing process is reconciled or stopped.  This record keeps the exact
    launch contract and child environment that produced that process.
    """

    spec: ModelDeploymentSpec
    contract: ServiceLaunchContract
    environment: tuple[tuple[str, str], ...]


__all__ = ["AppliedModelDeployment"]
