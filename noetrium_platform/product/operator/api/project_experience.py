from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from noetrium_platform.foundation.portfolio.api import ProjectIdentity

PROJECT_AUTHOR_TEMPLATE_REVISION = "noetrium.project-template.author.v2"
PROJECT_PROVIDER_TEMPLATE_REVISION = "noetrium.project-template.provider.v2"


class ProjectTemplateProfile(StrEnum):
    AUTHOR = "author"
    PROVIDER = "provider"


def project_template_revision(profile: ProjectTemplateProfile) -> str:
    if type(profile) is not ProjectTemplateProfile:
        raise TypeError("project template profile must be ProjectTemplateProfile")
    return {
        ProjectTemplateProfile.AUTHOR: PROJECT_AUTHOR_TEMPLATE_REVISION,
        ProjectTemplateProfile.PROVIDER: PROJECT_PROVIDER_TEMPLATE_REVISION,
    }[profile]


class ProjectDoctorDisposition(StrEnum):
    PASS = "pass"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ProjectCreateRequest:
    project_id: str
    version: str
    destination: Path
    program_id: str = "standalone"
    template_profile: ProjectTemplateProfile = ProjectTemplateProfile.AUTHOR

    def __post_init__(self) -> None:
        ProjectIdentity(self.project_id, self.version)
        if not isinstance(self.destination, Path):
            raise TypeError("project destination must be a pathlib.Path")
        if type(self.template_profile) is not ProjectTemplateProfile:
            raise TypeError("project template profile must be ProjectTemplateProfile")


@dataclass(frozen=True, slots=True)
class ProjectCreateReceipt:
    project_id: str
    version: str
    program_id: str
    destination: str
    template_profile: ProjectTemplateProfile
    template_revision: str
    manifest_path: str
    manifest_semantic_digest: str
    generated_files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectDoctorCheck:
    check_id: str
    disposition: ProjectDoctorDisposition
    summary: str
    remediation: str = ""

    def __post_init__(self) -> None:
        if not self.check_id.strip() or not self.summary.strip():
            raise ValueError("project doctor check identity/summary are required")
        if self.disposition is ProjectDoctorDisposition.BLOCKED and not self.remediation.strip():
            raise ValueError("blocked project doctor checks require remediation")


@dataclass(frozen=True, slots=True)
class ProjectDoctorReport:
    project_root: str
    template_profile: ProjectTemplateProfile | None
    template_revision: str | None
    checks: tuple[ProjectDoctorCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(
            check.disposition is ProjectDoctorDisposition.PASS for check in self.checks
        )


class ProjectTestStage(StrEnum):
    BUILD_INSTALL = "build_install"
    CONTRACT_TEST = "contract_test"


@dataclass(frozen=True, slots=True)
class ProjectTestStageReceipt:
    stage: ProjectTestStage
    command: tuple[str, ...]
    exit_code: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class ProjectTestReceipt:
    project_root: str
    stages: tuple[ProjectTestStageReceipt, ...]

    @property
    def passed(self) -> bool:
        return bool(self.stages) and all(stage.passed for stage in self.stages)


class ProjectExperiencePort(Protocol):
    """Injected product authority for downstream project experience operations."""

    def create(self, request: ProjectCreateRequest) -> ProjectCreateReceipt: ...

    def doctor(self, project_root: Path) -> ProjectDoctorReport: ...

    def test(self, project_root: Path) -> ProjectTestReceipt: ...


class ProjectFacade:
    """Topology-hiding Python facade over an explicitly injected project experience port."""

    def __init__(self, experience: ProjectExperiencePort) -> None:
        for name in ("create", "doctor", "test"):
            if not callable(getattr(experience, name, None)):
                raise TypeError(f"project experience must implement {name}()")
        self._experience = experience

    def create(
        self,
        project_id: str,
        version: str,
        destination: Path,
        *,
        program_id: str = "standalone",
        template_profile: ProjectTemplateProfile = ProjectTemplateProfile.AUTHOR,
    ) -> ProjectCreateReceipt:
        return self._experience.create(
            ProjectCreateRequest(
                project_id, version, destination, program_id, template_profile
            )
        )

    def doctor(self, project_root: Path) -> ProjectDoctorReport:
        return self._experience.doctor(project_root)

    def test(self, project_root: Path) -> ProjectTestReceipt:
        return self._experience.test(project_root)


__all__ = [
    "PROJECT_AUTHOR_TEMPLATE_REVISION",
    "PROJECT_PROVIDER_TEMPLATE_REVISION",
    "ProjectCreateReceipt",
    "ProjectCreateRequest",
    "ProjectDoctorCheck",
    "ProjectDoctorDisposition",
    "ProjectDoctorReport",
    "ProjectExperiencePort",
    "ProjectFacade",
    "ProjectTemplateProfile",
    "ProjectTestReceipt",
    "ProjectTestStage",
    "ProjectTestStageReceipt",
    "project_template_revision",
]
