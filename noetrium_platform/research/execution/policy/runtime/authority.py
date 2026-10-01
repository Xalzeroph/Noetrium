from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from threading import Condition, Lock
import time

from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionRejected,
    AdmissionTopologySnapshot,
    GroupAdmissionSnapshot,
    LaneAdmissionSnapshot,
    ResourceAdmissionSnapshot,
    TenantAdmissionSnapshot,
)
from noetrium_platform.research.execution.policy.scheduling.api import AdmissionSchedulingPolicyPort, SchedulingCandidate
from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    ExecutionLaneKind,
    TaskCancelled,
)


@dataclass(frozen=True, slots=True)
class _GroupIdentity:
    tenant_id: str | None
    resource_id: str | None

    @property
    def resource_key(self) -> tuple[str | None, str] | None:
        if self.resource_id is None:
            return None
        return (self.tenant_id, self.resource_id)


@dataclass(frozen=True, slots=True)
class _Waiter:
    ticket: int
    group_id: str
    lane_kind: ExecutionLaneKind
    permit_count: int
    intent: AdmissionIntent
    enqueued_monotonic: float


class _AdmissionLease:
    def __init__(self, authority: "HierarchicalAdmissionAuthority", group_id: str, lane_kind: ExecutionLaneKind) -> None:
        self._authority = authority
        self._group_id = group_id
        self._lane_kind = lane_kind
        self._released = False
        self._lock = Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._authority._release(self._group_id, self._lane_kind)
            self._released = True


