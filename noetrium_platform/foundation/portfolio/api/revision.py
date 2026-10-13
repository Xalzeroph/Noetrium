from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")


def _token(value: object, field: str) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a canonical token")
    return value


@dataclass(frozen=True, slots=True)
class PortfolioRevision:
    """Immutable Git-like metadata for one portfolio-owned subject.

    semantic_digest identifies the scientific definition. payload_digest is only
    the content-addressed byte representation used to retrieve it. Keeping these
    identities separate lets recursive Merkle structures revise locally without
    reserializing the whole payload just to determine semantic identity.
    """

    subject_id: str
    payload_digest: str
    payload_size_bytes: int
    parent_revision_digests: tuple[str, ...] = ()
    message: str = ""
    semantic_digest: str | None = None
    revision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.subject_id, "portfolio revision subject_id")
        require_sha256(self.payload_digest, "portfolio revision payload_digest")
        if type(self.payload_size_bytes) is not int or self.payload_size_bytes < 0:
            raise ValueError("portfolio revision payload_size_bytes must be non-negative")
        if type(self.parent_revision_digests) is not tuple:
            raise TypeError("portfolio revision parents must be a tuple")
        for parent in self.parent_revision_digests:
            require_sha256(parent, "portfolio revision parent")
        if len(self.parent_revision_digests) != len(set(self.parent_revision_digests)):
            raise ValueError("portfolio revision parents must be unique")
        if type(self.message) is not str:
            raise TypeError("portfolio revision message must be text")
        semantic = (
            self.payload_digest
            if self.semantic_digest is None
            else require_sha256(
                self.semantic_digest,
                "portfolio revision semantic_digest",
            )
        )
        object.__setattr__(self, "semantic_digest", semantic)
        object.__setattr__(
            self,
            "revision_digest",
            canonical_digest(
                {
                    "subject_id": self.subject_id,
                    "semantic_digest": semantic,
                    "parents": self.parent_revision_digests,
                    "message": self.message,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioBranchRef:
    subject_id: str
    name: str
    revision_digest: str
    generation: int

    def __post_init__(self) -> None:
        _token(self.subject_id, "portfolio branch subject_id")
        _token(self.name, "portfolio branch name")
        require_sha256(self.revision_digest, "portfolio branch revision_digest")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("portfolio branch generation must be positive")


@dataclass(frozen=True, slots=True)
class PortfolioTagRef:
    subject_id: str
    name: str
    revision_digest: str

    def __post_init__(self) -> None:
        _token(self.subject_id, "portfolio tag subject_id")
        _token(self.name, "portfolio tag name")
        require_sha256(self.revision_digest, "portfolio tag revision_digest")


class PortfolioRevisionConflict(RuntimeError):
    pass


class PortfolioRevisionNotFound(KeyError):
    pass


@runtime_checkable
class PortfolioRevisionStorePort(Protocol):
    def commit(self, revision: PortfolioRevision) -> PortfolioRevision: ...

    def revision(
        self,
        subject_id: str,
        revision_digest: str,
    ) -> PortfolioRevision: ...

    def move_branch(
        self,
        subject_id: str,
        name: str,
        revision_digest: str,
        *,
        expected_revision_digest: str | None,
    ) -> PortfolioBranchRef: ...

    def branch(self, subject_id: str, name: str) -> PortfolioBranchRef: ...

    def tag(
        self,
        subject_id: str,
        name: str,
        revision_digest: str,
    ) -> PortfolioTagRef: ...

    def resolve_tag(self, subject_id: str, name: str) -> PortfolioTagRef: ...


__all__ = [
    "PortfolioBranchRef",
    "PortfolioRevision",
    "PortfolioRevisionConflict",
    "PortfolioRevisionNotFound",
    "PortfolioRevisionStorePort",
    "PortfolioTagRef",
]
