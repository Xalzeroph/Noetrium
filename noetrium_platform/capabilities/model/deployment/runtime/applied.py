from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentSpec
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.substrate.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)


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
    process: ServiceProcessIdentity

    @property
    def runtime_digest(self) -> str:
        """Exact applied physical lifetime: frozen contract + OS process identity."""

        return canonical_digest(
            {
                "contract_digest": self.contract.digest(),
                "process": self.process,
            }
        )


__all__ = ["AppliedModelDeployment"]