class HierarchicalAdmissionAuthority:
    """Owns hierarchical execution admission; delegates ordering to scheduling.

    This runtime owns capacity/accounting only. It does not define priority rank,
    aging, or group fairness; those decisions are supplied by execution/scheduling.
    """

    _CANCELLATION_POLL_SECONDS = 0.05

    def __init__(self, *, budget: AdmissionBudget, scheduling: AdmissionSchedulingPolicyPort) -> None:
        self._budget = budget
        self._scheduling = scheduling
        self._lane_limits = {
            lane: budget.lane_limit(lane)
            for lane in (
                ExecutionLaneKind.BLOCKING_IO,
                ExecutionLaneKind.ASYNC_IO,
                ExecutionLaneKind.CPU,
                ExecutionLaneKind.SERIAL,
            )
        }
        self._condition = Condition()
        self._in_flight = 0
        self._groups: dict[str, int] = {}
        self._tenants: dict[str, int] = {}
        self._resources: dict[tuple[str | None, str], int] = {}
        self._lanes: dict[ExecutionLaneKind, int] = {}
        self._group_identities: dict[str, _GroupIdentity] = {}
        self._group_intents: dict[str, AdmissionIntent] = {}
        self._waiters: dict[int, _Waiter] = {}
        # Waiters that share group/lane/permit cardinality have identical
        # eligibility and fairness state except enqueue age/ticket. The oldest
        # one strictly dominates later rows, so only each shape head needs to
        # participate in scheduling selection.
        self._waiters_by_shape: dict[
            tuple[str, ExecutionLaneKind, int],
            dict[int, _Waiter],
        ] = {}
        self._shapes_by_group: dict[
            str, set[tuple[str, ExecutionLaneKind, int]]
        ] = {}
        self._shapes_by_tenant: dict[
            str, set[tuple[str, ExecutionLaneKind, int]]
        ] = {}
        self._selection_heap: list[tuple[tuple[int, ...], int]] = []
        self._selection_heap_valid_until = math.inf
        self._waiting_permits = 0
        self._waiting_by_group: dict[str, int] = {}
        self._waiting_by_lane: dict[ExecutionLaneKind, int] = {}
        self._waiting_by_tenant: dict[str, int] = {}
        self._waiting_by_resource: dict[tuple[str | None, str], int] = {}
        self._queue_version = 0
        self._selection_cache_version = -1
        self._selection_cache_valid_until = -math.inf
        self._selection_cache_ticket: int | None = None
        self._next_ticket = 0
        self._grant_sequence = 0
        self._group_last_grant: dict[str, int] = {}
        self._tenant_last_grant: dict[str, int] = {}
        self._closed = False
        self._admitted_total = 0
        self._rejected_total = 0
        self._cancelled_total = 0
        self._timed_out_total = 0
        self._queued_total = 0
        self._cumulative_queue_wait_seconds = 0.0
        self._max_queue_wait_seconds = 0.0

    @staticmethod
    def _group_id(value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("admission group id must be text")
        resolved = value.strip()
        if not resolved:
            raise ValueError("admission group id required")
        return resolved

    def register_group(self, group_id: str, *, identity: AdmissionIdentity, intent: AdmissionIntent = AdmissionIntent()) -> None:
        if not isinstance(identity, AdmissionIdentity):
            raise TypeError("admission identity must be AdmissionIdentity")
        if not isinstance(intent, AdmissionIntent):
            raise TypeError("admission intent must be AdmissionIntent")
        resolved_group = self._group_id(group_id)
        if not resolved_group:
            raise ValueError("admission group id required")
        resolved_identity = _GroupIdentity(
            tenant_id=identity.tenant_id,
            resource_id=identity.resource_id,
        )
        with self._condition:
            if self._closed:
                raise RuntimeError("execution admission authority is closed")
            if resolved_group in self._group_identities:
                raise ValueError(f"admission group id already registered: {resolved_group}")
            self._group_identities[resolved_group] = resolved_identity
            self._group_intents[resolved_group] = intent

    def unregister_group(self, group_id: str) -> None:
        resolved_group = self._group_id(group_id)
        with self._condition:
            self._identity(resolved_group)
            if self._groups.get(resolved_group, 0) != 0:
                raise RuntimeError(
                    f"cannot unregister admission group with active permits: {resolved_group}"
                )
            if self._waiting_by_group.get(resolved_group, 0) != 0:
                raise RuntimeError(
                    f"cannot unregister admission group with queued waiters: {resolved_group}"
                )
            self._group_identities.pop(resolved_group, None)
            self._group_intents.pop(resolved_group, None)
            self._group_last_grant.pop(resolved_group, None)
            self._invalidate_selection()
            self._condition.notify_all()

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    def _identity(self, group_id: str) -> _GroupIdentity:
        identity = self._group_identities.get(group_id)
        if identity is None:
            raise KeyError(f"execution group is not registered with admission authority: {group_id}")
        return identity

    def _can_ever_admit(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
    ) -> bool:
        identity = self._identity(group_id)
        limits = [
            int(self._budget.max_total_in_flight),
            int(self._budget.max_in_flight_per_group),
            int(self._lane_limits[lane_kind]),
        ]
        if identity.tenant_id is not None:
            limits.append(int(self._budget.max_in_flight_per_tenant))
        if identity.resource_key is not None:
            limits.append(int(self._budget.max_in_flight_per_resource))
        return permit_count <= min(limits)

    def _can_admit(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int = 1,
    ) -> bool:
        identity = self._identity(group_id)
        if self._in_flight + permit_count > self._budget.max_total_in_flight:
            return False
        if (
            self._groups.get(group_id, 0) + permit_count
            > int(self._budget.max_in_flight_per_group)
        ):
            return False
        if self._lanes.get(lane_kind, 0) + permit_count > self._lane_limits[lane_kind]:
            return False
        if (
            identity.tenant_id is not None
            and self._tenants.get(identity.tenant_id, 0) + permit_count
            > int(self._budget.max_in_flight_per_tenant)
        ):
            return False
        resource_key = identity.resource_key
        if (
            resource_key is not None
            and self._resources.get(resource_key, 0) + permit_count
            > int(self._budget.max_in_flight_per_resource)
        ):
            return False
        return True

    @staticmethod
    def _shape(waiter: _Waiter) -> tuple[str, ExecutionLaneKind, int]:
        return (waiter.group_id, waiter.lane_kind, waiter.permit_count)

    def _shape_head(
        self,
        shape: tuple[str, ExecutionLaneKind, int],
    ) -> _Waiter | None:
        queue = self._waiters_by_shape.get(shape)
        if not queue:
            return None
        return next(iter(queue.values()))

    def _candidate(self, waiter: _Waiter) -> SchedulingCandidate:
        identity = self._identity(waiter.group_id)
        group_in_flight = self._groups.get(waiter.group_id, 0)
        return SchedulingCandidate(
            ticket=waiter.ticket,
            group_id=waiter.group_id,
            priority=waiter.intent.priority,
            enqueued_monotonic=waiter.enqueued_monotonic,
            tenant_id=identity.tenant_id,
            group_in_flight=group_in_flight,
            tenant_in_flight=(
                self._tenants.get(identity.tenant_id, 0)
                if identity.tenant_id is not None
                else group_in_flight
            ),
        )

    def _ordering_key(self, waiter: _Waiter, now: float) -> tuple[int, ...]:
        return self._scheduling.ordering_key(
            self._candidate(waiter),
            group_last_grant=self._group_last_grant,
            tenant_last_grant=self._tenant_last_grant,
            now_monotonic=now,
        )

    def _push_waiter_order(self, waiter: _Waiter, now: float) -> None:
        heapq.heappush(
            self._selection_heap,
            (self._ordering_key(waiter, now), waiter.ticket),
        )
        next_change = self._scheduling.next_order_change_at(
            self._candidate(waiter),
            now_monotonic=now,
        )
        if next_change is not None:
            self._selection_heap_valid_until = min(
                self._selection_heap_valid_until,
                next_change,
            )

    def _rebuild_selection_heap(self, now: float) -> None:
        self._selection_heap = []
        self._selection_heap_valid_until = math.inf
        for shape in self._waiters_by_shape:
            waiter = self._shape_head(shape)
            if waiter is not None:
                self._push_waiter_order(waiter, now)

    def _refresh_released_owner_shapes(
        self,
        group_id: str,
        identity: _GroupIdentity,
        now: float,
    ) -> None:
        shapes = set(self._shapes_by_group.get(group_id, ()))
        if identity.tenant_id is not None:
            shapes.update(
                self._shapes_by_tenant.get(identity.tenant_id, ())
            )
        for shape in shapes:
            waiter = self._shape_head(shape)
            if waiter is not None:
                self._push_waiter_order(waiter, now)

    def _invalidate_selection(self) -> None:
        self._queue_version += 1
        self._selection_cache_ticket = None

    @staticmethod
    def _increment_waiting(counter: dict, key: object, value: int) -> None:
        counter[key] = counter.get(key, 0) + value

    @staticmethod
    def _decrement_waiting(counter: dict, key: object, value: int, *, label: str) -> None:
        current = counter.get(key, 0)
        if current < value:
            raise RuntimeError(f"admission {label} waiting accounting underflow")
        remaining = current - value
        if remaining == 0:
            counter.pop(key, None)
        else:
            counter[key] = remaining

    def _enqueue_waiter(self, waiter: _Waiter) -> None:
        if self._waiting_permits + waiter.permit_count > int(self._budget.max_waiting):
            self._rejected_total += waiter.permit_count
            raise AdmissionRejected(
                "execution admission waiting capacity exhausted: "
                f"waiting={self._waiting_permits} "
                f"requested={waiter.permit_count} "
                f"max_waiting={self._budget.max_waiting}"
            )
        self._waiters[waiter.ticket] = waiter
        shape = self._shape(waiter)
        shape_queue = self._waiters_by_shape.get(shape)
        new_shape = shape_queue is None
        if shape_queue is None:
            shape_queue = {}
            self._waiters_by_shape[shape] = shape_queue
            self._shapes_by_group.setdefault(
                waiter.group_id, set()
            ).add(shape)
            identity = self._identity(waiter.group_id)
            if identity.tenant_id is not None:
                self._shapes_by_tenant.setdefault(
                    identity.tenant_id, set()
                ).add(shape)
        shape_queue[waiter.ticket] = waiter
        if new_shape:
            self._push_waiter_order(waiter, time.monotonic())
        self._waiting_permits += waiter.permit_count
        identity = self._identity(waiter.group_id)
        self._increment_waiting(
            self._waiting_by_group,
            waiter.group_id,
            waiter.permit_count,
        )
        self._increment_waiting(
            self._waiting_by_lane,
            waiter.lane_kind,
            waiter.permit_count,
        )
        if identity.tenant_id is not None:
            self._increment_waiting(
                self._waiting_by_tenant,
                identity.tenant_id,
                waiter.permit_count,
            )
        if identity.resource_key is not None:
            self._increment_waiting(
                self._waiting_by_resource,
                identity.resource_key,
                waiter.permit_count,
            )
        self._invalidate_selection()

    def _remove_waiter(self, ticket: int) -> _Waiter | None:
        waiter = self._waiters.pop(ticket, None)
        if waiter is None:
            return None
        shape = self._shape(waiter)
        shape_queue = self._waiters_by_shape.get(shape)
        if shape_queue is None:
            raise RuntimeError(
                "execution admission waiter shape index drifted"
            )
        was_head = next(iter(shape_queue), None) == ticket
        if shape_queue.pop(ticket, None) is None:
            raise RuntimeError(
                "execution admission waiter shape index drifted"
            )
        if not shape_queue:
            self._waiters_by_shape.pop(shape, None)
            group_shapes = self._shapes_by_group.get(waiter.group_id)
            if group_shapes is not None:
                group_shapes.discard(shape)
                if not group_shapes:
                    self._shapes_by_group.pop(waiter.group_id, None)
            identity = self._identity(waiter.group_id)
            if identity.tenant_id is not None:
                tenant_shapes = self._shapes_by_tenant.get(identity.tenant_id)
                if tenant_shapes is not None:
                    tenant_shapes.discard(shape)
                    if not tenant_shapes:
                        self._shapes_by_tenant.pop(
                            identity.tenant_id, None
                        )
        elif was_head:
            next_head = next(iter(shape_queue.values()))
            self._push_waiter_order(next_head, time.monotonic())
        self._waiting_permits -= waiter.permit_count
        if self._waiting_permits < 0:
            raise RuntimeError("execution admission waiting accounting underflow")
        identity = self._identity(waiter.group_id)
        self._decrement_waiting(
            self._waiting_by_group,
            waiter.group_id,
            waiter.permit_count,
            label="group",
        )
        self._decrement_waiting(
            self._waiting_by_lane,
            waiter.lane_kind,
            waiter.permit_count,
            label="lane",
        )
        if identity.tenant_id is not None:
            self._decrement_waiting(
                self._waiting_by_tenant,
                identity.tenant_id,
                waiter.permit_count,
                label="tenant",
            )
        if identity.resource_key is not None:
            self._decrement_waiting(
                self._waiting_by_resource,
                identity.resource_key,
                waiter.permit_count,
                label="resource",
            )
        self._invalidate_selection()
        return waiter

    def _wait_timeout_seconds(
        self,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
        now_monotonic: float,
    ) -> float | None:
        """Return the next time this waiter must re-check authority state.

        Capacity/accounting changes notify the condition directly, so ordinary
        waits are fully event-driven. A timed wake is needed only for priority
        aging, an explicit deadline, or cooperative cancellation polling.
        """

        wake_at = self._selection_cache_valid_until
        timeout: float | None = None
        if math.isfinite(wake_at):
            timeout = max(0.0, wake_at - now_monotonic)
        if deadline is not None:
            remaining = deadline.remaining_seconds
            timeout = (
                remaining
                if timeout is None
                else min(timeout, remaining)
            )
        if cancellation is not None:
            timeout = (
                self._CANCELLATION_POLL_SECONDS
                if timeout is None
                else min(timeout, self._CANCELLATION_POLL_SECONDS)
            )
        return timeout

    def _selected_waiter(self) -> _Waiter | None:
        now = time.monotonic()
        active_shapes = len(self._waiters_by_shape)
        if (
            self._selection_heap
            and len(self._selection_heap) > max(64, active_shapes * 4)
        ):
            self._rebuild_selection_heap(now)
        if (
            self._selection_cache_version == self._queue_version
            and now < self._selection_cache_valid_until
        ):
            if self._selection_cache_ticket is None:
                return None
            return self._waiters.get(self._selection_cache_ticket)

        selected: _Waiter | None = None
        if self._in_flight < self._budget.max_total_in_flight:
            if (
                not self._selection_heap
                or now >= self._selection_heap_valid_until
            ):
                self._rebuild_selection_heap(now)

            blocked: list[tuple[tuple[int, ...], int]] = []
            while self._selection_heap:
                stored_key, ticket = heapq.heappop(
                    self._selection_heap
                )
                waiter = self._waiters.get(ticket)
                if waiter is None:
                    continue
                shape = self._shape(waiter)
                if self._shape_head(shape) is not waiter:
                    continue
                current_key = self._ordering_key(waiter, now)
                if current_key != stored_key:
                    heapq.heappush(
                        self._selection_heap,
                        (current_key, waiter.ticket),
                    )
                    continue
                if not self._can_admit(
                    waiter.group_id,
                    waiter.lane_kind,
                    waiter.permit_count,
                ):
                    blocked.append((current_key, waiter.ticket))
                    continue
                selected = waiter
                # Keep the selected head indexed until the caller actually
                # removes/grants it. This preserves idempotent repeated
                # selection within one authority state.
                heapq.heappush(
                    self._selection_heap,
                    (current_key, waiter.ticket),
                )
                break

            for row in blocked:
                heapq.heappush(self._selection_heap, row)

        self._selection_cache_version = self._queue_version
        self._selection_cache_valid_until = (
            self._selection_heap_valid_until
        )
        self._selection_cache_ticket = (
            None if selected is None else selected.ticket
        )
        return selected

    def _grant_many(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        waited_seconds: float,
    ) -> tuple[_AdmissionLease, ...]:
        if not self._can_admit(group_id, lane_kind, permit_count):
            raise RuntimeError("admission grant violated configured budget")
        identity = self._identity(group_id)
        self._in_flight += permit_count
        self._groups[group_id] = self._groups.get(group_id, 0) + permit_count
        self._lanes[lane_kind] = self._lanes.get(lane_kind, 0) + permit_count
        if identity.tenant_id is not None:
            self._tenants[identity.tenant_id] = (
                self._tenants.get(identity.tenant_id, 0) + permit_count
            )
        resource_key = identity.resource_key
        if resource_key is not None:
            self._resources[resource_key] = (
                self._resources.get(resource_key, 0) + permit_count
            )
        self._grant_sequence += 1
        self._group_last_grant[group_id] = self._grant_sequence
        if identity.tenant_id is not None:
            self._tenant_last_grant[identity.tenant_id] = self._grant_sequence
        self._invalidate_selection()
        self._admitted_total += permit_count
        self._cumulative_queue_wait_seconds += waited_seconds * permit_count
        self._max_queue_wait_seconds = max(
            self._max_queue_wait_seconds,
            waited_seconds,
        )
        return tuple(
            _AdmissionLease(self, group_id, lane_kind)
            for _ in range(permit_count)
        )

    def try_acquire(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> _AdmissionLease | None:
        """Attempt one immediate permit without entering the durable wait queue."""

        group_id = self._group_id(group_id)
        if lane_kind is ExecutionLaneKind.TIMER:
            raise ValueError("timer scheduler does not consume execution admission")
        if lane_kind not in self._lane_limits:
            raise ValueError(f"unsupported admission lane: {lane_kind}")
        with self._condition:
            self._identity(group_id)
            if not self._can_ever_admit(group_id, lane_kind, 1):
                raise AdmissionRejected(
                    "execution admission request exceeds configured capacity: "
                    f"group={group_id} lane={lane_kind.value}"
                )
            if self._closed:
                raise RuntimeError("execution admission authority is closed")
            if self._cancelled(cancellation):
                self._cancelled_total += 1
                raise TaskCancelled(
                    cancellation.reason or "execution admission cancelled"
                )
            if deadline is not None and deadline.expired:
                self._timed_out_total += 1
                raise TimeoutError("execution admission deadline expired")
            # A probe must never jump an already queued fair-scheduling waiter.
            if self._waiters or not self._can_admit(group_id, lane_kind, 1):
                return None
            leases = self._grant_many(
                group_id,
                lane_kind,
                permit_count=1,
                waited_seconds=0.0,
            )
            if len(leases) != 1:
                raise RuntimeError(
                    "nonblocking admission returned invalid lease cardinality"
                )
            return leases[0]

    def acquire(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> _AdmissionLease:
        leases = self.acquire_many(
            group_id,
            lane_kind,
            permit_count=1,
            deadline=deadline,
            cancellation=cancellation,
        )
        if len(leases) != 1:
            raise RuntimeError("single admission acquire returned invalid lease cardinality")
        return leases[0]

    def acquire_many(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[_AdmissionLease, ...]:
        group_id = self._group_id(group_id)
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError("execution admission permit_count must be a positive integer")
        if lane_kind is ExecutionLaneKind.TIMER:
            raise ValueError("timer scheduler does not consume execution admission")
        if lane_kind not in self._lane_limits:
            raise ValueError(f"unsupported admission lane: {lane_kind}")
        wait_started_monotonic = time.monotonic()
        with self._condition:
            self._identity(group_id)
            intent = self._group_intents[group_id]
            deadline = intent.constrain_wait_deadline(
                deadline,
                started_monotonic=wait_started_monotonic,
            )
            if not self._can_ever_admit(group_id, lane_kind, permit_count):
                raise AdmissionRejected(
                    "execution admission batch exceeds configured capacity: "
                    f"group={group_id} lane={lane_kind.value} permits={permit_count}"
                )
            if self._closed:
                raise RuntimeError("execution admission authority is closed")
            if self._cancelled(cancellation):
                self._cancelled_total += permit_count
                raise TaskCancelled(cancellation.reason or "execution admission cancelled")
            if deadline is not None and deadline.expired:
                self._timed_out_total += permit_count
                raise TimeoutError("execution admission deadline expired")

            if intent.reject_if_wait_required:
                if (
                    self._can_admit(group_id, lane_kind, permit_count)
                    and self._selected_waiter() is None
                ):
                    return self._grant_many(
                        group_id,
                        lane_kind,
                        permit_count=permit_count,
                        waited_seconds=0.0,
                    )
                self._rejected_total += permit_count
                raise AdmissionRejected(
                    "execution admission rejected "
                    f"group={group_id} lane={lane_kind.value} permits={permit_count}"
                )

            if (
                not self._waiters
                and self._can_admit(group_id, lane_kind, permit_count)
            ):
                return self._grant_many(
                    group_id,
                    lane_kind,
                    permit_count=permit_count,
                    waited_seconds=0.0,
                )

            waiter = _Waiter(
                ticket=self._next_ticket,
                group_id=group_id,
                lane_kind=lane_kind,
                permit_count=permit_count,
                intent=self._group_intents[group_id],
                enqueued_monotonic=time.monotonic(),
            )
            self._next_ticket += 1
            self._enqueue_waiter(waiter)
            self._queued_total += permit_count
            try:
                while True:
                    if self._closed:
                        raise RuntimeError("execution admission authority is closed")
                    if self._cancelled(cancellation):
                        self._cancelled_total += permit_count
                        raise TaskCancelled(
                            cancellation.reason or "execution admission cancelled"
                        )
                    if deadline is not None and deadline.expired:
                        self._timed_out_total += permit_count
                        raise TimeoutError("execution admission deadline expired")
                    if self._selected_waiter() is waiter:
                        removed = self._remove_waiter(waiter.ticket)
                        if removed is None:
                            raise RuntimeError(
                                "selected admission waiter disappeared"
                            )
                        waited = max(
                            0.0,
                            time.monotonic() - waiter.enqueued_monotonic,
                        )
                        leases = self._grant_many(
                            group_id,
                            lane_kind,
                            permit_count=permit_count,
                            waited_seconds=waited,
                        )
                        self._condition.notify_all()
                        return leases
                    self._condition.wait(
                        self._wait_timeout_seconds(
                            deadline=deadline,
                            cancellation=cancellation,
                            now_monotonic=time.monotonic(),
                        )
                    )
            finally:
                if waiter.ticket in self._waiters:
                    self._remove_waiter(waiter.ticket)
                    self._condition.notify_all()

    @staticmethod
    def _decrement(counter: dict, key: object, *, label: str) -> None:
        current = counter.get(key, 0)
        if current <= 0:
            raise RuntimeError(f"admission {label} accounting underflow")
        if current == 1:
            counter.pop(key, None)
        else:
            counter[key] = current - 1

    def _release(self, group_id: str, lane_kind: ExecutionLaneKind) -> None:
        with self._condition:
            if self._in_flight <= 0:
                raise RuntimeError("admission in-flight accounting underflow")
            identity = self._identity(group_id)
            self._decrement(self._groups, group_id, label="group")
            self._decrement(self._lanes, lane_kind, label="lane")
            if identity.tenant_id is not None:
                self._decrement(self._tenants, identity.tenant_id, label="tenant")
            if identity.resource_key is not None:
                self._decrement(self._resources, identity.resource_key, label="resource")
            self._in_flight -= 1
            self._refresh_released_owner_shapes(
                group_id,
                identity,
                time.monotonic(),
            )
            self._invalidate_selection()
            self._condition.notify_all()

    def snapshot(self) -> AdmissionTopologySnapshot:
        with self._condition:
            by_group = self._waiting_by_group
            by_lane = self._waiting_by_lane
            by_tenant = self._waiting_by_tenant
            by_resource = self._waiting_by_resource
            now = time.monotonic()
            oldest_waiter = next(iter(self._waiters.values()), None)
            oldest = (
                0.0
                if oldest_waiter is None
                else now - oldest_waiter.enqueued_monotonic
            )
            group_ids = sorted(set(self._group_identities) | set(self._groups) | set(by_group))
            tenant_ids = sorted(set(self._tenants) | set(by_tenant))
            resource_keys = sorted(set(self._resources) | set(by_resource), key=lambda item: ((item[0] or ""), item[1]))
            lane_kinds = (
                ExecutionLaneKind.BLOCKING_IO,
                ExecutionLaneKind.ASYNC_IO,
                ExecutionLaneKind.CPU,
                ExecutionLaneKind.SERIAL,
            )
            return AdmissionTopologySnapshot(
                max_total_in_flight=self._budget.max_total_in_flight,
                max_waiting=int(self._budget.max_waiting),
                max_in_flight_per_group=int(self._budget.max_in_flight_per_group),
                max_in_flight_per_tenant=int(self._budget.max_in_flight_per_tenant),
                max_in_flight_per_resource=int(self._budget.max_in_flight_per_resource),
                in_flight=self._in_flight,
                waiting=self._waiting_permits,
                closed=self._closed,
                admitted_total=self._admitted_total,
                rejected_total=self._rejected_total,
                cancelled_total=self._cancelled_total,
                timed_out_total=self._timed_out_total,
                queued_total=self._queued_total,
                cumulative_queue_wait_seconds=self._cumulative_queue_wait_seconds,
                max_queue_wait_seconds=self._max_queue_wait_seconds,
                oldest_wait_seconds=max(0.0, oldest),
                groups=tuple(
                    GroupAdmissionSnapshot(
                        group_id=group_id,
                        tenant_id=self._group_identities[group_id].tenant_id,
                        resource_id=self._group_identities[group_id].resource_id,
                        in_flight=self._groups.get(group_id, 0),
                        waiting=by_group.get(group_id, 0),
                    )
                    for group_id in group_ids
                ),
                tenants=tuple(
                    TenantAdmissionSnapshot(
                        tenant_id=tenant_id,
                        max_in_flight=int(self._budget.max_in_flight_per_tenant),
                        in_flight=self._tenants.get(tenant_id, 0),
                        waiting=by_tenant.get(tenant_id, 0),
                    )
                    for tenant_id in tenant_ids
                ),
                resources=tuple(
                    ResourceAdmissionSnapshot(
                        tenant_id=tenant_id,
                        resource_id=resource_id,
                        max_in_flight=int(self._budget.max_in_flight_per_resource),
                        in_flight=self._resources.get((tenant_id, resource_id), 0),
                        waiting=by_resource.get((tenant_id, resource_id), 0),
                    )
                    for tenant_id, resource_id in resource_keys
                ),
                lanes=tuple(
                    LaneAdmissionSnapshot(
                        lane_kind=lane,
                        max_in_flight=self._lane_limits[lane],
                        in_flight=self._lanes.get(lane, 0),
                        waiting=by_lane.get(lane, 0),
                    )
                    for lane in lane_kinds
                ),
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
