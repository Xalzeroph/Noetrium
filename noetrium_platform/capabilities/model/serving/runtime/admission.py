from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import Condition, Lock
import time

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort, TaskCancelled

from ..api.admission import ModelAdmissionClosed, ModelAdmissionTimeout


@dataclass(frozen=True, slots=True)
class ModelAdmissionOwnerSnapshot:
    owner_id: str
    active: int
    waiting: int


@dataclass(frozen=True, slots=True)
class AdmissionSnapshot:
    capacity: int
    active: int
    waiting: int
    owners: tuple[ModelAdmissionOwnerSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class _Waiter:
    ticket: int
    owner_id: str


class AdmissionLease:
    def __init__(self, controller: "ModelAdmissionController", owner_id: str) -> None:
        self._controller = controller
        self._owner_id = owner_id
        self._released = False
        self._release_lock = Lock()

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._controller._release(self._owner_id)
            self._released = True

    def __enter__(self) -> "AdmissionLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class ModelAdmissionController:
    """Work-conserving fair backpressure for one qualified deployment.

    A lone owner can use the full qualified capacity. Under contention, only the
    head waiter of each owner competes; owners with fewer active requests win
    first, then the least recently granted owner, then FIFO ticket order.
    """

    _ADMISSION_POLL_SECONDS = 0.05
    _ANONYMOUS_OWNER = "__anonymous__"

    def __init__(self, qualified_capacity: int) -> None:
        if type(qualified_capacity) is not int or qualified_capacity <= 0:
            raise ValueError("qualified capacity must be positive")
        self.capacity = qualified_capacity
        self._active = 0
        self._active_by_owner: dict[str, int] = {}
        self._waiters_by_owner: dict[str, OrderedDict[int, _Waiter]] = {}
        self._waiters_by_ticket: dict[int, _Waiter] = {}
        self._waiter_count = 0
        self._waiter_selection_version = 0
        self._waiter_selection_cache_version = -1
        self._waiter_selection_cache_ticket: int | None = None
        self._next_ticket = 0
        self._grant_sequence = 0
        self._owner_last_grant: dict[str, int] = {}
        self._cv = Condition()
        self._closed = False

    @classmethod
    def _owner(cls, owner_id: str | None) -> str:
        if owner_id is None:
            return cls._ANONYMOUS_OWNER
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError("model admission owner_id must be non-empty when provided")
        return owner_id.strip()

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    @staticmethod
    def _cancel_reason(cancellation: CancellationTokenPort | None) -> str:
        return (
            cancellation.reason
            if cancellation is not None and cancellation.reason
            else "model admission cancelled"
        )

    def _invalidate_waiter_selection(self) -> None:
        self._waiter_selection_version += 1
        self._waiter_selection_cache_ticket = None

    def _enqueue_waiter(self, waiter: _Waiter) -> None:
        queue = self._waiters_by_owner.get(waiter.owner_id)
        if queue is None:
            queue = OrderedDict()
            self._waiters_by_owner[waiter.owner_id] = queue
        if waiter.ticket in self._waiters_by_ticket:
            raise RuntimeError("duplicate model admission waiter ticket")
        queue[waiter.ticket] = waiter
        self._waiters_by_ticket[waiter.ticket] = waiter
        self._waiter_count += 1
        self._invalidate_waiter_selection()

    def _remove_waiter(self, waiter: _Waiter) -> bool:
        queue = self._waiters_by_owner.get(waiter.owner_id)
        if queue is None:
            return False
        removed = queue.pop(waiter.ticket, None)
        if removed is None:
            return False
        self._waiters_by_ticket.pop(waiter.ticket, None)
        self._waiter_count -= 1
        if self._waiter_count < 0:
            raise RuntimeError("model admission waiter accounting underflow")
        if not queue:
            self._waiters_by_owner.pop(waiter.owner_id, None)
        self._invalidate_waiter_selection()
        return True

    def _selected_waiter(self) -> _Waiter | None:
        if self._active >= self.capacity or self._waiter_count == 0:
            return None
        if self._waiter_selection_cache_version == self._waiter_selection_version:
            ticket = self._waiter_selection_cache_ticket
            return None if ticket is None else self._waiters_by_ticket.get(ticket)
        selected = min(
            (
                next(iter(queue.values()))
                for queue in self._waiters_by_owner.values()
                if queue
            ),
            key=lambda waiter: (
                self._active_by_owner.get(waiter.owner_id, 0),
                self._owner_last_grant.get(waiter.owner_id, -1),
                waiter.ticket,
            ),
            default=None,
        )
        self._waiter_selection_cache_version = self._waiter_selection_version
        self._waiter_selection_cache_ticket = (
            None if selected is None else selected.ticket
        )
        return selected

    def acquire(
        self,
        timeout_seconds: float | None = None,
        *,
        cancellation: CancellationTokenPort | None = None,
        owner_id: str | None = None,
    ) -> AdmissionLease:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("model admission timeout cannot be negative")
        owner = self._owner(owner_id)
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        admitted = False
        with self._cv:
            if self._closed:
                raise ModelAdmissionClosed("model admission controller is closed")
            waiter = _Waiter(self._next_ticket, owner)
            self._next_ticket += 1
            self._enqueue_waiter(waiter)
            try:
                while True:
                    if self._closed:
                        raise ModelAdmissionClosed("model admission controller is closed")
                    if self._cancelled(cancellation):
                        raise TaskCancelled(self._cancel_reason(cancellation))
                    if self._selected_waiter() is waiter:
                        if not self._remove_waiter(waiter):
                            raise RuntimeError(
                                "selected model admission waiter disappeared"
                            )
                        self._active += 1
                        self._active_by_owner[owner] = self._active_by_owner.get(owner, 0) + 1
                        self._grant_sequence += 1
                        self._owner_last_grant[owner] = self._grant_sequence
                        self._invalidate_waiter_selection()
                        admitted = True
                        self._cv.notify_all()
                        return AdmissionLease(self, owner)
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise ModelAdmissionTimeout(
                            "model admission timed out; no quality fallback was attempted"
                        )
                    wait_for = self._ADMISSION_POLL_SECONDS
                    if remaining is not None:
                        wait_for = min(wait_for, remaining)
                    self._cv.wait(wait_for)
            finally:
                if not admitted:
                    self._remove_waiter(waiter)
                    self._cv.notify_all()

    def _release(self, owner_id: str) -> None:
        with self._cv:
            if self._active <= 0:
                raise RuntimeError("admission lease underflow")
            current = self._active_by_owner.get(owner_id, 0)
            if current <= 0:
                raise RuntimeError("model admission owner accounting underflow")
            if current == 1:
                self._active_by_owner.pop(owner_id, None)
            else:
                self._active_by_owner[owner_id] = current - 1
            self._active -= 1
            self._invalidate_waiter_selection()
            self._cv.notify_all()

    def close(self) -> None:
        with self._cv:
            if self._closed:
                return
            self._closed = True
            self._cv.notify_all()

    @property
    def closed(self) -> bool:
        with self._cv:
            return self._closed

    def snapshot(self) -> AdmissionSnapshot:
        with self._cv:
            waiting_by_owner = {
                owner_id: len(queue)
                for owner_id, queue in self._waiters_by_owner.items()
                if queue
            }
            owners = sorted(set(self._active_by_owner) | set(waiting_by_owner))
            return AdmissionSnapshot(
                self.capacity,
                self._active,
                self._waiter_count,
                tuple(
                    ModelAdmissionOwnerSnapshot(
                        owner_id=owner,
                        active=self._active_by_owner.get(owner, 0),
                        waiting=waiting_by_owner.get(owner, 0),
                    )
                    for owner in owners
                ),
            )


class ModelAdmissionRegistry:
    """Share one qualified admission authority per exact deployment generation."""

    def __init__(self) -> None:
        self._registry_lock = Lock()
        self._controllers: dict[tuple[str, str], ModelAdmissionController] = {}
        self._registry_closed = False

    def controller_for(
        self,
        *,
        deployment_id: str,
        deployment_generation: str,
        qualified_capacity: int,
    ) -> ModelAdmissionController:
        if not deployment_id.strip():
            raise ValueError("model admission deployment_id is required")
        if len(deployment_generation) != 64 or any(
            char not in "0123456789abcdef" for char in deployment_generation
        ):
            raise ValueError("model admission deployment_generation must be SHA-256")
        key = (deployment_id, deployment_generation)
        with self._registry_lock:
            if self._registry_closed:
                raise ModelAdmissionClosed("model admission registry is closed")
            controller = self._controllers.get(key)
            if controller is None:
                controller = ModelAdmissionController(qualified_capacity)
                self._controllers[key] = controller
                return controller
            if controller.capacity != qualified_capacity:
                raise ValueError("qualified admission capacity drift for deployment generation")
            return controller

    def close(self) -> None:
        with self._registry_lock:
            if self._registry_closed:
                return
            self._registry_closed = True
            controllers = tuple(self._controllers.values())
        for controller in controllers:
            controller.close()

    @property
    def closed(self) -> bool:
        with self._registry_lock:
            return self._registry_closed


__all__ = [
    "AdmissionLease",
    "AdmissionSnapshot",
    "ModelAdmissionClosed",
    "ModelAdmissionController",
    "ModelAdmissionOwnerSnapshot",
    "ModelAdmissionRegistry",
    "ModelAdmissionTimeout",
]
