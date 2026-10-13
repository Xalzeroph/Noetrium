from __future__ import annotations

from threading import RLock

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.scope.api import (
    PLATFORM_SCOPE,
    scope_key,
    scope_link_unit,
    validate_scope_parent,
)


class ScopeIndexConflict(RuntimeError):
    pass


class ScopeNotIndexed(KeyError):
    pass


class InMemoryScopeIndex:
    """Thread-safe disposable index over immutable scope/link Units."""

    def __init__(self) -> None:
        root_key = scope_key(PLATFORM_SCOPE)
        self._scopes: dict[str, NoetriumUnit] = {root_key: PLATFORM_SCOPE}
        self._parents: dict[str, str | None] = {root_key: None}
        self._children: dict[str, set[str]] = {root_key: set()}
        self._links: dict[str, NoetriumUnit] = {}
        self._lock = RLock()

    def register(self, scope: NoetriumUnit, parent: NoetriumUnit | None) -> None:
        try:
            validate_scope_parent(scope, parent)
        except (TypeError, ValueError) as exc:
            raise ScopeIndexConflict(str(exc)) from exc
        key = scope_key(scope)
        parent_key = None if parent is None else scope_key(parent)
        with self._lock:
            if parent_key is not None and parent_key not in self._scopes:
                raise ScopeNotIndexed(parent_key)
            if key in self._parents:
                if self._parents[key] != parent_key or self._scopes[key] != scope:
                    raise ScopeIndexConflict(f"scope parent already fixed: {key}")
                return
            self._scopes[key] = scope
            self._parents[key] = parent_key
            self._children.setdefault(key, set())
            if parent is not None:
                self._children.setdefault(parent_key, set()).add(key)
                link = scope_link_unit(scope, parent)
                self._links[link.unit_digest] = link

    def parent(self, scope: NoetriumUnit) -> NoetriumUnit | None:
        key = scope_key(scope)
        with self._lock:
            if key not in self._parents:
                raise ScopeNotIndexed(key)
            parent_key = self._parents[key]
            return None if parent_key is None else self._scopes[parent_key]

    def ancestry(self, scope: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
        key = scope_key(scope)
        with self._lock:
            if key not in self._parents:
                raise ScopeNotIndexed(key)
            chain: list[NoetriumUnit] = []
            seen: set[str] = set()
            current: str | None = key
            while current is not None:
                if current in seen:
                    raise ScopeIndexConflict(f"scope cycle detected at {current}")
                seen.add(current)
                chain.append(self._scopes[current])
                current = self._parents.get(current)
            if chain[-1] != PLATFORM_SCOPE:
                raise ScopeIndexConflict("scope ancestry does not terminate at platform root")
            return tuple(chain)

    def children(self, scope: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
        key = scope_key(scope)
        with self._lock:
            if key not in self._parents:
                raise ScopeNotIndexed(key)
            return tuple(self._scopes[row] for row in sorted(self._children[key]))

    def contains(self, scope: NoetriumUnit) -> bool:
        key = scope_key(scope)
        with self._lock:
            return key in self._parents and self._scopes[key] == scope

    def links(self) -> tuple[NoetriumUnit, ...]:
        with self._lock:
            return tuple(self._links[key] for key in sorted(self._links))


__all__ = ["InMemoryScopeIndex", "ScopeIndexConflict", "ScopeNotIndexed"]
