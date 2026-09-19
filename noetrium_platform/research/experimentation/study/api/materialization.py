from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path

from .trial import TaskVerifierArtifact


@dataclass(frozen=True, slots=True)
class MaterializedTaskVerifierArchive:
    """Operational receipt for one verified verifier-artifact archive expansion."""

    artifact: TaskVerifierArtifact
    destination: str
    content_sha256: str
    tree_sha256: str
    file_count: int
    expanded_size: int
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.artifact) is not TaskVerifierArtifact:
            raise TypeError(
                "materialized verifier archive requires TaskVerifierArtifact"
            )
        if (
            type(self.destination) is not str
            or not is_absolute_target_path(self.destination)
        ):
            raise ValueError(
                "materialized verifier archive destination must be absolute"
            )
        object.__setattr__(
            self,
            "content_sha256",
            require_sha256(
                self.content_sha256,
                "materialized verifier archive content_sha256",
            ),
        )
        object.__setattr__(
            self,
            "tree_sha256",
            require_sha256(
                self.tree_sha256,
                "materialized verifier archive tree_sha256",
            ),
        )
        if (
            type(self.file_count) is not int
            or self.file_count < 0
            or type(self.expanded_size) is not int
            or self.expanded_size < 0
        ):
            raise ValueError(
                "materialized verifier archive counts must be non-negative"
            )
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest({
                "artifact_digest": self.artifact.artifact_digest,
                "content_sha256": self.content_sha256,
                "tree_sha256": self.tree_sha256,
                "file_count": self.file_count,
                "expanded_size": self.expanded_size,
            }),
        )


@runtime_checkable
class TaskVerifierArchiveMaterializationPort(Protocol):
    """Verify one declared artifact and expand it into caller-owned workspace."""

    def materialize(
        self,
        artifact: TaskVerifierArtifact,
        *,
        destination: str,
        required_relative_paths: tuple[str, ...] = (),
    ) -> MaterializedTaskVerifierArchive: ...


__all__ = [
    "MaterializedTaskVerifierArchive",
    "TaskVerifierArchiveMaterializationPort",
]
