from __future__ import annotations
from dataclasses import dataclass
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind

@dataclass(frozen=True, slots=True)
class StudySpec:
    study_id: str
    project_id: str
    name: str
    experiment_ids: tuple[str, ...]
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.study_id.strip() or not self.project_id.strip() or not self.name.strip():
            raise ValueError("study_id, project_id and name must be non-empty")
        if len(set(self.experiment_ids)) != len(self.experiment_ids):
            raise ValueError("duplicate experiment_ids")

    @property
    def scope(self) -> ScopeIdentity:
        return ScopeIdentity(ScopeKind.STUDY, self.study_id)

    def identity_digest(self) -> str:
        return canonical_digest(self)

__all__=["StudySpec"]
