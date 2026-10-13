from __future__ import annotations

from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, role


class ScopeKind(StrEnum):
    PLATFORM = "platform"
    WORKSPACE = "workspace"
    PROGRAM = "program"
    PROJECT = "project"
    EXECUTION_CUT = "execution_cut"
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
    ScopeKind.EXECUTION_CUT: ScopeKind.PROJECT,
    ScopeKind.STUDY: ScopeKind.PROJECT,
    ScopeKind.EXPERIMENT: ScopeKind.STUDY,
    ScopeKind.RUN: ScopeKind.EXPERIMENT,
    ScopeKind.BRANCH: ScopeKind.RUN,
    ScopeKind.PARTICIPANT: ScopeKind.RUN,
    ScopeKind.SESSION: ScopeKind.PARTICIPANT,
    ScopeKind.OPERATION: ScopeKind.SESSION,
}


def scope_unit(kind: ScopeKind, scope_id: str) -> NoetriumUnit:
    """Build the sole immutable semantic carrier for one ownership scope."""
    if not isinstance(kind, ScopeKind):
        raise TypeError("scope kind must be ScopeKind")
    if type(scope_id) is not str or not scope_id.strip() or scope_id != scope_id.strip():
        raise ValueError("scope_id must be non-empty canonical text")
    digest = canonical_digest({"scope_kind": kind.value, "scope_id": scope_id})
    return NoetriumUnit(
        f"scope:{kind.value}:{digest}",
        schemas=("scope",),
        attributes={
            "kind": "scope",
            "scope_kind": kind.value,
            "scope_id": scope_id,
        },
    )


def is_scope_unit(value: object) -> bool:
    return (
        type(value) is NoetriumUnit
        and value.has_schema("scope")
        and value.attribute("kind") == "scope"
    )


def scope_kind(scope: NoetriumUnit) -> ScopeKind:
    if not is_scope_unit(scope):
        raise TypeError("scope projection requires scope Unit")
    return ScopeKind(str(scope.attribute("scope_kind")))


def scope_id(scope: NoetriumUnit) -> str:
    if not is_scope_unit(scope):
        raise TypeError("scope projection requires scope Unit")
    value = scope.attribute("scope_id")
    if type(value) is not str or not value:
        raise TypeError("scope Unit has invalid scope_id")
    return value


def scope_key(scope: NoetriumUnit) -> str:
    return f"{scope_kind(scope).value}:{scope_id(scope)}"


_LIVE_LEASE_SCOPE_KINDS = frozenset(
    {
        ScopeKind.EXECUTION_CUT,
        ScopeKind.RUN,
        ScopeKind.BRANCH,
        ScopeKind.PARTICIPANT,
        ScopeKind.SESSION,
        ScopeKind.OPERATION,
    }
)


def expected_parent_kind(scope: NoetriumUnit) -> ScopeKind | None:
    return _PARENT_KIND[scope_kind(scope)]


def scope_requires_live_lease(scope: NoetriumUnit) -> bool:
    """Whether dynamic use of this scope requires an Authority TTL lease."""
    return scope_kind(scope) in _LIVE_LEASE_SCOPE_KINDS


def validate_scope_parent(
    scope: NoetriumUnit,
    parent: NoetriumUnit | None,
) -> None:
    expected = expected_parent_kind(scope)
    if expected is None:
        if scope != PLATFORM_SCOPE or parent is not None:
            raise ValueError("platform scope has one fixed root identity")
        return
    if parent is None:
        raise ValueError("non-platform scope requires explicit parent")
    actual = scope_kind(parent)
    if actual is not expected:
        raise ValueError(
            f"invalid scope parent: {scope_kind(scope).value} requires "
            f"{expected.value}, got {actual.value}"
        )


def scope_link_unit(scope: NoetriumUnit, parent: NoetriumUnit) -> NoetriumUnit:
    """Represent immutable containment as a Unit relation, never registry truth."""
    validate_scope_parent(scope, parent)
    digest = canonical_digest({"child": scope.unit_digest, "parent": parent.unit_digest})
    return NoetriumUnit(
        f"scope-link:{digest}",
        schemas=("scope.link",),
        attributes={"kind": "scope.link"},
        roles=(role("child", scope), role("parent", parent)),
    )


PLATFORM_SCOPE = scope_unit(ScopeKind.PLATFORM, "default")


__all__ = [
    "PLATFORM_SCOPE",
    "ScopeKind",
    "expected_parent_kind",
    "is_scope_unit",
    "scope_id",
    "scope_key",
    "scope_kind",
    "scope_link_unit",
    "scope_requires_live_lease",
    "scope_unit",
    "validate_scope_parent",
]
