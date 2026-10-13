from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from noetrium_platform.foundation.kernel.kernel.canonical import canonical_digest


class SemanticBoundaryClassification(str, Enum):
    DECLARATIVE_ONLY = "declarative_only"
    IMPLEMENTED_SEMANTIC_BOUNDARY = "implemented_semantic_boundary"
    DELETE_CANDIDATE = "delete_candidate"


class SemanticStateAuthorityKind(str, Enum):
    NONE = "none"
    GENERIC_LEAF_STATE = "generic_leaf_state"
    DOMAIN_TYPED = "domain_typed"


class SemanticBoundaryClaimError(ValueError):
    """A boundary claim is stronger than the source evidence permits."""


@dataclass(frozen=True, slots=True)
class SemanticBoundaryEvidence:
    node: str
    package_prefix: str
    classification: SemanticBoundaryClassification
    generic_leaf_runtime: bool
    generic_state_capable: bool
    semantic_source_files: tuple[str, ...]
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    components: tuple[str, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class SemanticBoundaryClaim:
    node: str
    implemented: bool
    state_authority: SemanticStateAuthorityKind = SemanticStateAuthorityKind.NONE


def validate_semantic_boundary_claim(
    evidence: SemanticBoundaryEvidence,
    claim: SemanticBoundaryClaim,
) -> None:
    if claim.node != evidence.node:
        raise SemanticBoundaryClaimError("semantic boundary claim node does not match evidence")
    if claim.implemented and evidence.classification is not SemanticBoundaryClassification.IMPLEMENTED_SEMANTIC_BOUNDARY:
        raise SemanticBoundaryClaimError(
            "generic/declarative boundary cannot claim implemented semantic authority"
        )
    if claim.state_authority is SemanticStateAuthorityKind.GENERIC_LEAF_STATE:
        raise SemanticBoundaryClaimError(
            "generic leaf state cannot be claimed as domain durable authority"
        )


__all__ = [
    "SemanticBoundaryClaim",
    "SemanticBoundaryClaimError",
    "SemanticBoundaryClassification",
    "SemanticBoundaryEvidence",
    "SemanticStateAuthorityKind",
    "validate_semantic_boundary_claim",
]
