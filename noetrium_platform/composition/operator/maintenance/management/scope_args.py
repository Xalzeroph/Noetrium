from __future__ import annotations

from noetrium_platform.foundation.scope.api import (
    NoetriumUnit,
    ScopeKind,
    scope_from_data,
    scope_unit,
)


def add_scope_arguments(parser, *, default_kind: ScopeKind = ScopeKind.PLATFORM, default_id: str = "default") -> None:
    parser.add_argument("--scope-kind", choices=[kind.value for kind in ScopeKind], default=default_kind.value)
    parser.add_argument("--scope-id", default=default_id)


def scope_from_args(args) -> NoetriumUnit:
    return scope_unit(ScopeKind(args.scope_kind), str(args.scope_id))


def scope_from_json(data: object) -> NoetriumUnit:
    try:
        return scope_from_data(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("deployment JSON requires canonical scope object") from exc


__all__ = ["add_scope_arguments", "scope_from_args", "scope_from_json"]
