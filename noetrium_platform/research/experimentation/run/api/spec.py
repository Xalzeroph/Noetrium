from __future__ import annotations

from dataclasses import dataclass
import re

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


@dataclass(frozen=True, slots=True)
class ExperimentRunSpec:
    """Immutable, environment-neutral identity of one experiment run.

    The specification deliberately contains no server, model-client, process
    or filesystem-provider object. Those are selected by an outer composition
    root and are represented here only by frozen identities/digests. MC and
    non-MC adapters therefore consume the same run identity without sharing
    provider details.
    """

    run_id: str
    project_id: str
    experiment_id: str
    study_id: str
    execution_profile: str
    task_manifest_digest: str
    seed_schedule_digest: str
    repetitions: int
    artifact_root: str
    environment_identity_digest: str
    model_roles_digest: str

    def __post_init__(self) -> None:
        required = (
            self.run_id,
            self.project_id,
            self.experiment_id,
            self.study_id,
            self.execution_profile,
            self.task_manifest_digest,
            self.seed_schedule_digest,
            self.artifact_root,
            self.environment_identity_digest,
        )
        if any(not value.strip() for value in required):
            raise ValueError("experiment run specification contains an empty identity")
        if re.fullmatch(r"[A-Za-z0-9_.:-]+", self.execution_profile) is None:
            raise ValueError("experiment run execution_profile is not a safe identity")
        require_sha256(self.task_manifest_digest, "experiment run task_manifest_digest")
        require_sha256(self.seed_schedule_digest, "experiment run seed_schedule_digest")
        require_sha256(self.environment_identity_digest, "experiment run environment_identity_digest")
        if self.repetitions <= 0:
            raise ValueError("experiment run repetitions must be positive")
        require_sha256(self.model_roles_digest, "experiment run model_roles_digest")

    def scientific_identity_digest(self) -> str:
        return canonical_digest({
            "run_id": self.run_id, "project_id": self.project_id,
            "experiment_id": self.experiment_id, "study_id": self.study_id,
            "task_manifest_digest": self.task_manifest_digest,
            "seed_schedule_digest": self.seed_schedule_digest,
            "repetitions": self.repetitions,
            "model_roles_digest": self.model_roles_digest,
        })

    def execution_placement_digest(self) -> str:
        return canonical_digest({
            "execution_profile": self.execution_profile,
            "artifact_root": self.artifact_root,
            "environment_identity_digest": self.environment_identity_digest,
        })

    def identity_digest(self) -> str:
        return canonical_digest({
            "scientific_identity_digest": self.scientific_identity_digest(),
            "execution_placement_digest": self.execution_placement_digest(),
        })


__all__ = ["ExperimentRunSpec"]
