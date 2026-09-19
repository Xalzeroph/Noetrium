from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.api import ExperimentRunSpec
from noetrium_platform.research.experimentation.run.control.api import RunControlTarget
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.manifest.api import RunLaunchManifest
from noetrium_platform.research.experimentation.study.api import StudyProtocol
from noetrium_platform.foundation.kernel.kernel import canonical_digest

_HEX = frozenset("0123456789abcdef")


class ProjectIdentityProjection(Protocol):
    project_id: str


class ProjectManifestProjection(Protocol):
    identity: ProjectIdentityProjection
    semantic_digest: str
    study_ids: tuple[str, ...]


def _project_manifest_identity(manifest: ProjectManifestProjection) -> tuple[str, str, tuple[str, ...]]:
    identity = getattr(manifest, "identity", None)
    project_id = getattr(identity, "project_id", None)
    digest = getattr(manifest, "semantic_digest", None)
    study_ids = getattr(manifest, "study_ids", None)
    if type(project_id) is not str or not project_id.strip():
        raise TypeError("project manifest projection requires identity.project_id")
    if type(digest) is not str or len(digest) != 64 or any(ch not in _HEX for ch in digest):
        raise TypeError("project manifest projection requires canonical semantic_digest")
    if type(study_ids) is not tuple or any(type(item) is not str or not item.strip() for item in study_ids):
        raise TypeError("project manifest projection requires typed study_ids")
    return project_id, digest, study_ids


@dataclass(frozen=True, slots=True)
class ProjectRunDefinition:
    """Project-facing identity join for one canonical project Experiment/Study/Run launch.

    This contract consumes only the narrow ROLE01 ProjectManifest projection it
    needs; it neither parses nor persists project-manifest authority.
    """

    project_manifest: ProjectManifestProjection
    experiment: ExperimentSpec
    study: StudyProtocol
    run: ExperimentRunSpec
    identity: RunIdentity
    manifest: RunLaunchManifest
    definition_digest: str = field(init=False)

    def __post_init__(self) -> None:
        project_id, project_digest, study_ids = _project_manifest_identity(self.project_manifest)
        expected = (
            (self.experiment, ExperimentSpec, "experiment"),
            (self.study, StudyProtocol, "study"),
            (self.run, ExperimentRunSpec, "run"),
            (self.identity, RunIdentity, "identity"),
            (self.manifest, RunLaunchManifest, "manifest"),
        )
        for value, value_type, field_name in expected:
            if type(value) is not value_type:
                raise TypeError(f"project run {field_name} must be {value_type.__name__}")

        if not (self.run.project_id == self.experiment.project_id == project_id):
            raise ValueError("project run project identity drifted")
        if self.run.experiment_id != self.experiment.experiment_id:
            raise ValueError("project run experiment identity drifted")
        if not (self.run.study_id == self.experiment.study_id == self.study.study_id):
            raise ValueError("project run study identity drifted")
        if self.study.study_id not in study_ids:
            raise ValueError("project run study is not declared by ProjectManifest")
        if not (
            self.run.repetitions == self.experiment.repetitions == self.study.repetitions
        ):
            raise ValueError("project run repetition contract drifted")
        if self.run.task_manifest_digest != self.study.task_manifest_digest:
            raise ValueError("project run task manifest identity drifted")
        if self.run.seed_schedule_digest != self.study.seed_schedule_digest:
            raise ValueError("project run seed schedule identity drifted")
        if self.run.model_roles_digest != self.experiment.model_roles_digest:
            raise ValueError("project run model role identity drifted")
        if self.identity.run_id != self.run.run_id:
            raise ValueError("project run RunIdentity does not match ExperimentRunSpec")

        experiment_digest = self.experiment.identity_digest()
        if self.manifest.project_manifest_digest != project_digest:
            raise ValueError("project run launch manifest does not bind the ProjectManifest")
        if self.manifest.experiment_spec_digest != experiment_digest:
            raise ValueError("project run launch manifest does not bind the ExperimentSpec")
        object.__setattr__(
            self,
            "definition_digest",
            canonical_digest(
                {
                    "project_manifest": project_digest,
                    "experiment": experiment_digest,
                    "study": self.study.protocol_digest,
                    "run": self.run.identity_digest(),
                    "identity": self.identity.digest(),
                    "manifest": self.manifest.digest(),
                }
            ),
        )

    @property
    def run_manifest_digest(self) -> str:
        return self.manifest.digest()

    def control_target(self, expected_generation: int | None = None) -> RunControlTarget:
        return RunControlTarget(
            self.identity.run_id,
            self.run_manifest_digest,
            expected_generation,
        )


__all__ = [
    "ProjectIdentityProjection",
    "ProjectManifestProjection",
    "ProjectRunDefinition",
]
