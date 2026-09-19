from __future__ import annotations

from .contracts import ScopeIdentity, ScopeKind


def scope_to_data(scope: ScopeIdentity) -> dict[str, str]:
    return {"kind": scope.kind.value, "scope_id": scope.scope_id}


def scope_from_data(data: object) -> ScopeIdentity:
    if not isinstance(data, dict):
        raise ValueError("scope payload must be an object")
    kind = data.get("kind")
    scope_id = data.get("scope_id")
    if not isinstance(kind, str) or not isinstance(scope_id, str):
        raise ValueError("scope payload requires string kind and scope_id")
    return ScopeIdentity(ScopeKind(kind), scope_id)


__all__ = ["scope_from_data", "scope_to_data"]
