from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from threading import Condition, Lock, RLock
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
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import SchedulingAuthorityPort, SchedulingCandidate
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
    add_cost_time_ns,
    add_cost_wait_ns,
    add_cost_work,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    ExecutionLaneKind,
    TaskCancelled,
    wake_on_cancellation,
)




EXECUTION_PRIORITY_AGING_COMPLEXITY = ComplexityContract(
    algorithm_id="execution.admission.priority-aging.v2",
    implementation_digest=canonical_digest(
        (
            "execution.admission.priority-aging.v2",
            "fixed-rank-monotonic-fifo-events",
        )
    ),
    time_upper_bound=ComplexityBound.linear("aging_events"),
    space_upper_bound=ComplexityBound.linear("waiting_permits"),
    assumptions=(
        "execution priority has a fixed four-rank lattice",
        "waiter enqueue timestamps are monotonic",
        "each waiter emits at most three rank-change events",
        "each ordinal aging stream is therefore FIFO-sorted without comparison sorting",
    ),
    time_lower_bound=ComplexityBound.linear("aging_events"),
    space_lower_bound=ComplexityBound.linear("waiting_permits"),
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
    def __init__(
        self,
        authority: "HierarchicalAdmissionAuthority",
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        started_monotonic: float,
    ) -> None:
        self._authority = authority
        self._group_id = group_id
        self._lane_kind = lane_kind
        self._started_monotonic = float(started_monotonic)
        self._released = False
        self._lock = Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._authority._release(
                self._group_id,
                self._lane_kind,
                started_monotonic=self._started_monotonic,
            )
            self._released = True

    def rollback(self) -> None:
        with self._lock:
            if self._released:
                return
            self._authority._rollback(
                self._group_id,
                self._lane_kind,
            )
            self._released = True


class HierarchicalAdmissionAuthority:
    """Owns hierarchical execution admission; delegates ordering to scheduling.

    This runtime owns capacity/accounting only. It does not define priority rank,
    aging, or group fairness; those decisions are supplied by execution/scheduling.
    """


    def __init__(self, *, budget: AdmissionBudget, scheduling_authority: SchedulingAuthorityPort) -> None:
        self._budget = budget
        self._scheduling = scheduling_authority
        self._lane_limits = {
            lane: budget.lane_limit(lane)
            for lane in (
                ExecutionLaneKind.BLOCKING_IO,
                ExecutionLaneKind.ASYNC_IO,
                ExecutionLaneKind.CPU,
                ExecutionLaneKind.SERIAL,
            )
        }
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._in_flight = 0
        self._groups: dict[str, int] = {}
        self._tenants: dict[str, int] = {}
        self._resources: dict[tuple[str | None, str], int] = {}
        self._lanes: dict[ExecutionLaneKind, int] = {}
        # Capacity reserved while the global Scheduling Authority durably
        # linearizes a grant. These counters are feasibility-only and are never
        # exposed as admitted/in-flight truth before that commit succeeds.
        self._provisional_in_flight = 0
        self._settling_in_flight = 0
        self._provisional_groups: dict[str, int] = {}
        self._provisional_tenants: dict[str, int] = {}
        self._provisional_resources: dict[tuple[str | None, str], int] = {}
        self._provisional_lanes: dict[ExecutionLaneKind, int] = {}
        self._group_identities: dict[str, _GroupIdentity] = {}
        self._group_intents: dict[str, AdmissionIntent] = {}
        self._waiters: dict[int, _Waiter] = {}
        self._waiter_conditions: dict[int, Condition] = {}
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
        self._selection_heaps: dict[
            ExecutionLaneKind, list[tuple[tuple[int | float, ...], int]]
        ] = {lane: [] for lane in self._lane_limits}
        # Capacity-infeasible shape heads are parked until the exact capacity
        # scope that blocks them changes. This prevents unrelated queue churn
        # from repeatedly pop/pushing the same infeasible heap prefix.
        self._capacity_block_key_by_shape: dict[
            tuple[str, ExecutionLaneKind, int],
            tuple[str, object],
        ] = {}
        self._capacity_blocked_shapes: dict[
            tuple[str, object],
            set[tuple[str, ExecutionLaneKind, int]],
        ] = {}
        self._waiting_permits = 0
        self._waiting_by_group: dict[str, int] = {}
        self._waiting_by_lane: dict[ExecutionLaneKind, int] = {}
        self._waiting_by_tenant: dict[str, int] = {}
        self._waiting_by_resource: dict[tuple[str | None, str], int] = {}
        self._queue_version = 0
        self._selection_cache_version = -1
        self._selection_cache_ticket: int | None = None
        # Projection revision, not another scheduling authority. A different
        # process may change fair service while this queue remains unchanged.
        self._scheduling_service_revision: int | None = None
        self._next_ticket = 0
        self._grant_sequence = 0
        self._closed = False
        self._closing = False
        self._provisional_condition = Condition(self._lock)
        self._grant_pressure_lock = Lock()
        self._grant_callers = 0
        self._settlement_pressure_lock = Lock()
        self._settlement_callers = 0
        self._admitted_total = 0
        self._rejected_total = 0
        self._cancelled_total = 0
        self._timed_out_total = 0
        self._queued_total = 0
        self._cumulative_queue_wait_seconds = 0.0
        self._max_queue_wait_seconds = 0.0
        # Exact sufficient statistics for later rate-aware scheduling.  These
        # are parameter-free cumulative observations, not a policy heuristic.
        self._group_service_completed: dict[str, int] = {}
        self._group_service_seconds: dict[str, float] = {}
        self._lane_service_completed: dict[ExecutionLaneKind, int] = {}
        self._lane_service_seconds: dict[ExecutionLaneKind, float] = {}

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
            if self._closed or self._closing:
                raise RuntimeError("execution admission authority is closed")
            if resolved_group in self._group_identities:
                raise ValueError(f"admission group id already registered: {resolved_group}")
            self._group_identities[resolved_group] = resolved_identity
            self._group_intents[resolved_group] = intent

    def unregister_group(self, group_id: str) -> None:
        resolved_group = self._group_id(group_id)
        with self._condition:
            self._identity(resolved_group)
            if (
                self._groups.get(resolved_group, 0) != 0
                or self._provisional_groups.get(resolved_group, 0) != 0
            ):
                raise RuntimeError(
                    f"cannot unregister admission group with active permits: {resolved_group}"
                )
            if self._waiting_by_group.get(resolved_group, 0) != 0:
                raise RuntimeError(
                    f"cannot unregister admission group with queued waiters: {resolved_group}"
                )
            identity = self._group_identities.pop(resolved_group)
            self._group_intents.pop(resolved_group, None)
            self._group_service_completed.pop(resolved_group, None)
            self._group_service_seconds.pop(resolved_group, None)
            resource_key = identity.resource_key
            release_resource = (
                resource_key is not None
                and all(
                    row.resource_key != resource_key
                    for row in self._group_identities.values()
                )
            )
            self._invalidate_selection()
            self._notify_selected_waiter_locked()
        self._scheduling.release_flow(
            resolved_group,
            tenant_id=identity.tenant_id,
            resource_id=identity.resource_id,
        )
        if release_resource and identity.resource_id is not None:
            self._scheduling.release_resource(
                tenant_id=identity.tenant_id,
                resource_id=identity.resource_id,
            )

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

    @staticmethod
    def _occupied(
        committed: dict, provisional: dict, key: object,
    ) -> int:
        return committed.get(key, 0) + provisional.get(key, 0)

    def _occupied_total(self) -> int:
        return self._in_flight + self._provisional_in_flight

    def _reserve_provisional(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
        identity: _GroupIdentity,
    ) -> None:
        if not self._can_admit(group_id, lane_kind, permit_count):
            raise RuntimeError("provisional admission violated configured budget")
        self._provisional_in_flight += permit_count
        self._provisional_groups[group_id] = (
            self._provisional_groups.get(group_id, 0) + permit_count
        )
        self._provisional_lanes[lane_kind] = (
            self._provisional_lanes.get(lane_kind, 0) + permit_count
        )
        if identity.tenant_id is not None:
            self._provisional_tenants[identity.tenant_id] = (
                self._provisional_tenants.get(identity.tenant_id, 0) + permit_count
            )
        if identity.resource_key is not None:
            self._provisional_resources[identity.resource_key] = (
                self._provisional_resources.get(identity.resource_key, 0) + permit_count
            )
        self._invalidate_selection()

    @staticmethod
    def _decrement_provisional(
        counter: dict, key: object, permit_count: int, *, label: str,
    ) -> None:
        current = counter.get(key, 0)
        if current < permit_count:
            raise RuntimeError(f"provisional admission {label} accounting underflow")
        remaining = current - permit_count
        if remaining:
            counter[key] = remaining
        else:
            counter.pop(key, None)

    def _release_provisional(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
        identity: _GroupIdentity,
    ) -> None:
        if self._provisional_in_flight < permit_count:
            raise RuntimeError("provisional admission in-flight accounting underflow")
        self._provisional_in_flight -= permit_count
        self._decrement_provisional(
            self._provisional_groups, group_id, permit_count, label="group"
        )
        self._decrement_provisional(
            self._provisional_lanes, lane_kind, permit_count, label="lane"
        )
        if identity.tenant_id is not None:
            self._decrement_provisional(
                self._provisional_tenants, identity.tenant_id, permit_count,
                label="tenant",
            )
        if identity.resource_key is not None:
            self._decrement_provisional(
                self._provisional_resources, identity.resource_key, permit_count,
                label="resource",
            )
        self._invalidate_selection()

    @staticmethod
    def _capacity_scope_keys(
        group_id: str,
        lane_kind: ExecutionLaneKind,
        identity: _GroupIdentity,
    ) -> tuple[tuple[str, object], ...]:
        rows: list[tuple[str, object]] = [
            ("global", None),
            ("lane", lane_kind),
            ("group", group_id),
        ]
        if identity.tenant_id is not None:
            rows.append(("tenant", identity.tenant_id))
        if identity.resource_key is not None:
            rows.append(("resource", identity.resource_key))
        return tuple(rows)

    def _settle_provisional_failure(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int,
        identity: _GroupIdentity,
    ) -> None:
        self._release_provisional(
            group_id, lane_kind, permit_count, identity
        )
        now = time.monotonic()
        self._reactivate_capacity_blocked_shapes(
            self._capacity_scope_keys(group_id, lane_kind, identity),
            now,
        )
        self._notify_selected_waiter_locked()
        self._provisional_condition.notify_all()

    def _can_admit(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        permit_count: int = 1,
    ) -> bool:
        identity = self._identity(group_id)
        # Preserve the historical zero-overhead common path when no durable
        # grant is currently between private reservation and publication.
        if self._provisional_in_flight == 0:
            if self._in_flight + permit_count > self._budget.max_total_in_flight:
                return False
            if (
                self._groups.get(group_id, 0) + permit_count
                > int(self._budget.max_in_flight_per_group)
            ):
                return False
            if (
                self._lanes.get(lane_kind, 0) + permit_count
                > self._lane_limits[lane_kind]
            ):
                return False
            if (
                identity.tenant_id is not None
                and self._tenants.get(identity.tenant_id, 0) + permit_count
                > int(self._budget.max_in_flight_per_tenant)
            ):
                return False
            resource_key = identity.resource_key
            return not (
                resource_key is not None
                and self._resources.get(resource_key, 0) + permit_count
                > int(self._budget.max_in_flight_per_resource)
            )

        if self._occupied_total() + permit_count > self._budget.max_total_in_flight:
            return False
        if (
            self._occupied(self._groups, self._provisional_groups, group_id) + permit_count
            > int(self._budget.max_in_flight_per_group)
        ):
            return False
        if (
            self._occupied(self._lanes, self._provisional_lanes, lane_kind) + permit_count
            > self._lane_limits[lane_kind]
        ):
            return False
        if (
            identity.tenant_id is not None
            and self._occupied(
                self._tenants, self._provisional_tenants, identity.tenant_id
            ) + permit_count
            > int(self._budget.max_in_flight_per_tenant)
        ):
            return False
        resource_key = identity.resource_key
        if (
            resource_key is not None
            and self._occupied(
                self._resources, self._provisional_resources, resource_key
            ) + permit_count
            > int(self._budget.max_in_flight_per_resource)
        ):
            return False
        return True

    @staticmethod
    def _shape(waiter: _Waiter) -> tuple[str, ExecutionLaneKind, int]:
        return (waiter.group_id, waiter.lane_kind, waiter.permit_count)

    def _capacity_block_key(
        self,
        waiter: _Waiter,
    ) -> tuple[str, object] | None:
        permit_count = waiter.permit_count
        if self._occupied_total() + permit_count > self._budget.max_total_in_flight:
            return ("global", None)
        if (
            self._occupied(
                self._groups, self._provisional_groups, waiter.group_id
            ) + permit_count
            > int(self._budget.max_in_flight_per_group)
        ):
            return ("group", waiter.group_id)
        if (
            self._occupied(
                self._lanes, self._provisional_lanes, waiter.lane_kind
            ) + permit_count
            > self._lane_limits[waiter.lane_kind]
        ):
            return ("lane", waiter.lane_kind)
        identity = self._identity(waiter.group_id)
        if (
            identity.tenant_id is not None
            and self._occupied(
                self._tenants, self._provisional_tenants, identity.tenant_id
            ) + permit_count
            > int(self._budget.max_in_flight_per_tenant)
        ):
            return ("tenant", identity.tenant_id)
        if (
            identity.resource_key is not None
            and self._occupied(
                self._resources, self._provisional_resources, identity.resource_key
            ) + permit_count
            > int(self._budget.max_in_flight_per_resource)
        ):
            return ("resource", identity.resource_key)
        return None

    def _park_capacity_blocked_shape(
        self,
        shape: tuple[str, ExecutionLaneKind, int],
        block_key: tuple[str, object],
    ) -> None:
        previous = self._capacity_block_key_by_shape.get(shape)
        if previous == block_key:
            return
        if previous is not None:
            previous_shapes = self._capacity_blocked_shapes.get(previous)
            if previous_shapes is not None:
                previous_shapes.discard(shape)
                if not previous_shapes:
                    self._capacity_blocked_shapes.pop(previous, None)
        self._capacity_block_key_by_shape[shape] = block_key
        self._capacity_blocked_shapes.setdefault(block_key, set()).add(shape)

    def _drop_capacity_blocked_shape(
        self,
        shape: tuple[str, ExecutionLaneKind, int],
    ) -> None:
        block_key = self._capacity_block_key_by_shape.pop(shape, None)
        if block_key is None:
            return
        shapes = self._capacity_blocked_shapes.get(block_key)
        if shapes is None:
            return
        shapes.discard(shape)
        if not shapes:
            self._capacity_blocked_shapes.pop(block_key, None)

    def _reactivate_capacity_blocked_shapes(
        self,
        block_keys: tuple[tuple[str, object], ...],
        now: float,
    ) -> None:
        shapes: set[tuple[str, ExecutionLaneKind, int]] = set()
        for block_key in block_keys:
            shapes.update(self._capacity_blocked_shapes.pop(block_key, ()))
        for shape in shapes:
            current_key = self._capacity_block_key_by_shape.get(shape)
            if current_key not in block_keys:
                continue
            self._capacity_block_key_by_shape.pop(shape, None)
            waiter = self._shape_head(shape)
            if waiter is not None:
                self._push_waiter_order(waiter, now)

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
        completed = self._group_service_completed.get(waiter.group_id, 0)
        service_seconds = self._group_service_seconds.get(waiter.group_id, 0.0)
        service_rate = (
            None
            if completed <= 0 or service_seconds <= 0.0
            else completed / service_seconds
        )
        return SchedulingCandidate(
            ticket=waiter.ticket,
            group_id=waiter.group_id,
            priority=waiter.intent.priority,
            enqueued_monotonic=waiter.enqueued_monotonic,
            tenant_id=identity.tenant_id,
            resource_id=identity.resource_id,
            waiting_permits=max(
                waiter.permit_count,
                self._waiting_by_group.get(waiter.group_id, 0),
            ),
            observed_service_rate_per_second=service_rate,
        )

    def _ordering_key(
        self,
        waiter: _Waiter,
        now: float,
    ) -> tuple[int | float, ...]:
        return self._scheduling.ordering_key(
            self._candidate(waiter),
            now_monotonic=now,
        )

    def _push_waiter_order(self, waiter: _Waiter, now: float) -> None:
        if self._shape(waiter) in self._capacity_block_key_by_shape:
            return
        heapq.heappush(
            self._selection_heaps[waiter.lane_kind],
            (self._ordering_key(waiter, now), waiter.ticket),
        )

    def _rebuild_selection_heaps(self, now: float) -> None:
        self._selection_heaps = {lane: [] for lane in self._lane_limits}
        # Rebuild from one coherent Scheduling Authority cut. The durable
        # authority can project an entire candidate batch under one read
        # transaction; issuing one ordering_key() call per shape needlessly
        # re-enters the same read boundary O(waiting_shapes) times. Parked
        # shapes remain absent exactly as in _push_waiter_order().
        waiters = tuple(
            waiter
            for shape in self._waiters_by_shape
            if shape not in self._capacity_block_key_by_shape
            if (waiter := self._shape_head(shape)) is not None
        )
        if not waiters:
            return
        keys = self._scheduling.ordering_keys(
            tuple(self._candidate(waiter) for waiter in waiters),
            now_monotonic=now,
        )
        if len(keys) != len(waiters):
            raise RuntimeError(
                'Scheduling Authority returned incomplete admission ranking'
            )
        for waiter, key in zip(waiters, keys, strict=True):
            heapq.heappush(
                self._selection_heaps[waiter.lane_kind],
                (key, waiter.ticket),
            )

    def _selection_heap_size(self) -> int:
        return sum(len(heap) for heap in self._selection_heaps.values())

    def _lane_selected_waiter(
        self,
        lane_kind: ExecutionLaneKind,
        now: float,
    ) -> _Waiter | None:
        # A saturated lane cannot admit any waiter regardless of priority,
        # tenant or group fairness. Skip it as one unit instead of repeatedly
        # popping every globally earlier-but-infeasible shape.
        if self._occupied(
            self._lanes, self._provisional_lanes, lane_kind
        ) >= self._lane_limits[lane_kind]:
            return None
        heap = self._selection_heaps[lane_kind]
        selected: _Waiter | None = None
        while heap:
            stored_key, ticket = heapq.heappop(heap)
            waiter = self._waiters.get(ticket)
            if waiter is None:
                continue
            shape = self._shape(waiter)
            if self._shape_head(shape) is not waiter:
                continue
            # Historical duplicate heap rows for a parked shape are discarded
            # lazily. The shape is re-indexed only when its blocking capacity
            # scope changes.
            if shape in self._capacity_block_key_by_shape:
                continue
            current_key = self._ordering_key(waiter, now)
            if current_key != stored_key:
                heapq.heappush(heap, (current_key, waiter.ticket))
                continue
            block_key = self._capacity_block_key(waiter)
            if block_key is not None:
                self._park_capacity_blocked_shape(shape, block_key)
                continue
            selected = waiter
            # Keep the selected head indexed until grant/removal, exactly as
            # the previous global heap did.
            heapq.heappush(heap, (current_key, waiter.ticket))
            break
        return selected

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

    def _refresh_group_rate_shapes(
        self,
        group_id: str,
        now: float,
    ) -> None:
        if self._group_service_completed.get(group_id, 0) <= 0:
            return
        for shape in self._shapes_by_group.get(group_id, ()):
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
        self._waiter_conditions[waiter.ticket] = Condition(self._lock)
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
        now = time.monotonic()
        if new_shape:
            self._push_waiter_order(waiter, now)
        else:
            self._refresh_group_rate_shapes(waiter.group_id, now)
        self._invalidate_selection()

    def _remove_waiter(self, ticket: int) -> _Waiter | None:
        waiter = self._waiters.pop(ticket, None)
        if waiter is None:
            return None
        condition = self._waiter_conditions.pop(ticket, None)
        if condition is None:
            raise RuntimeError(
                "execution admission waiter condition index drifted"
            )
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
            self._drop_capacity_blocked_shape(shape)
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
        self._refresh_group_rate_shapes(
            waiter.group_id,
            time.monotonic(),
        )
        self._invalidate_selection()
        return waiter

    def _notify_selected_waiter_locked(self) -> None:
        """Wake only the waiter that can make progress in the current state."""
        if not self._waiters:
            return
        selected = self._selected_waiter()
        if selected is None:
            return
        condition = self._waiter_conditions.get(selected.ticket)
        if condition is None:
            raise RuntimeError(
                "execution admission selected waiter condition disappeared"
            )
        condition.notify()

    def _notify_all_waiters_locked(self) -> None:
        """Broadcast only for authority-wide terminal state changes."""
        for condition in tuple(self._waiter_conditions.values()):
            condition.notify()

    def _wait_timeout_seconds(
        self,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
        now_monotonic: float,
    ) -> float | None:
        """Return the next time this waiter must re-check authority state.

        Capacity/accounting changes notify the condition directly, so ordinary
        waits are fully event-driven. Only an explicit deadline needs a timed
        wake: cancellation notifies the condition at its actual transition.
        """

        timeout: float | None = None
        if deadline is not None:
            remaining = deadline.remaining_seconds
            timeout = (
                remaining
                if timeout is None
                else min(timeout, remaining)
            )
        return timeout

    def _selected_waiter(self) -> _Waiter | None:
        now = time.monotonic()
        if self._waiters:
            service_revision = self._scheduling.service_revision()
            if service_revision != self._scheduling_service_revision:
                self._scheduling_service_revision = service_revision
                self._invalidate_selection()
                # Cached heap keys contain the old global service history;
                # every shape must be ranked again after a foreign commit.
                self._rebuild_selection_heaps(now)
        active_shapes = len(self._waiters_by_shape)
        if (
            self._selection_heap_size() > max(64, active_shapes * 4)
        ):
            self._rebuild_selection_heaps(now)
        if (
            self._selection_cache_version == self._queue_version
        ):
            if self._selection_cache_ticket is None:
                return None
            return self._waiters.get(self._selection_cache_ticket)

        selected: _Waiter | None = None
        if self._occupied_total() < self._budget.max_total_in_flight:
            if self._selection_heap_size() == 0:
                self._rebuild_selection_heaps(now)
            # Lane feasibility is an exact first-level partition: if one lane is
            # saturated, every shape in that lane is infeasible. Find each
            # non-saturated lane's best feasible head, then apply the unchanged
            # global fairness/priority key to at most four lane winners.
            lane_winners = tuple(
                waiter
                for lane in self._lane_limits
                if (waiter := self._lane_selected_waiter(lane, now)) is not None
            )
            if lane_winners:
                selected = min(
                    lane_winners,
                    key=lambda waiter: self._ordering_key(waiter, now),
                )

        self._selection_cache_version = self._queue_version
        self._selection_cache_ticket = (
            None if selected is None else selected.ticket
        )
        return selected

    def _publish_grant_locked(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        waited_seconds: float,
        identity: _GroupIdentity,
        sequence: int,
    ) -> tuple[_AdmissionLease, ...]:
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
        self._grant_sequence = max(self._grant_sequence, sequence)
        self._invalidate_selection()
        self._admitted_total += permit_count
        self._cumulative_queue_wait_seconds += waited_seconds * permit_count
        self._max_queue_wait_seconds = max(
            self._max_queue_wait_seconds,
            waited_seconds,
        )
        started_monotonic = time.monotonic()
        return tuple(
            _AdmissionLease(
                self,
                group_id,
                lane_kind,
                started_monotonic=started_monotonic,
            )
            for _ in range(permit_count)
        )

    def _grant_many(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        waited_seconds: float,
    ) -> tuple[_AdmissionLease, ...]:
        """Strict grant path used whenever queued fairness is participating."""
        if not self._can_admit(group_id, lane_kind, permit_count):
            raise RuntimeError("admission grant violated configured budget")
        identity = self._identity(group_id)
        sequence = self._scheduling.record_grant(
            tenant_id=identity.tenant_id,
            flow_id=group_id,
            resource_id=identity.resource_id,
            permit_count=permit_count,
        )
        return self._publish_grant_locked(
            group_id, lane_kind,
            permit_count=permit_count,
            waited_seconds=waited_seconds,
            identity=identity,
            sequence=sequence,
        )

    def _grant_many_immediate(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        waited_seconds: float,
    ) -> tuple[_AdmissionLease, ...]:
        """Durably grant an uncontended fast-path request without lock convoying."""
        if self._waiters:
            raise RuntimeError("immediate admission grant requires an empty wait queue")
        if not self._can_admit(group_id, lane_kind, permit_count):
            raise RuntimeError("immediate admission grant violated configured budget")
        identity = self._identity(group_id)
        self._reserve_provisional(
            group_id, lane_kind, permit_count, identity
        )
        failure: BaseException | None = None
        sequence: int | None = None
        self._condition.release()
        try:
            try:
                sequence = self._scheduling.record_grant(
                    tenant_id=identity.tenant_id,
                    flow_id=group_id,
                    resource_id=identity.resource_id,
                    permit_count=permit_count,
                )
            except BaseException as exc:
                failure = exc
        finally:
            self._condition.acquire()

        if failure is not None:
            self._settle_provisional_failure(
                group_id, lane_kind, permit_count, identity
            )
            raise failure
        if sequence is None:
            self._settle_provisional_failure(
                group_id, lane_kind, permit_count, identity
            )
            raise RuntimeError("durable scheduling grant lost its sequence")

        self._release_provisional(
            group_id, lane_kind, permit_count, identity
        )
        leases = self._publish_grant_locked(
            group_id, lane_kind,
            permit_count=permit_count,
            waited_seconds=waited_seconds,
            identity=identity,
            sequence=sequence,
        )
        self._provisional_condition.notify_all()
        return leases

    def _enter_grant_call(self) -> bool:
        with self._grant_pressure_lock:
            self._grant_callers += 1
            return self._grant_callers > 1

    def _leave_grant_call(self) -> None:
        with self._grant_pressure_lock:
            if self._grant_callers <= 0:
                raise RuntimeError("admission grant caller accounting underflow")
            self._grant_callers -= 1

    def _enter_settlement_call(self) -> bool:
        with self._settlement_pressure_lock:
            self._settlement_callers += 1
            return self._settlement_callers > 1

    def _leave_settlement_call(self) -> None:
        with self._settlement_pressure_lock:
            if self._settlement_callers <= 0:
                raise RuntimeError("admission settlement caller accounting underflow")
            self._settlement_callers -= 1

    def try_acquire(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> _AdmissionLease | None:
        """Attempt one immediate permit without entering the durable wait queue."""

        leases = self.try_acquire_many(
            group_id,
            lane_kind,
            permit_count=1,
            deadline=deadline,
            cancellation=cancellation,
        )
        if leases is None:
            return None
        if len(leases) != 1:
            raise RuntimeError(
                "nonblocking admission returned invalid lease cardinality"
            )
        return leases[0]

    def _max_admissible_now(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        max_permit_count: int,
    ) -> int:
        identity = self._identity(group_id)
        residuals = [
            max_permit_count,
            int(self._budget.max_total_in_flight) - self._occupied_total(),
            int(self._budget.max_in_flight_per_group)
            - self._occupied(self._groups, self._provisional_groups, group_id),
            int(self._lane_limits[lane_kind])
            - self._occupied(self._lanes, self._provisional_lanes, lane_kind),
        ]
        if identity.tenant_id is not None:
            residuals.append(
                int(self._budget.max_in_flight_per_tenant)
                - self._occupied(
                    self._tenants, self._provisional_tenants, identity.tenant_id
                )
            )
        if identity.resource_key is not None:
            residuals.append(
                int(self._budget.max_in_flight_per_resource)
                - self._occupied(
                    self._resources, self._provisional_resources, identity.resource_key
                )
            )
        return max(0, min(residuals))

    def try_acquire_up_to(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        max_permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[_AdmissionLease, ...]:
        """Grant the exact largest immediately admissible prefix.

        This is the sole policy/capacity cardinality calculation. Callers submit
        a ready-set upper bound and never infer concurrency from local ceilings.
        """

        group_id = self._group_id(group_id)
        if type(max_permit_count) is not int or max_permit_count <= 0:
            raise ValueError(
                "nonblocking execution admission max_permit_count must be positive"
            )
        if lane_kind is ExecutionLaneKind.TIMER:
            raise ValueError("timer scheduler does not consume execution admission")
        if lane_kind not in self._lane_limits:
            raise ValueError(f"unsupported admission lane: {lane_kind}")
        with self._condition:
            self._identity(group_id)
            if self._closed or self._closing:
                raise RuntimeError("execution admission authority is closed")
            if self._cancelled(cancellation):
                self._cancelled_total += 1
                raise TaskCancelled(
                    cancellation.reason or "execution admission cancelled"
                )
            if deadline is not None and deadline.expired:
                self._timed_out_total += 1
                raise TimeoutError("execution admission deadline expired")
            # Immediate probes never jump queued fair-scheduling work.
            if self._waiters:
                return ()
            permit_count = self._max_admissible_now(
                group_id,
                lane_kind,
                max_permit_count,
            )
            if permit_count <= 0:
                return ()
            return self._grant_many_immediate(
                group_id,
                lane_kind,
                permit_count=permit_count,
                waited_seconds=0.0,
            )

    def try_acquire_many(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[_AdmissionLease, ...] | None:
        """Attempt one all-or-none permit batch without joining the wait queue."""

        group_id = self._group_id(group_id)
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError(
                "nonblocking execution admission permit_count must be positive"
            )
        if lane_kind is ExecutionLaneKind.TIMER:
            raise ValueError("timer scheduler does not consume execution admission")
        if lane_kind not in self._lane_limits:
            raise ValueError(f"unsupported admission lane: {lane_kind}")
        with self._condition:
            self._identity(group_id)
            if not self._can_ever_admit(group_id, lane_kind, permit_count):
                raise AdmissionRejected(
                    "execution admission batch exceeds configured capacity: "
                    f"group={group_id} lane={lane_kind.value} permits={permit_count}"
                )
            if self._closed or self._closing:
                raise RuntimeError("execution admission authority is closed")
            if self._cancelled(cancellation):
                self._cancelled_total += permit_count
                raise TaskCancelled(
                    cancellation.reason or "execution admission cancelled"
                )
            if deadline is not None and deadline.expired:
                self._timed_out_total += permit_count
                raise TimeoutError("execution admission deadline expired")
            # A probe must never jump any already queued fair-scheduling waiter.
            if self._waiters or not self._can_admit(
                group_id,
                lane_kind,
                permit_count,
            ):
                return None
            return self._grant_many_immediate(
                group_id,
                lane_kind,
                permit_count=permit_count,
                waited_seconds=0.0,
            )

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
        concurrent_grant = self._enter_grant_call()
        try:
            return self._acquire_many_impl(
                group_id,
                lane_kind,
                permit_count=permit_count,
                deadline=deadline,
                cancellation=cancellation,
                concurrent_grant=concurrent_grant,
            )
        finally:
            self._leave_grant_call()

    def _acquire_many_impl(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
        concurrent_grant: bool,
    ) -> tuple[_AdmissionLease, ...]:
        group_id = self._group_id(group_id)
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError("execution admission permit_count must be a positive integer")
        if lane_kind is ExecutionLaneKind.TIMER:
            raise ValueError("timer scheduler does not consume execution admission")
        if lane_kind not in self._lane_limits:
            raise ValueError(f"unsupported admission lane: {lane_kind}")
        wait_started_monotonic = time.monotonic()
        with wake_on_cancellation(
            cancellation, self._condition,
            notify_waiters=self._notify_all_waiters_locked,
        ), self._condition:
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
            if self._closed or self._closing:
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
                grant = (
                    self._grant_many_immediate
                    if concurrent_grant
                    else self._grant_many
                )
                return grant(
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
            add_cost_work("scheduler_admission_queued_permits", permit_count)
            wait_cost_recorded = False
            try:
                while True:
                    if self._closed or self._closing:
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
                        add_cost_wait_ns(
                            "scheduler_admission",
                            max(0, int(waited * 1_000_000_000)),
                        )
                        wait_cost_recorded = True
                        leases = self._grant_many(
                            group_id,
                            lane_kind,
                            permit_count=permit_count,
                            waited_seconds=waited,
                        )
                        self._notify_selected_waiter_locked()
                        return leases
                    condition = self._waiter_conditions.get(waiter.ticket)
                    if condition is None:
                        raise RuntimeError(
                            "execution admission waiter condition disappeared"
                        )
                    condition.wait(
                        self._wait_timeout_seconds(
                            deadline=deadline,
                            cancellation=cancellation,
                            now_monotonic=time.monotonic(),
                        )
                    )
            finally:
                if not wait_cost_recorded:
                    waited = max(
                        0.0,
                        time.monotonic() - waiter.enqueued_monotonic,
                    )
                    add_cost_wait_ns(
                        "scheduler_admission",
                        max(0, int(waited * 1_000_000_000)),
                    )
                if waiter.ticket in self._waiters:
                    self._remove_waiter(waiter.ticket)
                    self._notify_selected_waiter_locked()

    @staticmethod
    def _decrement(counter: dict, key: object, *, label: str) -> None:
        current = counter.get(key, 0)
        if current <= 0:
            raise RuntimeError(f"admission {label} accounting underflow")
        if current == 1:
            counter.pop(key, None)
        else:
            counter[key] = current - 1

    def _release_dimensions(
        self, group_id: str, lane_kind: ExecutionLaneKind,
        identity: _GroupIdentity,
    ) -> tuple[tuple[dict, object, str], ...]:
        rows: list[tuple[dict, object, str]] = [
            (self._groups, group_id, "group"),
            (self._lanes, lane_kind, "lane"),
        ]
        if identity.tenant_id is not None:
            rows.append((self._tenants, identity.tenant_id, "tenant"))
        if identity.resource_key is not None:
            rows.append((self._resources, identity.resource_key, "resource"))
        for counts, key, name in rows:
            if counts.get(key, 0) <= 0:
                raise RuntimeError(f"admission {name} accounting underflow")
        return tuple(rows)

    def _rollback(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
    ) -> None:
        """Undo a provisional grant without recording completed service."""

        with self._condition:
            if self._in_flight <= 0:
                raise RuntimeError("admission rollback in-flight accounting underflow")
            identity = self._identity(group_id)
            dimensions = self._release_dimensions(group_id, lane_kind, identity)
            self._scheduling.rollback_grant(
                tenant_id=identity.tenant_id,
                flow_id=group_id,
                resource_id=identity.resource_id,
                permit_count=1,
            )
            for counter, key, label in dimensions:
                self._decrement(counter, key, label=label)
            self._in_flight -= 1
            now = time.monotonic()
            self._refresh_released_owner_shapes(
                group_id,
                identity,
                now,
            )
            block_keys: list[tuple[str, object]] = [
                ("global", None),
                ("lane", lane_kind),
                ("group", group_id),
            ]
            if identity.tenant_id is not None:
                block_keys.append(("tenant", identity.tenant_id))
            if identity.resource_key is not None:
                block_keys.append(("resource", identity.resource_key))
            self._reactivate_capacity_blocked_shapes(
                tuple(block_keys),
                now,
            )
            self._invalidate_selection()
            self._notify_selected_waiter_locked()

    def _release_serial(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        started_monotonic: float,
    ) -> None:
        completed_at = time.monotonic()
        elapsed = max(0.0, completed_at - float(started_monotonic))
        add_cost_time_ns(
            "scheduler_service",
            max(0, int(elapsed * 1_000_000_000)),
        )
        add_cost_work("scheduler_completed_permits", 1)
        with self._condition:
            if self._in_flight <= 0:
                raise RuntimeError("admission in-flight accounting underflow")
            identity = self._identity(group_id)
            dimensions = self._release_dimensions(group_id, lane_kind, identity)
            self._scheduling.record_completion(
                tenant_id=identity.tenant_id,
                flow_id=group_id,
                service_quanta=max(1, int(elapsed * 1_000_000_000)),
                resource_id=identity.resource_id,
                permit_count=1,
            )
            for counter, key, label in dimensions:
                self._decrement(counter, key, label=label)
            self._in_flight -= 1
            self._group_service_completed[group_id] = (
                self._group_service_completed.get(group_id, 0) + 1
            )
            self._group_service_seconds[group_id] = (
                self._group_service_seconds.get(group_id, 0.0) + elapsed
            )
            self._lane_service_completed[lane_kind] = (
                self._lane_service_completed.get(lane_kind, 0) + 1
            )
            self._lane_service_seconds[lane_kind] = (
                self._lane_service_seconds.get(lane_kind, 0.0) + elapsed
            )
            now = time.monotonic()
            self._refresh_released_owner_shapes(group_id, identity, now)
            self._reactivate_capacity_blocked_shapes(
                self._capacity_scope_keys(group_id, lane_kind, identity), now
            )
            self._invalidate_selection()
            self._notify_selected_waiter_locked()

    def _release(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        started_monotonic: float,
    ) -> None:
        concurrent_settlement = self._enter_settlement_call()
        try:
            if concurrent_settlement:
                self._release_concurrent(
                    group_id,
                    lane_kind,
                    started_monotonic=started_monotonic,
                )
            else:
                self._release_serial(
                    group_id,
                    lane_kind,
                    started_monotonic=started_monotonic,
                )
        finally:
            self._leave_settlement_call()

    def _release_concurrent(
        self,
        group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        started_monotonic: float,
    ) -> None:
        completed_at = time.monotonic()
        elapsed = max(0.0, completed_at - float(started_monotonic))
        add_cost_time_ns(
            "scheduler_service",
            max(0, int(elapsed * 1_000_000_000)),
        )
        add_cost_work("scheduler_completed_permits", 1)

        # Keep the committed capacity occupied while durable service settlement
        # runs, but do not hold the admission state lock around SQLite. This is
        # conservative for admission safety and lets naturally concurrent
        # completions reach the scheduler's existing group-commit path.
        with self._condition:
            if self._in_flight <= 0:
                raise RuntimeError("admission in-flight accounting underflow")
            identity = self._identity(group_id)
            self._release_dimensions(group_id, lane_kind, identity)
            self._settling_in_flight += 1

        failure: BaseException | None = None
        try:
            self._scheduling.record_completion(
                tenant_id=identity.tenant_id,
                flow_id=group_id,
                service_quanta=max(1, int(elapsed * 1_000_000_000)),
                resource_id=identity.resource_id,
                permit_count=1,
            )
        except BaseException as exc:
            failure = exc

        with self._condition:
            if self._settling_in_flight <= 0:
                raise RuntimeError("admission settlement accounting underflow")
            self._settling_in_flight -= 1
            if failure is not None:
                self._provisional_condition.notify_all()
                raise failure

            # unregister_group cannot retire this identity while committed
            # capacity remains non-zero, so the same ownership cut is intact.
            current_identity = self._identity(group_id)
            if current_identity != identity:
                raise RuntimeError(
                    "admission identity drifted during durable completion"
                )
            dimensions = self._release_dimensions(
                group_id, lane_kind, identity
            )
            for counter, key, label in dimensions:
                self._decrement(counter, key, label=label)
            self._in_flight -= 1
            self._group_service_completed[group_id] = (
                self._group_service_completed.get(group_id, 0) + 1
            )
            self._group_service_seconds[group_id] = (
                self._group_service_seconds.get(group_id, 0.0) + elapsed
            )
            self._lane_service_completed[lane_kind] = (
                self._lane_service_completed.get(lane_kind, 0) + 1
            )
            self._lane_service_seconds[lane_kind] = (
                self._lane_service_seconds.get(lane_kind, 0.0) + elapsed
            )
            now = time.monotonic()
            self._refresh_released_owner_shapes(
                group_id,
                identity,
                now,
            )
            self._reactivate_capacity_blocked_shapes(
                self._capacity_scope_keys(group_id, lane_kind, identity),
                now,
            )
            self._invalidate_selection()
            self._notify_selected_waiter_locked()
            self._provisional_condition.notify_all()

    @staticmethod
    def _service_statistics(
        completed: int,
        cumulative_seconds: float,
    ) -> tuple[float | None, float | None]:
        if completed <= 0 or cumulative_seconds <= 0.0:
            return (None, None)
        mean = cumulative_seconds / completed
        return (mean, completed / cumulative_seconds)

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
                        completed_total=self._group_service_completed.get(group_id, 0),
                        cumulative_service_seconds=self._group_service_seconds.get(
                            group_id, 0.0
                        ),
                        mean_service_seconds=self._service_statistics(
                            self._group_service_completed.get(group_id, 0),
                            self._group_service_seconds.get(group_id, 0.0),
                        )[0],
                        service_rate_per_second=self._service_statistics(
                            self._group_service_completed.get(group_id, 0),
                            self._group_service_seconds.get(group_id, 0.0),
                        )[1],
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
                        completed_total=self._lane_service_completed.get(lane, 0),
                        cumulative_service_seconds=self._lane_service_seconds.get(
                            lane, 0.0
                        ),
                        mean_service_seconds=self._service_statistics(
                            self._lane_service_completed.get(lane, 0),
                            self._lane_service_seconds.get(lane, 0.0),
                        )[0],
                        service_rate_per_second=self._service_statistics(
                            self._lane_service_completed.get(lane, 0),
                            self._lane_service_seconds.get(lane, 0.0),
                        )[1],
                    )
                    for lane in lane_kinds
                ),
            )

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closing = True
            self._notify_all_waiters_locked()
            while self._provisional_in_flight or self._settling_in_flight:
                self._provisional_condition.wait()
            self._closed = True
            self._closing = False
            self._notify_all_waiters_locked()
