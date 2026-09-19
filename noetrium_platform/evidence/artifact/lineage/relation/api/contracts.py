from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.foundation.kernel.kernel import strict_finite_json_digest as canonical_digest


def _content_document(value: ArtifactContentIdentity) -> dict[str, str]:
    return {
        "artifact_id": value.artifact_id,
        "content_sha256": value.content_sha256,
    }


@dataclass(frozen=True, slots=True)
class ArtifactLineageEdge:
    parent: ArtifactContentIdentity
    child: ArtifactContentIdentity
    relation_type: str
    evidence_refs: tuple[ArtifactContentIdentity, ...] = ()

    def __post_init__(self) -> None:
        if type(self.parent) is not ArtifactContentIdentity:
            raise TypeError("artifact lineage parent must be ArtifactContentIdentity")
        if type(self.child) is not ArtifactContentIdentity:
            raise TypeError("artifact lineage child must be ArtifactContentIdentity")
        if type(self.relation_type) is not str or not self.relation_type.strip():
            raise ValueError("artifact lineage relation_type must be non-empty")
        if self.parent.artifact_id == self.child.artifact_id:
            raise ValueError("artifact lineage cannot contain a self-edge")
        if any(type(ref) is not ArtifactContentIdentity for ref in self.evidence_refs):
            raise TypeError("artifact lineage evidence refs must be ArtifactContentIdentity values")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("artifact lineage evidence refs must be unique")
        ordered = tuple(
            sorted(self.evidence_refs, key=lambda ref: (ref.artifact_id, ref.content_sha256))
        )
        if self.evidence_refs != ordered:
            raise ValueError("artifact lineage evidence refs must be canonically ordered")

    @property
    def edge_id(self) -> str:
        return canonical_digest(
            {
                "parent": _content_document(self.parent),
                "child": _content_document(self.child),
                "relation_type": self.relation_type,
                "evidence_refs": tuple(_content_document(ref) for ref in self.evidence_refs),
            }
        )


class ArtifactLineageCycle(RuntimeError):
    pass


class ArtifactLineageConflict(RuntimeError):
    pass


class ArtifactLineageCorruptionError(RuntimeError):
    pass


__all__ = [
    "ArtifactLineageConflict",
    "ArtifactLineageCorruptionError",
    "ArtifactLineageCycle",
    "ArtifactLineageEdge",
]
