from __future__ import annotations

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


def add_scope_arguments(parser, *, default_kind: ScopeKind = ScopeKind.PLATFORM, default_id: str = "default") -> None:
    parser.add_argument("--scope-kind", choices=[kind.value for kind in ScopeKind], default=default_kind.value)
    parser.add_argument("--scope-id", default=default_id)


def scope_from_args(args) -> ScopeIdentity:
    return ScopeIdentity(ScopeKind(args.scope_kind), str(args.scope_id))


def scope_from_json(data: object) -> ScopeIdentity:
    if not isinstance(data, dict):
        raise ValueError("deployment JSON requires scope object")
    kind = data.get("kind")
    scope_id = data.get("scope_id")
    if not isinstance(kind, str) or not isinstance(scope_id, str):
        raise ValueError("scope requires string kind and scope_id")
    return ScopeIdentity(ScopeKind(kind), scope_id)


__all__ = ["add_scope_arguments", "scope_from_args", "scope_from_json"]
