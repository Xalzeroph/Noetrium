from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.architecture.repository_boundary.api import RepositoryBoundaryAuditor
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort
from noetrium_platform.product.operator.api import (
    ProjectCreateReceipt,
    ProjectCreateRequest,
    ProjectDoctorReport,
    ProjectSyncReceipt,
    ProjectTestReceipt,
)
from noetrium_platform.composition.operator.project.project_doctor import doctor_project
from noetrium_platform.composition.operator.project.project_scaffold import (
    create_project,
    sync_project,
)
from noetrium_platform.composition.operator.project.project_testing import test_project


class LocalProjectExperience:
    """Filesystem product adapter; project/domain truth remains producer-owned."""

    def __init__(
        self,
        boundary_auditor: RepositoryBoundaryAuditor,
        command_runner: LocalCommandRunnerPort,
    ) -> None:
        if not callable(boundary_auditor):
            raise TypeError("boundary_auditor must be callable")
        self._boundary_auditor = boundary_auditor
        self._command_runner = command_runner

    def create(self, request: ProjectCreateRequest) -> ProjectCreateReceipt:
        return create_project(request)

    def sync(self, project_root: Path) -> ProjectSyncReceipt:
        return sync_project(project_root)

    def doctor(self, project_root: Path) -> ProjectDoctorReport:
        return doctor_project(
            project_root,
            boundary_auditor=self._boundary_auditor,
            command_runner=self._command_runner,
        )

    def test(self, project_root: Path) -> ProjectTestReceipt:
        return test_project(
            project_root,
            command_runner=self._command_runner,
        )


__all__ = [
    "LocalProjectExperience",
    "create_project",
    "sync_project",
    "doctor_project",
    "test_project",
]
