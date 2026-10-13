from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .contracts import ScopeKind, scope_id, scope_kind, scope_unit


def scope_to_data(scope: NoetriumUnit) -> dict[str, str]:
    return {"kind": scope_kind(scope).value, "scope_id": scope_id(scope)}


def scope_from_data(data: object) -> NoetriumUnit:
    if not isinstance(data, Mapping):
        raise ValueError(
            "scope payload must be an object; "
            f"got {type(data).__name__}: {data!r}"
        )
    kind = data.get("kind")
    identity = data.get("scope_id")
    if not isinstance(kind, str) or not isinstance(identity, str):
        raise ValueError("scope payload requires string kind and scope_id")
    return scope_unit(ScopeKind(kind), identity)


__all__ = ["scope_from_data", "scope_to_data"]
