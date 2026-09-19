from __future__ import annotations

from threading import RLock

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind, ScopeLink


class ScopeRegistryConflict(RuntimeError):
    pass


class ScopeNotRegistered(KeyError):
    pass


class InMemoryScopeRegistry:
    """Thread-safe ephemeral implementation of the scope hierarchy contract."""

    def __init__(self) -> None:
        self._parents: dict[ScopeIdentity, ScopeIdentity | None] = {PLATFORM_SCOPE: None}
        self._children: dict[ScopeIdentity, set[ScopeIdentity]] = {PLATFORM_SCOPE: set()}
        self._lock = RLock()

    @staticmethod
    def _validate_parent_kind(scope: ScopeIdentity, parent: ScopeIdentity | None) -> None:
        if scope.kind is ScopeKind.PLATFORM:
            if scope != PLATFORM_SCOPE or parent is not None:
                raise ScopeRegistryConflict("platform scope has one fixed root identity")
            return
        if parent is None:
            raise ScopeRegistryConflict("non-platform scope requires explicit parent")
        try:
            ScopeLink(scope, parent)
        except ValueError as exc:
            raise ScopeRegistryConflict(str(exc)) from exc

    def register(self, scope: ScopeIdentity, parent: ScopeIdentity | None) -> None:
        self._validate_parent_kind(scope, parent)
        with self._lock:
            if parent is not None and parent not in self._parents:
                raise ScopeNotRegistered(parent.key)
            if scope in self._parents:
                current = self._parents[scope]
                if current != parent:
                    raise ScopeRegistryConflict(f"scope parent already fixed: {scope.key}")
                return
            self._parents[scope] = parent
            self._children.setdefault(scope, set())
            if parent is not None:
                self._children.setdefault(parent, set()).add(scope)

    def parent(self, scope: ScopeIdentity) -> ScopeIdentity | None:
        with self._lock:
            try:
                return self._parents[scope]
            except KeyError as exc:
                raise ScopeNotRegistered(scope.key) from exc

    def ancestry(self, scope: ScopeIdentity) -> tuple[ScopeIdentity, ...]:
        with self._lock:
            if scope not in self._parents:
                raise ScopeNotRegistered(scope.key)
            chain: list[ScopeIdentity] = []
            seen: set[ScopeIdentity] = set()
            current: ScopeIdentity | None = scope
            while current is not None:
                if current in seen:
                    raise ScopeRegistryConflict(f"scope cycle detected at {current.key}")
                seen.add(current)
                chain.append(current)
                try:
                    current = self._parents[current]
                except KeyError as exc:
                    raise ScopeNotRegistered(current.key) from exc
            return tuple(chain)

    def children(self, scope: ScopeIdentity) -> tuple[ScopeIdentity, ...]:
        """Return direct children from the parent-local index, then sort that subset."""
        with self._lock:
            if scope not in self._parents:
                raise ScopeNotRegistered(scope.key)
            return tuple(sorted(self._children[scope], key=lambda item: item.key))

    def contains(self, scope: ScopeIdentity) -> bool:
        with self._lock:
            return scope in self._parents


__all__ = ["InMemoryScopeRegistry", "ScopeNotRegistered", "ScopeRegistryConflict"]
