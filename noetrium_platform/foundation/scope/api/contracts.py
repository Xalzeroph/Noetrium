from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScopeKind(StrEnum):
    PLATFORM = "platform"
    WORKSPACE = "workspace"
    PROGRAM = "program"
    PROJECT = "project"
    STUDY = "study"
    EXPERIMENT = "experiment"
    RUN = "run"
    BRANCH = "branch"
    PARTICIPANT = "participant"
    SESSION = "session"
    OPERATION = "operation"


_PARENT_KIND: dict[ScopeKind, ScopeKind | None] = {
    ScopeKind.PLATFORM: None,
    ScopeKind.WORKSPACE: ScopeKind.PLATFORM,
    ScopeKind.PROGRAM: ScopeKind.WORKSPACE,
    ScopeKind.PROJECT: ScopeKind.PROGRAM,
    ScopeKind.STUDY: ScopeKind.PROJECT,
    ScopeKind.EXPERIMENT: ScopeKind.STUDY,
    ScopeKind.RUN: ScopeKind.EXPERIMENT,
    ScopeKind.BRANCH: ScopeKind.RUN,
    ScopeKind.PARTICIPANT: ScopeKind.RUN,
    ScopeKind.SESSION: ScopeKind.PARTICIPANT,
    ScopeKind.OPERATION: ScopeKind.SESSION,
}


@dataclass(frozen=True, slots=True, order=True)
class ScopeIdentity:
    kind: ScopeKind
    scope_id: str

    def __post_init__(self) -> None:
        if not self.scope_id.strip():
            raise ValueError("scope_id must be non-empty")

    @property
    def key(self) -> str:
        return f"{self.kind.value}:{self.scope_id}"

    @property
    def expected_parent_kind(self) -> ScopeKind | None:
        return _PARENT_KIND[self.kind]


PLATFORM_SCOPE = ScopeIdentity(ScopeKind.PLATFORM, "default")


@dataclass(frozen=True, slots=True)
class ScopeLink:
    child: ScopeIdentity
    parent: ScopeIdentity

    def __post_init__(self) -> None:
        expected = self.child.expected_parent_kind
        if expected is None:
            raise ValueError("platform scope cannot have a parent")
        if self.parent.kind is not expected:
            raise ValueError(
                f"invalid scope parent: {self.child.kind.value} requires {expected.value}, "
                f"got {self.parent.kind.value}"
            )


__all__ = ["PLATFORM_SCOPE", "ScopeIdentity", "ScopeKind", "ScopeLink"]
