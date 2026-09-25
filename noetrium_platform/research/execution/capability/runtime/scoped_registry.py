from __future__ import annotations

from contextlib import contextmanager
from threading import Condition, Lock, RLock
import time

from noetrium_platform.research.execution.capability.api import (
    CapabilityRegistration, CapabilityTypeMismatch, RegistrationConflict, RegistrationKey, ScopeDisposed,
)


class _RegistrationHandle:
    def __init__(self, owner: "ScopedRegistrationRuntime", key: RegistrationKey) -> None:
        self._owner = owner
        self._key = key
        self._closed = False
        self._lock = Lock()

    @property
    def key(self) -> RegistrationKey:
        return self._key

    def close(self, *, timeout_s: float | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            self._owner._unregister(self._key, timeout_s=timeout_s)
            self._closed = True


class ScopedRegistrationRuntime:
    """Hierarchical registration scope with reversible ownership and quiescence.

    Child scopes see ancestor registrations, but every lease is counted against the
    scope through which it entered. Registration handles can retire one owned
    registration without destroying the scope; retirement waits for active users of
    that key. Scope disposal blocks new leases, recursively disposes children, waits
    for all in-flight leases, and then drops the remaining owned registrations.
    """

    def __init__(self, scope_id: str, *, parent: "ScopedRegistrationRuntime | None" = None) -> None:
        if not scope_id.strip():
            raise ValueError("scope_id must be non-empty")
        self._scope_id = scope_id
        self._parent = parent
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._registrations: dict[RegistrationKey, object] = {}
        self._contracts: dict[RegistrationKey, CapabilityRegistration] = {}
        self._active_by_key: dict[RegistrationKey, int] = {}
        self._retiring: set[RegistrationKey] = set()
        self._active = 0
        self._disposing = False
        self._disposed = False
        self._children: list[ScopedRegistrationRuntime] = []

    @property
    def scope_id(self) -> str:
        return self._scope_id

    def child(self, scope_id: str) -> "ScopedRegistrationRuntime":
        with self._condition:
            self._ensure_open()
            child = ScopedRegistrationRuntime(scope_id, parent=self)
            self._children.append(child)
            return child

    def register(self, key: RegistrationKey, value: object) -> _RegistrationHandle:
        with self._condition:
            self._ensure_open()
            if key in self._registrations or key in self._retiring:
                raise RegistrationConflict(f"registration already exists in scope: {key.namespace}/{key.name}")
            self._registrations[key] = value
            self._active_by_key[key] = 0
        return _RegistrationHandle(self, key)

    def register_typed(self, contract: CapabilityRegistration, value: object) -> _RegistrationHandle:
        if not isinstance(value, contract.value_type):
            raise CapabilityTypeMismatch(
                f"capability {contract.key.namespace}/{contract.key.name} requires {contract.value_type.__name__}"
            )
        with self._condition:
            self._ensure_open()
            key = contract.key
            if key in self._registrations or key in self._retiring:
                raise RegistrationConflict(f"registration already exists in scope: {key.namespace}/{key.name}")
            self._registrations[key] = value
            self._contracts[key] = contract
            self._active_by_key[key] = 0
        return _RegistrationHandle(self, contract.key)
    def _ensure_open(self) -> None:
        if self._disposed or self._disposing:
            raise ScopeDisposed(f"registration scope is disposing/disposed: {self._scope_id}")

    def _owner_for(self, key: RegistrationKey) -> "ScopedRegistrationRuntime":
        with self._condition:
            if key in self._registrations and key not in self._retiring:
                return self
        if self._parent is not None:
            return self._parent._owner_for(key)
        raise KeyError(f"registration not found: {key.namespace}/{key.name}")

    def _release_requester_lease(self) -> None:
        with self._condition:
            self._active -= 1
            self._condition.notify_all()

    @contextmanager
    def acquire(self, key: RegistrationKey):
        # The requester scope is a lifetime boundary even for inherited values.
        with self._condition:
            self._ensure_open()
            self._active += 1
        owner: ScopedRegistrationRuntime | None = None
        owner_counted = False
        key_counted = False
        try:
            owner = self._owner_for(key)
            with owner._condition:
                owner._ensure_open()
                if key not in owner._registrations or key in owner._retiring:
                    raise KeyError(f"registration not found: {key.namespace}/{key.name}")
                value = owner._registrations[key]
                owner._active_by_key[key] = owner._active_by_key.get(key, 0) + 1
                key_counted = True
                if owner is not self:
                    owner._active += 1
                    owner_counted = True
            try:
                yield value
            finally:
                if owner is not None and key_counted:
                    with owner._condition:
                        owner._active_by_key[key] -= 1
                        if owner_counted:
                            owner._active -= 1
                        owner._condition.notify_all()
        finally:
            self._release_requester_lease()

    @contextmanager
    def acquire_typed(self, contract: CapabilityRegistration):
        owner = self._owner_for(contract.key)
        with self.acquire(contract.key) as value:
            with owner._condition:
                registered_contract = owner._contracts.get(contract.key)
            if registered_contract != contract:
                raise CapabilityTypeMismatch(
                    f"capability contract mismatch: {contract.key.namespace}/{contract.key.name}"
                )
            if not isinstance(value, contract.value_type):
                raise CapabilityTypeMismatch(
                    f"capability value type drift: {contract.key.namespace}/{contract.key.name}"
                )
            yield value
    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        return None if deadline is None else deadline - time.monotonic()

    def _unregister(self, key: RegistrationKey, *, timeout_s: float | None = None) -> None:
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("registration close timeout_s must be non-negative")
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        with self._condition:
            # Whole-scope disposal owns teardown once it starts. A handle closing in
            # parallel waits for that same boundary rather than racing the registry.
            while self._disposing and not self._disposed:
                remaining = self._remaining(deadline)
                if remaining is not None and remaining <= 0:
                    raise TimeoutError(f"registration did not quiesce before timeout: {key.namespace}/{key.name}")
                self._condition.wait(remaining)
            if self._disposed or key not in self._registrations:
                return
            self._retiring.add(key)
            try:
                while self._active_by_key.get(key, 0):
                    remaining = self._remaining(deadline)
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError(f"registration did not quiesce before timeout: {key.namespace}/{key.name}")
                    self._condition.wait(remaining)
                self._registrations.pop(key, None)
                self._active_by_key.pop(key, None)
                self._contracts.pop(key, None)
            finally:
                self._retiring.discard(key)
                self._condition.notify_all()

    def dispose(self, *, timeout_s: float | None = None) -> None:
        if timeout_s is not None and timeout_s < 0:
            raise ValueError("scope dispose timeout_s must be non-negative")
        deadline = None if timeout_s is None else time.monotonic() + timeout_s

        # Elect one disposal leader; concurrent callers share the terminal boundary.
        while True:
            with self._condition:
                if self._disposed:
                    return
                if not self._disposing:
                    self._disposing = True
                    children = tuple(reversed(self._children))
                    break
                remaining = self._remaining(deadline)
                if remaining is not None and remaining <= 0:
                    raise TimeoutError(f"scope did not quiesce before timeout: {self._scope_id}")
                self._condition.wait(remaining)

        try:
            for child in children:
                remaining = self._remaining(deadline)
                if remaining is not None and remaining <= 0:
                    raise TimeoutError(f"scope did not quiesce before timeout: {self._scope_id}")
                child.dispose(timeout_s=remaining)

            with self._condition:
                while self._active:
                    remaining = self._remaining(deadline)
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError(f"scope did not quiesce before timeout: {self._scope_id}")
                    self._condition.wait(remaining)
                self._registrations.clear()
                self._contracts.clear()
                self._active_by_key.clear()
                self._retiring.clear()
                self._children.clear()
                self._disposed = True
                self._disposing = False
                self._condition.notify_all()
        except BaseException:
            with self._condition:
                if not self._disposed:
                    self._disposing = False
                    self._condition.notify_all()
            raise




class ScopedRegistrationRuntimeFactory:
    def create(self, scope_id: str) -> ScopedRegistrationRuntime:
        return ScopedRegistrationRuntime(scope_id)


__all__ = ["ScopedRegistrationRuntime", "ScopedRegistrationRuntimeFactory"]
