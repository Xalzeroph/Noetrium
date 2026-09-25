from __future__ import annotations

from noetrium_platform.foundation.governance.architecture.repository_boundary.runtime import audit_downstream_project_imports
from noetrium_platform.product.operator.api import ProjectFacade
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort
from noetrium_platform.composition.operator.project import LocalProjectExperience


def build_project_facade(
    command_runner: LocalCommandRunnerPort,
) -> ProjectFacade:
    """Build the local downstream-project facade from explicit authorities."""

    return ProjectFacade(
        LocalProjectExperience(
            audit_downstream_project_imports,
            command_runner,
        )
    )


__all__ = ["build_project_facade"]
